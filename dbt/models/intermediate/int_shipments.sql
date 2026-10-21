select
    s.shipment_id,
    s.order_id,
    s.product_id,
    s.plant_id,
    s.ship_date,
    {{ period_of('s.ship_date') }} as period_id,
    s.ship_qty,
    sp.std_unit_cost,
    {{ money('s.ship_qty', 'sp.std_unit_cost') }} as std_value
from {{ ref('stg_shipments') }} s
left join {{ ref('int_std_product') }} sp
    on sp.product_id = s.product_id
    and s.ship_date between sp.effective_from and sp.effective_to
