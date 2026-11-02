"""Pydantic schemas for the inventory, overview and health endpoints.

The discovery endpoints reuse ``ecom.discovery.schemas`` unchanged, so the
contract agreed in docs/contracts.md (Contract 5) is the one the API serves.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class InventoryItem(BaseModel):
    """One seller-product row of the synthetic inventory, joined to its context."""

    seller_id: str
    product_id: str
    product_name: str = Field(..., description="Deterministic display title")
    category: str | None = Field(None, description="English category name")
    seller_city: str | None = None
    seller_state: str | None = None
    status: str = Field(..., description="Urgent, Monitor, Healthy or Insufficient data")
    evidence: str = Field(..., description="Whether enough sales exist to trust the velocity")
    units_sold: int = Field(..., ge=0, description="Real units sold in the window")
    daily_sales_rate: float = Field(..., ge=0, description="Real units sold per active day")
    current_quantity: int = Field(..., ge=0, description="Synthetic stock on hand")
    reorder_point: float = Field(
        ..., ge=0, description="Units of demand over lead time plus safety days; fractional"
    )
    lead_time_days: int = Field(..., ge=0, description="Synthetic supplier lead time")
    days_of_inventory: float = Field(..., ge=0, description="current_quantity / daily_sales_rate")
    last_restock_date: date | None = None
    is_synthetic: bool = Field(True, description="Stock columns are generated, not observed")


class InventoryListResponse(BaseModel):
    """A filtered, paginated page of inventory rows, most urgent first."""

    items: list[InventoryItem] = Field(default_factory=list)
    total_found: int = Field(..., ge=0, description="Rows matching the filters before paging")
    limit: int = Field(..., ge=1)
    offset: int = Field(..., ge=0)


class StatusCount(BaseModel):
    """How many seller-products sit in one restock status."""

    status: str
    count: int = Field(..., ge=0)
    share_pct: float = Field(..., ge=0, le=100)


class CategoryUrgency(BaseModel):
    """Urgent seller-products within one category."""

    category: str
    urgent_count: int = Field(..., ge=0)


class InventorySummary(BaseModel):
    """Restock status distribution across the whole inventory."""

    total: int = Field(..., ge=0)
    by_status: list[StatusCount] = Field(default_factory=list)
    top_urgent_categories: list[CategoryUrgency] = Field(default_factory=list)
    categories: list[str] = Field(
        default_factory=list, description="Every category present, for filter controls"
    )
    is_synthetic: bool = True


class SellerInventoryResponse(BaseModel):
    """Every seller-product held by one seller, with its status breakdown."""

    seller_id: str
    seller_city: str | None = None
    seller_state: str | None = None
    by_status: list[StatusCount] = Field(default_factory=list)
    items: list[InventoryItem] = Field(default_factory=list)


class ProductDetail(BaseModel):
    """Catalogue facts for one product plus its place in the graph."""

    product_id: str
    product_name: str
    category: str | None = None
    graph_degree: int = Field(..., ge=0, description="Distinct products bought with it")
    inventory: list[InventoryItem] = Field(
        default_factory=list, description="One row per seller stocking it"
    )


class MonthlyOrders(BaseModel):
    """Distinct orders placed in one calendar month."""

    month: date
    order_count: int = Field(..., ge=0)


class OverviewResponse(BaseModel):
    """Headline figures for the dashboard's first screen."""

    window_start: date
    window_end: date
    products: int
    sellers: int
    orders_in_window: int = Field(..., description="Delivered orders inside the window")
    revenue_brl: float = Field(..., description="Delivered revenue inside the window")
    average_order_value_brl: float
    multi_product_share_pct: float = Field(..., description="Orders holding 2+ distinct products")
    cooccurrence_pairs: int
    graph_products: int = Field(..., description="Products with at least one co-purchase")
    orders_by_month: list[MonthlyOrders] = Field(default_factory=list)
    inventory: InventorySummary


class HealthResponse(BaseModel):
    """Liveness plus what data the service loaded and when it was built."""

    status: str = "ok"
    storage: str
    ingested_at: str | None = None
    inventory_generated_at: str | None = None
    graph_products: int
    graph_links: int
    inventory_rows: int
