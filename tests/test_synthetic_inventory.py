"""Validity tests for the synthetic inventory table.

Grouped to match the validation report: structural validity, reproducibility,
and faithfulness to the real data. Seed stability and sensitivity are reported
by the validation script rather than asserted here, because they describe a
distribution rather than a pass/fail property.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ecom.synthetic.inventory import (
    REAL_COLUMNS,
    GeneratorParams,
    assign_lead_times,
    build_sales_base,
    classify_status,
    generate_synthetic_inventory,
)
from ecom.synthetic.run_generate import frame_digest

# --------------------------------------------------------------------- fixtures


@pytest.fixture
def orders() -> pd.DataFrame:
    """Six orders: one cancelled, one outside the window, four usable."""
    return pd.DataFrame(
        {
            "order_id": ["o1", "o2", "o3", "o4", "o5", "o6"],
            "order_status": [
                "delivered",
                "delivered",
                "delivered",
                "canceled",
                "delivered",
                "unavailable",
            ],
            "order_purchase_timestamp": pd.to_datetime(
                [
                    "2017-03-01",
                    "2017-04-01",
                    "2018-08-30",
                    "2017-05-01",
                    "2016-10-01",
                    "2018-01-01",
                ]
            ),
        }
    )


@pytest.fixture
def order_lines() -> pd.DataFrame:
    """Lines for those orders. Seller s1 sells p1 three times, s2 sells p2 once."""
    return pd.DataFrame(
        {
            "order_id": ["o1", "o2", "o3", "o4", "o5", "o6"],
            "product_id": ["p1", "p1", "p1", "p1", "p1", "p2"],
            "seller_id": ["s1", "s1", "s1", "s1", "s1", "s2"],
            "quantity": [1, 1, 1, 5, 9, 4],
        }
    )


@pytest.fixture
def params() -> GeneratorParams:
    return GeneratorParams()


@pytest.fixture
def table(order_lines, orders, params) -> pd.DataFrame:
    return generate_synthetic_inventory(order_lines, orders, params)


# ------------------------------------------------------- A. structural validity


def test_grain_is_unique_on_seller_and_product(table: pd.DataFrame) -> None:
    assert not table.duplicated(["seller_id", "product_id"]).any()


def test_every_pair_exists_in_order_lines(table, order_lines) -> None:
    """Foreign key: the generator must not invent a seller-product pair."""
    source = set(map(tuple, order_lines[["seller_id", "product_id"]].drop_duplicates().values))
    generated = set(map(tuple, table[["seller_id", "product_id"]].values))
    assert generated <= source


def test_no_nulls_anywhere(table: pd.DataFrame) -> None:
    assert table.notna().all().all()


def test_quantities_and_rates_are_non_negative(table: pd.DataFrame) -> None:
    for column in (
        "units_sold",
        "active_days",
        "daily_sales_rate",
        "reorder_point",
        "current_quantity",
        "days_of_inventory",
    ):
        assert (table[column] >= 0).all(), column


def test_lead_time_within_declared_range(table, params) -> None:
    low, high = params.lead_time_range
    assert table["lead_time_days"].between(low, high).all()


def test_one_lead_time_per_seller(table: pd.DataFrame) -> None:
    """Lead time belongs to a supplier relationship, not to a product."""
    distinct_pairs = table[["seller_id", "lead_time_days"]].drop_duplicates()
    assert len(distinct_pairs) == table["seller_id"].nunique()


def test_reorder_point_formula_holds_on_every_row(table, params) -> None:
    expected = np.maximum(
        1, np.ceil(table["daily_sales_rate"] * (table["lead_time_days"] + params.safety_days))
    ).astype("int64")
    pd.testing.assert_series_equal(
        table["reorder_point"], expected, check_names=False, check_dtype=False
    )


def test_days_of_inventory_formula_holds(table: pd.DataFrame) -> None:
    expected = table["current_quantity"] / table["daily_sales_rate"]
    np.testing.assert_allclose(table["days_of_inventory"], expected, rtol=1e-9)


def test_status_rule_holds_on_every_row(table, params) -> None:
    doi, lead = table["days_of_inventory"], table["lead_time_days"]
    expected = np.where(
        table["evidence"] == "insufficient",
        "Insufficient data",
        np.where(
            doi < lead,
            "Urgent",
            np.where(doi < lead + params.monitor_extra_days, "Monitor", "Healthy"),
        ),
    )
    assert (table["status"].to_numpy() == expected).all()


def test_every_row_is_flagged_synthetic(table: pd.DataFrame) -> None:
    assert table["is_synthetic"].all()


def test_generator_does_not_mutate_its_inputs(order_lines, orders, params) -> None:
    """We never touch real data: the inputs must come back unchanged."""
    lines_before, orders_before = order_lines.copy(), orders.copy()
    generate_synthetic_inventory(order_lines, orders, params)
    pd.testing.assert_frame_equal(order_lines, lines_before)
    pd.testing.assert_frame_equal(orders, orders_before)


# ------------------------------------------------------------ B. reproducibility


def test_same_seed_gives_identical_digest(order_lines, orders) -> None:
    a = generate_synthetic_inventory(order_lines, orders, GeneratorParams(seed=42))
    b = generate_synthetic_inventory(order_lines, orders, GeneratorParams(seed=42))
    assert frame_digest(a) == frame_digest(b)


def test_different_seed_gives_different_digest(order_lines, orders) -> None:
    a = generate_synthetic_inventory(order_lines, orders, GeneratorParams(seed=42))
    b = generate_synthetic_inventory(order_lines, orders, GeneratorParams(seed=7))
    assert frame_digest(a) != frame_digest(b)


def test_seed_changes_only_synthetic_columns(order_lines, orders) -> None:
    """The real-derived columns must be identical no matter the seed."""
    a = generate_synthetic_inventory(order_lines, orders, GeneratorParams(seed=42))
    b = generate_synthetic_inventory(order_lines, orders, GeneratorParams(seed=7))
    pd.testing.assert_frame_equal(a[list(REAL_COLUMNS)], b[list(REAL_COLUMNS)])


# ----------------------------------------------------- C. faithfulness to source


def test_units_sold_recomputed_independently_matches(table, order_lines, orders, params) -> None:
    """Recompute from the source with a different code path and compare."""
    joined = order_lines.merge(orders, on="order_id")
    usable = joined[
        ~joined["order_status"].isin(params.excluded_statuses)
        & joined["order_purchase_timestamp"].between(
            pd.Timestamp(params.window[0]), pd.Timestamp(params.window[1])
        )
    ]
    expected = usable.groupby(["seller_id", "product_id"])["quantity"].sum()
    for row in table.itertuples(index=False):
        assert row.units_sold == expected.loc[(row.seller_id, row.product_id)]


def test_daily_sales_rate_equals_units_over_active_days(table: pd.DataFrame) -> None:
    np.testing.assert_allclose(
        table["daily_sales_rate"], table["units_sold"] / table["active_days"], rtol=1e-12
    )


def test_active_days_respects_its_floor(table, params) -> None:
    assert (table["active_days"] >= params.min_active_days).all()


def test_cancelled_and_out_of_window_orders_are_excluded(table: pd.DataFrame) -> None:
    """p1 sold 5 units in a cancelled order and 9 outside the window; only 3 count."""
    row = table[(table.seller_id == "s1") & (table.product_id == "p1")].iloc[0]
    assert row.units_sold == 3
    assert (table.product_id == "p2").sum() == 0, "unavailable-only pair must not appear"


def test_evidence_threshold_labels_weak_rows(order_lines, orders) -> None:
    table = generate_synthetic_inventory(order_lines, orders, GeneratorParams(evidence_min_units=4))
    assert (table["evidence"] == "insufficient").all()
    assert (table["status"] == "Insufficient data").all()


# ------------------------------------------------------------ unit-level checks


def test_assign_lead_times_is_deterministic_and_sorted(params) -> None:
    sellers = pd.Series(["s3", "s1", "s2", "s1"])
    a = assign_lead_times(sellers, np.random.default_rng(42), params)
    b = assign_lead_times(sellers, np.random.default_rng(42), params)
    pd.testing.assert_frame_equal(a, b)
    assert list(a["seller_id"]) == ["s1", "s2", "s3"]


def test_classify_status_boundaries(params) -> None:
    """Exactly at the lead time is Monitor, not Urgent: the rule uses <, not <=."""
    df = pd.DataFrame(
        {
            "evidence": ["sufficient"] * 3,
            "daily_sales_rate": [1.0, 1.0, 1.0],
            "current_quantity": [9, 10, 20],
            "lead_time_days": [10, 10, 10],
        }
    )
    out = classify_status(df, params)
    assert list(out["status"]) == ["Urgent", "Monitor", "Healthy"]


def test_build_sales_base_has_no_synthetic_columns(order_lines, orders, params) -> None:
    base = build_sales_base(order_lines, orders, params)
    assert set(base.columns) == set(REAL_COLUMNS)
