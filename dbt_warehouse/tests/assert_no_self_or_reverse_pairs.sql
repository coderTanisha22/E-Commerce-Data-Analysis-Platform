select * from {{ ref('fct_product_cooccurrence') }} where product_a >= product_b
