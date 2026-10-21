-- Delivered order-item lines per product over the global observation window.
--
-- This model keeps the stricter delivered-only filter on purpose, unlike
-- int_order_products. It reports realised sales, and an order still in flight
-- is not money yet. Co-occurrence asks a different question -- did a customer
-- choose these together -- which is answered as soon as the basket is placed.
--
-- The rate is line count per day across the window actually observed in the
-- data, computed from min/max delivered purchase date rather than hardcoded,
-- so the figure stays correct if the source is refreshed.
with delivered as (
  select f.product_id, f.order_id, f.order_item_id, f.order_date, f.price
  from {{ ref('fct_order_items') }} f
  where lower(f.order_status) = 'delivered'
),
window_bounds as (
  select min(order_date) as start_date, max(order_date) as end_date from delivered
),
product_sales as (
  select
    product_id,
    count(*) as delivered_item_line_count,
    count(distinct order_id) as delivered_order_count,
    sum(price) as delivered_gross_sales
  from delivered
  group by product_id
)
select
  p.product_id,
  coalesce(s.delivered_item_line_count, 0) as delivered_item_line_count,
  coalesce(s.delivered_order_count, 0) as delivered_order_count,
  coalesce(s.delivered_gross_sales, 0) as delivered_gross_sales,
  b.start_date as observation_start_date,
  b.end_date as observation_end_date,
  case
    when b.start_date is null then 0
    else {{ safe_divide(
           'coalesce(s.delivered_item_line_count, 0)',
           dbt.datediff('b.start_date', 'b.end_date', 'day') ~ ' + 1'
         ) }}
  end as item_lines_per_day
from {{ ref('dim_products') }} p
left join product_sales s using (product_id)
cross join window_bounds b
