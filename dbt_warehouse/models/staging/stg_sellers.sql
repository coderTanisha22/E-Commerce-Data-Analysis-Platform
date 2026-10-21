SELECT
  CAST(seller_id AS {{ dbt.type_string() }})                AS seller_id,
  CAST(seller_zip_code_prefix AS {{ dbt.type_string() }})   AS seller_zip_code_prefix,
  CAST(seller_city AS {{ dbt.type_string() }})              AS seller_city,
  CAST(seller_state AS {{ dbt.type_string() }})             AS seller_state,
  {{ provenance_columns() }}
FROM {{ source('olist_cleaned', 'olist_sellers_dataset') }}
