{{ config(materialized='table', cluster_by=['product_a', 'product_b']) }}
-- Grain: one unordered pair of distinct products per delivered order population.
with op as (select distinct order_id, product_id from {{ ref('int_order_products') }})
select a.product_id as product_a, b.product_id as product_b, count(*) as order_count
from op a
join op b on a.order_id = b.order_id and a.product_id < b.product_id
group by 1, 2
