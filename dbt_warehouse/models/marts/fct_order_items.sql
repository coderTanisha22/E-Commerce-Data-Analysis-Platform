{{ config(materialized='table', partition_by={'field': 'order_date', 'data_type': 'date'}, cluster_by=['product_id', 'seller_id']) }}
-- Grain: exactly one row per source order_id + order_item_id. Do not aggregate away the item key.
select
  i.order_id, i.order_item_id, i.product_id, i.seller_id,
  o.customer_id,
  date(o.order_purchase_timestamp) as order_date,
  o.order_status,
  i.price,
  i.freight_value,
  i.price + i.freight_value as item_total_amount,
  i.shipping_limit_date,
  i._run_date, i._source_hash, i._loaded_at,
  current_timestamp() as _built_at
from {{ ref('stg_order_items') }} i
join {{ ref('stg_orders') }} o using (order_id)
