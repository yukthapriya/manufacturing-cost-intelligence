-- Every open reconciliation exception in one list: the work queue for period close and
-- the source of the close package. `is_critical` exceptions block close sign-off.
select
    'subledger_to_gl' as recon_type,
    recon_id as exception_key,
    period_id,
    plant_id,
    account || ' ' || account_name || ' / ' || source_type as description,
    diff as amount,
    status,
    root_cause,
    age_days,
    aging_bucket,
    is_material as is_critical
from {{ ref('recon_subledger_to_gl') }}
where status = 'exception'

union all

select
    'wip_rollforward', rollforward_id, period_id, plant_id,
    'WIP roll-forward does not tie to open orders', rollforward_diff, 'exception', 'rollforward_break',
    null, null, true
from {{ ref('recon_wip_rollforward') }}
where not ties_out

union all

select
    'three_way_match', match_id, period_id, plant_id,
    coalesce(po_id || '/' || po_line, 'invoice ' || invoice_refs) || ' ' || material_id,
    amount_at_risk, status, root_cause, age_days, aging_bucket, false
from {{ ref('recon_three_way_match') }}
where status = 'exception'

union all

select
    'inventory', discrepancy_id, period_id, plant_id,
    material_id || case when flag_negative_system_qty then ' negative system qty'
                        when flag_system_break then ' ERP qty differs from perpetual'
                        else ' cycle count variance' end,
    coalesce(case when flag_system_break then system_vs_perpetual_value end, count_vs_system_value),
    'exception',
    case when flag_negative_system_qty then 'negative_inventory'
         when flag_system_break then 'erp_vs_perpetual'
         else 'count_variance' end,
    null, null, false
from {{ ref('fct_inventory_discrepancy') }}
where flag_negative_system_qty or flag_system_break or flag_count_variance
