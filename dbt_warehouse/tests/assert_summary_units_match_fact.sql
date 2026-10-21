-- total_units_sold across all products must equal the delivered item lines in
-- the window counted directly from the fact. Catches a join that drops or
-- duplicates products in the summary.
WITH summary_total AS (
  SELECT SUM(total_units_sold) AS units
  FROM {{ ref('product_sales_summary') }}
),

fact_total AS (
  SELECT COUNT(*) AS units
  FROM {{ ref('fct_order_items') }}
  WHERE LOWER(order_status) = 'delivered'
    AND order_date BETWEEN DATE '{{ var("window_start") }}' AND DATE '{{ var("window_end") }}'
)

SELECT 1 AS failure
FROM summary_total
CROSS JOIN fact_total
WHERE summary_total.units <> fact_total.units
