"""Pydantic schemas for product discovery and search endpoints.

These models define the API contract between Person C's discovery service
and Person D's FastAPI routing layer.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RecommendationItem(BaseModel):
    """A single product recommended via graph co-occurrence."""

    product_id: str = Field(..., description="Unique product identifier")
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

