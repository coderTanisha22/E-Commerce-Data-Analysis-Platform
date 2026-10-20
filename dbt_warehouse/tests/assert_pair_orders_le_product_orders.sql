with product_orders as (
  select product_id, count(distinct order_id) as n
  from {{ ref('int_order_products') }} group by product_id
)
select c.*
from {{ ref('fct_product_cooccurrence') }} c
join product_orders a on a.product_id = c.product_a
join product_orders b on b.product_id = c.product_b
where c.order_count > least(a.n, b.n)
