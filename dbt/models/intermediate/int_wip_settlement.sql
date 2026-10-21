-- Period-end settlement of completed orders: whatever is left in WIP after completions
-- and scrap is the order's variance and is cleared to account 5200.
--   * first accounting period at/after the completion period: settle the whole balance
--   * later periods (late-posted labor on a settled order): settle that period's activity
-- Open orders are never settled; their balance is the WIP carried forward.
with act as (
    select order_id, period_id, sum(amount) as amount
    from {{ ref('int_wip_activity') }}
    group by 1, 2
),

orders as (
    select order_id, plant_id, {{ period_of('completion_date') }} as completion_period
    from {{ ref('stg_production_orders') }}
    where is_completed
),

a as (
    select
        act.order_id,
        act.period_id,
        act.amount,
        o.plant_id,
        o.completion_period,
        sum(act.amount) over (partition by act.order_id order by act.period_id) as cumulative,
        lag(act.period_id) over (partition by act.order_id order by act.period_id) as prev_period
    from act
    join orders o using (order_id)
)

select
    order_id,
    plant_id,
    period_id,
    completion_period,
    case when coalesce(prev_period, '') < completion_period then cumulative else amount end as settle_amount
from a
where period_id >= completion_period
