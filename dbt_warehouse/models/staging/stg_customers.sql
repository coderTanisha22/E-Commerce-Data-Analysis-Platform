SELECT
  CAST(customer_id AS {{ dbt.type_string() }})                AS customer_id,
  CAST(customer_unique_id AS {{ dbt.type_string() }})         AS customer_unique_id,
  CAST(customer_zip_code_prefix AS {{ dbt.type_string() }})   AS customer_zip_code_prefix,
  CAST(customer_city AS {{ dbt.type_string() }})              AS customer_city,
  CAST(customer_state AS {{ dbt.type_string() }})             AS customer_state,
  {{ provenance_columns() }}
FROM {{ source('olist_cleaned', 'olist_customers_dataset') }}
