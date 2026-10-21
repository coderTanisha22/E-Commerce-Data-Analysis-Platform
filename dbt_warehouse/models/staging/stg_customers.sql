select
  cast(customer_id as {{ dbt.type_string() }}) as customer_id,
  cast(customer_unique_id as {{ dbt.type_string() }}) as customer_unique_id,
  cast(customer_zip_code_prefix as {{ dbt.type_string() }}) as customer_zip_code_prefix,
  cast(customer_city as {{ dbt.type_string() }}) as customer_city,
  cast(customer_state as {{ dbt.type_string() }}) as customer_state,
  {{ provenance_columns() }}
from {{ source('olist_cleaned', 'olist_customers_dataset') }}
