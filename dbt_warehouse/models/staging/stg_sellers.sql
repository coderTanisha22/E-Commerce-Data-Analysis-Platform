select
  cast(seller_id as string) as seller_id,
  cast(seller_zip_code_prefix as string) as seller_zip_code_prefix,
  cast(seller_city as string) as seller_city,
  cast(seller_state as string) as seller_state,
  _run_date, _source_hash, _loaded_at
from {{ source('olist_cleaned', 'olist_sellers_dataset') }}
