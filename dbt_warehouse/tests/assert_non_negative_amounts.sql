-- A negative price or freight value would silently distort every revenue figure.
SELECT
  order_id,
  order_item_id
FROM {{ ref('fct_order_items') }}
WHERE price < 0
  OR freight_value < 0
