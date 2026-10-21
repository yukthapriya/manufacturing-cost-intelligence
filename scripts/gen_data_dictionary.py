"""Regenerate docs/data_dictionary.md from ingestion/schemas.py (single source of truth).

python scripts/gen_data_dictionary.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion.schemas import PG_TYPES, SOURCES  # noqa: E402

DESCRIPTIONS = {
    "plants": "Manufacturing plants.",
    "production_lines": "Production lines, two per plant.",
    "suppliers": "Raw material suppliers.",
    "materials": "Purchased materials with base unit of measure and primary supplier.",
    "products": "Finished goods; each is built on one line.",
    "subassemblies": "Phantom subassemblies (exploded into their materials, never stocked).",
    "bom": "Two-level bill of materials: product -> material | subassembly, subassembly -> material, "
    "with a standard scrap allowance per material line.",
    "standard_costs": "Versioned standards (long format): material STD_PRICE, line LABOR_RATE / OVERHEAD_RATE, "
    "product LABOR_HOURS / UNIT_COST. Joined on transaction date between effective_from and effective_to.",
    "uom_conversions": "Unit conversions to base UOM (G -> KG, CM -> M).",
    "gl_accounts": "Chart of accounts used by the cost subledger.",
    "fiscal_calendar": "Monthly periods; close_date is the posting cutoff (day before business day 1 of the next "
    "month). Postings after it route to the open period.",
    "production_orders": "CDC events: a RELEASED row at start and a COMPLETED row (with completed_qty, actual_end) "
    "at completion. Staging keeps the current state.",
    "material_issues": "Goods issued to orders (kitting at order start). Some terminals book kilogram materials in "
    "grams (uom = G). Junk rows with negative quantities are rejected at load.",
    "labor_entries": "Time bookings per employee shift. posting_date can lag work_date (late postings); "
    "partitioned by posting_date because that is when they arrive.",
    "scrap_records": "Material scrapped against an order, with reason code.",
    "shipments": "Finished goods shipped (relieves finished goods inventory to COGS).",
    "opening_inventory": "Raw material stock at the start of the window.",
    "purchase_order_lines": "Purchase order lines with agreed unit price.",
    "goods_receipts": "Receipts against PO lines (some short receipts; some never received).",
    "invoice_lines": "Supplier invoice lines from the AP feed. Contains resubmitted duplicates and lines without "
    "a PO reference.",
    "inventory_snapshots": "ERP month-end on-hand quantity (contains a few posting errors and negative balances).",
    "cycle_counts": "Physical counts of a sample of plant/material combinations at month end.",
    "gl_journal_entries": "General ledger, summarised by day, plant, source type and account (as an ERP posts "
    "to the ledger). Contains four injected breaks.",
}


def main() -> None:
    out = [
        "# Data dictionary: source extracts",
        "",
        "Generated from `ingestion/schemas.py` by `scripts/gen_data_dictionary.py`. Every raw table also has",
        "`_batch_id`, `_source_file` and `_loaded_at`. Rows failing these rules go to `raw.rejects` with a reason.",
        "",
        "Files land as `<source>/<YYYY-MM-DD>/<source>.csv`, partitioned by the date the record reaches the source",
        "system (issue date, posting date, invoice date, ...). Master data lands once, on the window start date.",
        "",
    ]
    for name, src in SOURCES.items():
        out += [f"## {name}", "", DESCRIPTIONS.get(name, ""), ""]
        meta = []
        if src.keys:
            meta.append(f"natural key: `{', '.join(src.keys)}`")
        if src.partition_by:
            meta.append(f"raw table range-partitioned monthly on `{src.partition_by}`")
        if meta:
            out += ["; ".join(meta).capitalize() + ".", ""]
        out += ["| column | type | nullable | rule |", "|---|---|---|---|"]
        for c in src.columns:
            rules = []
            if c.gt is not None:
                rules.append(f"> {c.gt:g}")
            if c.min is not None:
                rules.append(f">= {c.min:g}")
            if c.max is not None:
                rules.append(f"<= {c.max:g}")
            if c.allowed:
                rules.append("one of " + ", ".join(c.allowed))
            out.append(f"| `{c.name}` | {PG_TYPES[c.type]} | {'yes' if c.nullable else 'no'} | {'; '.join(rules)} |")
        out.append("")
    path = Path(__file__).resolve().parents[1] / "docs" / "data_dictionary.md"
    path.write_text("\n".join(out))
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
