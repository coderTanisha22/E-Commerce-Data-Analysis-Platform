select
  cast(product_id as {{ dbt.type_string() }}) as product_id,
  cast(product_category_name as {{ dbt.type_string() }}) as product_category_name,
  {{ dbt.safe_cast('product_name_lenght', dbt.type_int()) }} as product_name_length,
  {{ dbt.safe_cast('product_description_lenght', dbt.type_int()) }} as product_description_length,
  {{ dbt.safe_cast('product_photos_qty', dbt.type_int()) }} as product_photos_qty,
  {{ dbt.safe_cast('product_weight_g', dbt.type_int()) }} as product_weight_g,
  {{ dbt.safe_cast('product_length_cm', dbt.type_int()) }} as product_length_cm,
  {{ dbt.safe_cast('product_height_cm', dbt.type_int()) }} as product_height_cm,
  {{ dbt.safe_cast('product_width_cm', dbt.type_int()) }} as product_width_cm,
  {{ provenance_columns() }}
from {{ source('olist_cleaned', 'olist_products_dataset') }}
