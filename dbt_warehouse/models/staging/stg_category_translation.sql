select
  cast(product_category_name as {{ dbt.type_string() }}) as product_category_name,
  cast(product_category_name_english as {{ dbt.type_string() }}) as product_category_name_english
from {{ source('olist_cleaned', 'product_category_name_translation') }}
