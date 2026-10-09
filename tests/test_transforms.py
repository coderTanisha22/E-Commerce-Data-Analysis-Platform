"""Unit tests for the pure cleaning transforms."""

from __future__ import annotations

import pandas as pd

from ecom.cleaning.transforms import (
    attach_english_category,
    build_order_products,
    coerce_types,
    derive_order_lines,
    flag_order_status,
    normalise_category,
    trim_whitespace,
)
from ecom.config import UNKNOWN_CATEGORY
from ecom.contracts import ORDER_ITEMS


def test_derive_order_lines_aggregates_repeats_into_quantity(order_items: pd.DataFrame) -> None:
    lines = derive_order_lines(order_items)
    o1_p1 = lines[(lines.order_id == "o1") & (lines.product_id == "p1")].iloc[0]
    assert o1_p1.quantity == 2, "two unit rows for the same product are one line of quantity 2"
    assert o1_p1.line_revenue == 20.0
    assert o1_p1.unit_price == 10.0


def test_derive_order_lines_preserves_total_revenue(order_items: pd.DataFrame) -> None:
    """The collapse must aggregate, never deduplicate - this is the money invariant."""
    lines = derive_order_lines(order_items)
    assert lines["line_revenue"].sum() == order_items["price"].sum()
    assert lines["quantity"].sum() == len(order_items)


def test_derive_order_lines_reduces_row_count(order_items: pd.DataFrame) -> None:
    assert len(derive_order_lines(order_items)) == 4  # 5 unit rows -> 4 lines


def test_build_order_products_counts_each_product_once_per_order(
    order_items: pd.DataFrame,
) -> None:
    pairs = build_order_products(derive_order_lines(order_items))
    o1 = pairs[pairs.order_id == "o1"]
    assert set(o1.product_id) == {"p1", "p2"}
    assert len(o1) == 2, "p1 bought twice must appear once"
    assert not pairs.duplicated(["order_id", "product_id"]).any()


def test_normalise_category_fills_nulls_and_flags_them(products: pd.DataFrame) -> None:
    out = normalise_category(products)
    assert out.loc[out.product_id == "p3", "product_category_name"].item() == UNKNOWN_CATEGORY
    assert not out.loc[out.product_id == "p3", "has_category"].item()
    assert out.loc[out.product_id == "p1", "has_category"].item()
    assert out["product_category_name"].notna().all()


def test_attach_english_category_keeps_untranslated_rows(
    products: pd.DataFrame, translation: pd.DataFrame
) -> None:
    """A LEFT join with slug fallback: an inner join would silently drop pc_gamer."""
    out = attach_english_category(normalise_category(products), translation)
    assert len(out) == len(products), "no product may be lost to a missing translation"
    assert out["product_category_english"].notna().all()
    assert out.loc[out.product_id == "p1", "product_category_english"].item() == "bed_bath_table"
    assert out.loc[out.product_id == "p2", "product_category_english"].item() == "pc_gamer"


def test_flag_order_status_marks_without_dropping() -> None:
    orders = pd.DataFrame({"order_id": ["a", "b"], "order_status": ["delivered", "canceled"]})
    out = flag_order_status(orders)
    assert len(out) == 2, "non-delivered orders are flagged, never removed"
    assert out.loc[out.order_id == "a", "is_delivered"].item()
    assert not out.loc[out.order_id == "b", "is_delivered"].item()


def test_trim_whitespace_enables_numeric_coercion() -> None:
    df = pd.DataFrame({"price": [" 12.5 "], "freight_value": ["1.0"]}, dtype="string")
    coerced = coerce_types(trim_whitespace(df), ORDER_ITEMS)
    assert coerced["price"].item() == 12.5


def test_coerce_types_turns_unparseable_into_na_rather_than_raising() -> None:
    df = pd.DataFrame({"price": ["not-a-number"], "freight_value": ["2.0"]}, dtype="string")
    coerced = coerce_types(df, ORDER_ITEMS)
    assert pd.isna(coerced["price"].item()), "the quality gate decides, not the transform"


def test_transforms_do_not_mutate_their_input(order_items: pd.DataFrame) -> None:
    """The purity rule, enforced: a transform returning a copy cannot surprise a caller."""
    before = order_items.copy()
    derive_order_lines(order_items)
    trim_whitespace(order_items)
    pd.testing.assert_frame_equal(order_items, before)
