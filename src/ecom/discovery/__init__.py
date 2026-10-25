"""Product discovery and co-occurrence graph package.

Provides deterministic product recommendation and relationship-aware search
functionality built on historical basket co-occurrence data.
"""

from __future__ import annotations

from ecom.discovery.graph import ProductGraphService, load_discovery_service
from ecom.discovery.schemas import (
    RecommendationItem,
    RecommendationResponse,
    SearchItem,
    SearchResponse,
)

__all__ = [
    "ProductGraphService",
    "load_discovery_service",
    "RecommendationItem",
    "RecommendationResponse",
    "SearchItem",
    "SearchResponse",
]
