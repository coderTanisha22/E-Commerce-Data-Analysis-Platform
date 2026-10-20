"""Shared fixtures.

Deliberately tiny: a rule that needs 100k rows to test is a rule we cannot
reason about.
"""

from __future__ import annotations

import pandas as pd
import pytest


@pytest.fixture
def order_items() -> pd.DataFrame:
    """Five unit rows across three orders, including a genuine quantity-2 line.

    Order o1 buys p1 twice and p2 once, so it exercises both the quantity
    aggregation and the DISTINCT step. Order o3 is single-product, the Olist
    majority case.
    """
    return pd.DataFrame(
        {
            "order_id": ["o1", "o1", "o1", "o2", "o3"],
            "order_item_id": ["1", "2", "3", "1", "1"],
            "product_id": ["p1", "p1", "p2", "p1", "p3"],
            "seller_id": ["s1", "s1", "s2", "s1", "s3"],
            "shipping_limit_date": pd.to_datetime(
                ["2017-05-01", "2017-05-01", "2017-05-02", "2017-06-01", "2017-07-01"]
            ),
            "price": [10.0, 10.0, 25.5, 10.0, 99.0],
            "freight_value": [1.0, 1.0, 2.0, 1.5, 3.0],
        }
    )


@pytest.fixture
def products() -> pd.DataFrame:
    """Three products: one normal, one untranslated category, one NULL category."""
    return pd.DataFrame(
        {
            "product_id": ["p1", "p2", "p3"],
            "product_category_name": ["cama_mesa_banho", "pc_gamer", None],
        }
    )


@pytest.fixture
def translation() -> pd.DataFrame:
    """Translation covering only the first category, mirroring the real 71-of-73 gap."""
    return pd.DataFrame(
        {
            "product_category_name": ["cama_mesa_banho"],
            "product_category_name_english": ["bed_bath_table"],
        }
    )
