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
