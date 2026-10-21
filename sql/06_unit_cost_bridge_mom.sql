-- Month-over-month unit cost bridge per product family: how much of the change in
-- actual unit cost came from material, labor and overhead, plus mix (rate x volume).
with fam as (
    select
        family,
        period_id,
        sum(units_completed) as units,
        sum(actual_material_per_unit * units_completed) / sum(units_completed) as material_pu,
        sum(actual_labor_per_unit * units_completed) / sum(units_completed) as labor_pu,
        sum(actual_overhead_per_unit * units_completed) / sum(units_completed) as overhead_pu,
        sum(total_actual_cost) / sum(units_completed) as actual_pu,
        sum(total_std_cost) / sum(units_completed) as std_pu
    from marts.fct_unit_cost
    group by 1, 2
),

bridge as (
    select
        family,
        period_id,
        units,
        actual_pu,
        std_pu,
        lag(actual_pu) over w as prior_actual_pu,
        material_pu - lag(material_pu) over w as d_material,
        labor_pu - lag(labor_pu) over w as d_labor,
        overhead_pu - lag(overhead_pu) over w as d_overhead
    from fam
    window w as (partition by family order by period_id)
)

select
    family,
    period_id,
    units,
    round(prior_actual_pu, 2) as prior_unit_cost,
    round(d_material, 2) as material_change,
    round(d_labor, 2) as labor_change,
    round(d_overhead, 2) as overhead_change,
    round(actual_pu, 2) as unit_cost,
    round(actual_pu - std_pu, 2) as unit_variance_vs_std,
    round(100 * (actual_pu / nullif(prior_actual_pu, 0) - 1), 2) as mom_pct
from bridge
where prior_actual_pu is not null
order by family, period_id;
