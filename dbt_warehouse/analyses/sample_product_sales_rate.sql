-- Sales rate for the ten best-selling products over the agreed window.
SELECT
  product_id,
  total_units_sold,
  number_of_days,
  item_lines_per_day
FROM {{ ref('product_sales_summary') }}
ORDER BY total_units_sold DESC, product_id
LIMIT 10
