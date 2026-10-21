{{
    config(
        materialized='incremental',
        unique_key='labor_entry_id',
        incremental_strategy='delete+insert',
        indexes=[
            {'columns': ['labor_entry_id'], 'unique': True},
            {'columns': ['order_id']},
            {'columns': ['_max_loaded_at']},
        ],
    )
}}

-- Labor at actual rate plus overhead applied at the line's standard rate per hour.
-- Entries posted after their work period closed are routed to the posting period.
select
    l.labor_entry_id,
    l.order_id,
    l.employee_id,
    l.plant_id,
    l.line_id,
    l.work_date,
    l.posting_date,
    {{ period_of('l.work_date') }} as work_period_id,
    {{ accounting_period('l.work_date', 'l.posting_date') }} as period_id,
    {{ accounting_period('l.work_date', 'l.posting_date') }} <> {{ period_of('l.work_date') }} as is_late_posting,
    l.posting_date - l.work_date as posting_lag_days,
    l.hours,
    l.hourly_rate,
    l.overtime_flag,
    r.std_labor_rate,
    r.overhead_rate,
    {{ money('l.hours', 'l.hourly_rate') }} as labor_cost,
    {{ money('l.hours', 'r.overhead_rate') }} as overhead_applied,
    l._loaded_at as _max_loaded_at
from {{ ref('stg_labor_entries') }} l
join {{ ref('stg_fiscal_calendar') }} cal on cal.period_id = {{ period_of('l.work_date') }}
left join {{ ref('int_std_line_rates') }} r
    on r.line_id = l.line_id
    and l.work_date between r.effective_from and r.effective_to
{% if is_incremental() %}
where l._loaded_at > {{ incremental_watermark() }}
{% endif %}
