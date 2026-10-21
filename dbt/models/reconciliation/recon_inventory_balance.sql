-- Grain: period x plant x inventory account. Month-end balance per the cost subledger
-- vs. the GL, plus an independent valuation where one exists:
--   1300 raw materials: perpetual quantity x standard price (rounded per material)
--   1400 WIP:          sum of open-order balances (from the WIP roll-forward)
with periods as (
    select c.period_id, c.period_end, p.plant_id, a.account
    from {{ ref('stg_fiscal_calendar') }} c
    cross join {{ ref('stg_plants') }} p
    cross join (values ('1300'), ('1400'), ('1500')) a(account)
    where c.period_id <= (select max(period_id) from {{ ref('stg_gl_journal_entries') }})
),

sub as (
    select period_id, plant_id, account, sum(amount) as activity
    from {{ ref('int_subledger_postings') }} where account in ('1300', '1400', '1500') group by 1, 2, 3
),

gl as (
    select period_id, plant_id, account, sum(net_amount) as activity
    from {{ ref('stg_gl_journal_entries') }} where account in ('1300', '1400', '1500') group by 1, 2, 3
),

bal as (
    select
        p.period_id, p.period_end, p.plant_id, p.account,
        sum(coalesce(s.activity, 0)) over w as subledger_balance,
        sum(coalesce(g.activity, 0)) over w as gl_balance
    from periods p
    left join sub s using (period_id, plant_id, account)
    left join gl g using (period_id, plant_id, account)
    window w as (partition by p.plant_id, p.account order by p.period_id)
),

perpetual as (
    select i.plant_id, i.period_id, '1300' as account, sum(round(i.perpetual_qty * sp.std_price, 2)) as valuation
    from {{ ref('int_inventory_perpetual') }} i
    join {{ ref('int_std_material_price') }} sp
      on sp.material_id = i.material_id and i.period_end between sp.effective_from and sp.effective_to
    group by 1, 2
    union all
    select plant_id, period_id, '1400', ending_open_orders from {{ ref('recon_wip_rollforward') }}
)

select
    {{ dbt_utils_surrogate(['b.period_id', 'b.plant_id', 'b.account']) }} as balance_id,
    b.period_id,
    b.period_end,
    b.plant_id,
    b.account,
    a.account_name,
    b.subledger_balance,
    b.gl_balance,
    round(b.gl_balance - b.subledger_balance, 2) as gl_vs_subledger_diff,
    pv.valuation as independent_valuation,
    round(pv.valuation - b.subledger_balance, 2) as valuation_vs_subledger_diff,
    case when abs(b.gl_balance - b.subledger_balance) < 0.01 then 'matched'
         when abs(b.gl_balance - b.subledger_balance) <= {{ var('recon_tolerance_usd') }} then 'within_tolerance'
         else 'exception' end as status,
    abs(b.gl_balance - b.subledger_balance) > {{ var('materiality_usd') }} as is_material
from bal b
left join perpetual pv using (plant_id, period_id, account)
left join {{ ref('stg_gl_accounts') }} a on a.account = b.account
