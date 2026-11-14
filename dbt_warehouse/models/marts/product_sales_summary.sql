-- Grain: one row per product (every product in dim_products, including those
-- with no sales in the window). Unique key: product_id.
--
-- Contract for the inventory consumer: total_units_sold over the agreed
-- observation window, plus the window bounds and number_of_days. In Olist every
-- order_items row is one unit, so units = item lines.
--
-- The window is the project-wide analysis window (vars window_start and
-- window_end, equal to ecom.config.WINDOW_START / WINDOW_END), not the min and
-- max date found in the data. The data run from late 2016 to late 2018 with
-- sparse months at both ends, so a data-derived window would give a different
-- rate from the one the synthetic inventory and the API use.
--
-- This model keeps the stricter delivered-only filter on purpose, unlike
-- int_order_products. It reports realised sales, and an order still in flight
-- is not money yet. Co-occurrence asks a different question -- did a customer
-- choose these together -- which is answered as soon as the basket is placed.
-- The pipeline's inventory generator excludes only canceled and unavailable
-- orders, so its unit counts can be slightly higher than total_units_sold.
WITH delivered_lines AS (
  SELECT
    product_id,
    order_id,
    order_item_id,
    order_date,
    price
  FROM {{ ref('fct_order_items') }}
  WHERE LOWER(order_status) = 'delivered'
    AND order_date BETWEEN DATE '{{ var("window_start") }}' AND DATE '{{ var("window_end") }}'
),

observation_window AS (
  SELECT
    DATE '{{ var("window_start") }}'  AS start_date,
    DATE '{{ var("window_end") }}'    AS end_date,
    {{ dbt.datediff("DATE '" ~ var("window_start") ~ "'", "DATE '" ~ var("window_end") ~ "'", 'day') }} + 1 AS number_of_days
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
  COALESCE(sales.delivered_item_line_count, 0)   AS total_units_sold,
  COALESCE(sales.delivered_item_line_count, 0)   AS delivered_item_line_count,
  COALESCE(sales.delivered_order_count, 0)       AS delivered_order_count,
  COALESCE(sales.delivered_gross_sales, 0)       AS delivered_gross_sales,
  observation.start_date                         AS observation_start_date,
  observation.end_date                           AS observation_end_date,
  observation.number_of_days                     AS number_of_days,
  {{ safe_divide('COALESCE(sales.delivered_item_line_count, 0)', 'observation.number_of_days') }} AS item_lines_per_day
FROM {{ ref('dim_products') }} AS products
LEFT JOIN sales_per_product AS sales
  ON products.product_id = sales.product_id
CROSS JOIN observation_window AS observation
