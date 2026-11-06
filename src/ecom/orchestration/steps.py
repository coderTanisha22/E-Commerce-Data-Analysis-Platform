"""The DAG steps that are checks rather than transforms.

Every other Airflow task runs an existing ``ecom`` command. These three exist
because the DAG needs a gate at points the pipeline never had one: before the
raw layer is touched, after the warehouse is built, and before the dashboard
is declared fresh. Each raises on failure, so the Airflow task fails with it.

This is an orchestration module: it reads files, the warehouse and storage,
and leaves every comparison to pure functions in ``ecom.quality``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path

import duckdb
import pandas as pd

from ecom.api.inventory import STATUS_ORDER
from ecom.api.loader import load_platform
from ecom.config import Settings, get_settings
from ecom.contracts import OLIST_CONTRACTS, TableContract
from ecom.ingestion.ingest import IngestionError, validate_against_contract
from ecom.quality.checks import CheckResult, run_gate
from ecom.quality.reconcile import check_pairs_identical, check_row_parity, check_sum_parity
from ecom.storage import StorageBackend, get_storage
from ecom.synthetic.run_generate import MANIFEST_KEY as INVENTORY_MANIFEST_KEY

logger = logging.getLogger(__name__)

ROW_PARITY: tuple[tuple[str, str], ...] = (
    ("fct_order_items", "order_items"),
    ("dim_products", "products"),
    ("dim_sellers", "sellers"),
)
"""(warehouse model, processed table) pairs that must hold the same rows."""


def check_sources(
    *,
    settings: Settings | None = None,
    contracts: tuple[TableContract, ...] = OLIST_CONTRACTS,
) -> dict[str, int]:
    """Confirm every source file exists and satisfies its contract, writing nothing.

    Runs before ``store_raw`` so a missing or reshaped download fails the DAG
    while the previous raw layer is still intact.

    Returns:
        Data row count per table.

    Raises:
        IngestionError: Naming every missing file at once, or the first file
            whose header breaks its contract.
    """
    settings = settings or get_settings()
    source_dir = settings.resolve(settings.source_dir)
    paths = {contract.name: source_dir / contract.filename for contract in contracts}
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise IngestionError(f"source files not found: {missing}")

    rows = {
        contract.name: validate_against_contract(paths[contract.name].read_bytes(), contract)[0]
        for contract in contracts
    }
    logger.info("sources ready: %d tables, %d rows", len(rows), sum(rows.values()))
    return rows


def reconcile_warehouse(
    *,
    storage: StorageBackend | None = None,
    settings: Settings | None = None,
    warehouse_path: Path | None = None,
) -> list[CheckResult]:
    """Compare the local DuckDB warehouse with the processed layer that fed it.

    Raises:
        FileNotFoundError: If the warehouse has not been built.
        DataQualityError: If any count, total or co-occurrence pair disagrees.
    """
    settings = settings or get_settings()
    storage = storage or get_storage(settings)
    path = warehouse_path or settings.warehouse_path
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing; run dbt_build first")

    with duckdb.connect(str(path), read_only=True) as warehouse:
        results = _reconcile(
            frame=lambda sql: warehouse.execute(sql).df(), table=lambda name: name, storage=storage
        )
    return run_gate(results, stage="warehouse")


def reconcile_bigquery(
    *,
    storage: StorageBackend | None = None,
    settings: Settings | None = None,
) -> list[CheckResult]:
    """Compare the BigQuery warehouse with the processed layer, with the same checks.

    Raises:
        ValueError: If no GCP project is configured.
        DataQualityError: If any count, total or co-occurrence pair disagrees.
    """
    # Imported here: google-cloud-bigquery is the optional [bigquery] extra.
    from google.cloud import bigquery

    settings = settings or get_settings()
    storage = storage or get_storage(settings)
    if not settings.gcp_project:
        raise ValueError("set ECOM_GCP_PROJECT to reconcile the BigQuery warehouse")

    client = bigquery.Client(project=settings.gcp_project)
    dataset = f"{settings.gcp_project}.{settings.bigquery_dataset}"
    results = _reconcile(
        frame=lambda sql: client.query(sql).to_dataframe(),
        table=lambda name: f"`{dataset}.{name}`",
        storage=storage,
    )
    return run_gate(results, stage="bigquery")


def _reconcile(
    *,
    frame: Callable[[str], pd.DataFrame],
    table: Callable[[str], str],
    storage: StorageBackend,
) -> list[CheckResult]:
    """Run every warehouse-vs-pipeline check through one engine's SQL runner.

    Args:
        frame: Runs a query on the warehouse and returns the result as a frame.
        table: Turns a model name into the engine's fully qualified table name.
        storage: Where the processed layer is read from.
    """

    def processed(name: str) -> pd.DataFrame:
        return storage.get_parquet(storage.processed_key(name))

    def scalar(sql: str) -> float:
        return float(frame(sql).iloc[0, 0])

    results = [
        check_row_parity(
            model,
            warehouse_rows=int(scalar(f"SELECT COUNT(*) FROM {table(model)}")),
            pipeline_rows=len(processed(name)),
        )
        for model, name in ROW_PARITY
    ]
    results.append(
        check_sum_parity(
            "fct_order_items.price",
            warehouse_sum=scalar(f"SELECT SUM(price) FROM {table('fct_order_items')}"),
            pipeline_sum=float(processed("order_items")["price"].sum()),
        )
    )
    pairs = frame(
        f"SELECT product_a, product_b, order_count FROM {table('fct_product_cooccurrence')}"
    )
    results.append(check_pairs_identical(pairs, processed("product_cooccurrence")))
    return results


def check_dashboard_ready(
    *,
    storage: StorageBackend | None = None,
    settings: Settings | None = None,
) -> dict[str, object]:
    """Load the data exactly as the API does and check it is internally consistent.

    A dashboard that starts is not the same as one showing this run's data, so
    this compares what the API would serve against the manifests the run wrote.

    Returns:
        The headline figures the dashboard will show.

    Raises:
        DataQualityError: If the loaded data contradicts the run's manifests.
    """
    settings = settings or get_settings()
    storage = storage or get_storage(settings)
    platform = load_platform(storage=storage, settings=settings)
    manifest = json.loads(storage.get_bytes(INVENTORY_MANIFEST_KEY))
    summary = platform.inventory.summary()
    statuses = {row.status for row in summary.by_status if row.count}
    graph = platform.discovery.graph

    loaded_rows, manifest_rows = len(platform.inventory), int(manifest["rows"])
    links, pairs = graph.number_of_edges(), platform.overview.cooccurrence_pairs
    results = [
        CheckResult(
            "parity:inventory_manifest",
            loaded_rows == manifest_rows,
            "error",
            f"API loads {loaded_rows:,} inventory rows; this run's manifest says {manifest_rows:,}",
            abs(loaded_rows - manifest_rows),
        ),
        CheckResult(
            "parity:graph_links",
            links == pairs,
            "error",
            f"graph has {links:,} links for {pairs:,} co-occurrence pairs",
            abs(links - pairs),
        ),
        CheckResult(
            "statuses:inventory",
            statuses <= set(STATUS_ORDER),
            "error",
            f"statuses present: {sorted(statuses)}",
        ),
        CheckResult(
            "nonempty:overview",
            platform.overview.orders_in_window > 0 and graph.number_of_nodes() > 0,
            "error",
            f"{platform.overview.orders_in_window} orders, "
            f"{graph.number_of_nodes()} graph products",
        ),
    ]
    run_gate(results, stage="dashboard")
    return {
        "inventory_sha256": manifest["sha256"],
        "inventory_rows": len(platform.inventory),
        "urgent": next(row.count for row in summary.by_status if row.status == "Urgent"),
        "graph_products": graph.number_of_nodes(),
        "graph_links": graph.number_of_edges(),
    }
