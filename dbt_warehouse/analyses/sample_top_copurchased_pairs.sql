-- Top 20 product pairs bought together, with their categories.
SELECT
  pairs.product_a,
  products_a.product_category_name_english AS category_a,
  pairs.product_b,
  products_b.product_category_name_english AS category_b,
  pairs.order_count
FROM {{ ref('fct_product_cooccurrence') }} AS pairs
INNER JOIN {{ ref('dim_products') }} AS products_a
  ON pairs.product_a = products_a.product_id
INNER JOIN {{ ref('dim_products') }} AS products_b
  ON pairs.product_b = products_b.product_id
ORDER BY pairs.order_count DESC, pairs.product_a, pairs.product_b
LIMIT 20
