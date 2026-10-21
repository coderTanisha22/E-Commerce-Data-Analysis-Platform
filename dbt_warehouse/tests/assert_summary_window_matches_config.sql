-- The sales summary must use the agreed analysis window, not a window
-- derived from the data. Returns a row (a failure) if it drifts.
SELECT 1 AS failure
FROM {{ ref('product_sales_summary') }}
WHERE observation_start_date <> DATE '{{ var("window_start") }}'
  OR observation_end_date <> DATE '{{ var("window_end") }}'
LIMIT 1
