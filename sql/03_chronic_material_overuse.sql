-- Lines with chronic material overuse: usage variance that is materially unfavorable
-- month after month, not one bad order. Order-level usage first, then a run-length
-- (gaps-and-islands) of consecutive months above a 1% overuse threshold.
with orders as (
    select line_id, period_id, order_id,
           sum(variance_amount) as usage_variance,
           sum(std_cost) as std_material_cost
    from marts.fct_cost_variance
    where cost_element = 'material_usage'
    group by 1, 2, 3
),

monthly as (
    select
        line_id,
        period_id,
        sum(usage_variance) as usage_variance,
        sum(std_material_cost) as std_material_cost,
        sum(usage_variance) / nullif(sum(std_material_cost), 0) as overuse_ratio,
        count(*) filter (where usage_variance > 0) as orders_over,
        count(*) as orders
    from orders
    group by 1, 2
),

flagged as (
    select
        *,
        overuse_ratio > 0.01 as over_threshold,
        row_number() over (partition by line_id order by period_id)
          - row_number() over (partition by line_id, overuse_ratio > 0.01 order by period_id) as island
    from monthly
),

runs as (
    select line_id, island, count(*) as consecutive_months
    from flagged
    where over_threshold
    group by 1, 2
)

select
    f.line_id,
    round(sum(f.usage_variance), 2) as usage_variance_ytd,
    round(100 * sum(f.usage_variance) / nullif(sum(f.std_material_cost), 0), 2) as overuse_pct_of_std,
    round(100.0 * sum(f.orders_over) / sum(f.orders), 1) as pct_orders_over_standard,
    coalesce(max(r.consecutive_months), 0) as months_in_a_row_over_1pct,
    case when coalesce(max(r.consecutive_months), 0) >= 3 then 'CHRONIC' else 'ok' end as assessment
from flagged f
left join runs r using (line_id)
group by f.line_id
order by usage_variance_ytd desc;
