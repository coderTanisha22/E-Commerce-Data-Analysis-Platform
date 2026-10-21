-- Reconciliation between the warehouse and the pipeline that feeds it.
--
-- Compile with `dbt compile -s warehouse_reconciliation` and run the result.
-- Every row should reconcile exactly.
WITH source_items AS (
  SELECT
    COUNT(*)                                                       AS rows_in,
    ROUND(SUM({{ dbt.safe_cast('price', dbt.type_numeric()) }}), 2) AS price_sum
  FROM {{ source('olist_cleaned', 'olist_order_items_dataset') }}
),

fact_items AS (
  SELECT
    COUNT(*)              AS rows_out,
    ROUND(SUM(price), 2)  AS price_sum
  FROM {{ ref('fct_order_items') }}
),

memberships AS (
  SELECT COUNT(*) AS countable_order_product_rows
  FROM {{ ref('int_order_products') }}
),

pairs AS (
  SELECT
    COUNT(*)           AS pair_rows,
    SUM(order_count)   AS weight_sum
  FROM {{ ref('fct_product_cooccurrence') }}
)

SELECT
  source_items.rows_in                           AS source_item_rows,
  fact_items.rows_out                            AS fact_item_rows,
  source_items.rows_in - fact_items.rows_out     AS item_row_difference,
  source_items.price_sum                         AS source_price_sum,
  fact_items.price_sum                           AS fact_price_sum,
  source_items.price_sum - fact_items.price_sum  AS price_difference,
  memberships.countable_order_product_rows,
  pairs.pair_rows                                AS cooccurrence_pairs,
  pairs.weight_sum                               AS cooccurrence_weight_sum
FROM source_items
CROSS JOIN fact_items
CROSS JOIN memberships
CROSS JOIN pairs

-- Expected on the current dataset:
--   source_item_rows = fact_item_rows = 112,650, difference 0
--   price sums both 13,591,643.70, difference 0
--   countable_order_product_rows = 101,953
--   cooccurrence_pairs = 4,054, weight_sum = 4,476
