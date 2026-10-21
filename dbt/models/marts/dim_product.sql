with bom as (
    select product_id, count(*) as component_count, max(max_depth) as bom_levels
    from {{ ref('int_bom_exploded') }}
    group by 1
),

rollup as (
    -- standard cost rolled up from the BOM, to compare with the published standard
    select b.product_id, sum(b.std_qty_per_incl_scrap * m.std_price) as std_material_cost
    from {{ ref('int_bom_exploded') }} b
    join {{ ref('int_std_material_price') }} m
      on m.material_id = b.material_id
      and (select min(period_start) from {{ ref('stg_fiscal_calendar') }}) between m.effective_from and m.effective_to
    group by 1
)

select
    p.product_id,
    p.product_name,
    p.family,
    p.line_id,
    p.plant_id,
    s.std_unit_cost,
    s.std_labor_hours,
    r.std_material_cost,
    s.std_labor_hours * lr.std_labor_rate as std_labor_cost,
    s.std_labor_hours * lr.overhead_rate as std_overhead_cost,
    round(r.std_material_cost + s.std_labor_hours * (lr.std_labor_rate + lr.overhead_rate), 4) as std_unit_cost_rollup,
    b.component_count,
    b.bom_levels,
    s.version as std_version
from {{ ref('stg_products') }} p
left join {{ ref('int_std_product') }} s
    on s.product_id = p.product_id
    and (select min(period_start) from {{ ref('stg_fiscal_calendar') }}) between s.effective_from and s.effective_to
left join {{ ref('int_std_line_rates') }} lr
    on lr.line_id = p.line_id and lr.version = s.version
left join bom b on b.product_id = p.product_id
left join rollup r on r.product_id = p.product_id
