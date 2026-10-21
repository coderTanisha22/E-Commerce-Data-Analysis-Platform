SELECT
  CAST(product_id AS {{ dbt.type_string() }})                        AS product_id,
  CAST(product_category_name AS {{ dbt.type_string() }})             AS product_category_name,
  {{ dbt.safe_cast('product_name_lenght', dbt.type_int()) }}         AS product_name_length,
  {{ dbt.safe_cast('product_description_lenght', dbt.type_int()) }}  AS product_description_length,
  {{ dbt.safe_cast('product_photos_qty', dbt.type_int()) }}          AS product_photos_qty,
  {{ dbt.safe_cast('product_weight_g', dbt.type_int()) }}            AS product_weight_g,
  {{ dbt.safe_cast('product_length_cm', dbt.type_int()) }}           AS product_length_cm,
  {{ dbt.safe_cast('product_height_cm', dbt.type_int()) }}           AS product_height_cm,
  {{ dbt.safe_cast('product_width_cm', dbt.type_int()) }}            AS product_width_cm,
  {{ provenance_columns() }}
FROM {{ source('olist_cleaned', 'olist_products_dataset') }}
