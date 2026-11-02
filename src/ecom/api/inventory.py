"""Restock queries over the synthetic inventory table.

The service is built from DataFrames and never does I/O, so every query is
testable on a five-row fixture; reading the processed layer happens once, in
``ecom.api.loader``.
"""

from __future__ import annotations

import pandas as pd

from ecom.api.schemas import (
    CategoryUrgency,
    InventoryItem,
    InventoryListResponse,
    InventorySummary,
    SellerInventoryResponse,
    StatusCount,
)
from ecom.discovery.names import synthesize_product_name
from ecom.synthetic.inventory import (
    STATUS_HEALTHY,
    STATUS_INSUFFICIENT,
    STATUS_MONITOR,
    STATUS_URGENT,
)

STATUS_ORDER: tuple[str, ...] = (STATUS_URGENT, STATUS_MONITOR, STATUS_HEALTHY, STATUS_INSUFFICIENT)
"""Display and sort order: the rows a retailer must act on come first."""

TOP_URGENT_CATEGORIES = 10
"""Categories listed in the summary; enough for a bar chart to stay legible."""


class InventoryService:
    """Filter, rank and summarise seller-product restock status."""

    def __init__(
        self,
        inventory: pd.DataFrame,
        *,
        products: pd.DataFrame | None = None,
        sellers: pd.DataFrame | None = None,
    ) -> None:
        """Join inventory to catalogue and seller context once, up front.

        Args:
            inventory: The synthetic inventory table, one row per seller-product.
            products: Optional catalogue with ``product_id`` and
                ``product_category_english``.
            sellers: Optional sellers with ``seller_id``, ``seller_city``,
                ``seller_state``.
        """
        self._frame = _enrich(inventory, products, sellers)

    def __len__(self) -> int:
        """Number of seller-product rows held."""
        return len(self._frame)

    def list_items(
        self,
        *,
        status: str | None = None,
        seller_id: str | None = None,
        category: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> InventoryListResponse:
        """Return one page of rows matching every given filter, most urgent first."""
        frame = self._frame
        if status is not None:
            frame = frame[frame["status"] == status]
        if seller_id is not None:
            frame = frame[frame["seller_id"] == seller_id]
        if category is not None:
            frame = frame[frame["category"] == category]
        page = frame.iloc[offset : offset + limit]
        return InventoryListResponse(
            items=_to_items(page), total_found=len(frame), limit=limit, offset=offset
        )

    def summary(self) -> InventorySummary:
        """Status distribution plus the categories carrying the most urgent rows."""
        urgent = self._frame.loc[self._frame["status"] == STATUS_URGENT, "category"]
        top = urgent.fillna("unknown").value_counts().head(TOP_URGENT_CATEGORIES)
        return InventorySummary(
            total=len(self._frame),
            by_status=_status_counts(self._frame),
            top_urgent_categories=[
                CategoryUrgency(category=str(name), urgent_count=int(count))
                for name, count in top.items()
            ],
            categories=sorted(self._frame["category"].dropna().unique().tolist()),
        )

    def for_seller(self, seller_id: str) -> SellerInventoryResponse | None:
        """Every row one seller holds, or None if the seller has no inventory."""
        rows = self._frame[self._frame["seller_id"] == seller_id]
        if rows.empty:
            return None
        first = rows.iloc[0]
        return SellerInventoryResponse(
            seller_id=seller_id,
            seller_city=_optional_str(first["seller_city"]),
            seller_state=_optional_str(first["seller_state"]),
            by_status=_status_counts(rows),
            items=_to_items(rows),
        )

    def for_product(self, product_id: str) -> list[InventoryItem]:
        """Every seller's row for one product, most urgent first."""
        return _to_items(self._frame[self._frame["product_id"] == product_id])


def _enrich(
    inventory: pd.DataFrame,
    products: pd.DataFrame | None,
    sellers: pd.DataFrame | None,
) -> pd.DataFrame:
    """Attach category, seller location and display name, then sort by urgency."""
    frame = inventory.copy()
    frame["seller_id"] = frame["seller_id"].astype(str)
    frame["product_id"] = frame["product_id"].astype(str)

    if products is not None:
        categories = products.set_index(products["product_id"].astype(str))
        frame["category"] = frame["product_id"].map(categories["product_category_english"])
    else:
        frame["category"] = None
    frame["category"] = frame["category"].astype(object).where(frame["category"].notna(), None)

    for column in ("seller_city", "seller_state"):
        if sellers is not None:
            lookup = sellers.set_index(sellers["seller_id"].astype(str))[column]
            frame[column] = frame["seller_id"].map(lookup).astype(object)
        else:
            frame[column] = None

    frame["product_name"] = [
        synthesize_product_name(pid, cat)
        for pid, cat in zip(frame["product_id"], frame["category"], strict=True)
    ]
    rank = {status: position for position, status in enumerate(STATUS_ORDER)}
    frame["_status_rank"] = frame["status"].map(rank).fillna(len(STATUS_ORDER))
    return frame.sort_values(
        ["_status_rank", "days_of_inventory", "seller_id", "product_id"], kind="stable"
    ).reset_index(drop=True)


def _status_counts(frame: pd.DataFrame) -> list[StatusCount]:
    """Count rows per status in display order, including statuses with zero rows."""
    counts = frame["status"].value_counts()
    total = len(frame)
    return [
        StatusCount(
            status=status,
            count=int(counts.get(status, 0)),
            share_pct=round(100 * int(counts.get(status, 0)) / total, 2) if total else 0.0,
        )
        for status in STATUS_ORDER
    ]


def _to_items(frame: pd.DataFrame) -> list[InventoryItem]:
    """Convert enriched rows into response models."""
    return [
        InventoryItem(
            seller_id=row.seller_id,
            product_id=row.product_id,
            product_name=row.product_name,
            category=_optional_str(row.category),
            seller_city=_optional_str(row.seller_city),
            seller_state=_optional_str(row.seller_state),
            status=row.status,
            evidence=row.evidence,
            units_sold=int(row.units_sold),
            daily_sales_rate=float(row.daily_sales_rate),
            current_quantity=int(row.current_quantity),
            reorder_point=float(row.reorder_point),
            lead_time_days=int(row.lead_time_days),
            days_of_inventory=float(row.days_of_inventory),
            last_restock_date=(
                None if pd.isna(row.last_restock_date) else row.last_restock_date.date()
            ),
            is_synthetic=bool(row.is_synthetic),
        )
        for row in frame.itertuples(index=False)
    ]


def _optional_str(value: object) -> str | None:
    """Turn pandas missing markers into None so JSON gets null, not 'nan'."""
    return None if value is None or pd.isna(value) else str(value)
