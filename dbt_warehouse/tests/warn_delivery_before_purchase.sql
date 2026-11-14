{{ config(severity='warn') }}
-- A delivery date earlier than the purchase date is a timestamp defect in the
-- source. Reported as a warning so the count is visible without blocking.
SELECT order_id
FROM {{ ref('stg_orders') }}
WHERE order_delivered_customer_date < order_purchase_timestamp
