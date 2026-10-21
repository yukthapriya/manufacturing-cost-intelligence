-- depends_on: {{ ref('int_material_issues') }}
-- depends_on: {{ ref('int_labor_entries') }}
-- depends_on: {{ ref('stg_scrap_records') }}
-- depends_on: {{ ref('stg_production_orders') }}
{{
    config(
        materialized='incremental',
        unique_key='order_id',
        incremental_strategy='delete+insert',
        indexes=[{'columns': ['order_id', 'material_id'], 'unique': True}, {'columns': ['_max_loaded_at']}],
    )
}}

-- Actual consumption per order and material: total issued quantity (good + scrap),
-- recorded scrap, and the actual purchase price for the month the material was issued.
with iss as (
    select
        order_id,
        material_id,
        min(plant_id) as plant_id,
        min(issue_date) as first_issue_date,
        sum(issue_qty) as actual_qty,
        min(std_price) as std_price,
        sum(std_value) as issued_std_value,
        string_agg(issue_id::text, ',' order by issue_id) as issue_ids,
        count(*) as issue_count,
        max(_max_loaded_at) as _max_loaded_at
    from {{ ref('int_material_issues') }}
    {% if is_incremental() %}
    where order_id in ({{ changed_orders() }})
    {% endif %}
    group by 1, 2
),

scr as (
    select
        order_id,
        material_id,
        sum(scrap_qty) as actual_scrap_qty,
        string_agg(scrap_id::text, ',' order by scrap_id) as scrap_ids,
        max(_loaded_at) as _max_loaded_at
    from {{ ref('int_scrap') }}
    {% if is_incremental() %}
    where order_id in ({{ changed_orders() }})
    {% endif %}
    group by 1, 2
)

select
    i.order_id,
    i.material_id,
    i.plant_id,
    i.first_issue_date,
    i.actual_qty,
    coalesce(s.actual_scrap_qty, 0) as actual_scrap_qty,
    i.std_price,
    ap.actual_price,
    ap.price_source,
    i.issued_std_value,
    i.issue_ids,
    i.issue_count,
    s.scrap_ids,
    greatest(i._max_loaded_at, s._max_loaded_at) as _max_loaded_at
from iss i
left join scr s using (order_id, material_id)
left join {{ ref('int_actual_material_price') }} ap
    on ap.plant_id = i.plant_id
    and ap.material_id = i.material_id
    and ap.period_id = {{ period_of('i.first_issue_date') }}
