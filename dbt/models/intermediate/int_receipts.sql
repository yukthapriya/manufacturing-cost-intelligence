select
    g.gr_id,
    g.po_id,
    g.po_line,
    g.material_id,
    g.plant_id,
    pol.supplier_id,
    g.receipt_date,
    {{ period_of('g.receipt_date') }} as period_id,
    g.receipt_qty,
    g.uom,
    pol.unit_price as po_price,
    p.std_price,
    {{ money('g.receipt_qty', 'p.std_price') }} as std_value,
    {{ money('g.receipt_qty', 'pol.unit_price') }} as po_value
from {{ ref('stg_goods_receipts') }} g
left join {{ ref('stg_purchase_order_lines') }} pol on pol.po_id = g.po_id and pol.po_line = g.po_line
left join {{ ref('int_std_material_price') }} p
    on p.material_id = g.material_id
    and g.receipt_date between p.effective_from and p.effective_to
