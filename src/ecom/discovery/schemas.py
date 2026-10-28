"""Pydantic schemas for product discovery and search endpoints.

These models define the API contract between Person C's discovery service
and Person D's FastAPI routing and dashboard layer.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RecommendationItem(BaseModel):
    """A single product recommended via graph co-occurrence."""

    product_id: str = Field(..., description="Unique product identifier")
    product_name: str = Field(..., description="Deterministic human-readable display title")
    weight: int = Field(..., ge=1, description="Number of orders containing both products")
    category: str | None = Field(None, description="English category name of the product")


class RecommendationResponse(BaseModel):
    """Response payload for product recommendations."""

    product_id: str = Field(..., description="Query product identifier")
    recommendations: list[RecommendationItem] = Field(
        default_factory=list, description="Ranked list of neighboring products"
    )
    total_found: int = Field(..., ge=0, description="Total recommendation candidates available")


class SearchItem(BaseModel):
    """A search result item, either a direct match or a graph-expanded neighbor."""

    product_id: str = Field(..., description="Unique product identifier")
    product_name: str = Field(..., description="Deterministic human-readable display title")
    match_type: Literal["direct", "expanded"] = Field(
        ..., description="Direct category/keyword match or 1-hop graph expansion"
    )
    weight: int | None = Field(
        None, description="Co-occurrence weight to the seed match (expanded only)"
    )
    category: str | None = Field(None, description="English category name")


class SearchResponse(BaseModel):
    """Response payload for relationship-aware search."""

    query: str = Field(..., description="Search query string")
    results: list[SearchItem] = Field(
        default_factory=list, description="Ranked list of matching products"
    )
    total_found: int = Field(..., ge=0, description="Total search results returned")


class GraphNode(BaseModel):
    """A node representing a product in the graph for frontend visualization."""

    id: str = Field(..., description="Unique product identifier")
    name: str = Field(..., description="Deterministic human-readable display title")
    category: str | None = Field(None, description="English category name")
    degree: int = Field(..., ge=0, description="Number of connected product neighbors")


class GraphLink(BaseModel):
    """An undirected link representing co-occurrence between two products."""

    source: str = Field(..., description="Source product ID")
    target: str = Field(..., description="Target product ID")
    weight: int = Field(..., ge=1, description="Co-occurrence order count")


class GraphDataResponse(BaseModel):
    """Standard Node-Link JSON consumable by dashboard renderers (D3, Cytoscape, ECharts)."""

    nodes: list[GraphNode] = Field(default_factory=list, description="List of product nodes")
    links: list[GraphLink] = Field(default_factory=list, description="List of co-occurrence edges")
    total_nodes: int = Field(..., ge=0, description="Total nodes in subgraph")
    total_links: int = Field(..., ge=0, description="Total links in subgraph")
