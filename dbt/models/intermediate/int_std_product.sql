select
    item_id as product_id,
    max(std_value) filter (where cost_component = 'LABOR_HOURS') as std_labor_hours,
    max(std_value) filter (where cost_component = 'UNIT_COST') as std_unit_cost,
    effective_from,
    effective_to,
    version
from {{ ref('stg_standard_costs') }}
where item_type = 'PRODUCT'
group by item_id, effective_from, effective_to, version
