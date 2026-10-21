-- Covers 71 of the 73 categories present, so every join to this model must be
-- a LEFT join or products in the untranslated categories are silently dropped.
SELECT
  CAST(product_category_name AS {{ dbt.type_string() }})           AS product_category_name,
  CAST(product_category_name_english AS {{ dbt.type_string() }})   AS product_category_name_english
FROM {{ source('olist_cleaned', 'product_category_name_translation') }}
