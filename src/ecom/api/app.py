"""FastAPI application: discovery, inventory and the dashboard that uses them.

Endpoints follow docs/CODING_STANDARDS.md section 9 (lowercase, resource
oriented, no verbs) and docs/contracts.md Contracts 4 and 5. Data is loaded
once at startup by ``ecom.api.loader``; routes only query in-memory services.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ecom.api.loader import PlatformData, load_platform
from ecom.api.schemas import (
    HealthResponse,
    InventoryListResponse,
    InventorySummary,
    OverviewResponse,
    ProductDetail,
    SellerInventoryResponse,
)
from ecom.discovery.names import synthesize_product_name
from ecom.discovery.schemas import (
    CategoryRelationsResponse,
    GraphDataResponse,
    RecommendationResponse,
    SearchResponse,
)
from ecom.synthetic.inventory import (
    STATUS_HEALTHY,
    STATUS_INSUFFICIENT,
    STATUS_MONITOR,
    STATUS_URGENT,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"

MAX_PAGE_SIZE = 500
"""Largest inventory page; the full table is 33,787 rows, too many for one response."""

MAX_GRAPH_NODES = 500
"""Above this a force-directed layout stops being readable or responsive in a browser."""

StatusFilter = Literal[STATUS_URGENT, STATUS_MONITOR, STATUS_HEALTHY, STATUS_INSUFFICIENT]


def create_app(loader: Callable[[], PlatformData] = load_platform) -> FastAPI:
    """Build the application.

    Args:
        loader: Returns the data the routes serve. Tests pass a fixture-built
            loader; production reads the processed layer.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.platform = loader()
        yield

    app = FastAPI(
        title="Olist Co-Occurrence and Inventory API",
        version="0.1.0",
        description="Graph recommendations and restock status over the Olist batch pipeline.",
        lifespan=lifespan,
    )
    _register_product_routes(app)
    _register_inventory_routes(app)
    _register_platform_routes(app)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.middleware("http")
    async def revalidate_dashboard(request: Request, call_next):
        # Without this header browsers reuse a stale app.js after an update.
        # no-cache still lets them use their copy after a cheap ETag check.
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    return app


def get_platform(request: Request) -> PlatformData:
    """Dependency returning the data loaded at startup."""
    return request.app.state.platform


Platform = Annotated[PlatformData, Depends(get_platform)]


def _register_product_routes(app: FastAPI) -> None:
    """Contract 5: recommendations, search and graph export."""

    @app.get("/products/search", response_model=SearchResponse, tags=["products"])
    def search_products(
        platform: Platform,
        q: Annotated[str, Query(min_length=1, max_length=100)],
        expand: bool = True,
        limit: Annotated[int, Query(ge=1, le=100)] = 10,
    ) -> SearchResponse:
        """Category matches first, then their strongest 1-hop co-purchases."""
        return platform.discovery.search_products(q, expand_graph=expand, limit=limit)

    @app.get("/products/graph", response_model=GraphDataResponse, tags=["products"])
    def global_graph(
        platform: Platform,
        min_weight: Annotated[int, Query(ge=1)] = 2,
        max_nodes: Annotated[int, Query(ge=2, le=MAX_GRAPH_NODES)] = 150,
    ) -> GraphDataResponse:
        """The strongest co-purchase edges across the catalogue."""
        return platform.discovery.to_node_link_data(min_weight=min_weight, max_nodes=max_nodes)

    @app.get("/products/{product_id}", response_model=ProductDetail, tags=["products"])
    def product_detail(platform: Platform, product_id: str) -> ProductDetail:
        """Catalogue facts, graph degree and per-seller stock for one product."""
        discovery = platform.discovery
        if not discovery.knows_product(product_id):
            raise HTTPException(status_code=404, detail=f"unknown product {product_id}")
        category = discovery.category_of(product_id)
        in_graph = product_id in discovery.graph
        return ProductDetail(
            product_id=product_id,
            product_name=synthesize_product_name(product_id, category),
            category=category,
            graph_degree=discovery.graph.degree[product_id] if in_graph else 0,
            inventory=platform.inventory.for_product(product_id),
        )

    @app.get(
        "/products/{product_id}/recommendations",
        response_model=RecommendationResponse,
        tags=["products"],
    )
    def recommendations(
        platform: Platform,
        product_id: str,
        limit: Annotated[int, Query(ge=1, le=50)] = 5,
    ) -> RecommendationResponse:
        """Products most often bought with this one; empty if it has no co-purchases."""
        return platform.discovery.get_recommendations(product_id, limit=limit)

    @app.get("/products/{product_id}/graph", response_model=GraphDataResponse, tags=["products"])
    def ego_graph(
        platform: Platform,
        product_id: str,
        min_weight: Annotated[int, Query(ge=1)] = 1,
        max_nodes: Annotated[int, Query(ge=2, le=MAX_GRAPH_NODES)] = 50,
    ) -> GraphDataResponse:
        """The product and its direct co-purchase neighbours."""
        return platform.discovery.to_node_link_data(
            product_id=product_id, min_weight=min_weight, max_nodes=max_nodes
        )

    @app.get(
        "/categories/{category}/related",
        response_model=CategoryRelationsResponse,
        tags=["products"],
    )
    def related_categories(
        platform: Platform,
        category: str,
        limit: Annotated[int, Query(ge=1, le=50)] = 8,
    ) -> CategoryRelationsResponse:
        """Fallback for products never bought with another: what their category is bought with."""
        if not platform.discovery.knows_category(category):
            raise HTTPException(status_code=404, detail=f"unknown category {category}")
        return platform.discovery.category_relations(category, limit=limit)


def _register_inventory_routes(app: FastAPI) -> None:
    """Contract 4: restock status by seller-product."""

    @app.get("/inventory", response_model=InventoryListResponse, tags=["inventory"])
    def list_inventory(
        platform: Platform,
        status: StatusFilter | None = None,
        seller_id: str | None = None,
        category: str | None = None,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> InventoryListResponse:
        """Seller-products ordered Urgent, Monitor, Healthy, then by days of cover."""
        return platform.inventory.list_items(
            status=status, seller_id=seller_id, category=category, limit=limit, offset=offset
        )

    @app.get("/inventory/summary", response_model=InventorySummary, tags=["inventory"])
    def inventory_summary(platform: Platform) -> InventorySummary:
        """Status distribution and the categories with the most urgent rows."""
        return platform.inventory.summary()

    @app.get(
        "/sellers/{seller_id}/inventory",
        response_model=SellerInventoryResponse,
        tags=["inventory"],
    )
    def seller_inventory(platform: Platform, seller_id: str) -> SellerInventoryResponse:
        """Everything one seller stocks, most urgent first."""
        result = platform.inventory.for_seller(seller_id)
        if result is None:
            raise HTTPException(status_code=404, detail=f"no inventory for seller {seller_id}")
        return result


def _register_platform_routes(app: FastAPI) -> None:
    """Health, overview and the dashboard page."""

    @app.get("/health", response_model=HealthResponse, tags=["platform"])
    def health(platform: Platform) -> HealthResponse:
        """Liveness and the provenance of the loaded data."""
        return HealthResponse(
            storage=platform.storage_description,
            ingested_at=platform.ingested_at,
            inventory_generated_at=platform.inventory_generated_at,
            graph_products=platform.discovery.graph.number_of_nodes(),
            graph_links=platform.discovery.graph.number_of_edges(),
            inventory_rows=len(platform.inventory),
        )

    @app.get("/overview", response_model=OverviewResponse, tags=["platform"])
    def overview(platform: Platform) -> OverviewResponse:
        """Headline figures, precomputed at startup."""
        return platform.overview

    @app.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        """The single-page dashboard; it reads everything through the endpoints above."""
        return FileResponse(STATIC_DIR / "index.html")
