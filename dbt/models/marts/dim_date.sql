with bounds as (
    select min(period_start) as d0, max(period_end) as d1 from {{ ref('stg_fiscal_calendar') }}
)

select
    d::date as date_day,
    to_char(d, 'YYYY-MM') as period_id,
    extract(year from d)::int as year,
    extract(quarter from d)::int as quarter,
    extract(month from d)::int as month,
    to_char(d, 'Mon') as month_name,
    extract(isodow from d)::int as iso_day_of_week,
    extract(isodow from d) < 6 as is_weekday,
    c.close_date,
    c.business_day_1,
    d::date = c.business_day_1 as is_business_day_1,
    d::date = c.period_end as is_period_end
from bounds
cross join generate_series(bounds.d0, bounds.d1, interval '1 day') d
join {{ ref('stg_fiscal_calendar') }} c on c.period_id = to_char(d, 'YYYY-MM')
