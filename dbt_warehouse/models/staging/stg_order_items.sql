-- Grain: one row per (order_id, order_item_id). This is the finest grain the
-- source provides and the grain fct_order_items is built at.
SELECT
  CAST(order_id AS {{ dbt.type_string() }})                          AS order_id,
  {{ dbt.safe_cast('order_item_id', dbt.type_int()) }}               AS order_item_id,
  CAST(product_id AS {{ dbt.type_string() }})                        AS product_id,
  CAST(seller_id AS {{ dbt.type_string() }})                         AS seller_id,
  {{ dbt.safe_cast('shipping_limit_date', dbt.type_timestamp()) }}   AS shipping_limit_date,
  {{ dbt.safe_cast('price', dbt.type_numeric()) }}                   AS price,
  {{ dbt.safe_cast('freight_value', dbt.type_numeric()) }}           AS freight_value,
  {{ provenance_columns() }}
FROM {{ source('olist_cleaned', 'olist_order_items_dataset') }}
