-- Run manually in BigQuery after dbt build to reconcile input and fact totals.
select
  (select count(*) from {{ source('olist_cleaned', 'olist_order_items_dataset') }}) as source_item_rows,
  (select count(*) from {{ ref('fct_order_items') }}) as fact_item_rows,
  (select round(sum(safe_cast(price as numeric)), 2) from {{ source('olist_cleaned', 'olist_order_items_dataset') }}) as source_price_sum,
  (select round(sum(price), 2) from {{ ref('fct_order_items') }}) as fact_price_sum;
