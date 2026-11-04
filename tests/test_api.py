"""Tests for the HTTP API and the services behind it.

The app is built from a fixture ``PlatformData``, so every endpoint is tested
without a processed layer on disk. One test at the end exercises the real
loader and is skipped when the pipeline has not been run.
"""

from __future__ import annotations

from collections.abc import Iterator

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from ecom.api import PlatformData, create_app
from ecom.api.inventory import InventoryService
from ecom.api.loader import build_overview, load_platform
from ecom.config import Settings
from ecom.discovery.graph import ProductGraphService
from ecom.storage import get_storage


@pytest.fixture
def frames() -> dict[str, pd.DataFrame]:
    """Three orders, four products, two sellers; o1 is the only multi-product basket."""
    orders = pd.DataFrame(
        {
            "order_id": ["o1", "o2", "o3"],
            "order_status": ["delivered", "delivered", "canceled"],
            "order_purchase_timestamp": pd.to_datetime(["2017-03-05", "2017-04-10", "2017-04-11"]),
            "is_delivered": [True, True, False],
        }
    )
    order_lines = pd.DataFrame(
        {
            "order_id": ["o1", "o1", "o2", "o3"],
            "product_id": ["p1", "p2", "p3", "p4"],
            "seller_id": ["s1", "s1", "s2", "s2"],
            "quantity": [1, 2, 1, 1],
            "line_revenue": [10.0, 40.0, 30.0, 99.0],
        }
    )
    order_products = order_lines[["order_id", "product_id"]]
    products = pd.DataFrame(
        {
            "product_id": ["p1", "p2", "p3", "p4"],
            "product_category_english": ["toys", "toys", "bed_bath_table", None],
        }
    )
    sellers = pd.DataFrame(
        {
            "seller_id": ["s1", "s2"],
            "seller_city": ["campinas", "rio"],
            "seller_state": ["SP", "RJ"],
        }
    )
    pairs = pd.DataFrame({"product_a": ["p1"], "product_b": ["p2"], "order_count": [3]})
    inventory = pd.DataFrame(
        {
            "seller_id": ["s1", "s1", "s2", "s2"],
            "product_id": ["p1", "p2", "p3", "p4"],
            "units_sold": [1, 12, 30, 2],
            "daily_sales_rate": [0.002, 0.2, 0.5, 0.004],
            "evidence": ["insufficient", "sufficient", "sufficient", "insufficient"],
            "lead_time_days": [10, 10, 7, 5],
            "reorder_point": [1, 3, 5, 1],
            "current_quantity": [1, 30, 2, 0],
            "last_restock_date": pd.to_datetime(["2018-07-01"] * 4),
            "days_of_inventory": [500.0, 150.0, 4.0, 0.0],
            "status": ["Insufficient data", "Healthy", "Urgent", "Insufficient data"],
            "is_synthetic": [True] * 4,
        }
    )
    return {
        "orders": orders,
        "order_lines": order_lines,
        "order_products": order_products,
        "products": products,
        "sellers": sellers,
        "pairs": pairs,
        "inventory": inventory,
    }


@pytest.fixture
def platform(frames: dict[str, pd.DataFrame]) -> PlatformData:
    """A fully built PlatformData over the fixture frames."""
    inventory = InventoryService(
        frames["inventory"], products=frames["products"], sellers=frames["sellers"]
    )
    overview = build_overview(
        orders=frames["orders"],
        order_lines=frames["order_lines"],
        order_products=frames["order_products"],
        products=frames["products"],
        sellers=frames["sellers"],
        pairs=frames["pairs"],
        inventory=inventory,
        settings=Settings(),
    )
    return PlatformData(
        discovery=ProductGraphService(pairs=frames["pairs"], products=frames["products"]),
        inventory=inventory,
        overview=overview,
        storage_description="fixture",
    )


@pytest.fixture
def client(platform: PlatformData) -> Iterator[TestClient]:
    """A client whose app loads the fixture instead of the processed layer."""
    with TestClient(create_app(loader=lambda: platform)) as test_client:
        yield test_client


# ---------------------------------------------------------------- inventory service


def test_inventory_list_orders_urgent_first(platform: PlatformData) -> None:
    """Urgent outranks Healthy, and Insufficient data comes last by days of cover."""
    page = platform.inventory.list_items(limit=10)
    assert [item.product_id for item in page.items] == ["p3", "p2", "p4", "p1"]


def test_inventory_list_filters_and_pages(platform: PlatformData) -> None:
    """Filters combine, and total_found counts matches before paging."""
    page = platform.inventory.list_items(seller_id="s2", limit=1, offset=1)
    assert page.total_found == 2
    assert [item.product_id for item in page.items] == ["p4"]
    assert platform.inventory.list_items(category="toys").total_found == 2


def test_inventory_null_category_serialises_as_none(platform: PlatformData) -> None:
    """A product with no category yields null, not the string 'nan'."""
    (item,) = platform.inventory.for_product("p4")
    assert item.category is None
    assert item.seller_state == "RJ"


def test_inventory_summary_lists_every_status(platform: PlatformData) -> None:
    """Statuses with zero rows still appear, so the dashboard legend is stable."""
    summary = platform.inventory.summary()
    counts = {row.status: row.count for row in summary.by_status}
    assert counts == {"Urgent": 1, "Monitor": 0, "Healthy": 1, "Insufficient data": 2}
    assert summary.top_urgent_categories[0].category == "bed_bath_table"
    assert summary.categories == ["bed_bath_table", "toys"]


# ---------------------------------------------------------------- overview


def test_overview_counts_delivered_revenue_only(platform: PlatformData) -> None:
    """The cancelled order's 99.0 is excluded, matching profile_sales."""
    overview = platform.overview
    assert overview.revenue_brl == pytest.approx(80.0)
    assert overview.orders_in_window == 2
    assert overview.cooccurrence_pairs == 1
    assert overview.graph_products == 2


def test_overview_multi_product_share_excludes_failed_orders(platform: PlatformData) -> None:
    """o3 is cancelled, so 1 of the 2 countable orders is multi-product."""
    assert platform.overview.multi_product_share_pct == pytest.approx(50.0)


# ---------------------------------------------------------------- endpoints


def test_health_reports_loaded_data(client: TestClient) -> None:
    """Health returns the graph and inventory sizes the app loaded."""
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["graph_products"] == 2
    assert body["inventory_rows"] == 4


def test_recommendations_endpoint_follows_contract(client: TestClient) -> None:
    """Contract 5: neighbours ranked by weight, with display names."""
    body = client.get("/products/p1/recommendations").json()
    assert body["total_found"] == 1
    assert body["recommendations"][0]["product_id"] == "p2"
    assert body["recommendations"][0]["weight"] == 3


def test_recommendations_for_unknown_product_are_empty(client: TestClient) -> None:
    """Contract 5 returns an empty list rather than 404 for a product with no pairs."""
    response = client.get("/products/zzz/recommendations")
    assert response.status_code == 200
    assert response.json()["recommendations"] == []


def test_search_endpoint_expands_through_graph(client: TestClient) -> None:
    """A category search returns direct matches; regex characters do not raise."""
    body = client.get("/products/search", params={"q": "toys"}).json()
    assert {item["product_id"] for item in body["results"]} == {"p1", "p2"}
    assert client.get("/products/search", params={"q": "(["}).status_code == 200


def test_search_endpoint_rejects_empty_query(client: TestClient) -> None:
    """q is required and must be non-empty."""
    assert client.get("/products/search", params={"q": ""}).status_code == 422


def test_graph_endpoints_return_node_link_data(client: TestClient) -> None:
    """Global and ego graphs share the node-link shape."""
    global_graph = client.get("/products/graph", params={"min_weight": 1}).json()
    assert global_graph["total_links"] == 1
    ego = client.get("/products/p1/graph").json()
    assert {node["id"] for node in ego["nodes"]} == {"p1", "p2"}


def test_product_detail_joins_graph_and_inventory(client: TestClient) -> None:
    """Detail combines catalogue, graph degree and per-seller stock."""
    body = client.get("/products/p2").json()
    assert body["category"] == "toys"
    assert body["graph_degree"] == 1
    assert body["inventory"][0]["status"] == "Healthy"


def test_product_detail_unknown_is_404(client: TestClient) -> None:
    """A product neither in the catalogue nor the graph is a 404."""
    assert client.get("/products/zzz").status_code == 404


def test_inventory_endpoint_validates_status(client: TestClient) -> None:
    """Only the four real statuses are accepted."""
    assert client.get("/inventory", params={"status": "Urgent"}).json()["total_found"] == 1
    assert client.get("/inventory", params={"status": "urgent"}).status_code == 422


def test_inventory_endpoint_caps_page_size(client: TestClient) -> None:
    """A page larger than the cap is rejected rather than served."""
    assert client.get("/inventory", params={"limit": 10_000}).status_code == 422


def test_seller_inventory_and_unknown_seller(client: TestClient) -> None:
    """A seller's rows come back most urgent first; an unknown seller is 404."""
    body = client.get("/sellers/s2/inventory").json()
    assert body["seller_state"] == "RJ"
    assert [item["product_id"] for item in body["items"]] == ["p3", "p4"]
    assert client.get("/sellers/nobody/inventory").status_code == 404


def test_dashboard_page_and_assets_are_served(client: TestClient) -> None:
    """The dashboard and its script load from the same origin as the API."""
    page = client.get("/")
    assert page.status_code == 200
    assert "Olist Retail Dashboard" in page.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/styles.css").status_code == 200


# ---------------------------------------------------------------- real data


def test_loader_on_processed_layer_matches_reconciled_figures() -> None:
    """End to end over the real processed layer: the contract's reconciled numbers."""
    storage = get_storage()
    if not storage.exists(storage.processed_key("synthetic_inventory")):
        pytest.skip("processed layer not built; run make pipeline")
    platform = load_platform(storage=storage)
    assert platform.overview.cooccurrence_pairs == 4054
    assert platform.overview.graph_products == 4881
    assert len(platform.inventory) == 33787


def test_search_ranks_connected_products_first(client: TestClient) -> None:
    """In 'toys', p1 and p2 are both connected; an unconnected match would come last."""
    body = client.get("/products/search", params={"q": "toys", "expand": False}).json()
    assert [item["degree"] for item in body["results"]] == [1, 1]


def test_category_fallback_lists_related_categories_and_connected_products(
    platform: PlatformData,
) -> None:
    """A cross-category pair adds weight to both categories; same-category pairs do not."""
    pairs = pd.DataFrame(
        {"product_a": ["p1", "p1"], "product_b": ["p2", "p3"], "order_count": [3, 2]}
    )
    products = pd.DataFrame(
        {
            "product_id": ["p1", "p2", "p3", "p4"],
            "product_category_english": ["toys", "toys", "bed_bath_table", "toys"],
        }
    )
    service = ProductGraphService(pairs=pairs, products=products)
    result = service.category_relations("toys")
    assert [(r.category, r.weight) for r in result.related] == [("bed_bath_table", 2)]
    assert [p.id for p in result.connected_products] == ["p1", "p2"]


def test_category_endpoint_404s_for_unknown_category(client: TestClient) -> None:
    assert client.get("/categories/toys/related").status_code == 200
    assert client.get("/categories/no_such_thing/related").status_code == 404
