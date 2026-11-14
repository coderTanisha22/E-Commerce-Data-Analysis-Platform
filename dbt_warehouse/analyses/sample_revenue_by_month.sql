-- Item revenue per purchase month, delivered orders only.
SELECT
  dates.year_month,
  COUNT(DISTINCT items.order_id)  AS orders,
  SUM(items.price)                AS item_revenue
FROM {{ ref('fct_order_items') }} AS items
INNER JOIN {{ ref('dim_dates') }} AS dates
  ON items.order_date = dates.date_day
WHERE LOWER(items.order_status) = 'delivered'
GROUP BY dates.year_month
ORDER BY dates.year_month
