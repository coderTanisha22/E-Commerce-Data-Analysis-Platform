-- Grain: one row per (order_id, product_id) for orders that count as evidence.
-- This is the graph / co-occurrence input.
--
-- The filter excludes `canceled` and `unavailable` only -- deliberately not
-- "delivered only". Measured on this dataset, requiring delivery discards 32
-- product pairs belonging to orders that were merely still in flight
-- (shipped, invoiced, processing) while removing only 4 belonging to orders
-- that actually failed. A customer who put two products in one basket chose
-- them together regardless of what logistics did afterwards.
--
-- This is the same rule as ecom.config.EXCLUDED_STATUSES, so the warehouse and
-- the pipeline's own analysis report the same pair count.
SELECT DISTINCT
  items.order_id,
  items.product_id
FROM {{ ref('stg_order_items') }} AS items
INNER JOIN {{ ref('stg_orders') }} AS orders
  ON items.order_id = orders.order_id
WHERE LOWER(orders.order_status) NOT IN ('canceled', 'unavailable')
