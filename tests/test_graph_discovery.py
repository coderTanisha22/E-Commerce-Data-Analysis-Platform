"""Tests for product discovery and graph construction.

Validates:
- Worked-example correctness from guide page 7 (Order 1: A, B, B; Order 2: A, C)
- Duplicate product lines in a single order do not inflate edge weights
- Self-pairs (A, A) are safely excluded from the graph
- Deterministic ranked recommendations with tie-breaking
- No self-recommendations
- Unknown products return empty recommendations safely
- Relationship-aware search with direct-before-expanded ranking and deduplication
"""

from __future__ import annotations

import pandas as pd
import pytest

from ecom.analysis.profile import build_cooccurrence
from ecom.discovery.graph import ProductGraphService


@pytest.fixture
def sample_products() -> pd.DataFrame:
    """Fixture providing toy product metadata."""
    return pd.DataFrame(
        {
            "product_id": ["p_apple", "p_banana", "p_cherry", "p_date", "p_elderberry"],
            "product_category_english": [
                "fruit",
                "fruit",
                "fruit",
                "dried_fruit",
                "berries",
            ],
        }
    )


def test_hand_calculated_worked_example() -> None:
    """Worked example from sequential implementation guide (page 7).

    Order 1 contains A, B, B.
    Order 2 contains A, C.
    Deduplicated memberships: (1, A), (1, B), (2, A), (2, C).
    Expected pairs: (A, B) = 1, (A, C) = 1.
    No (B, B) self-edge, and no (B, C) edge.
    """
    raw_memberships = pd.DataFrame(
        {
            "order_id": ["o1", "o1", "o1", "o2", "o2"],
            "product_id": ["A", "B", "B", "A", "C"],
        }
    ).drop_duplicates()

    pairs_df = build_cooccurrence(raw_memberships)
    service = ProductGraphService(pairs=pairs_df)

    assert service.graph.number_of_nodes() == 3
    assert service.graph.number_of_edges() == 2
    assert service.graph.has_edge("A", "B")
    assert service.graph.has_edge("A", "C")
    assert not service.graph.has_edge("B", "C")
    assert not service.graph.has_edge("B", "B")

    assert service.graph["A"]["B"]["weight"] == 1
    assert service.graph["A"]["C"]["weight"] == 1


def test_duplicate_product_lines_in_order_do_not_inflate_weight() -> None:
    """Multiple identical products in one order must contribute only 1 membership."""
    memberships = pd.DataFrame(
        {
            "order_id": ["o1", "o1", "o1", "o1"],
            "product_id": ["prod_1", "prod_1", "prod_2", "prod_2"],
        }
    ).drop_duplicates()

    pairs_df = build_cooccurrence(memberships)
    service = ProductGraphService(pairs=pairs_df)

    assert service.graph.number_of_edges() == 1
    assert service.graph["prod_1"]["prod_2"]["weight"] == 1


def test_self_pairs_are_excluded() -> None:
    """A self-pair (A, A) must never create a self-loop in the graph."""
    pairs_df = pd.DataFrame(
        {
            "product_a": ["p1", "p1"],
            "product_b": ["p1", "p2"],
            "order_count": [5, 2],
        }
    )
    service = ProductGraphService(pairs=pairs_df)
    assert not service.graph.has_edge("p1", "p1")
    assert service.graph.has_edge("p1", "p2")
    assert service.graph["p1"]["p2"]["weight"] == 2


def test_recommendations_ranking_and_deterministic_tie_breaking(
    sample_products: pd.DataFrame,
) -> None:
    """Recommendations sort by weight DESC, then product_id ASC for ties."""
    pairs_df = pd.DataFrame(
        {
            "product_a": ["target", "target", "target"],
            "product_b": ["p_date", "p_banana", "p_cherry"],
            "order_count": [2, 5, 2],
        }
    )
    service = ProductGraphService(pairs=pairs_df, products=sample_products)
    recs = service.get_recommendations("target", limit=5)

    assert len(recs) == 3
    # p_banana has highest weight (5)
    assert recs[0]["product_id"] == "p_banana"
    assert recs[0]["weight"] == 5

    # p_cherry and p_date are tied at weight 2 -> p_cherry wins alphabetical tie-break
    assert recs[1]["product_id"] == "p_cherry"
    assert recs[1]["weight"] == 2
    assert recs[2]["product_id"] == "p_date"
    assert recs[2]["weight"] == 2


def test_no_self_recommendation(sample_products: pd.DataFrame) -> None:
    """The requested product must never be recommended to itself."""
    pairs_df = pd.DataFrame(
        {
            "product_a": ["p_apple", "p_apple"],
            "product_b": ["p_banana", "p_cherry"],
            "order_count": [3, 2],
        }
    )
    service = ProductGraphService(pairs=pairs_df, products=sample_products)
    recs = service.get_recommendations("p_apple", limit=5)

    rec_ids = [r["product_id"] for r in recs]
    assert "p_apple" not in rec_ids


def test_unknown_product_returns_empty_recommendations(
    sample_products: pd.DataFrame,
) -> None:
    """Unknown product ID returns an empty list without crashing."""
    pairs_df = pd.DataFrame(
        {
            "product_a": ["p_apple"],
            "product_b": ["p_banana"],
            "order_count": [1],
        }
    )
    service = ProductGraphService(pairs=pairs_df, products=sample_products)
    recs = service.get_recommendations("non_existent_id")
    assert recs == []


def test_search_direct_before_expanded_and_deduplicated(
    sample_products: pd.DataFrame,
) -> None:
    """Direct matches appear before expanded neighbors; duplicates are eliminated."""
    # p_apple, p_banana, p_cherry have category 'fruit' (direct matches).
    # p_elderberry is 'berries' (not fruit), but connected to p_apple in graph.
    pairs_df = pd.DataFrame(
        {
            "product_a": ["p_apple", "p_banana"],
            "product_b": ["p_elderberry", "p_cherry"],
            "order_count": [4, 1],
        }
    )
    service = ProductGraphService(pairs=pairs_df, products=sample_products)
    results = service.search_products(query="fruit", expand_graph=True, limit=10)

    # Direct matches must be first
    assert results[0]["match_type"] == "direct"
    assert results[1]["match_type"] == "direct"
    assert results[2]["match_type"] == "direct"

    # Expanded match comes after direct matches
    expanded = [r for r in results if r["match_type"] == "expanded"]
    assert len(expanded) == 1
    assert expanded[0]["product_id"] == "p_elderberry"
    assert expanded[0]["weight"] == 4

    # Ensure no duplicates
    result_ids = [r["product_id"] for r in results]
    assert len(result_ids) == len(set(result_ids))


def test_search_respects_limit(sample_products: pd.DataFrame) -> None:
    """Search truncates results when limit is reached."""
    pairs_df = pd.DataFrame(
        {
            "product_a": ["p_apple"],
            "product_b": ["p_banana"],
            "order_count": [1],
        }
    )
    service = ProductGraphService(pairs=pairs_df, products=sample_products)
    results = service.search_products(query="fruit", limit=2)
    assert len(results) == 2


def test_empty_search_query_returns_empty_list(
    sample_products: pd.DataFrame,
) -> None:
    """Empty or whitespace search query returns empty list."""
    pairs_df = pd.DataFrame(
        {
            "product_a": ["p_apple"],
            "product_b": ["p_banana"],
            "order_count": [1],
        }
    )
    service = ProductGraphService(pairs=pairs_df, products=sample_products)
    results = service.search_products(query="   ")
    assert results == []
