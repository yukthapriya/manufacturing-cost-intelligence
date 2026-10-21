-- Grain: plant x material x month end. Three views of on-hand quantity:
--   perpetual  - rebuilt by this pipeline from opening + receipts - issues
--   system     - the ERP's own month-end snapshot
--   physical   - cycle count, when one was taken that month
with snap as (
    select plant_id, material_id, to_char(snapshot_date, 'YYYY-MM') as period_id, snapshot_date, system_qty
    from {{ ref('stg_inventory_snapshots') }}
),

counts as (
    select distinct on (plant_id, material_id, to_char(count_date, 'YYYY-MM'))
        plant_id, material_id, to_char(count_date, 'YYYY-MM') as period_id, count_id, count_date, counted_qty
    from {{ ref('stg_cycle_counts') }}
    order by plant_id, material_id, to_char(count_date, 'YYYY-MM'), count_date desc
)

select
    {{ dbt_utils_surrogate(['s.plant_id', 's.material_id', 's.period_id']) }} as discrepancy_id,
    s.plant_id,
    s.material_id,
    s.period_id,
    s.snapshot_date,
    p.perpetual_qty,
    s.system_qty,
    c.counted_qty,
    c.count_id,
    c.count_date,
    sp.std_price,
    s.system_qty - p.perpetual_qty as system_vs_perpetual_qty,
    round((s.system_qty - p.perpetual_qty) * sp.std_price, 2) as system_vs_perpetual_value,
    c.counted_qty - s.system_qty as count_vs_system_qty,
    round((c.counted_qty - s.system_qty) * sp.std_price, 2) as count_vs_system_value,
    round(p.perpetual_qty * sp.std_price, 2) as perpetual_value,
    s.system_qty < 0 as flag_negative_system_qty,
    abs(s.system_qty - p.perpetual_qty) > 0.0005 as flag_system_break,
    c.counted_qty is not null
        and abs(c.counted_qty - s.system_qty) > greatest(0.02 * abs(s.system_qty), 1) as flag_count_variance
from snap s
left join {{ ref('int_inventory_perpetual') }} p using (plant_id, material_id, period_id)
left join counts c using (plant_id, material_id, period_id)
left join {{ ref('int_std_material_price') }} sp
    on sp.material_id = s.material_id and s.snapshot_date between sp.effective_from and sp.effective_to
