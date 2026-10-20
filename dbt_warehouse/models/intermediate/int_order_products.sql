-- One delivered order-product membership. This is the graph/co-occurrence input.
select distinct i.order_id, i.product_id
from {{ ref('stg_order_items') }} i
join {{ ref('stg_orders') }} o using (order_id)
where lower(o.order_status) = 'delivered'
