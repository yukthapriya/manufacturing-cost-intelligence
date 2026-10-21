-- Subledger vs. GL at posting grain (day x plant x source x account), with a root-cause
-- tag for every break. Day grain is what makes root causes identifiable: at month grain
-- a duplicated or missing day just looks like "a difference".
with sub as (
    select posting_date as je_date, period_id, plant_id, source_type, account, sum(amount) as amount
    from {{ ref('int_subledger_postings') }}
    group by 1, 2, 3, 4, 5
),

gl as (
    select je_date, period_id, plant_id, source_type, account, sum(net_amount) as amount
    from {{ ref('stg_gl_journal_entries') }}
    where account in ('1300', '1400', '1500', '5000', '5200', '5300')
    group by 1, 2, 3, 4, 5
),

j as (
    select
        je_date, period_id, plant_id, source_type, account,
        sub.amount as subledger_amount,
        gl.amount as gl_amount,
        round(coalesce(gl.amount, 0) - coalesce(sub.amount, 0), 2) as diff
    from sub
    full outer join gl using (je_date, period_id, plant_id, source_type, account)
),

breaks as (
    select * from j where abs(diff) >= 0.01
)

select
    b.*,
    case
        when exists (  -- same day/account/source, another plant, equal and opposite
            select 1 from breaks o
            where o.je_date = b.je_date and o.account = b.account and o.source_type = b.source_type
              and o.plant_id <> b.plant_id and abs(o.diff + b.diff) < 0.01
        ) then 'misposted_plant'
        when exists (  -- same plant/account/source, a few days away in another period, opposite
            select 1 from breaks o
            where o.plant_id = b.plant_id and o.account = b.account and o.source_type = b.source_type
              and o.period_id <> b.period_id and abs(o.je_date - b.je_date) <= 5 and abs(o.diff + b.diff) < 0.01
        ) then 'timing_cutoff'
        when b.subledger_amount <> 0 and abs(b.gl_amount - 2 * b.subledger_amount) < 0.01 then 'duplicate_gl_posting'
        when b.gl_amount is null and b.subledger_amount <> 0 then 'missing_gl_posting'
        when b.subledger_amount is null then 'gl_without_subledger'
        else 'unexplained'
    end as root_cause
from breaks b
