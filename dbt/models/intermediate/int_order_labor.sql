{{ config(materialized='view') }}

-- Labor and overhead per order: actuals vs. standard hours for the output produced.
with lab as (
    select
        order_id,
        sum(hours) as actual_hours,
        sum(labor_cost) as actual_labor_cost,
        sum(overhead_applied) as overhead_applied,
        sum(hours) filter (where overtime_flag) as overtime_hours,
        count(*) filter (where is_late_posting) as late_entries,
        string_agg(labor_entry_id::text, ',' order by labor_entry_id) as labor_entry_ids,
        count(*) as entry_count,
        max(_max_loaded_at) as _max_loaded_at
    from {{ ref('int_labor_entries') }}
    group by 1
)

select
    o.order_id,
    o.product_id,
    o.line_id,
    o.plant_id,
    o.is_completed,
    o.completed_qty,
    coalesce(l.actual_hours, 0) as actual_hours,
    coalesce(l.actual_labor_cost, 0) as actual_labor_cost,
    coalesce(l.overhead_applied, 0) as overhead_applied,
    coalesce(l.overtime_hours, 0) as overtime_hours,
    coalesce(l.late_entries, 0) as late_entries,
    l.actual_labor_cost / nullif(l.actual_hours, 0) as actual_rate,
    sp.std_labor_hours * o.completed_qty as std_hours,
    r.std_labor_rate,
    r.overhead_rate,
    l.labor_entry_ids,
    coalesce(l.entry_count, 0) as entry_count,
    l._max_loaded_at
from {{ ref('stg_production_orders') }} o
left join lab l on l.order_id = o.order_id
left join {{ ref('int_std_product') }} sp
    on sp.product_id = o.product_id
    and coalesce(o.completion_date, o.actual_start::date) between sp.effective_from and sp.effective_to
left join {{ ref('int_std_line_rates') }} r
    on r.line_id = o.line_id
    and coalesce(o.completion_date, o.actual_start::date) between r.effective_from and r.effective_to
