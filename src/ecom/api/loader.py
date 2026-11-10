"""Load the processed layer once and build every service the API serves.

This is the API's only I/O boundary. Routes receive a ``PlatformData`` and never
touch storage, so a test can hand the app a fixture-built ``PlatformData`` and
exercise every endpoint without a processed layer on disk.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import pandas as pd

from ecom.analysis.profile import profile_cooccurrence, profile_sales, select_countable_orders
from ecom.api.inventory import InventoryService
from ecom.api.schemas import MonthlyOrders, OverviewResponse
from ecom.config import Settings, get_settings
from ecom.discovery.graph import ProductGraphService
from ecom.ingestion.ingest import MANIFEST_KEY as RAW_MANIFEST_KEY
from ecom.storage import StorageBackend, get_storage
from ecom.synthetic.run_generate import MANIFEST_KEY as INVENTORY_MANIFEST_KEY

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlatformData:
    """Everything the routes need, built once per process."""

    discovery: ProductGraphService
    inventory: InventoryService
    overview: OverviewResponse
    storage_description: str
    ingested_at: str | None = None
    inventory_generated_at: str | None = None


def build_overview(
    *,
    orders: pd.DataFrame,
    order_lines: pd.DataFrame,
    order_products: pd.DataFrame,
    products: pd.DataFrame,
    sellers: pd.DataFrame,
    pairs: pd.DataFrame,
    inventory: InventoryService,
    settings: Settings,
) -> OverviewResponse:
    """Compute the dashboard's headline figures from processed tables.

    Reuses the analysis layer's own metric functions so the API cannot report a
    different revenue or multi-product share than ``reports/profile.json``.
    """
    sales = profile_sales(orders, order_lines, settings)
    cooccurrence = profile_cooccurrence(select_countable_orders(order_products, orders), pairs)
    graph_products = pd.concat([pairs["product_a"], pairs["product_b"]]).nunique()
    start, end = pd.Timestamp(settings.window_start), pd.Timestamp(settings.window_end)
    monthly = [
        MonthlyOrders(month=pd.Timestamp(month).date(), order_count=count)
        for month, count in sales["orders_by_month"].items()
        if start <= pd.Timestamp(month) <= end
    ]
    return OverviewResponse(
        window_start=settings.window_start,
        window_end=settings.window_end,
        products=len(products),
        sellers=len(sellers),
        orders_in_window=sales["orders_in_window"],
        revenue_brl=sales["revenue_brl"],
        average_order_value_brl=sales["average_order_value_brl"],
        multi_product_share_pct=cooccurrence["multi_product_share_pct"],
        cooccurrence_pairs=len(pairs),
        graph_products=int(graph_products),
        orders_by_month=monthly,
        inventory=inventory.summary(),
    )


OVERVIEW_KEY = "processed/_overview.json"
"""Headline figures saved by ``ecom save-overview``, tagged with the run they describe."""

SERVING_TABLES = ("products", "sellers", "product_cooccurrence", "synthetic_inventory")
"""Tables the routes query on every request."""

OVERVIEW_TABLES = ("orders", "order_lines", "order_products")
"""The three largest tables, needed only to compute the headline figures."""


def load_platform(
    *,
    storage: StorageBackend | None = None,
    settings: Settings | None = None,
    use_saved_overview: bool | None = None,
) -> PlatformData:
    """Read the processed layer and build the discovery and inventory services.

    Args:
        use_saved_overview: Take the headline figures from ``ecom save-overview``
            when they were saved from this same run. Defaults to the
            ``api_saved_overview`` setting; a stale or missing file falls back
            to recomputing, so the dashboard never shows another run's numbers.

    Raises:
        FileNotFoundError: If the pipeline has not produced a table the API needs;
            the message names the command that builds it.
    """
    settings = settings or get_settings()
    storage = storage or get_storage(settings)
    if use_saved_overview is None:
        use_saved_overview = settings.api_saved_overview
    fingerprint = _run_fingerprint(storage)
    saved = _saved_overview(storage, fingerprint) if use_saved_overview else None
    names = SERVING_TABLES if saved is not None else SERVING_TABLES + OVERVIEW_TABLES
    tables = {name: _read_table(storage, name) for name in names}
    discovery = ProductGraphService(
        pairs=tables["product_cooccurrence"], products=tables["products"]
    )
    inventory = InventoryService(
        tables["synthetic_inventory"], products=tables["products"], sellers=tables["sellers"]
    )
    if saved is not None:
        overview = OverviewResponse.model_validate({**saved, "inventory": inventory.summary()})
    else:
        overview = build_overview(
            orders=tables["orders"],
            order_lines=tables["order_lines"],
            order_products=tables["order_products"],
            products=tables["products"],
            sellers=tables["sellers"],
            pairs=tables["product_cooccurrence"],
            inventory=inventory,
            settings=settings,
        )
    logger.info(
        "api data loaded: %d graph products, %d inventory rows, overview %s",
        discovery.graph.number_of_nodes(),
        len(inventory),
        "saved" if saved is not None else "computed",
    )
    return PlatformData(
        discovery=discovery,
        inventory=inventory,
        overview=overview,
        storage_description=storage.describe(),
        ingested_at=fingerprint["ingested_at"],
        inventory_generated_at=fingerprint["inventory_generated_at"],
    )


def save_overview(
    *, storage: StorageBackend | None = None, settings: Settings | None = None
) -> str:
    """Compute the headline figures for the current run and save them; return the key."""
    settings = settings or get_settings()
    storage = storage or get_storage(settings)
    platform = load_platform(storage=storage, settings=settings, use_saved_overview=False)
    document = {
        "fingerprint": _run_fingerprint(storage),
        "overview": platform.overview.model_dump(mode="json", exclude={"inventory"}),
    }
    storage.put_bytes(OVERVIEW_KEY, json.dumps(document, indent=2).encode())
    return OVERVIEW_KEY


def _run_fingerprint(storage: StorageBackend) -> dict[str, str | None]:
    """Identify the pipeline run behind the processed layer by its two build timestamps."""
    return {
        "ingested_at": _manifest_field(storage, RAW_MANIFEST_KEY, "ingested_at"),
        "inventory_generated_at": _manifest_field(storage, INVENTORY_MANIFEST_KEY, "generated_at"),
    }


def _saved_overview(storage: StorageBackend, fingerprint: dict[str, str | None]) -> dict | None:
    """The saved figures if they describe this run, else None (and the caller recomputes)."""
    if not storage.exists(OVERVIEW_KEY):
        logger.warning("no saved overview at %s; computing it", OVERVIEW_KEY)
        return None
    document = json.loads(storage.get_bytes(OVERVIEW_KEY))
    if document.get("fingerprint") != fingerprint:
        logger.warning("saved overview belongs to another pipeline run; computing it")
        return None
    return document["overview"]


def _read_table(storage: StorageBackend, name: str) -> pd.DataFrame:
    """Read one processed table, failing with the fix rather than a bare KeyError."""
    key = storage.processed_key(name)
    if not storage.exists(key):
        raise FileNotFoundError(f"{key} is missing; run 'make pipeline' before starting the API")
    return storage.get_parquet(key)


def _manifest_field(storage: StorageBackend, key: str, field: str) -> str | None:
    """Read one field of a JSON manifest, or None if the manifest is absent."""
    if not storage.exists(key):
        return None
    return json.loads(storage.get_bytes(key)).get(field)
