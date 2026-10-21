-- Suppliers sometimes resubmit the same invoice under a new document id.
-- Same supplier + invoice number + material + qty + price = duplicate; the first
-- submission is kept as the original, later ones are flagged (not deleted) so the
-- three-way match and the DQ dashboard can report them.
with lines as (
    {{ latest_by(source('raw', 'invoice_lines'), ['invoice_id', 'invoice_line']) }}
)

select
    *,
    row_number() over (
        partition by supplier_id, invoice_number, material_id, invoice_qty, invoice_price
        order by invoice_date, invoice_id, invoice_line
    ) > 1 as is_duplicate,
    po_id is null as is_missing_po
from lines
