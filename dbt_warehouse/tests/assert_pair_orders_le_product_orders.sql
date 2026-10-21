-- A pair cannot appear in more orders than either of its products does. A
-- failure here means the join fanned out and inflated the counts.
WITH orders_per_product AS (
  SELECT
    product_id,
    COUNT(DISTINCT order_id) AS order_count
  FROM {{ ref('int_order_products') }}
  GROUP BY product_id
)
SELECT
  pairs.product_a,
  pairs.product_b,
  pairs.order_count
FROM {{ ref('fct_product_cooccurrence') }} AS pairs
INNER JOIN orders_per_product AS side_a
  ON side_a.product_id = pairs.product_a
INNER JOIN orders_per_product AS side_b
  ON side_b.product_id = pairs.product_b
WHERE pairs.order_count > LEAST(side_a.order_count, side_b.order_count)
