SELECT
  CAST(order_id AS {{ dbt.type_string() }})                                AS order_id,
  CAST(customer_id AS {{ dbt.type_string() }})                             AS customer_id,
  CAST(order_status AS {{ dbt.type_string() }})                            AS order_status,
  {{ dbt.safe_cast('order_purchase_timestamp', dbt.type_timestamp()) }}    AS order_purchase_timestamp,
  {{ dbt.safe_cast('order_approved_at', dbt.type_timestamp()) }}           AS order_approved_at,
  {{ dbt.safe_cast('order_delivered_carrier_date', dbt.type_timestamp()) }} AS order_delivered_carrier_date,
  {{ dbt.safe_cast('order_delivered_customer_date', dbt.type_timestamp()) }} AS order_delivered_customer_date,
  {{ dbt.safe_cast('order_estimated_delivery_date', dbt.type_timestamp()) }} AS order_estimated_delivery_date,
  {{ provenance_columns() }}
FROM {{ source('olist_cleaned', 'olist_orders_dataset') }}
