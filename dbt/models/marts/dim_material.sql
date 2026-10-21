select
    m.material_id,
    m.material_desc,
    m.category,
    m.base_uom,
    m.primary_supplier_id,
    s.supplier_name as primary_supplier_name,
    m.lead_time_days,
    p.std_price,
    p.version as std_version
from {{ ref('stg_materials') }} m
left join {{ ref('stg_suppliers') }} s on s.supplier_id = m.primary_supplier_id
left join {{ ref('int_std_material_price') }} p
    on p.material_id = m.material_id
    and (select min(period_start) from {{ ref('stg_fiscal_calendar') }}) between p.effective_from and p.effective_to
