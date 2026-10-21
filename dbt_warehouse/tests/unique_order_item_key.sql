-- The declared grain of the fact: one row per (order_id, order_item_id).
SELECT
  order_id,
  order_item_id,
  COUNT(*) AS row_count
FROM {{ ref('fct_order_items') }}
GROUP BY order_id, order_item_id
HAVING COUNT(*) > 1
