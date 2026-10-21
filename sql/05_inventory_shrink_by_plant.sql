-- Inventory shrink by plant from cycle counts: counted vs. ERP system quantity, valued at
-- standard, with shrink rate against the value of what was counted and the worst items.
with counted as (
    select *
    from marts.fct_inventory_discrepancy
    where counted_qty is not null
),

plant as (
    select
        plant_id,
        count(*) as counts_taken,
        count(*) filter (where flag_count_variance) as counts_with_variance,
        sum(count_vs_system_value) filter (where count_vs_system_value < 0) as shrink_value,
        sum(count_vs_system_value) filter (where count_vs_system_value > 0) as overage_value,
        sum(greatest(system_qty, 0) * std_price) as counted_system_value
    from counted
    group by 1
),

worst as (
    select plant_id, string_agg(material_id || ' (' || to_char(count_vs_system_value, 'FM999,999,990.00') || ')', ', '
                                order by count_vs_system_value) as worst_items
    from (
        select plant_id, material_id, count_vs_system_value,
               row_number() over (partition by plant_id order by count_vs_system_value) as rn
        from counted where count_vs_system_value < 0
    ) w
    where rn <= 3
    group by 1
)

select
    p.plant_id,
    p.counts_taken,
    p.counts_with_variance,
    round(p.shrink_value, 2) as shrink_value,
    round(p.overage_value, 2) as overage_value,
    round(100 * -p.shrink_value / nullif(p.counted_system_value, 0), 3) as shrink_rate_pct,
    w.worst_items
from plant p
left join worst w using (plant_id)
order by p.shrink_value;
