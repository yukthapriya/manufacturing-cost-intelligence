-- Top 10 variance drivers per production line for a period range.
-- A "driver" is a cost element + material (or labor/overhead) combination; ranked by
-- absolute unfavorable impact so offsetting favorable noise does not hide problems.
-- Params: replace the period range as needed.
with drivers as (
    select
        v.line_id,
        v.cost_element,
        coalesce(m.material_desc, initcap(replace(v.cost_element, '_', ' '))) as driver,
        sum(v.variance_amount) as variance_amount,
        count(distinct v.order_id) as orders_affected
    from marts.fct_cost_variance v
    left join marts.dim_material m on m.material_id = v.material_id
    where v.period_id between '2025-01' and '2025-12'
    group by 1, 2, 3
),

ranked as (
    select
        *,
        row_number() over (partition by line_id order by variance_amount desc) as rnk,
        variance_amount / sum(variance_amount) over (partition by line_id) as share_of_line_variance
    from drivers
)

select line_id, rnk, cost_element, driver, round(variance_amount, 2) as variance_amount, orders_affected,
       round(100 * share_of_line_variance, 1) as pct_of_line_total
from ranked
where rnk <= 10
order by line_id, rnk;
