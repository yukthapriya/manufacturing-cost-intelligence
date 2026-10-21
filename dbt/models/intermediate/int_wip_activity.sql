-- Every movement into or out of WIP, per order, accounting period and source.
-- Charges: material issued at standard, labor at actual, overhead applied.
-- Relief: completions at standard unit cost, scrap at standard.
select order_id, plant_id, period_id, 'ISSUE' as source_type, sum(std_value) as amount
from {{ ref('int_material_issues') }} group by 1, 2, 3

union all
select order_id, plant_id, period_id, 'LABOR', sum(labor_cost)
from {{ ref('int_labor_entries') }} group by 1, 2, 3

union all
select order_id, plant_id, period_id, 'OVERHEAD', sum(overhead_applied)
from {{ ref('int_labor_entries') }} group by 1, 2, 3

union all
select order_id, plant_id, period_id, 'SCRAP', -sum(std_value)
from {{ ref('int_scrap') }} group by 1, 2, 3

union all
select order_id, plant_id, period_id, 'COMPLETION', -sum(std_value)
from {{ ref('int_completions') }} group by 1, 2, 3
