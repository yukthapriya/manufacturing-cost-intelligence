-- Multi-level BOM explosion: finished good -> purchased material, through any number of
-- (phantom) subassembly levels. Quantities multiply along the path; the scrap allowance
-- of the material's own BOM line applies. Cycle-safe via the path array.
with recursive bom as (
    select parent_id, parent_type, component_id, component_type, qty_per::numeric as qty_per, scrap_allowance_pct
    from {{ ref('stg_bom') }}
),

walk as (
    select
        b.parent_id as product_id,
        b.component_id,
        b.component_type,
        b.qty_per as path_qty,
        b.scrap_allowance_pct,
        1 as depth,
        array[b.parent_id, b.component_id] as path
    from bom b
    where b.parent_type = 'PRODUCT'

    union all

    select
        w.product_id,
        b.component_id,
        b.component_type,
        w.path_qty * b.qty_per,
        b.scrap_allowance_pct,
        w.depth + 1,
        w.path || b.component_id
    from walk w
    join bom b on b.parent_id = w.component_id
    where w.component_type = 'SUBASSEMBLY'
      and w.depth < 10
      and not b.component_id = any(w.path)
)

select
    product_id,
    component_id as material_id,
    sum(path_qty) as qty_per,
    sum(path_qty * (1 + scrap_allowance_pct)) as std_qty_per_incl_scrap,
    max(depth) as max_depth,
    count(*) as path_count
from walk
where component_type = 'MATERIAL'
group by 1, 2
