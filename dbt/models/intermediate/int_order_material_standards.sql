-- What completed output should have consumed: BOM quantity per good unit, and the
-- scrap allowance on top, priced at the standard in force on the completion date.
select
    o.order_id,
    b.material_id,
    o.product_id,
    o.plant_id,
    o.completed_qty,
    b.qty_per * o.completed_qty as std_qty_good,
    b.std_qty_per_incl_scrap * o.completed_qty as std_qty_incl_scrap,
    (b.std_qty_per_incl_scrap - b.qty_per) * o.completed_qty as allowed_scrap_qty,
    sp.std_price
from {{ ref('stg_production_orders') }} o
join {{ ref('int_bom_exploded') }} b on b.product_id = o.product_id
left join {{ ref('int_std_material_price') }} sp
    on sp.material_id = b.material_id
    and o.completion_date between sp.effective_from and sp.effective_to
where o.is_completed
