select
  cast(order_id as string) as order_id,
  cast(customer_id as string) as customer_id,
  cast(order_status as string) as order_status,
  safe_cast(order_purchase_timestamp as timestamp) as order_purchase_timestamp,
  safe_cast(order_approved_at as timestamp) as order_approved_at,
  safe_cast(order_delivered_carrier_date as timestamp) as order_delivered_carrier_date,
  safe_cast(order_delivered_customer_date as timestamp) as order_delivered_customer_date,
  safe_cast(order_estimated_delivery_date as timestamp) as order_estimated_delivery_date,
  _run_date, _source_hash, _loaded_at
from {{ source('olist_cleaned', 'olist_orders_dataset') }}
