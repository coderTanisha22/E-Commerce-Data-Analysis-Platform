-- Item-level grain preserves source price sum; test uses source item rows directly.
with source_total as (
  select sum(safe_cast(price as numeric)) as amount
  from {{ source('olist_cleaned', 'olist_order_items_dataset') }}
), fact_total as (
  select sum(price) as amount from {{ ref('fct_order_items') }}
)
select 1 as failure
from source_total cross join fact_total
where abs(coalesce(source_total.amount, 0) - coalesce(fact_total.amount, 0)) > 0.01
