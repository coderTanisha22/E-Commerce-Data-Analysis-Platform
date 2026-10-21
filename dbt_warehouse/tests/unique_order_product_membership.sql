-- A product belongs to an order once. A duplicate here would inflate every
-- pair weight built from this model.
SELECT
  order_id,
  product_id,
  COUNT(*) AS row_count
FROM {{ ref('int_order_products') }}
GROUP BY order_id, product_id
HAVING COUNT(*) > 1
