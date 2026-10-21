{{ config(materialized='view') }}

-- Labor and overhead variances for completed orders.
--   AH actual hours   SH standard hours for output   SR standard rate   OHR overhead rate
--   labor rate variance        = actual labor cost - SR * AH        (= (AR - SR) * AH)
--   labor efficiency variance  = (AH - SH) * SR
--   overhead efficiency var.   = overhead applied - OHR * SH        (= (AH - SH) * OHR)
--   the three sum exactly to actual (labor + overhead) - standard (labor + overhead)
select
    order_id,
    product_id,
    line_id,
    plant_id,
    actual_hours,
    std_hours,
    actual_rate,
    std_labor_rate,
    overhead_rate,
    actual_labor_cost,
    overhead_applied,
    std_labor_rate * std_hours as std_labor_cost,
    overhead_rate * std_hours as std_overhead_cost,
    actual_labor_cost - std_labor_rate * actual_hours as labor_rate_variance,
    (actual_hours - std_hours) * std_labor_rate as labor_efficiency_variance,
    overhead_applied - overhead_rate * std_hours as overhead_efficiency_variance,
    labor_entry_ids,
    entry_count,
    _max_loaded_at
from {{ ref('int_order_labor') }}
where is_completed
