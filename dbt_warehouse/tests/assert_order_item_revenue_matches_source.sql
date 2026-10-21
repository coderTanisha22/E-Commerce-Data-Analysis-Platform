-- The revenue invariant, asserted at the warehouse boundary.
--
-- The item-level grain must preserve the source price sum exactly. This is the
-- same invariant src/ecom/cleaning/run_clean.py enforces between order_items
-- and order_lines, checked again here because the warehouse is a separate
-- consumer: if a future model aggregated the item key away, this is what would
-- catch it.
with source_total as (
  select sum({{ dbt.safe_cast('price', dbt.type_numeric()) }}) as amount
  from {{ source('olist_cleaned', 'olist_order_items_dataset') }}
),
fact_total as (
  select sum(price) as amount from {{ ref('fct_order_items') }}
)
select 1 as failure
from source_total cross join fact_total
where abs(coalesce(source_total.amount, 0) - coalesce(fact_total.amount, 0)) > 0.01
