select
  cast(order_id as string) as order_id,
  safe_cast(order_item_id as int64) as order_item_id,
  cast(product_id as string) as product_id,
  cast(seller_id as string) as seller_id,
  safe_cast(shipping_limit_date as timestamp) as shipping_limit_date,
  safe_cast(price as numeric) as price,
  safe_cast(freight_value as numeric) as freight_value,
  _run_date, _source_hash, _loaded_at
from {{ source('olist_cleaned', 'olist_order_items_dataset') }}
