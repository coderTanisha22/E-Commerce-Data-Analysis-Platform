-- Grain: one row per order that has at least one item. Unique key: order_id.
-- Orders with no items (775 in Olist) are not here; they have nothing to sum.
--
-- distinct_products is the basket size the co-occurrence analysis depends on:
-- an order can only create a product pair when it is 2 or more.
SELECT
  order_id,
  MAX(customer_id)                  AS customer_id,
  MIN(order_date)                   AS order_date,
  MAX(order_month_key)              AS order_month_key,
  MAX(order_status)                 AS order_status,
  COUNT(*)                          AS item_count,
  COUNT(DISTINCT product_id)        AS distinct_products,
  COUNT(DISTINCT seller_id)         AS distinct_sellers,
  SUM(price)                        AS items_amount,
  SUM(freight_value)                AS freight_amount,
  SUM(item_total_amount)            AS order_total_amount
FROM {{ ref('fct_order_items') }}
GROUP BY order_id
