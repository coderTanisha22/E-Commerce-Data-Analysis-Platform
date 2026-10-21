-- fct_orders is an aggregation of fct_order_items, so it must neither lose nor
-- invent orders or money.
WITH order_totals AS (
  SELECT
    COUNT(*)             AS order_rows,
    SUM(item_count)      AS item_rows,
    SUM(items_amount)    AS price_total
  FROM {{ ref('fct_orders') }}
),

item_totals AS (
  SELECT
    COUNT(DISTINCT order_id)  AS order_rows,
    COUNT(*)                  AS item_rows,
    SUM(price)                AS price_total
  FROM {{ ref('fct_order_items') }}
)

SELECT 1 AS failure
FROM order_totals
CROSS JOIN item_totals
WHERE order_totals.order_rows <> item_totals.order_rows
  OR order_totals.item_rows <> item_totals.item_rows
  OR ABS(order_totals.price_total - item_totals.price_total) > 0.01
