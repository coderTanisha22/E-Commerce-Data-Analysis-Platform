{{
  config(
    materialized='table',
    partition_by=(
      {'field': 'order_date', 'data_type': 'date'}
      if target.type == 'bigquery' else none
    ),
    cluster_by=(['product_id', 'seller_id'] if target.type == 'bigquery' else none)
  )
}}
-- Grain: exactly one row per (order_id, order_item_id). Do not aggregate away
-- the item key -- it cannot be recovered afterwards, and the pipeline already
-- publishes the aggregated order_lines for consumers that want it.
--
-- Partitioning by order_date and clustering by (product_id, seller_id) is the
-- physical design the fragmentation study arrived at independently: dashboard
-- queries are month-scoped, which is the selective case partition pruning
-- serves, while a seller predicate cannot be pruned by a date partition and so
-- is better served by clustering. Both are BigQuery-only and are dropped on
-- the local DuckDB target, which reads single Parquet files.
SELECT
  items.order_id,
  items.order_item_id,
  items.product_id,
  items.seller_id,
  orders.customer_id,
  CAST(orders.order_purchase_timestamp AS DATE)    AS order_date,
  orders.order_status,
  items.price,
  items.freight_value,
  items.price + items.freight_value                AS item_total_amount,
  items.shipping_limit_date,
  items._run_date,
  items._source_hash,
  items._loaded_at,
  {{ dbt.current_timestamp() }}                    AS _built_at
FROM {{ ref('stg_order_items') }} AS items
INNER JOIN {{ ref('stg_orders') }} AS orders
  ON items.order_id = orders.order_id
