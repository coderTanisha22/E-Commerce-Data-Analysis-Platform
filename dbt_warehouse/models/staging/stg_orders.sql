select
  cast(order_id as {{ dbt.type_string() }}) as order_id,
  cast(customer_id as {{ dbt.type_string() }}) as customer_id,
  cast(order_status as {{ dbt.type_string() }}) as order_status,
  {{ dbt.safe_cast('order_purchase_timestamp', dbt.type_timestamp()) }} as order_purchase_timestamp,
  {{ dbt.safe_cast('order_approved_at', dbt.type_timestamp()) }} as order_approved_at,
  {{ dbt.safe_cast('order_delivered_carrier_date', dbt.type_timestamp()) }} as order_delivered_carrier_date,
  {{ dbt.safe_cast('order_delivered_customer_date', dbt.type_timestamp()) }} as order_delivered_customer_date,
  {{ dbt.safe_cast('order_estimated_delivery_date', dbt.type_timestamp()) }} as order_estimated_delivery_date,
  {{ provenance_columns() }}
from {{ source('olist_cleaned', 'olist_orders_dataset') }}
