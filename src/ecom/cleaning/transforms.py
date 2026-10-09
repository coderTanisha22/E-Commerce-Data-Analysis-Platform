"""Pure cleaning transforms.

Every function here takes DataFrames and returns a DataFrame. None of them read
or write anything (docs/CODING_STANDARDS.md section 2), which is what keeps them
unit-testable on five-row fixtures and portable to PySpark unchanged in intent.

Each rule encodes a property measured on the real files rather than a guess.
"""

from __future__ import annotations

import logging

import pandas as pd

from ecom.config import DELIVERED_STATUS, UNKNOWN_CATEGORY
from ecom.contracts import TableContract

logger = logging.getLogger(__name__)


def trim_whitespace(df: pd.DataFrame) -> pd.DataFrame:
    """Strip leading and trailing whitespace from every string column.

    Applied before coercion so that " 12.5 " parses as a number rather than
    becoming NaN.

    Args:
        df: Any frame read from CSV.

    Returns:
        A copy with object and string columns stripped.
    """
    out = df.copy()
    for column in out.columns:
        if out[column].dtype == "object" or str(out[column].dtype) == "string":
            out[column] = out[column].str.strip()
    return out


def coerce_types(df: pd.DataFrame, contract: TableContract) -> pd.DataFrame:
    """Cast declared timestamp and numeric columns to real dtypes.

    Source CSVs are read entirely as strings so that coercion is one explicit,
    reviewable step. Unparseable values become NaT/NaN rather than raising: the
    quality gate decides whether that count is acceptable, not this function.

    Args:
        df: Frame with string columns.
        contract: Contract naming which columns are timestamps and numerics.

    Returns:
        A copy with coerced dtypes.
    """
    out = df.copy()
    for column in contract.timestamp_columns:
        if column in out.columns:
            out[column] = pd.to_datetime(out[column], errors="coerce")
    for column in contract.numeric_columns:
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="coerce")
    return out


def normalise_category(products: pd.DataFrame) -> pd.DataFrame:
    """Fill the NULL product category with an explicit unknown bucket.

    610 products have no category. Because the products table carries no name or
    description text, category is the only attribute search can match on, so
    leaving these NULL would make those products unreachable instead of merely
    uncategorised.

    Args:
        products: Frame with a ``product_category_name`` column.

    Returns:
        A copy with the category filled and a ``has_category`` flag added.
    """
    out = products.copy()
    out["has_category"] = out["product_category_name"].notna()
    out["product_category_name"] = out["product_category_name"].fillna(UNKNOWN_CATEGORY)
    filled = int((~out["has_category"]).sum())
    if filled:
        logger.info("filled %d NULL product categories with %r", filled, UNKNOWN_CATEGORY)
    return out


def attach_english_category(products: pd.DataFrame, translation: pd.DataFrame) -> pd.DataFrame:
    """Left-join English category names, falling back to the source slug.

    A LEFT join is mandatory: the translation file covers 71 of the 73 categories
    present, so an inner join would silently drop every product in ``pc_gamer``
    and ``portateis_cozinha_e_preparadores_de_alimentos``.

    Args:
        products: Frame with ``product_category_name``.
        translation: Frame with the Portuguese and English category columns.

    Returns:
        A copy with ``product_category_english`` never null.
    """
    out = products.merge(
        translation[["product_category_name", "product_category_name_english"]],
        on="product_category_name",
        how="left",
        validate="many_to_one",
    )
    missing = out["product_category_name_english"].isna()
    # UNKNOWN_CATEGORY is our own bucket, not a genuinely untranslated category.
    # Excluding it keeps this warning meaningful rather than firing on every run.
    unmapped = sorted(set(out.loc[missing, "product_category_name"].unique()) - {UNKNOWN_CATEGORY})
    if unmapped:
        logger.warning(
            "%d categories have no English name, using slug: %s", len(unmapped), unmapped
        )
    out["product_category_english"] = out["product_category_name_english"].fillna(
        out["product_category_name"]
    )
    return out.drop(columns=["product_category_name_english"])


def flag_order_status(orders: pd.DataFrame) -> pd.DataFrame:
    """Add an ``is_delivered`` flag instead of deleting non-delivered orders.

    2,963 orders are not delivered. Dropping them here would make order counts
    disagree with the source and hide cancellation rates, which the Operations
    dashboard reports. Consumers filter on the flag when they need realised
    sales; nothing is lost at this layer.

    Args:
        orders: Frame with an ``order_status`` column.

    Returns:
        A copy with ``is_delivered`` added.
    """
    out = orders.copy()
    out["is_delivered"] = out["order_status"].eq(DELIVERED_STATUS)
    return out


def derive_order_lines(order_items: pd.DataFrame) -> pd.DataFrame:
    """Collapse unit rows into order lines with a real ``quantity``.

    Olist has no quantity column: each ``order_items`` row is one unit, and
    10,225 rows repeat a (order_id, product_id) pair. Those repeats are genuine
    multi-quantity purchases, not ingestion duplicates, so they are aggregated
    rather than dropped. 112,650 unit rows become 102,425 lines, of which 7,088
    have quantity > 1, and no revenue is lost because price is summed.

    Args:
        order_items: Unit-grain frame with price and freight already numeric.

    Returns:
        One row per (order_id, product_id, seller_id) with ``quantity``,
        ``unit_price``, ``line_revenue`` and ``line_freight``.
    """
    grouped = order_items.groupby(
        ["order_id", "product_id", "seller_id"], as_index=False, sort=False
    ).agg(
        quantity=("price", "size"),
        unit_price=("price", "mean"),
        line_revenue=("price", "sum"),
        line_freight=("freight_value", "sum"),
        shipping_limit_date=("shipping_limit_date", "min"),
    )
    logger.info(
        "collapsed %d unit rows into %d order lines (%d with quantity > 1)",
        len(order_items),
        len(grouped),
        int((grouped["quantity"] > 1).sum()),
    )
    return grouped


def build_order_products(order_lines: pd.DataFrame) -> pd.DataFrame:
    """Reduce order lines to the distinct (order_id, product_id) pairs.

    This is the ``DISTINCT(order_id, product_id)`` step the co-occurrence design
    requires, isolated so that the fact table keeps its quantities while the
    graph input counts each product once per order.

    Args:
        order_lines: Output of :func:`derive_order_lines`.

    Returns:
        Two columns, deduplicated.
    """
    return order_lines[["order_id", "product_id"]].drop_duplicates().reset_index(drop=True)
