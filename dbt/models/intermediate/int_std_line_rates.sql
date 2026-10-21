select
    item_id as line_id,
    max(std_value) filter (where cost_component = 'LABOR_RATE') as std_labor_rate,
    max(std_value) filter (where cost_component = 'OVERHEAD_RATE') as overhead_rate,
    effective_from,
    effective_to,
    version
from {{ ref('stg_standard_costs') }}
where item_type = 'LINE'
group by item_id, effective_from, effective_to, version
