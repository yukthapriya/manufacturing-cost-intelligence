-- Grain: line x month x scrap reason. Scrap value at standard and scrap rate against
-- material issued to the same line in the same month.
with scrap as (
    select line_id, plant_id, period_id, reason_code,
           count(*) as scrap_events, sum(std_value) as scrap_value
    from {{ ref('int_scrap') }}
    group by 1, 2, 3, 4
),

issued as (
    select line_id, period_id, sum(std_value) as issued_value
    from {{ ref('int_material_issues') }}
    group by 1, 2
)

select
    {{ dbt_utils_surrogate(['s.line_id', 's.period_id', 's.reason_code']) }} as scrap_summary_id,
    s.line_id,
    s.plant_id,
    s.period_id,
    s.reason_code,
    s.scrap_events,
    s.scrap_value,
    i.issued_value,
    s.scrap_value / nullif(i.issued_value, 0) as scrap_rate,
    sum(s.scrap_value) over (partition by s.line_id, s.period_id) / nullif(i.issued_value, 0) as line_scrap_rate
from scrap s
left join issued i using (line_id, period_id)
