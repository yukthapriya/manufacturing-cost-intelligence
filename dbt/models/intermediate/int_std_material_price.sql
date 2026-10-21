select
    item_id as material_id,
    std_value as std_price,
    uom,
    effective_from,
    effective_to,
    version
from {{ ref('stg_standard_costs') }}
where item_type = 'MATERIAL' and cost_component = 'STD_PRICE'
