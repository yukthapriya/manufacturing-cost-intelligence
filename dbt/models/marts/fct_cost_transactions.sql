{{ config(indexes=[{'columns': ['order_id']}, {'columns': ['txn_type', 'txn_id']}]) }}

-- Transaction-level detail behind every order cost and variance: the drill-through
-- target for the dashboards (join on order_id, and material_id for material rows).
select
    'ISSUE' as txn_type,
    i.issue_id as txn_id,
    i.order_id,
    i.material_id,
    i.plant_id,
    i.line_id,
    i.issue_date as txn_date,
    i.period_id,
    i.issue_qty as qty,
    i.uom,
    i.std_price as unit_std_cost,
    i.std_value as std_value,
    ap.actual_price as unit_actual_cost,
    round(i.issue_qty * ap.actual_price, 2) as actual_value,
    i.uom_converted as flag_uom_converted,
    false as flag_late_posting,
    null::text as reason_code,
    null::text as employee_id
from {{ ref('int_material_issues') }} i
left join {{ ref('int_actual_material_price') }} ap
    on ap.plant_id = i.plant_id and ap.material_id = i.material_id and ap.period_id = i.period_id

union all

select
    'SCRAP', s.scrap_id, s.order_id, s.material_id, s.plant_id, s.line_id, s.scrap_date, s.period_id,
    s.scrap_qty, s.uom, s.std_price, s.std_value, null, null, false, false, s.reason_code, null
from {{ ref('int_scrap') }} s

union all

select
    'LABOR', l.labor_entry_id, l.order_id, null, l.plant_id, l.line_id, l.work_date, l.period_id,
    l.hours, 'HR', l.std_labor_rate, round(l.hours * l.std_labor_rate, 2), l.hourly_rate, l.labor_cost,
    false, l.is_late_posting, null, l.employee_id
from {{ ref('int_labor_entries') }} l
