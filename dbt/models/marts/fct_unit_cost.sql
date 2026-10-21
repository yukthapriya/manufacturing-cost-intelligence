-- Grain: product x line x month of completion. Weighted unit cost actual vs. standard.
select
    {{ dbt_utils_surrogate(['f.product_id', 'f.line_id', 'f.period_id']) }} as unit_cost_id,
    f.product_id,
    p.family,
    f.line_id,
    f.plant_id,
    f.period_id,
    count(*) as orders_completed,
    sum(f.completed_qty) as units_completed,
    sum(f.total_actual_cost) as total_actual_cost,
    sum(f.total_std_cost) as total_std_cost,
    sum(f.total_variance) as total_variance,
    sum(f.total_actual_cost) / nullif(sum(f.completed_qty), 0) as actual_unit_cost,
    sum(f.total_std_cost) / nullif(sum(f.completed_qty), 0) as std_unit_cost,
    max(f.published_std_unit_cost) as published_std_unit_cost,
    sum(f.actual_material_cost) / nullif(sum(f.completed_qty), 0) as actual_material_per_unit,
    sum(f.actual_labor_cost) / nullif(sum(f.completed_qty), 0) as actual_labor_per_unit,
    sum(f.overhead_applied) / nullif(sum(f.completed_qty), 0) as actual_overhead_per_unit,
    sum(f.total_variance) / nullif(sum(f.total_std_cost), 0) as variance_pct
from {{ ref('fct_production_cost') }} f
join {{ ref('dim_product') }} p using (product_id)
where f.is_completed
group by f.product_id, p.family, f.line_id, f.plant_id, f.period_id
