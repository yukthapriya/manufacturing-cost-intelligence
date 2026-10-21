select
    s.scrap_id,
    s.order_id,
    s.material_id,
    s.plant_id,
    s.line_id,
    s.scrap_date,
    {{ period_of('s.scrap_date') }} as period_id,
    s.scrap_qty,
    s.uom,
    s.reason_code,
    p.std_price,
    {{ money('s.scrap_qty', 'p.std_price') }} as std_value,
    s._loaded_at
from {{ ref('stg_scrap_records') }} s
left join {{ ref('int_std_material_price') }} p
    on p.material_id = s.material_id
    and s.scrap_date between p.effective_from and p.effective_to
