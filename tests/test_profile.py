"""Tests for the analysis layer's population rules.

The one rule worth pinning down here is *which orders count as evidence*. The
project measured three different answers to that in its own code, so the
behaviour is asserted rather than assumed.
"""

from __future__ import annotations

import pandas as pd

from ecom.analysis.profile import build_cooccurrence, select_countable_orders
from ecom.config import EXCLUDED_STATUSES


def _orders(statuses: dict[str, str]) -> pd.DataFrame:
    return pd.DataFrame({"order_id": list(statuses), "order_status": list(statuses.values())})


def test_in_flight_orders_still_count_as_evidence() -> None:
    """shipped, invoiced and processing are not failures.

    This is the whole point of the rule. Requiring delivery was measured to
    discard 32 real product pairs on this dataset while removing only 4 from
    orders that actually failed: a customer who put two products in one basket
    chose them together whatever logistics did next.
    """
    order_products = pd.DataFrame(
        {
            "order_id": ["o1", "o1", "o2", "o2", "o3", "o3", "o4", "o4"],
            "product_id": ["p1", "p2", "p1", "p2", "p1", "p2", "p1", "p2"],
        }
    )
    orders = _orders({"o1": "delivered", "o2": "shipped", "o3": "invoiced", "o4": "processing"})
    kept = select_countable_orders(order_products, orders)
    assert set(kept["order_id"]) == {"o1", "o2", "o3", "o4"}
    assert len(kept) == 8


def test_failed_orders_are_excluded() -> None:
    """canceled and unavailable are the only statuses that count as no evidence."""
    order_products = pd.DataFrame(
        {
            "order_id": ["o1", "o1", "o2", "o2", "o3", "o3"],
            "product_id": ["p1", "p2", "p1", "p2", "p1", "p2"],
        }
    )
    orders = _orders({"o1": "delivered", "o2": "canceled", "o3": "unavailable"})
    kept = select_countable_orders(order_products, orders)
    assert set(kept["order_id"]) == {"o1"}


def test_the_rule_is_not_delivered_only() -> None:
    """Guard against someone 'simplifying' this back to is_delivered."""
    assert "shipped" not in EXCLUDED_STATUSES
    assert "invoiced" not in EXCLUDED_STATUSES
    assert "processing" not in EXCLUDED_STATUSES
    assert set(EXCLUDED_STATUSES) == {"canceled", "unavailable"}


def test_excluding_a_failed_order_removes_its_pair() -> None:
    """The filter must actually change the graph, not just the row count."""
    order_products = pd.DataFrame(
        {
            "order_id": ["o1", "o1", "o2", "o2"],
            "product_id": ["p1", "p2", "p3", "p4"],
        }
    )
    orders = _orders({"o1": "delivered", "o2": "canceled"})
    all_pairs = build_cooccurrence(order_products)
    kept_pairs = build_cooccurrence(select_countable_orders(order_products, orders))
    assert len(all_pairs) == 2
    assert len(kept_pairs) == 1
    assert kept_pairs.iloc[0]["product_a"] == "p1"


def test_select_countable_orders_does_not_mutate_its_input() -> None:
    order_products = pd.DataFrame({"order_id": ["o1", "o2"], "product_id": ["p1", "p2"]})
    before = order_products.copy()
    select_countable_orders(order_products, _orders({"o1": "delivered", "o2": "canceled"}))
    pd.testing.assert_frame_equal(order_products, before)
