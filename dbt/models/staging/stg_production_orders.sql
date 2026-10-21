-- Collapse the CDC event stream to the current state of each order.
-- A COMPLETED event always wins over RELEASED, whatever order they were loaded in.
select distinct on (order_id)
    order_id,
    product_id,
    line_id,
    plant_id,
    planned_qty,
    completed_qty,
    status,
    status = 'COMPLETED' as is_completed,
    actual_start,
    actual_end,
    actual_end::date as completion_date,
    extract_ts,
    _loaded_at
from {{ source('raw', 'production_orders') }}
order by order_id, (status = 'COMPLETED') desc, extract_ts desc, _loaded_at desc
