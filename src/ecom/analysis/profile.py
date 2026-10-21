"""Profiling metrics computed from the processed layer.

Every figure the project quotes in a report comes from here, so the numbers in
prose and the numbers in the warehouse cannot drift apart. The module returns
plain dicts rather than printing, keeping it usable from the CLI, a test, or an
Airflow task.
"""

from __future__ import annotations

import itertools
import logging
from collections import Counter

import networkx as nx
import pandas as pd

from ecom.config import EXCLUDED_STATUSES, MIN_COOCCURRENCE_COUNT, Settings, get_settings
from ecom.storage import StorageBackend, get_storage

logger = logging.getLogger(__name__)


def select_countable_orders(
    order_products: pd.DataFrame,
    orders: pd.DataFrame,
    excluded_statuses: tuple[str, ...] = EXCLUDED_STATUSES,
) -> pd.DataFrame:
    """Drop memberships belonging to orders that genuinely failed.

    The cleaning layer flags order status rather than deleting rows, so the
    decision about which orders count as evidence belongs here, to the
    consumer. ``order_products`` carries no status of its own, so the flag is
    joined back on.

    The filter is ``canceled`` and ``unavailable`` only -- deliberately not
    ``is_delivered``. Measured on this dataset, requiring delivery would drop
    32 product pairs belonging to orders that were merely still in flight
    (``shipped``, ``invoiced``, ``processing``) while removing only 4 belonging
    to orders that actually failed. A customer who put two products in one
    basket chose them together regardless of what logistics did afterwards.

    Args:
        order_products: Deduplicated (order_id, product_id) frame.
        orders: Frame carrying ``order_id`` and ``order_status``.
        excluded_statuses: Statuses treated as no evidence at all.

    Returns:
        ``order_products`` less the rows whose order failed.
    """
    status = orders.set_index("order_id")["order_status"]
    failed = order_products["order_id"].map(status).isin(excluded_statuses)
    dropped = int(failed.sum())
    if dropped:
        logger.info(
            "excluded %d order-product rows in statuses %s", dropped, list(excluded_statuses)
        )
    return order_products.loc[~failed].reset_index(drop=True)


def build_cooccurrence(order_products: pd.DataFrame) -> pd.DataFrame:
    """Count how many distinct orders contain each unordered product pair.

    Implements the documented rule set: input is already deduplicated to
    (order_id, product_id), pairs are emitted with ``product_a < product_b`` so a
    pair is stored once, and self-pairs cannot occur.

    Args:
        order_products: Deduplicated (order_id, product_id) frame.

    Returns:
        Columns ``product_a``, ``product_b``, ``order_count``, sorted by count
        descending.
    """
    basket_sizes = order_products.groupby("order_id")["product_id"].size()
    multi = basket_sizes[basket_sizes >= 2].index
    baskets = order_products[order_products["order_id"].isin(multi)].groupby("order_id")[
        "product_id"
    ]

    counter: Counter[tuple[str, str]] = Counter()
    for _, products in baskets:
        for pair in itertools.combinations(sorted(set(products)), 2):
            counter[pair] += 1

    pairs = pd.DataFrame(
        [(a, b, n) for (a, b), n in counter.items()],
        columns=["product_a", "product_b", "order_count"],
    )
    logger.info(
        "co-occurrence: %d multi-product orders produced %d unique pairs",
        len(multi),
        len(pairs),
    )
    return pairs.sort_values("order_count", ascending=False, ignore_index=True)


def profile_cooccurrence(order_products: pd.DataFrame, pairs: pd.DataFrame) -> dict[str, object]:
    """Summarise basket sparsity and the shape of the resulting graph."""
    sizes = order_products.groupby("order_id")["product_id"].size()
    graph = nx.Graph()
    for row in pairs.itertuples(index=False):
        graph.add_edge(row.product_a, row.product_b, weight=row.order_count)

    components = sorted((len(c) for c in nx.connected_components(graph)), reverse=True)
    degrees = pd.Series([d for _, d in graph.degree()], dtype="int64")
    served = pairs[pairs["order_count"] >= MIN_COOCCURRENCE_COUNT]

    return {
        "orders_total": len(sizes),
        "orders_multi_product": int((sizes >= 2).sum()),
        "multi_product_share_pct": round(100 * float((sizes >= 2).mean()), 2),
        "basket_size_distribution": {int(k): int(v) for k, v in sizes.value_counts().items()},
        "pairs_total": len(pairs),
        "pairs_weight_1": int((pairs["order_count"] == 1).sum()),
        "weight_1_share_pct": round(100 * float((pairs["order_count"] == 1).mean()), 2),
        "pair_weight_distribution": {
            int(k): int(v) for k, v in pairs["order_count"].value_counts().items()
        },
        "graph_nodes": graph.number_of_nodes(),
        "graph_edges": graph.number_of_edges(),
        "components": len(components),
        "largest_component": components[0] if components else 0,
        "mean_degree": round(float(degrees.mean()), 3) if len(degrees) else 0.0,
        "degree_1_share_pct": round(100 * float((degrees == 1).mean()), 2) if len(degrees) else 0.0,
        "pairs_at_or_above_threshold": len(served),
        "cooccurrence_threshold": MIN_COOCCURRENCE_COUNT,
    }


def profile_sales(
    orders: pd.DataFrame, order_lines: pd.DataFrame, settings: Settings
) -> dict[str, object]:
    """Compute headline sales metrics inside the configured window."""
    joined = order_lines.merge(
        orders[["order_id", "order_purchase_timestamp", "is_delivered"]], on="order_id", how="inner"
    )
    start = pd.Timestamp(settings.window_start)
    end = pd.Timestamp(settings.window_end) + pd.Timedelta(days=1)
    in_window = joined[
        joined["order_purchase_timestamp"].between(start, end, inclusive="left")
        & joined["is_delivered"]
    ]

    revenue = float(in_window["line_revenue"].sum())
    order_count = int(in_window["order_id"].nunique())
    monthly = joined.set_index("order_purchase_timestamp")["order_id"].resample("MS").nunique()

    return {
        "window_start": str(settings.window_start),
        "window_end": str(settings.window_end),
        "window_days": settings.window_days,
        "revenue_brl": round(revenue, 2),
        "units_sold": int(in_window["quantity"].sum()),
        "orders_in_window": order_count,
        "average_order_value_brl": round(revenue / order_count, 2) if order_count else 0.0,
        "orders_by_month": {str(k.date()): int(v) for k, v in monthly.items()},
    }


def profile_velocity(
    orders: pd.DataFrame, order_lines: pd.DataFrame, settings: Settings
) -> dict[str, object]:
    """Compute per-seller-product sales velocity inside the window.

    This is the input the synthetic inventory generator needs: without it,
    ``current_quantity`` cannot be expressed as days of cover and the restock
    rule degenerates into a constant.
    """
    joined = order_lines.merge(
        orders[["order_id", "order_purchase_timestamp", "is_delivered"]], on="order_id", how="inner"
    )
    start = pd.Timestamp(settings.window_start)
    end = pd.Timestamp(settings.window_end) + pd.Timedelta(days=1)
    in_window = joined[
        joined["order_purchase_timestamp"].between(start, end, inclusive="left")
        & joined["is_delivered"]
    ]

    per_pair = in_window.groupby(["seller_id", "product_id"], as_index=False)["quantity"].sum()
    per_pair["units_per_day"] = per_pair["quantity"] / settings.window_days

    return {
        "seller_products_with_sales": len(per_pair),
        "units_per_day_median": round(float(per_pair["units_per_day"].median()), 6),
        "units_per_day_max": round(float(per_pair["units_per_day"].max()), 4),
        "sold_once_only": int((per_pair["quantity"] == 1).sum()),
        "sold_once_share_pct": round(100 * float((per_pair["quantity"] == 1).mean()), 2),
        "units_distribution_head": {
            int(k): int(v) for k, v in per_pair["quantity"].value_counts().head(8).items()
        },
    }


def build_profile(
    *,
    storage: StorageBackend | None = None,
    settings: Settings | None = None,
) -> dict[str, object]:
    """Read the processed layer and return the full profile.

    Returns:
        Nested dict with ``sales``, ``cooccurrence`` and ``velocity`` sections.
    """
    settings = settings or get_settings()
    storage = storage or get_storage(settings)

    orders = storage.get_parquet(storage.processed_key("orders"))
    order_lines = storage.get_parquet(storage.processed_key("order_lines"))
    order_products = storage.get_parquet(storage.processed_key("order_products"))
    products = storage.get_parquet(storage.processed_key("products"))

    # Co-occurrence is computed over orders that were really placed, which is
    # not the same population as realised revenue below: sales keeps the
    # stricter delivered-only filter because an in-flight order is not money
    # yet, while a basket is a basket as soon as it is ordered.
    countable = select_countable_orders(order_products, orders)
    pairs = build_cooccurrence(countable)
    storage.put_parquet(storage.processed_key("product_cooccurrence"), pairs)

    return {
        "catalogue": {
            "products": len(products),
            "products_without_category": int((~products["has_category"]).sum()),
            "distinct_categories": int(products["product_category_english"].nunique()),
        },
        "sales": profile_sales(orders, order_lines, settings),
        "cooccurrence": profile_cooccurrence(countable, pairs),
        "velocity": profile_velocity(orders, order_lines, settings),
    }
