-- Traceability: the transaction-level drill-through adds back up to the order-level
-- material-at-standard and labor cost in fct_production_cost.
with txn as (
    select order_id,
           sum(std_value) filter (where txn_type = 'ISSUE') as issue_std,
           sum(actual_value) filter (where txn_type = 'LABOR') as labor_actual
    from {{ ref('fct_cost_transactions') }}
    group by 1
)

select f.order_id, f.material_at_std_price, t.issue_std, f.actual_labor_cost, t.labor_actual
from {{ ref('fct_production_cost') }} f
left join txn t using (order_id)
where abs(f.material_at_std_price - coalesce(t.issue_std, 0)) > 0.005
   or abs(f.actual_labor_cost - coalesce(t.labor_actual, 0)) > 0.005
