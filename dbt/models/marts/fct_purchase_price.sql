-- Grain: supplier invoice line (duplicates excluded). Invoice price vs. PO and standard;
-- feeds the supplier price trend and purchase price variance views.
select
    i.invoice_id,
    i.invoice_line,
    i.invoice_number,
    i.supplier_id,
    i.plant_id,
    i.material_id,
    m.category,
    i.invoice_date,
    {{ period_of('i.invoice_date') }} as period_id,
    i.invoice_qty,
    i.invoice_price,
    pol.unit_price as po_price,
    sp.std_price,
    i.invoice_price / nullif(sp.std_price, 0) - 1 as price_vs_std_pct,
    i.invoice_price / nullif(pol.unit_price, 0) - 1 as price_vs_po_pct,
    round(i.invoice_qty * (i.invoice_price - sp.std_price), 2) as ppv_vs_std,
    i.is_missing_po
from {{ ref('stg_invoice_lines') }} i
left join {{ ref('stg_purchase_order_lines') }} pol on pol.po_id = i.po_id and pol.po_line = i.po_line
left join {{ ref('stg_materials') }} m on m.material_id = i.material_id
left join {{ ref('int_std_material_price') }} sp
    on sp.material_id = i.material_id and i.invoice_date between sp.effective_from and sp.effective_to
where not i.is_duplicate
