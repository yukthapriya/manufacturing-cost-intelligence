-- Critical: for every completed order, price + usage + scrap + labor rate + labor
-- efficiency + overhead efficiency must equal total actual cost - total standard cost.
select order_id, total_actual_cost, total_std_cost, total_variance,
       total_actual_cost - total_std_cost - total_variance as gap
from {{ ref('fct_production_cost') }}
where is_completed
  and abs(total_actual_cost - total_std_cost - total_variance) > 0.01
