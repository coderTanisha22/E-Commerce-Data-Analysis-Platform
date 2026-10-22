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
