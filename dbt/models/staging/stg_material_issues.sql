-- Deduplicate reloads and normalise units to the material's base UOM
-- (some MES terminals book kilogram materials in grams).
with issues as (
    {{ latest_by(source('raw', 'material_issues'), ['issue_id']) }}
)

select
    i.issue_id,
    i.order_id,
    i.material_id,
    i.plant_id,
    i.line_id,
    i.issue_date,
    i.issue_qty as issue_qty_raw,
    i.uom as uom_raw,
    i.issue_qty * c.factor as issue_qty,
    c.to_uom as uom,
    i.uom <> c.to_uom as uom_converted,
    c.to_uom is distinct from m.base_uom as uom_mismatch,
    i._loaded_at
from issues i
left join {{ ref('stg_uom_conversions') }} c on c.from_uom = i.uom
left join {{ ref('stg_materials') }} m on m.material_id = i.material_id
