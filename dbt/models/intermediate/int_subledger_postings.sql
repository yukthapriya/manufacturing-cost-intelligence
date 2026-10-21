{{ config(indexes=[{'columns': ['posting_date', 'plant_id', 'account', 'source_type']}]) }}

-- The cost subledger expressed as the GL postings it implies, at the same grain the ERP
-- posts to the ledger (day x plant x source x account). Debits positive, credits negative.
-- This is what reconciliation compares against stg_gl_journal_entries.
with cal as (select * from {{ ref('stg_fiscal_calendar') }}),

moves as (
    select as_of_date as posting_date, {{ period_of('as_of_date') }} as period_id, plant_id, 'OPENING' as source_type,
           '1300' as dr, '3900' as cr, {{ money('o.qty', 'p.std_price') }} as amount
    from {{ ref('stg_opening_inventory') }} o
    join {{ ref('int_std_material_price') }} p
      on p.material_id = o.material_id and o.as_of_date between p.effective_from and p.effective_to

    union all
    select receipt_date, period_id, plant_id, 'RECEIPT', '1300', '2110', std_value from {{ ref('int_receipts') }}

    union all
    select issue_date, period_id, plant_id, 'ISSUE', '1400', '1300', std_value from {{ ref('int_material_issues') }}

    union all
    select posting_date, period_id, plant_id, 'LABOR', '1400', '2200', labor_cost from {{ ref('int_labor_entries') }}

    union all
    select posting_date, period_id, plant_id, 'OVERHEAD', '1400', '5900', overhead_applied
    from {{ ref('int_labor_entries') }}

    union all
    select scrap_date, period_id, plant_id, 'SCRAP', '5300', '1400', std_value from {{ ref('int_scrap') }}

    union all
    select completion_date, period_id, plant_id, 'COMPLETION', '1500', '1400', std_value
    from {{ ref('int_completions') }}

    union all
    select ship_date, period_id, plant_id, 'SHIPMENT', '5000', '1500', std_value from {{ ref('int_shipments') }}

    union all
    select cal.period_end, s.period_id, s.plant_id, 'SETTLEMENT', '5200', '1400', s.settle_amount
    from {{ ref('int_wip_settlement') }} s
    join cal on cal.period_id = s.period_id
),

legs as (
    select posting_date, period_id, plant_id, source_type, dr as account, amount from moves
    union all
    select posting_date, period_id, plant_id, source_type, cr as account, -amount from moves
)

select posting_date, period_id, plant_id, source_type, account, sum(amount) as amount, count(*) as txn_count
from legs
where account in ('1300', '1400', '1500', '5000', '5200', '5300')
group by 1, 2, 3, 4, 5
