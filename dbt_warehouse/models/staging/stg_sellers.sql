select
  cast(seller_id as {{ dbt.type_string() }}) as seller_id,
  cast(seller_zip_code_prefix as {{ dbt.type_string() }}) as seller_zip_code_prefix,
  cast(seller_city as {{ dbt.type_string() }}) as seller_city,
  cast(seller_state as {{ dbt.type_string() }}) as seller_state,
  {{ provenance_columns() }}
from {{ source('olist_cleaned', 'olist_sellers_dataset') }}
