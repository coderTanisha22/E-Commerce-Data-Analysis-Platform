-- Grain: one row per product.
--
-- The join to the translation must be LEFT: it covers 71 of the 73 categories
-- present. The coalesce then falls back to the source slug, and finally to
-- 'unknown', so this column is never null for a downstream filter.
SELECT
  products.product_id,
  products.product_category_name,
  COALESCE(
    NULLIF(translation.product_category_name_english, ''),
    NULLIF(products.product_category_name, ''),
    'unknown'
  ) AS product_category_name_english,
  products.product_name_length,
  products.product_description_length,
  products.product_photos_qty,
  products.product_weight_g,
  products.product_length_cm,
  products.product_height_cm,
  products.product_width_cm
FROM {{ ref('stg_products') }} AS products
LEFT JOIN {{ ref('stg_category_translation') }} AS translation
  ON products.product_category_name = translation.product_category_name
