-- Grain: period x plant x account x source type. Status, aging and root cause for every
-- line of the subledger-to-GL reconciliation (matched lines included, for completeness).
with sub as (
    select period_id, plant_id, source_type, account, sum(amount) as amount
    from {{ ref('int_subledger_postings') }} group by 1, 2, 3, 4
),

gl as (
    select period_id, plant_id, source_type, account, sum(net_amount) as amount
    from {{ ref('stg_gl_journal_entries') }}
    where account in ('1300', '1400', '1500', '5000', '5200', '5300')
    group by 1, 2, 3, 4
),

causes as (
    -- dominant root cause = the largest daily break inside the period
    select distinct on (period_id, plant_id, source_type, account)
        period_id, plant_id, source_type, account, root_cause, je_date as break_date
    from {{ ref('recon_gl_daily') }}
    order by period_id, plant_id, source_type, account, abs(diff) desc
),

as_of as (
    select max(je_date) as as_of_date from {{ ref('stg_gl_journal_entries') }}
),

j as (
    select
        period_id, plant_id, source_type, account,
        coalesce(sub.amount, 0) as subledger_amount,
        coalesce(gl.amount, 0) as gl_amount,
        round(coalesce(gl.amount, 0) - coalesce(sub.amount, 0), 2) as diff
    from sub
    full outer join gl using (period_id, plant_id, source_type, account)
)

select
    {{ dbt_utils_surrogate(['j.period_id', 'j.plant_id', 'j.source_type', 'j.account']) }} as recon_id,
    j.period_id,
    j.plant_id,
    j.account,
    a.account_name,
    j.source_type,
    j.subledger_amount,
    j.gl_amount,
    j.diff,
    case when abs(j.diff) < 0.01 then 'matched'
         when abs(j.diff) <= {{ var('recon_tolerance_usd') }} then 'within_tolerance'
         else 'exception' end as status,
    abs(j.diff) > {{ var('materiality_usd') }} as is_material,
    case when abs(j.diff) >= 0.01 then coalesce(c.root_cause, 'unexplained') end as root_cause,
    c.break_date,
    case when abs(j.diff) >= 0.01 then (ao.as_of_date - cal.period_end) end as age_days,
    case when abs(j.diff) >= 0.01 then {{ aging_bucket('(ao.as_of_date - cal.period_end)') }} end as aging_bucket,
    ao.as_of_date
from j
cross join as_of ao
left join causes c using (period_id, plant_id, source_type, account)
left join {{ ref('stg_fiscal_calendar') }} cal on cal.period_id = j.period_id
left join {{ ref('stg_gl_accounts') }} a on a.account = j.account
