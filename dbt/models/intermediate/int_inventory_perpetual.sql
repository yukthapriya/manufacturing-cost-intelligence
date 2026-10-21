-- Perpetual raw-material quantity rebuilt from transactions:
-- opening + receipts - issues (in base UOM), cumulative at each month end.
with flows as (
    select plant_id, material_id, {{ period_of('as_of_date') }} as period_id, qty, 0 as receipts, 0 as issues
    from {{ ref('stg_opening_inventory') }}
    union all
    select plant_id, material_id, period_id, 0, receipt_qty, 0 from {{ ref('int_receipts') }}
    union all
    select plant_id, material_id, period_id, 0, 0, issue_qty from {{ ref('int_material_issues') }}
),

by_period as (
    select plant_id, material_id, period_id,
           sum(qty) as opening_qty, sum(receipts) as receipt_qty, sum(issues) as issue_qty
    from flows group by 1, 2, 3
),

grid as (
    select k.plant_id, k.material_id, c.period_id, c.period_end
    from (select distinct plant_id, material_id from flows) k
    cross join {{ ref('stg_fiscal_calendar') }} c
)

select
    g.plant_id,
    g.material_id,
    g.period_id,
    g.period_end,
    coalesce(b.opening_qty, 0) as opening_qty,
    coalesce(b.receipt_qty, 0) as receipt_qty,
    coalesce(b.issue_qty, 0) as issue_qty,
    sum(coalesce(b.opening_qty, 0) + coalesce(b.receipt_qty, 0) - coalesce(b.issue_qty, 0))
        over (partition by g.plant_id, g.material_id order by g.period_id) as perpetual_qty
from grid g
left join by_period b using (plant_id, material_id, period_id)
