{{ config(materialized='table', cluster_by=['product_a', 'product_b']) }}
-- Grain: one unordered pair of distinct products, counted over the orders that
-- int_order_products accepts as evidence.
--
-- The `<` condition does two jobs: it drops self-pairs, and it stores each
-- unordered pair once rather than twice.
WITH order_memberships AS (
  SELECT DISTINCT
    order_id,
    product_id
  FROM {{ ref('int_order_products') }}
)
SELECT
  left_side.product_id   AS product_a,
  right_side.product_id  AS product_b,
  COUNT(*)               AS order_count
FROM order_memberships AS left_side
INNER JOIN order_memberships AS right_side
  ON left_side.order_id = right_side.order_id
  AND left_side.product_id < right_side.product_id
GROUP BY left_side.product_id, right_side.product_id
