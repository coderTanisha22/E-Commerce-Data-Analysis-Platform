"""Product discovery and co-occurrence graph package.

Provides deterministic product recommendation, relationship-aware search,
synthetic display naming, and interactive graph visualization built on
historical basket co-occurrence data.
"""

from __future__ import annotations

from ecom.discovery.graph import ProductGraphService, load_discovery_service
from ecom.discovery.names import synthesize_product_name
from ecom.discovery.schemas import (
    GraphDataResponse,
    GraphLink,
    GraphNode,
    RecommendationItem,
    RecommendationResponse,
    SearchItem,
    SearchResponse,
)
from ecom.discovery.visualize import render_interactive_graph_html

__all__ = [
    "GraphDataResponse",
    "GraphLink",
    "GraphNode",
    "ProductGraphService",
    "RecommendationItem",
    "RecommendationResponse",
    "SearchItem",
    "SearchResponse",
    "load_discovery_service",
    "render_interactive_graph_html",
    "synthesize_product_name",
]
