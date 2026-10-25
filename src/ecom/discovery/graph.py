"""Product co-occurrence graph and discovery service.

Builds an undirected NetworkX graph from validated product co-occurrence pairs
and exposes deterministic recommendations and relationship-aware search.
No machine learning or vector search: recommendations are pure graph lookups
ranked by co-occurrence order counts.
"""

from __future__ import annotations

import logging

import networkx as nx
import pandas as pd

from ecom.config import Settings, get_settings
from ecom.discovery.schemas import (
    RecommendationItem,
    RecommendationResponse,
    SearchItem,
    SearchResponse,
)
from ecom.storage import StorageBackend, get_storage

logger = logging.getLogger(__name__)


class ProductGraphService:
    """In-memory product co-occurrence graph and discovery engine.

    Uses an undirected NetworkX graph where nodes represent products and edge
    weights represent the count of distinct orders containing both products.
    """

    def __init__(
        self,
        pairs: pd.DataFrame,
        products: pd.DataFrame | None = None,
    ) -> None:
        """Initialize the graph from co-occurrence pairs and optional catalogue.

        Args:
            pairs: DataFrame with columns ``product_a``, ``product_b``, ``order_count``.
            products: Optional DataFrame with catalogue metadata including
                ``product_id`` and ``product_category_english``.
        """
        self.graph = nx.Graph()
        self._products = (
            products.set_index("product_id")
            if products is not None and "product_id" in products.columns
            else pd.DataFrame()
        )
        self._build_graph(pairs)

    def _build_graph(self, pairs: pd.DataFrame) -> None:
        """Populate the graph asserting canonical ordering and positive weights.

        Args:
            pairs: DataFrame of co-occurring product pairs.
        """
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
    ) -> RecommendationResponse:
        """Return neighbouring products ranked by co-occurrence weight.

        Ties are broken deterministically by product_id ascending, eliminating
        non-deterministic ranking when weights are equal.

        Args:
            product_id: Target product identifier.
            limit: Maximum number of recommendations to return.

        Returns:
            RecommendationResponse with ranked recommendations.
        """
        if product_id not in self.graph:
            return RecommendationResponse(product_id=product_id, recommendations=[], total_found=0)

        candidates: list[RecommendationItem] = []
        for neighbor in self.graph.neighbors(product_id):
            if neighbor == product_id:
                continue
            weight = int(self.graph[product_id][neighbor]["weight"])
            category = self._get_category(neighbor)
            candidates.append(
                RecommendationItem(product_id=neighbor, weight=weight, category=category)
            )

        # Deterministic sorting: weight descending, then product_id ascending
        candidates.sort(key=lambda item: (-item.weight, item.product_id))
        total_found = len(candidates)
        return RecommendationResponse(
            product_id=product_id,
            recommendations=candidates[:limit],
            total_found=total_found,
        )

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
    ) -> SearchResponse:
        """Search products by category keyword with optional 1-hop graph expansion.

        Direct matches appear first. Graph-expanded neighbours of direct matches
        follow, ordered by connection weight. Duplicate products are suppressed.

        Args:
            query: Search string matching category name or product ID.
            expand_graph: Whether to append 1-hop neighbours from the graph.
            limit: Maximum total results to return.

        Returns:
            SearchResponse containing ranked direct and expanded matches.
        """
        direct_ids = self._find_direct_matches(query)
        results: list[SearchItem] = []
        seen: set[str] = set()

        for pid in direct_ids:
            if pid not in seen:
                seen.add(pid)
                results.append(
                    SearchItem(
                        product_id=pid,
                        match_type="direct",
                        weight=None,
                        category=self._get_category(pid),
                    )
                )
            if len(results) >= limit:
                return SearchResponse(query=query, results=results, total_found=len(results))

        if expand_graph and direct_ids:
            self._append_expanded_neighbors(direct_ids, seen, results, limit)

        return SearchResponse(query=query, results=results, total_found=len(results))

    def _append_expanded_neighbors(
        self,
        seed_ids: list[str],
        seen: set[str],
        results: list[SearchItem],
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
                    SearchItem(
                        product_id=neighbor,
                        match_type="expanded",
                        weight=weight,
                        category=self._get_category(neighbor),
                    )
                )
            if len(results) >= limit:
                break


def load_discovery_service(
    *,
    storage: StorageBackend | None = None,
    settings: Settings | None = None,
) -> ProductGraphService:
    """Load co-occurrence pairs and products from processed storage.

    Args:
        storage: Configured storage backend (local or MinIO).
        settings: Application settings.

    Returns:
        Initialized and graph-populated ProductGraphService instance.
    """
    settings = settings or get_settings()
    storage = storage or get_storage(settings)

    pairs = storage.get_parquet(storage.processed_key("product_cooccurrence"))
    products = storage.get_parquet(storage.processed_key("products"))
    return ProductGraphService(pairs=pairs, products=products)
