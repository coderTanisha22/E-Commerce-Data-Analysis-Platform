-- Calendar dimension spanning the whole Olist timeline, not just the
-- analytical window, so a date filter can be applied in the mart layer rather
-- than being baked into the dimension.
with spine as (
  {{ date_spine_days('2016-01-01', '2018-12-31') }}
)
select
  date_day,
  extract(year from date_day) as year,
  extract(month from date_day) as month,
  {{ day_of_week('date_day') }} as day_of_week,
  {{ year_month('date_day') }} as year_month
from spine
