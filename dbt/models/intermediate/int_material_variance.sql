{{ config(materialized='view') }}

-- Material variance decomposition per completed order and material.
--   AQ actual qty issued (good + scrap)   AS actual scrap qty
--   AP actual price                       SP standard price
--   SQg standard qty for good output      SQa allowed scrap qty   (SQ = SQg + SQa)
--
--   price variance  = (AP - SP) * AQ
--   usage variance  = (AQ - AS - SQg) * SP        good-material over/under use
--   scrap variance  = (AS - SQa) * SP             scrap beyond the allowance
--   price + usage + scrap = AP*AQ - SP*SQ = actual cost - standard cost   (exact)
with a as (
    select a.*
    from {{ ref('int_order_material_actuals') }} a
    join {{ ref('stg_production_orders') }} o on o.order_id = a.order_id and o.is_completed
),

s as (
    select * from {{ ref('int_order_material_standards') }}
),

j as (
    select
        coalesce(s.order_id, a.order_id) as order_id,
        coalesce(s.material_id, a.material_id) as material_id,
        coalesce(a.actual_qty, 0) as aq,
        coalesce(a.actual_scrap_qty, 0) as asq,
        coalesce(s.std_price, a.std_price) as sp,
        coalesce(a.actual_price, s.std_price, a.std_price) as ap,
        coalesce(s.std_qty_good, 0) as sq_good,
        coalesce(s.allowed_scrap_qty, 0) as sq_allow,
        coalesce(s.std_qty_incl_scrap, 0) as sq,
        a.price_source,
        a.issue_ids,
        a.scrap_ids,
        coalesce(a.issue_count, 0) as issue_count,
        a._max_loaded_at,
        s.order_id is null as not_in_bom
    from s
    full outer join a on a.order_id = s.order_id and a.material_id = s.material_id
)

select
    order_id,
    material_id,
    aq as actual_qty,
    asq as actual_scrap_qty,
    sq_good as std_qty_good,
    sq_allow as allowed_scrap_qty,
    sq as std_qty,
    ap as actual_price,
    sp as std_price,
    ap * aq as actual_cost,
    sp * sq as std_cost,
    (ap - sp) * aq as price_variance,
    (aq - asq - sq_good) * sp as usage_variance,
    (asq - sq_allow) * sp as scrap_variance,
    price_source,
    not_in_bom,
    issue_ids,
    scrap_ids,
    issue_count,
    _max_loaded_at
from j
