select
    l.line_id,
    l.line_name,
    l.plant_id,
    p.plant_name,
    r.std_labor_rate,
    r.overhead_rate,
    r.version as std_version
from {{ ref('stg_production_lines') }} l
join {{ ref('stg_plants') }} p using (plant_id)
left join {{ ref('int_std_line_rates') }} r
    on r.line_id = l.line_id
    and (select min(period_start) from {{ ref('stg_fiscal_calendar') }}) between r.effective_from and r.effective_to
