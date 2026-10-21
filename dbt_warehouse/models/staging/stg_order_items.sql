select
  cast(order_id as {{ dbt.type_string() }}) as order_id,
  {{ dbt.safe_cast('order_item_id', dbt.type_int()) }} as order_item_id,
  cast(product_id as {{ dbt.type_string() }}) as product_id,
  cast(seller_id as {{ dbt.type_string() }}) as seller_id,
  {{ dbt.safe_cast('shipping_limit_date', dbt.type_timestamp()) }} as shipping_limit_date,
  {{ dbt.safe_cast('price', dbt.type_numeric()) }} as price,
  {{ dbt.safe_cast('freight_value', dbt.type_numeric()) }} as freight_value,
  {{ provenance_columns() }}
from {{ source('olist_cleaned', 'olist_order_items_dataset') }}
