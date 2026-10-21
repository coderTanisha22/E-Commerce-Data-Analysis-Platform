-- Reconciliation between the warehouse and the pipeline that feeds it.
--
-- Compile with `dbt compile -s warehouse_reconciliation` and run the result,
-- or run `dbt build` first and query the models directly. Every row below
-- should reconcile exactly except `cooccurrence_pairs`, which is expected to
-- differ and is explained underneath.
with source_items as (
  select
    count(*) as rows_in,
    round(sum({{ dbt.safe_cast('price', dbt.type_numeric()) }}), 2) as price_sum
  from {{ source('olist_cleaned', 'olist_order_items_dataset') }}
),
fact_items as (
  select count(*) as rows_out, round(sum(price), 2) as price_sum
  from {{ ref('fct_order_items') }}
),
memberships as (
  select count(*) as delivered_order_product_rows from {{ ref('int_order_products') }}
),
pairs as (
  select count(*) as pair_rows, sum(order_count) as weight_sum
  from {{ ref('fct_product_cooccurrence') }}
)
select
  s.rows_in                          as source_item_rows,
  f.rows_out                         as fact_item_rows,
  s.rows_in - f.rows_out             as item_row_difference,   -- must be 0
  s.price_sum                        as source_price_sum,
  f.price_sum                        as fact_price_sum,
  s.price_sum - f.price_sum          as price_difference,      -- must be 0
  m.delivered_order_product_rows,
  p.pair_rows                        as cooccurrence_pairs,
  p.weight_sum                       as cooccurrence_weight_sum
from source_items s
cross join fact_items f
cross join memberships m
cross join pairs p

-- Expected on the current dataset:
--   source_item_rows = fact_item_rows = 112,650
--   price sums both 13,591,643.70, difference 0
--   delivered_order_product_rows = 100,196
--   cooccurrence_pairs = 4,022, weight_sum = 4,437
--
-- The pipeline's own analysis reports 4,058 pairs and weight sum 4,481. The
-- 36-pair gap is not a defect in either implementation: the warehouse counts
-- co-occurrence over delivered orders only, while src/ecom/analysis/profile.py
-- counts every order status. Those 36 pairs are evidenced solely by orders
-- that were never delivered. See docs/contracts_alignment.md.
