-- Supplier price trend vs. standard: quantity-weighted invoice price index by month
-- (standard = 100), month-over-month change, and cumulative purchase price variance.
-- Surfaces suppliers drifting away from standard and sudden surcharges.
with monthly as (
    select
        supplier_id,
        period_id,
        sum(invoice_qty * invoice_price) / sum(invoice_qty * std_price) * 100 as price_index,
        sum(ppv_vs_std) as ppv,
        count(*) as invoice_lines
    from marts.fct_purchase_price
    group by 1, 2
)

select
    m.supplier_id,
    s.supplier_name,
    m.period_id,
    round(m.price_index, 2) as price_index_vs_std,
    round(m.price_index - lag(m.price_index) over w, 2) as mom_change_pts,
    round(m.ppv, 2) as ppv,
    round(sum(m.ppv) over (w rows between unbounded preceding and current row), 2) as cumulative_ppv,
    m.invoice_lines,
    case when m.price_index - lag(m.price_index) over w > 5 then 'price jump > 5 pts' end as alert
from monthly m
join marts.dim_supplier s using (supplier_id)
window w as (partition by m.supplier_id order by m.period_id)
order by max(m.price_index) over (partition by m.supplier_id) desc, m.supplier_id, m.period_id;
