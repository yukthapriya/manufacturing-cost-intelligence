-- Three-way match: purchase order line vs. goods received vs. supplier invoiced.
-- Grain: PO line (plus one row per invoice line that carries no PO reference).
--   matched           quantities equal and price within 0.5% of PO
--   within_tolerance  qty within qty_tolerance_pct, price within price_tolerance_pct
--   exception         anything else, or a duplicate invoice was submitted
with as_of as (select max(invoice_date) as as_of_date from {{ ref('stg_invoice_lines') }}),

rec as (
    select po_id, po_line, sum(receipt_qty) as received_qty, max(receipt_date) as last_receipt_date,
           string_agg(gr_id, ',' order by gr_id) as gr_ids
    from {{ ref('stg_goods_receipts') }} group by 1, 2
),

inv as (
    select
        po_id, po_line,
        sum(invoice_qty) filter (where not is_duplicate) as invoiced_qty,
        sum(invoice_qty * invoice_price) filter (where not is_duplicate)
            / nullif(sum(invoice_qty) filter (where not is_duplicate), 0) as invoice_price,
        min(invoice_date) as first_invoice_date,
        count(*) filter (where is_duplicate) as duplicate_lines,
        sum(invoice_qty * invoice_price) filter (where is_duplicate) as duplicate_value,
        string_agg(invoice_id::text || '-' || invoice_line::text, ',' order by invoice_id) as invoice_refs
    from {{ ref('stg_invoice_lines') }}
    where po_id is not null
    group by 1, 2
),

po as (
    select
        pol.po_id, pol.po_line, pol.supplier_id, pol.plant_id, pol.material_id, pol.order_date,
        pol.po_qty, pol.unit_price as po_price,
        r.received_qty, r.last_receipt_date, r.gr_ids,
        i.invoiced_qty, i.invoice_price, i.first_invoice_date, coalesce(i.duplicate_lines, 0) as duplicate_lines,
        i.duplicate_value, i.invoice_refs,
        abs(coalesce(i.invoiced_qty, 0) - coalesce(r.received_qty, 0)) / pol.po_qty as qty_diff_pct,
        abs(i.invoice_price - pol.unit_price) / pol.unit_price as price_diff_pct
    from {{ ref('stg_purchase_order_lines') }} pol
    left join rec r using (po_id, po_line)
    left join inv i using (po_id, po_line)
    cross join as_of
    -- in scope: invoiced lines, and received lines that should have been invoiced by now
    where i.invoiced_qty is not null
       or (r.received_qty is not null and as_of.as_of_date - r.last_receipt_date > 30)
),

-- invoices that arrived without a PO reference, as candidates for un-invoiced receipts
no_po as (
    select invoice_id, invoice_line, supplier_id, plant_id, material_id, invoice_qty
    from {{ ref('stg_invoice_lines') }}
    where po_id is null and not is_duplicate
),

with_candidate as (
    select
        po.*,
        (select n.invoice_id::text || '-' || n.invoice_line::text
         from no_po n
         where po.invoiced_qty is null
           and n.supplier_id = po.supplier_id and n.plant_id = po.plant_id
           and n.material_id = po.material_id and n.invoice_qty = po.po_qty
         order by n.invoice_id limit 1) as candidate_invoice_ref
    from po
),

classified as (
    select
        *,
        case
            when duplicate_lines > 0 then 'duplicate_invoice'
            when invoiced_qty is null and candidate_invoice_ref is not null then 'invoice_missing_po_reference'
            when invoiced_qty is null then 'receipt_not_invoiced'
            when received_qty is null then 'no_receipt'
            when price_diff_pct > {{ var('price_tolerance_pct') }} then 'price_variance'
            when qty_diff_pct > {{ var('qty_tolerance_pct') }} then 'qty_mismatch'
            when qty_diff_pct > 0 or price_diff_pct > 0.005 then 'minor_variance'
            else 'none'
        end as root_cause
    from with_candidate
)

select
    {{ dbt_utils_surrogate(['po_id', 'po_line']) }} as match_id,
    po_id, po_line, supplier_id, plant_id, material_id, order_date,
    po_qty, received_qty, invoiced_qty, po_price, invoice_price,
    round(qty_diff_pct, 4) as qty_diff_pct,
    round(price_diff_pct, 4) as price_diff_pct,
    duplicate_lines,
    case root_cause
        when 'none' then 'matched'
        when 'minor_variance' then 'within_tolerance'
        else 'exception' end as status,
    root_cause,
    round(case root_cause
        when 'duplicate_invoice' then duplicate_value
        when 'price_variance' then (invoice_price - po_price) * invoiced_qty
        when 'qty_mismatch' then (invoiced_qty - coalesce(received_qty, 0)) * po_price
        when 'no_receipt' then invoiced_qty * invoice_price
        when 'receipt_not_invoiced' then received_qty * po_price
        when 'invoice_missing_po_reference' then received_qty * po_price
        else 0 end, 2) as amount_at_risk,
    {{ period_of('coalesce(first_invoice_date, last_receipt_date)') }} as period_id,
    (select as_of_date from as_of) - coalesce(first_invoice_date, last_receipt_date) as age_days,
    {{ aging_bucket('(select as_of_date from as_of) - coalesce(first_invoice_date, last_receipt_date)') }}
        as aging_bucket,
    gr_ids,
    invoice_refs,
    candidate_invoice_ref
from classified

union all

select
    {{ dbt_utils_surrogate(["'NOPO'", 'invoice_id', 'invoice_line']) }},
    null, null, supplier_id, plant_id, material_id, null,
    null, null, invoice_qty, null, invoice_price,
    null, null,
    0,
    'exception',
    'missing_po_reference',
    round(invoice_qty * invoice_price, 2),
    {{ period_of('invoice_date') }},
    (select as_of_date from as_of) - invoice_date,
    {{ aging_bucket('(select as_of_date from as_of) - invoice_date') }},
    null,
    invoice_id::text || '-' || invoice_line::text,
    null
from {{ ref('stg_invoice_lines') }}
where po_id is null and not is_duplicate
