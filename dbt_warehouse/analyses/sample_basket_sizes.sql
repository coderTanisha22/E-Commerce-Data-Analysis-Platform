-- How many orders have 1, 2, 3+ distinct products. Only baskets of 2 or more
-- can create a product pair, which is why the graph covers so little.
SELECT
  CASE WHEN distinct_products >= 3 THEN '3+' ELSE CAST(distinct_products AS {{ dbt.type_string() }}) END AS basket_size,
  COUNT(*)                                                                                            AS orders
FROM {{ ref('fct_orders') }}
GROUP BY 1
ORDER BY 1
