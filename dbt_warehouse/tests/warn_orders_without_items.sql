{{ config(severity='warn') }}
-- Known Olist quirk: 775 orders have no item rows. A warning, not an error:
-- the rows are real, they just cannot contribute sales or product pairs.
SELECT orders.order_id
FROM {{ ref('stg_orders') }} AS orders
LEFT JOIN {{ ref('stg_order_items') }} AS items
  ON orders.order_id = items.order_id
WHERE items.order_id IS NULL
