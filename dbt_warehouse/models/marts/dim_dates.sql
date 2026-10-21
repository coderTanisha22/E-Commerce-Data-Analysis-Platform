select d as date_day,
       extract(year from d) as year,
       extract(month from d) as month,
       extract(dayofweek from d) as day_of_week,
       format_date('%Y-%m', d) as year_month
from unnest(generate_date_array('2016-01-01','2018-12-31')) as d
