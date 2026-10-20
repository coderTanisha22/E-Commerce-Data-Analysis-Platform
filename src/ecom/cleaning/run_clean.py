"""Raw to processed orchestration.

This is the only module in the cleaning package that performs I/O. It reads the
raw layer, applies the pure transforms in a fixed order, runs the quality gate,
and writes typed Parquet to the processed layer.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone

import pandas as pd

from ecom import contracts as con
from ecom.cleaning.transforms import (
    attach_english_category,
    build_order_products,
    coerce_types,
    derive_order_lines,
    flag_order_status,
    normalise_category,
    trim_whitespace,
)
from ecom.config import Settings, get_settings
from ecom.ingestion.ingest import SOURCE_NAME
from ecom.quality.checks import (
    CheckResult,
    check_foreign_key,
    check_no_nulls,
    check_row_count,
    check_unique_key,
    run_gate,
)
from ecom.storage import StorageBackend, get_storage

logger = logging.getLogger(__name__)

QUALITY_REPORT_KEY = "processed/_quality_report.json"


def _load_raw(storage: StorageBackend, contract: con.TableContract) -> pd.DataFrame:
    """Read one raw CSV as all-string columns, then trim and coerce.

    Reading as ``string`` rather than letting pandas infer is deliberate: it
    keeps zero-padded identifiers intact and makes every cast an explicit,
    reviewable step.
    """
    key = storage.raw_key(SOURCE_NAME, contract.name)
    df = storage.get_csv(key, dtype=con.CSV_DTYPE, encoding="utf-8-sig")
    df = trim_whitespace(df)
    return coerce_types(df, contract)


def _load_raw_tables(storage: StorageBackend) -> dict[str, pd.DataFrame]:
    """Read every contracted Olist table out of the raw layer."""
    logger.info("loading raw layer")
    return {c.name: _load_raw(storage, c) for c in con.OLIST_CONTRACTS}


def _gate_source(raw: dict[str, pd.DataFrame]) -> list[CheckResult]:
    """Check the raw layer before any transform touches it."""
    orders, items = raw["orders"], raw["order_items"]
    products, sellers, customers = raw["products"], raw["sellers"], raw["customers"]

    results = [
        *(check_unique_key(raw[c.name], c.name, c.key) for c in con.OLIST_CONTRACTS if c.key),
        check_no_nulls(items, "order_items", ("order_id", "product_id", "seller_id")),
        check_no_nulls(orders, "orders", ("order_id", "customer_id", "order_status")),
        check_foreign_key(items, orders, "order_id", "order_id", "order_items->orders"),
        check_foreign_key(items, products, "product_id", "product_id", "order_items->products"),
        check_foreign_key(items, sellers, "seller_id", "seller_id", "order_items->sellers"),
        check_foreign_key(orders, customers, "customer_id", "customer_id", "orders->customers"),
        check_row_count(items, "order_items", minimum=100_000),
        # Documented Olist quirk, not a regression: some orders carry no items.
        check_foreign_key(
            orders, items, "order_id", "order_id", "orders_without_items", severity="warn"
        ),
    ]
    return run_gate(results, stage="raw")


def _apply_transforms(raw: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Run the pure transforms in dependency order."""
    logger.info("applying transforms")
    order_lines = derive_order_lines(raw["order_items"])
    return {
        "orders": flag_order_status(raw["orders"]),
        "order_lines": order_lines,
        "order_products": build_order_products(order_lines),
        "products": attach_english_category(
            normalise_category(raw["products"]), raw["category_translation"]
        ),
        "customers": raw["customers"],
        "sellers": raw["sellers"],
    }


def _gate_processed(out: dict[str, pd.DataFrame]) -> list[CheckResult]:
    """Check the transformed frames before anything is written."""
    results = [
        check_unique_key(
            out["order_lines"], "order_lines", ("order_id", "product_id", "seller_id")
        ),
        check_unique_key(out["order_products"], "order_products", ("order_id", "product_id")),
        check_no_nulls(out["products"], "products", ("product_category_english",)),
        check_no_nulls(out["order_lines"], "order_lines", ("quantity", "line_revenue")),
    ]
    return run_gate(results, stage="processed")


def _assert_revenue_preserved(order_items: pd.DataFrame, order_lines: pd.DataFrame) -> float:
    """Verify the line collapse aggregated rather than deduplicated.

    Without this invariant a future "optimisation" that replaces the aggregation
    with a DISTINCT would silently discard 10,225 unit rows of revenue.

    Returns:
        The preserved revenue total.

    Raises:
        ValueError: If source and derived revenue disagree by more than a cent.
    """
    source = float(order_items["price"].sum())
    derived = float(order_lines["line_revenue"].sum())
    if abs(source - derived) > 0.01:
        raise ValueError(f"revenue changed during line derivation: {source:.2f} -> {derived:.2f}")
    logger.info("revenue invariant holds: R$ %.2f preserved", derived)
    return derived


def _write_processed(
    storage: StorageBackend,
    outputs: dict[str, pd.DataFrame],
    checks: list[CheckResult],
    revenue: float,
) -> None:
    """Persist every processed table plus the run's quality report."""
    for table, df in outputs.items():
        storage.put_parquet(storage.processed_key(table), df)
        logger.info("wrote processed/%-16s %7d rows", table + ".parquet", len(df))

    report = {
        "cleaned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "row_counts": {t: len(df) for t, df in outputs.items()},
        "revenue_preserved": round(revenue, 2),
        "checks": [asdict(c) for c in checks],
    }
    storage.put_bytes(QUALITY_REPORT_KEY, json.dumps(report, indent=2).encode())


def clean_all(
    *,
    storage: StorageBackend | None = None,
    settings: Settings | None = None,
) -> dict[str, int]:
    """Build the processed layer from the raw layer.

    Args:
        storage: Backend to read and write. Defaults to the configured one.
        settings: Override settings, mainly for tests.

    Returns:
        Row count per processed table.

    Raises:
        DataQualityError: If any error-severity check fails, leaving the
            previous processed layer untouched.
    """
    settings = settings or get_settings()
    storage = storage or get_storage(settings)

    raw = _load_raw_tables(storage)
    source_checks = _gate_source(raw)
    outputs = _apply_transforms(raw)
    processed_checks = _gate_processed(outputs)
    revenue = _assert_revenue_preserved(raw["order_items"], outputs["order_lines"])

    _write_processed(storage, outputs, [*source_checks, *processed_checks], revenue)
    return {table: len(df) for table, df in outputs.items()}
