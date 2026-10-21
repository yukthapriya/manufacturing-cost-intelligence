-- Completed production moves from WIP to finished goods at the published standard unit cost.
select
    o.order_id,
    o.product_id,
    o.line_id,
    o.plant_id,
    o.completion_date,
    {{ period_of('o.completion_date') }} as period_id,
    o.completed_qty,
    sp.std_unit_cost,
    {{ money('o.completed_qty', 'sp.std_unit_cost') }} as std_value
from {{ ref('stg_production_orders') }} o
left join {{ ref('int_std_product') }} sp
    on sp.product_id = o.product_id
    and o.completion_date between sp.effective_from and sp.effective_to
where o.is_completed
