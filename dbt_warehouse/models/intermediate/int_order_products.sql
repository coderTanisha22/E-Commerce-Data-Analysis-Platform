-- One order-product membership per order that counts as evidence. This is the
-- graph / co-occurrence input.
--
-- The filter excludes `canceled` and `unavailable` only -- deliberately not
-- "delivered only". Measured on this dataset, requiring delivery discards 32
-- product pairs belonging to orders that were merely still in flight
-- (shipped, invoiced, processing) while removing only 4 belonging to orders
-- that actually failed. A customer who put two products in one basket chose
-- them together regardless of what logistics did afterwards.
--
-- This is the same rule as ecom.config.EXCLUDED_STATUSES, so the warehouse and
-- the pipeline's own analysis report the same pair count.
select distinct i.order_id, i.product_id
from {{ ref('stg_order_items') }} i
join {{ ref('stg_orders') }} o using (order_id)
where lower(o.order_status) not in ('canceled', 'unavailable')
