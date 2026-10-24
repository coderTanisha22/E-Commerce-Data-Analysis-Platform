"""Product co-occurrence graph and discovery service."""

from __future__ import annotations

import logging
import networkx as nx
import pandas as pd

logger = logging.getLogger(__name__)


class ProductGraphService:
    """In-memory product co-occurrence graph and discovery engine."""

    def __init__(
        self,
        pairs: pd.DataFrame,
        products: pd.DataFrame | None = None,
    ) -> None:
        self.graph = nx.Graph()
        self._products = (
            products.set_index("product_id")
            if products is not None and "product_id" in products.columns
            else pd.DataFrame()
        )
        self._build_graph(pairs)

    def _build_graph(self, pairs: pd.DataFrame) -> None:
        """Populate the graph asserting canonical ordering and positive weights."""
        for row in pairs.itertuples(index=False):
            prod_a = str(row.product_a)
            prod_b = str(row.product_b)
            count = int(row.order_count)

            if prod_a == prod_b:
                logger.warning("skipping self-pair for product %s", prod_a)
                continue
            if prod_a > prod_b:
                prod_a, prod_b = prod_b, prod_a

            self.graph.add_edge(prod_a, prod_b, weight=count)

    def _get_category(self, product_id: str) -> str | None:
        """Lookup English category name from catalogue metadata if present."""
        if not self._products.empty and product_id in self._products.index:
            val = self._products.loc[product_id, "product_category_english"]
            if pd.notna(val):
                return str(val)
        return None

    def get_recommendations(
        self,
        product_id: str,
        limit: int = 5,
    ) -> list[dict[str, object]]:
        """Return neighbouring products ranked by co-occurrence weight.

        Ties are broken deterministically by product_id ascending, eliminating
        non-deterministic ranking when weights are equal.

        Args:
            product_id: Target product identifier.
            limit: Maximum number of recommendations to return.

        Returns:
            List of dicts with keys 'product_id', 'weight', and 'category'.
        """
        if product_id not in self.graph:
            return []

        candidates: list[dict[str, object]] = []
        for neighbor in self.graph.neighbors(product_id):
            if neighbor == product_id:
                continue
            weight = int(self.graph[product_id][neighbor]["weight"])
            category = self._get_category(neighbor)
            candidates.append(
                {"product_id": neighbor, "weight": weight, "category": category}
            )

        # Deterministic sorting: weight descending, then product_id ascending
        candidates.sort(key=lambda item: (-int(item["weight"]), str(item["product_id"])))
        return candidates[:limit]

    def _find_direct_matches(self, query: str) -> list[str]:
        """Find product IDs matching query against category or product ID."""
        if self._products.empty or not query.strip():
            return []

        q = query.strip().lower()
        cat_series = self._products["product_category_english"].astype(str).str.lower()
        mask = cat_series.str.contains(q, na=False) | (self._products.index.str.lower() == q)
        return list(self._products[mask].index)

    def search_products(
        self,
        query: str,
        expand_graph: bool = True,
        limit: int = 10,
    ) -> list[dict[str, object]]:
        """Search products by category keyword with optional 1-hop graph expansion.

        Direct matches appear first. Graph-expanded neighbours of direct matches
        follow, ordered by connection weight. Duplicate products are suppressed.

        Args:
            query: Search string matching category name or product ID.
            expand_graph: Whether to append 1-hop neighbours from the graph.
            limit: Maximum total results to return.

        Returns:
            List of dicts containing ranked direct and expanded matches.
        """
        direct_ids = self._find_direct_matches(query)
        results: list[dict[str, object]] = []
        seen: set[str] = set()

        for pid in direct_ids:
            if pid not in seen:
                seen.add(pid)
                results.append(
                    {
                        "product_id": pid,
                        "match_type": "direct",
                        "weight": None,
                        "category": self._get_category(pid),
                    }
                )
            if len(results) >= limit:
                return results

        if expand_graph and direct_ids:
            self._append_expanded_neighbors(direct_ids, seen, results, limit)

        return results

    def _append_expanded_neighbors(
        self,
        seed_ids: list[str],
        seen: set[str],
        results: list[dict[str, object]],
        limit: int,
    ) -> None:
        """Append 1-hop graph neighbors of seed products ordered by weight."""
        expanded: list[tuple[str, int]] = []
        for seed in seed_ids:
            if seed in self.graph:
                for neighbor in self.graph.neighbors(seed):
                    if neighbor not in seen:
                        w = int(self.graph[seed][neighbor]["weight"])
                        expanded.append((neighbor, w))

        # Highest weight first, then product_id ascending
        expanded.sort(key=lambda pair: (-pair[1], pair[0]))
        for neighbor, weight in expanded:
            if neighbor not in seen:
                seen.add(neighbor)
                results.append(
                    {
                        "product_id": neighbor,
                        "match_type": "expanded",
                        "weight": weight,
                        "category": self._get_category(neighbor),
                    }
                )
            if len(results) >= limit:
                break
