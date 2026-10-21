{{
    config(
        materialized='incremental',
        unique_key='issue_id',
        incremental_strategy='delete+insert',
        indexes=[
            {'columns': ['issue_id'], 'unique': True},
            {'columns': ['order_id']},
            {'columns': ['_max_loaded_at']},
        ],
    )
}}

-- Issues valued at the standard price in force on the issue date, rounded per
-- transaction like the ERP. Issues post the same day, so they never route.
select
    i.issue_id,
    i.order_id,
    i.material_id,
    i.plant_id,
    i.line_id,
    i.issue_date,
    {{ period_of('i.issue_date') }} as period_id,
    i.issue_qty,
    i.uom,
    i.issue_qty_raw,
    i.uom_raw,
    i.uom_converted,
    p.std_price,
    {{ money('i.issue_qty', 'p.std_price') }} as std_value,
    i._loaded_at as _max_loaded_at
from {{ ref('stg_material_issues') }} i
left join {{ ref('int_std_material_price') }} p
    on p.material_id = i.material_id
    and i.issue_date between p.effective_from and p.effective_to
{% if is_incremental() %}
where i._loaded_at > {{ incremental_watermark() }}
{% endif %}
