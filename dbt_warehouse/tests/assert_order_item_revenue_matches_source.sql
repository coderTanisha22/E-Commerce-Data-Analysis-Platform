-- The revenue invariant, asserted at the warehouse boundary.
--
-- The item-level grain must preserve the source price sum exactly. This is the
-- same invariant src/ecom/cleaning/run_clean.py enforces between order_items
-- and order_lines, checked again here because the warehouse is a separate
-- consumer: if a future model aggregated the item key away, this is what would
-- catch it.
WITH source_total AS (
  SELECT SUM({{ dbt.safe_cast('price', dbt.type_numeric()) }}) AS amount
  FROM {{ source('olist_cleaned', 'olist_order_items_dataset') }}
),

fact_total AS (
  SELECT SUM(price) AS amount
  FROM {{ ref('fct_order_items') }}
)

SELECT 1 AS failure
FROM source_total
CROSS JOIN fact_total
WHERE ABS(COALESCE(source_total.amount, 0) - COALESCE(fact_total.amount, 0)) > 0.01
