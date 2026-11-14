-- Grain: one row per product.
--
-- This model keeps the stricter delivered-only filter on purpose, unlike
-- int_order_products. It reports realised sales, and an order still in flight
-- is not money yet. Co-occurrence asks a different question -- did a customer
-- choose these together -- which is answered as soon as the basket is placed.
--
-- The rate is line count per day over the window actually observed in the
-- data, computed from the min and max delivered purchase date rather than
-- hardcoded, so it stays correct if the source is refreshed.
WITH delivered_lines AS (
  SELECT
    product_id,
    order_id,
    order_item_id,
    order_date,
    price
  FROM {{ ref('fct_order_items') }}
  WHERE LOWER(order_status) = 'delivered'
),

observation_window AS (
  SELECT
    MIN(order_date) AS start_date,
    MAX(order_date) AS end_date
  FROM delivered_lines
),

sales_per_product AS (
  SELECT
    product_id,
    COUNT(*)                   AS delivered_item_line_count,
    COUNT(DISTINCT order_id)   AS delivered_order_count,
    SUM(price)                 AS delivered_gross_sales
  FROM delivered_lines
  GROUP BY product_id
)

SELECT
  products.product_id,
  COALESCE(sales.delivered_item_line_count, 0)   AS delivered_item_line_count,
  COALESCE(sales.delivered_order_count, 0)       AS delivered_order_count,
  COALESCE(sales.delivered_gross_sales, 0)       AS delivered_gross_sales,
  observation.start_date                         AS observation_start_date,
  observation.end_date                           AS observation_end_date,
  CASE
    WHEN observation.start_date IS NULL THEN 0
    ELSE {{ safe_divide(
           'COALESCE(sales.delivered_item_line_count, 0)',
           dbt.datediff('observation.start_date', 'observation.end_date', 'day') ~ ' + 1'
         ) }}
  END AS item_lines_per_day
FROM {{ ref('dim_products') }} AS products
LEFT JOIN sales_per_product AS sales
  ON products.product_id = sales.product_id
CROSS JOIN observation_window AS observation
