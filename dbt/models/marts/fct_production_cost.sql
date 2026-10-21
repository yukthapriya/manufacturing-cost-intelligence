-- depends_on: {{ ref('int_material_issues') }}
-- depends_on: {{ ref('int_labor_entries') }}
-- depends_on: {{ ref('stg_scrap_records') }}
-- depends_on: {{ ref('stg_production_orders') }}
{{
    config(
        materialized='incremental',
        unique_key='order_id',
        incremental_strategy='delete+insert',
        indexes=[{'columns': ['order_id'], 'unique': True}, {'columns': ['period_id', 'line_id']}],
    )
}}

-- Grain: production order. Actual vs. standard cost of each order. For open orders
-- the actuals are cost-to-date and standard/variance columns are null.
with orders as (
    select * from {{ ref('stg_production_orders') }}
    {% if is_incremental() %}
    where order_id in ({{ changed_orders() }})
    {% endif %}
),

mat as (
    select
        order_id,
        sum(actual_qty * coalesce(actual_price, std_price)) as actual_material_cost,
        sum(issued_std_value) as material_at_std_price,
        sum(actual_scrap_qty * std_price) as scrap_cost_at_std,
        sum(issue_count) as issue_count,
        max(_max_loaded_at) as _max_loaded_at
    from {{ ref('int_order_material_actuals') }}
    where order_id in (select order_id from orders)
    group by 1
),

std_mat as (
    select order_id, sum(std_qty_incl_scrap * std_price) as std_material_cost
    from {{ ref('int_order_material_standards') }}
    where order_id in (select order_id from orders)
    group by 1
),

var as (
    select order_id,
           sum(variance_amount) as total_variance,
           sum(variance_amount) filter (where cost_element = 'material_price') as material_price_variance,
           sum(variance_amount) filter (where cost_element = 'material_usage') as material_usage_variance,
           sum(variance_amount) filter (where cost_element = 'scrap') as scrap_variance,
           sum(variance_amount) filter (where cost_element = 'labor_rate') as labor_rate_variance,
           sum(variance_amount) filter (where cost_element = 'labor_efficiency') as labor_efficiency_variance,
           sum(variance_amount) filter (where cost_element = 'overhead_efficiency') as overhead_efficiency_variance
    from {{ ref('fct_cost_variance') }}
    where order_id in (select order_id from orders)
    group by 1
)

select
    o.order_id,
    o.product_id,
    o.line_id,
    o.plant_id,
    o.status,
    o.is_completed,
    o.actual_start,
    o.actual_end,
    o.completion_date,
    {{ period_of('o.completion_date') }} as period_id,
    o.planned_qty,
    o.completed_qty,
    o.completed_qty::numeric / nullif(o.planned_qty, 0) as yield_to_plan,
    coalesce(m.actual_material_cost, 0) as actual_material_cost,
    coalesce(m.material_at_std_price, 0) as material_at_std_price,
    coalesce(l.actual_labor_cost, 0) as actual_labor_cost,
    coalesce(l.overhead_applied, 0) as overhead_applied,
    coalesce(m.actual_material_cost, 0) + coalesce(l.actual_labor_cost, 0) + coalesce(l.overhead_applied, 0)
        as total_actual_cost,
    sm.std_material_cost,
    case when o.is_completed then l.std_labor_rate * l.std_hours end as std_labor_cost,
    case when o.is_completed then l.overhead_rate * l.std_hours end as std_overhead_cost,
    case when o.is_completed
         then coalesce(sm.std_material_cost, 0) + l.std_hours * (l.std_labor_rate + l.overhead_rate) end
        as total_std_cost,
    v.total_variance,
    v.material_price_variance,
    v.material_usage_variance,
    v.scrap_variance,
    v.labor_rate_variance,
    v.labor_efficiency_variance,
    v.overhead_efficiency_variance,
    c.std_unit_cost as published_std_unit_cost,
    (coalesce(m.actual_material_cost, 0) + coalesce(l.actual_labor_cost, 0) + coalesce(l.overhead_applied, 0))
        / nullif(o.completed_qty, 0) as actual_unit_cost,
    coalesce(m.scrap_cost_at_std, 0) as scrap_cost_at_std,
    l.actual_hours,
    l.std_hours,
    l.overtime_hours,
    l.late_entries as late_labor_entries,
    coalesce(m.issue_count, 0) as issue_count,
    l.entry_count as labor_entry_count,
    greatest(m._max_loaded_at, l._max_loaded_at, o._loaded_at) as _max_loaded_at
from orders o
left join mat m on m.order_id = o.order_id
left join std_mat sm on sm.order_id = o.order_id
left join {{ ref('int_order_labor') }} l on l.order_id = o.order_id
left join var v on v.order_id = o.order_id
left join {{ ref('int_completions') }} c on c.order_id = o.order_id
