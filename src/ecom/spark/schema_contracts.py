"""Cleaned-data contract for each Olist table.

This is the single source of truth Spark cleaning reads against. B's dbt
models should be built from these same column names/types - if a column
needs to change here, update this file first and notify B (see
docs/contracts.md).

Each table entry has:
  key_columns        - column(s) that must be unique together (business key)
  required_columns   - columns that must never be null
  numeric_columns     - {column: minimum_allowed_value}; invalid if below
  range_columns        - {column: (minimum, maximum)}; invalid if outside
  date_columns        - string columns to parse into timestamps
  trim_columns        - free-text columns to strip of leading/trailing space
"""

TABLE_CONTRACTS = {
    "olist_customers_dataset": {
        "key_columns": ["customer_id"],
        "required_columns": ["customer_id", "customer_unique_id"],
        "numeric_columns": {"customer_zip_code_prefix": 0},
        "range_columns": {},
        "date_columns": [],
        "trim_columns": ["customer_city", "customer_state"],
    },
    "olist_geolocation_dataset": {
        # Not unique per row by design - many lat/lng samples share a zip
        # prefix. Duplication is therefore not a meaningful check here.
        "key_columns": [],
        "required_columns": ["geolocation_zip_code_prefix"],
        "numeric_columns": {"geolocation_zip_code_prefix": 0},
        "range_columns": {"geolocation_lat": (-90, 90), "geolocation_lng": (-180, 180)},
        "date_columns": [],
        "trim_columns": ["geolocation_city", "geolocation_state"],
    },
    "olist_order_items_dataset": {
        "key_columns": ["order_id", "order_item_id"],
        "required_columns": ["order_id", "order_item_id", "product_id", "seller_id"],
        "numeric_columns": {"order_item_id": 1, "price": 0, "freight_value": 0},
        "range_columns": {},
        "date_columns": ["shipping_limit_date"],
        "trim_columns": [],
    },
    "olist_order_payments_dataset": {
        "key_columns": ["order_id", "payment_sequential"],
        "required_columns": ["order_id", "payment_type"],
        "numeric_columns": {
            "payment_sequential": 1,
            "payment_installments": 0,
            "payment_value": 0,
        },
        "range_columns": {},
        "date_columns": [],
        "trim_columns": ["payment_type"],
    },
    "olist_order_reviews_dataset": {
        "key_columns": ["review_id"],
        "required_columns": ["review_id", "order_id"],
        "numeric_columns": {},
        "range_columns": {"review_score": (1, 5)},
        "date_columns": ["review_creation_date", "review_answer_timestamp"],
        "trim_columns": [],
    },
    "olist_orders_dataset": {
        "key_columns": ["order_id"],
        "required_columns": ["order_id", "customer_id", "order_status"],
        "numeric_columns": {},
        "range_columns": {},
        # Only purchase/estimated-delivery dates are guaranteed on every
        # order; approval/carrier/customer-delivery dates are legitimately
        # null for orders that never reached that stage yet.
        "date_columns": [
            "order_purchase_timestamp",
            "order_approved_at",
            "order_delivered_carrier_date",
            "order_delivered_customer_date",
            "order_estimated_delivery_date",
        ],
        "trim_columns": ["order_status"],
    },
    "olist_products_dataset": {
        "key_columns": ["product_id"],
        "required_columns": ["product_id"],
        "numeric_columns": {
            "product_name_lenght": 0,
            "product_description_lenght": 0,
            "product_photos_qty": 0,
            "product_weight_g": 0,
            "product_length_cm": 0,
            "product_height_cm": 0,
            "product_width_cm": 0,
        },
        "range_columns": {},
        "date_columns": [],
        "trim_columns": ["product_category_name"],
    },
    "olist_sellers_dataset": {
        "key_columns": ["seller_id"],
        "required_columns": ["seller_id"],
        "numeric_columns": {"seller_zip_code_prefix": 0},
        "range_columns": {},
        "date_columns": [],
        "trim_columns": ["seller_city", "seller_state"],
    },
    "product_category_name_translation": {
        "key_columns": ["product_category_name"],
        "required_columns": ["product_category_name", "product_category_name_english"],
        "numeric_columns": {},
        "range_columns": {},
        "date_columns": [],
        "trim_columns": ["product_category_name", "product_category_name_english"],
    },
}


def get_table_contract(table_name):
    """Return the cleaned-data contract for one table."""
    return TABLE_CONTRACTS[table_name]


def get_contracted_tables():
    """Return the list of table names Spark cleaning knows how to handle."""
    return list(TABLE_CONTRACTS.keys())
