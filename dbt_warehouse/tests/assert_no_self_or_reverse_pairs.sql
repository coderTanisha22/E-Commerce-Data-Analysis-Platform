-- Every pair must be stored once, with product_a < product_b. A self-pair or a
-- mirrored duplicate would double-count the relationship downstream.
SELECT
  product_a,
  product_b,
  order_count
FROM {{ ref('fct_product_cooccurrence') }}
WHERE product_a >= product_b
