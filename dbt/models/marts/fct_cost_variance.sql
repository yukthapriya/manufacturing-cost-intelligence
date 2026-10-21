-- depends_on: {{ ref('int_material_issues') }}
-- depends_on: {{ ref('int_labor_entries') }}
-- depends_on: {{ ref('stg_scrap_records') }}
-- depends_on: {{ ref('stg_production_orders') }}
{{
    config(
        materialized='incremental',
        unique_key='order_id',
        incremental_strategy='delete+insert',
        indexes=[
            {'columns': ['variance_id'], 'unique': True},
            {'columns': ['order_id']},
            {'columns': ['period_id', 'line_id']},
        ],
    )
}}

-- Grain: completed order x cost element (x material for material elements).
-- Elements: material_price, material_usage, scrap, labor_rate, labor_efficiency,
-- overhead_efficiency. Positive = unfavorable (cost above standard).
-- source_txn_ids lists the issue / scrap / labor entry ids behind each row so every
-- dashboard number drills to transactions (see fct_cost_transactions).
with orders as (
    select o.order_id, o.product_id, o.line_id, o.plant_id, o.completion_date, o.completed_qty
    from {{ ref('stg_production_orders') }} o
    where o.is_completed
    {% if is_incremental() %}
      and o.order_id in ({{ changed_orders() }})
    {% endif %}
),

mat as (
    select v.*, e.element, e.amount
    from {{ ref('int_material_variance') }} v
    cross join lateral (values
        ('material_price', v.price_variance),
        ('material_usage', v.usage_variance),
        ('scrap', v.scrap_variance)
    ) as e(element, amount)
    where v.order_id in (select order_id from orders)
),

lab as (
    select v.*, e.element, e.amount
    from {{ ref('int_labor_variance') }} v
    cross join lateral (values
        ('labor_rate', v.labor_rate_variance),
        ('labor_efficiency', v.labor_efficiency_variance),
        ('overhead_efficiency', v.overhead_efficiency_variance)
    ) as e(element, amount)
    where v.order_id in (select order_id from orders)
),

unioned as (
    select
        order_id,
        element as cost_element,
        'MATERIAL' as cost_category,
        material_id,
        std_qty,
        actual_qty,
        case when element = 'scrap' then allowed_scrap_qty end as allowed_scrap_qty,
        case when element = 'scrap' then actual_scrap_qty end as actual_scrap_qty,
        std_price as std_rate,
        actual_price as actual_rate,
        null::numeric as std_hours,
        null::numeric as actual_hours,
        std_cost,
        actual_cost,
        amount,
        case when element = 'scrap' then scrap_ids else issue_ids end as source_txn_ids,
        price_source,
        _max_loaded_at
    from mat

    union all

    select
        order_id,
        element,
        case when element = 'overhead_efficiency' then 'OVERHEAD' else 'LABOR' end,
        null,
        null, null, null, null,
        case when element = 'overhead_efficiency' then overhead_rate else std_labor_rate end,
        case when element = 'overhead_efficiency' then overhead_rate else actual_rate end,
        std_hours,
        actual_hours,
        case when element = 'overhead_efficiency' then std_overhead_cost else std_labor_cost end,
        case when element = 'overhead_efficiency' then overhead_applied else actual_labor_cost end,
        amount,
        labor_entry_ids,
        null,
        _max_loaded_at
    from lab
)

select
    md5(u.order_id::text || '|' || u.cost_element || '|' || coalesce(u.material_id, '')) as variance_id,
    u.order_id,
    o.product_id,
    o.line_id,
    o.plant_id,
    o.completion_date,
    {{ period_of('o.completion_date') }} as period_id,
    o.completed_qty,
    u.cost_category,
    u.cost_element,
    u.material_id,
    u.std_qty,
    u.actual_qty,
    u.allowed_scrap_qty,
    u.actual_scrap_qty,
    u.std_rate,
    u.actual_rate,
    u.std_hours,
    u.actual_hours,
    u.std_cost,
    u.actual_cost,
    round(u.amount, 4) as variance_amount,
    u.amount > 0 as is_unfavorable,
    u.source_txn_ids,
    coalesce(array_length(string_to_array(u.source_txn_ids, ','), 1), 0) as source_txn_count,
    u.price_source,
    u._max_loaded_at
from unioned u
join orders o using (order_id)
