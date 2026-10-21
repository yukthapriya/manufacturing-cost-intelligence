-- Actual purchase price per plant, material and month: quantity-weighted average of
-- (de-duplicated) supplier invoice prices. Months without invoices carry the last
-- known price forward; if a material was never invoiced, fall back to standard.
with inv as (
    select
        plant_id,
        material_id,
        {{ period_of('invoice_date') }} as period_id,
        sum(invoice_qty * invoice_price) / nullif(sum(invoice_qty), 0) as wavg_price,
        sum(invoice_qty) as invoiced_qty,
        count(*) as invoice_lines
    from {{ ref('stg_invoice_lines') }}
    where not is_duplicate
    group by 1, 2, 3
),

grid as (
    select k.plant_id, k.material_id, c.period_id, c.period_start, c.period_end
    from (
        select distinct plant_id, material_id from {{ ref('stg_material_issues') }}
        union
        select distinct plant_id, material_id from inv
    ) k
    cross join {{ ref('stg_fiscal_calendar') }} c
),

joined as (
    select
        g.*,
        inv.wavg_price,
        inv.invoiced_qty,
        inv.invoice_lines,
        count(inv.wavg_price) over (partition by g.plant_id, g.material_id order by g.period_id) as price_grp
    from grid g
    left join inv using (plant_id, material_id, period_id)
),

filled as (
    select
        *,
        first_value(wavg_price) over (
            partition by plant_id, material_id, price_grp order by period_id
        ) as carried_price
    from joined
)

select
    f.plant_id,
    f.material_id,
    f.period_id,
    f.period_start,
    f.period_end,
    coalesce(f.carried_price, sp.std_price) as actual_price,
    case when f.wavg_price is not null then 'invoice_month'
         when f.carried_price is not null then 'carried_forward'
         else 'standard' end as price_source,
    f.invoiced_qty,
    f.invoice_lines,
    sp.std_price
from filled f
left join {{ ref('int_std_material_price') }} sp
    on sp.material_id = f.material_id
    and f.period_start between sp.effective_from and sp.effective_to
