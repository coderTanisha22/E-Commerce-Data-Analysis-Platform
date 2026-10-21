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
-- Grain: exactly one row per source order_id + order_item_id. Do not aggregate
-- away the item key -- it cannot be recovered afterwards, and the pipeline
-- already publishes the aggregated order_lines for consumers that want it.
--
-- Partitioning by order_date and clustering by (product_id, seller_id) is the
-- physical design the fragmentation study arrived at independently: dashboard
-- queries are month-scoped, which is the selective case partition pruning
-- serves, while a seller predicate cannot be pruned by a date partition and so
-- is better served by clustering. Both are BigQuery-only and are dropped on
-- the local DuckDB target, which reads single Parquet files.
select
  i.order_id,
  i.order_item_id,
  i.product_id,
  i.seller_id,
  o.customer_id,
  cast(o.order_purchase_timestamp as date) as order_date,
  o.order_status,
  i.price,
  i.freight_value,
  i.price + i.freight_value as item_total_amount,
  i.shipping_limit_date,
  i._run_date,
  i._source_hash,
  i._loaded_at,
  {{ dbt.current_timestamp() }} as _built_at
from {{ ref('stg_order_items') }} i
join {{ ref('stg_orders') }} o using (order_id)
