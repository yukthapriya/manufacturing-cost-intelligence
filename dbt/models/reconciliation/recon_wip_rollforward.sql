-- WIP roll-forward per plant and period:
--   beginning + material issued + labor + overhead - completions - scrap - settlement
--   = ending (roll-forward)
-- checked against an independently built ending balance: the cumulative activity of
-- every order still open at period end. Also compared with the GL WIP account.
with periods as (
    select c.period_id, p.plant_id
    from {{ ref('stg_fiscal_calendar') }} c
    cross join {{ ref('stg_plants') }} p
    where c.period_id <= (select max(period_id) from {{ ref('stg_gl_journal_entries') }})
),

flows as (
    select
        plant_id, period_id,
        sum(amount) filter (where source_type = 'ISSUE') as material_issued,
        sum(amount) filter (where source_type = 'LABOR') as labor,
        sum(amount) filter (where source_type = 'OVERHEAD') as overhead,
        -sum(amount) filter (where source_type = 'COMPLETION') as completions,
        -sum(amount) filter (where source_type = 'SCRAP') as scrap
    from {{ ref('int_wip_activity') }}
    group by 1, 2
),

settle as (
    select plant_id, period_id, sum(settle_amount) as settlement
    from {{ ref('int_wip_settlement') }} group by 1, 2
),

-- independent ending balance: orders not completed by period end (or completed later)
order_cum as (
    select a.plant_id, p.period_id, sum(a.amount) as balance
    from {{ ref('int_wip_activity') }} a
    join {{ ref('stg_production_orders') }} o using (order_id)
    join periods p on p.plant_id = a.plant_id and a.period_id <= p.period_id
    where not o.is_completed or {{ period_of('o.completion_date') }} > p.period_id
    group by 1, 2
),

gl as (
    select plant_id, period_id, sum(net_amount) as activity
    from {{ ref('stg_gl_journal_entries') }} where account = '1400' group by 1, 2
),

rf as (
    select
        p.plant_id,
        p.period_id,
        coalesce(f.material_issued, 0) as material_issued,
        coalesce(f.labor, 0) as labor,
        coalesce(f.overhead, 0) as overhead,
        coalesce(f.completions, 0) as completions,
        coalesce(f.scrap, 0) as scrap,
        coalesce(s.settlement, 0) as settlement,
        coalesce(oc.balance, 0) as ending_open_orders,
        sum(coalesce(g.activity, 0)) over (partition by p.plant_id order by p.period_id) as gl_ending
    from periods p
    left join flows f using (plant_id, period_id)
    left join settle s using (plant_id, period_id)
    left join order_cum oc using (plant_id, period_id)
    left join gl g using (plant_id, period_id)
),

net as (
    select
        *,
        material_issued + labor + overhead - completions - scrap - settlement as net_change
    from rf
)

select
    {{ dbt_utils_surrogate(['plant_id', 'period_id']) }} as rollforward_id,
    plant_id,
    period_id,
    coalesce(sum(net_change) over w_prev, 0) as beginning_wip,
    material_issued,
    labor,
    overhead,
    completions,
    scrap,
    settlement,
    sum(net_change) over w as ending_wip_rollforward,
    ending_open_orders,
    round(sum(net_change) over w - ending_open_orders, 2) as rollforward_diff,
    abs(sum(net_change) over w - ending_open_orders) < 0.01 as ties_out,
    gl_ending as gl_ending_wip,
    round(gl_ending - sum(net_change) over w, 2) as gl_diff
from net
window
    w as (partition by plant_id order by period_id),
    w_prev as (partition by plant_id order by period_id rows between unbounded preceding and 1 preceding)
