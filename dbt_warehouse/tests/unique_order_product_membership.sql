select order_id, product_id, count(*) as n
from {{ ref('int_order_products') }}
group by 1, 2
having count(*) > 1
