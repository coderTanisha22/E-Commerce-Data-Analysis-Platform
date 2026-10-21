"""Declared schema for every table the pipeline touches.

A table with no contract cannot be ingested (docs/CODING_STANDARDS.md section 6).
Contracts carry the facts an audit of the real files established, so the pipeline
fails on a changed source file instead of quietly producing different numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

CSV_DTYPE = "string"
"""All source columns are read as strings; coercion is an explicit cleaning step."""


@dataclass(frozen=True)
class TableContract:
    """Schema and key declaration for one source table.

    Attributes:
        name: Logical table name used throughout the pipeline.
        filename: File as it appears in the Olist download.
        columns: Every column expected, in source order.
        key: Columns forming the primary key. Empty when the table has none.
        timestamp_columns: Columns to coerce to datetime during cleaning.
        numeric_columns: Columns to coerce to float during cleaning.
        expected_rows: Row count measured on the reference download, used as a
            drift signal rather than a hard gate.
        notes: Why this table behaves the way it does.
    """

    name: str
    filename: str
    columns: tuple[str, ...]
    key: tuple[str, ...] = ()
    timestamp_columns: tuple[str, ...] = ()
    numeric_columns: tuple[str, ...] = ()
    expected_rows: int | None = None
    notes: str = ""
    foreign_keys: dict[str, tuple[str, str]] = field(default_factory=dict)


ORDERS = TableContract(
    name="orders",
    filename="olist_orders_dataset.csv",
    columns=(
        "order_id",
        "customer_id",
        "order_status",
        "order_purchase_timestamp",
        "order_approved_at",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ),
    key=("order_id",),
    timestamp_columns=(
        "order_purchase_timestamp",
        "order_approved_at",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ),
    expected_rows=99_441,
    notes="775 orders carry no item rows; 2,965 have no delivered_customer_date.",
    foreign_keys={"customer_id": ("customers", "customer_id")},
)

ORDER_ITEMS = TableContract(
    name="order_items",
    filename="olist_order_items_dataset.csv",
    columns=(
        "order_id",
        "order_item_id",
        "product_id",
        "seller_id",
        "shipping_limit_date",
        "price",
        "freight_value",
    ),
    key=("order_id", "order_item_id"),
    timestamp_columns=("shipping_limit_date",),
    numeric_columns=("price", "freight_value"),
    expected_rows=112_650,
    notes=(
        "One row is ONE UNIT: there is no quantity column. 10,225 rows repeat a "
        "(order_id, product_id) pair, which is genuine multi-quantity, not duplication."
    ),
    foreign_keys={
        "order_id": ("orders", "order_id"),
        "product_id": ("products", "product_id"),
        "seller_id": ("sellers", "seller_id"),
    },
)

PRODUCTS = TableContract(
    name="products",
    filename="olist_products_dataset.csv",
    columns=(
        "product_id",
        "product_category_name",
        "product_name_lenght",
        "product_description_lenght",
        "product_photos_qty",
        "product_weight_g",
        "product_length_cm",
        "product_height_cm",
        "product_width_cm",
    ),
    key=("product_id",),
    numeric_columns=(
        "product_name_lenght",
        "product_description_lenght",
        "product_photos_qty",
        "product_weight_g",
        "product_length_cm",
        "product_height_cm",
        "product_width_cm",
    ),
    expected_rows=32_951,
    notes=(
        "There is NO product name or description text. The '_lenght' columns are "
        "misspelled in the source and hold integer character counts. 610 products "
        "have a NULL category. Price is NOT here - it varies per order line."
    ),
)

CUSTOMERS = TableContract(
    name="customers",
    filename="olist_customers_dataset.csv",
    columns=(
        "customer_id",
        "customer_unique_id",
        "customer_zip_code_prefix",
        "customer_city",
        "customer_state",
    ),
    key=("customer_id",),
    expected_rows=99_441,
    notes="customer_id is per-order; customer_unique_id is the real person (96,096 distinct).",
)

SELLERS = TableContract(
    name="sellers",
    filename="olist_sellers_dataset.csv",
    columns=("seller_id", "seller_zip_code_prefix", "seller_city", "seller_state"),
    key=("seller_id",),
    expected_rows=3_095,
)

CATEGORY_TRANSLATION = TableContract(
    name="category_translation",
    filename="product_category_name_translation.csv",
    columns=("product_category_name", "product_category_name_english"),
    key=("product_category_name",),
    expected_rows=71,
    notes=(
        "Covers 71 of the 73 categories present in products. pc_gamer and "
        "portateis_cozinha_e_preparadores_de_alimentos have no English name, so the "
        "join must be a LEFT join with a slug fallback."
    ),
)

INVENTORY = TableContract(
    name="inventory",
    filename="synthetic_inventory.csv",
    columns=(
        "seller_id",
        "product_id",
        "current_quantity",
        "reorder_point",
        "lead_time_days",
        "last_restock_date",
    ),
    key=("seller_id", "product_id"),
    timestamp_columns=("last_restock_date",),
    numeric_columns=("current_quantity", "reorder_point", "lead_time_days"),
    notes="SYNTHETIC. Generated from observed velocity; never presented as real stock.",
    foreign_keys={
        "product_id": ("products", "product_id"),
        "seller_id": ("sellers", "seller_id"),
    },
)

OLIST_CONTRACTS: tuple[TableContract, ...] = (
    ORDERS,
    ORDER_ITEMS,
    PRODUCTS,
    CUSTOMERS,
    SELLERS,
    CATEGORY_TRANSLATION,
)
"""Tables read from the Olist download. Ingestion iterates this tuple."""

ALL_CONTRACTS: dict[str, TableContract] = {
    contract.name: contract for contract in (*OLIST_CONTRACTS, INVENTORY)
}


def get_contract(name: str) -> TableContract:
    """Look up a contract by logical table name.

    Raises:
        KeyError: If the table has no declared contract, which blocks ingestion
            by design rather than letting an unknown schema through.
    """
    if name not in ALL_CONTRACTS:
        known = ", ".join(sorted(ALL_CONTRACTS))
        raise KeyError(f"no contract declared for table {name!r}; known tables: {known}")
    return ALL_CONTRACTS[name]
