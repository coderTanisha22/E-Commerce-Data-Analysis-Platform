-- Grain: one row per calendar day.
--
-- Spans the whole Olist timeline rather than the analytical window, so a date
-- filter can be applied in the mart layer instead of being baked in here.
WITH calendar_days AS (
  {{ date_spine_days('2016-01-01', '2018-12-31') }}
)
SELECT
  date_day,
  EXTRACT(YEAR FROM date_day)        AS year,
  EXTRACT(MONTH FROM date_day)       AS month,
  {{ day_of_week('date_day') }}      AS day_of_week,
  {{ year_month('date_day') }}       AS year_month
FROM calendar_days
