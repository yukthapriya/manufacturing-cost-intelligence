"""Declarative schemas for every source extract.

Each column: (name, type, nullable, checks). Types: int, num, text, date, ts, bool.
Checks are evaluated vectorised in ``ingestion.validate``; failing rows are routed to
``raw.rejects`` with a reason instead of failing the whole file.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Col:
    name: str
    type: str
    nullable: bool = False
    min: float | None = None  # inclusive
    max: float | None = None  # inclusive
    gt: float | None = None  # strictly greater than
    allowed: tuple[str, ...] | None = None


@dataclass(frozen=True)
class Source:
    name: str
    columns: tuple[Col, ...]
    partition_by: str | None = None  # monthly range partitioning on this date column
    keys: tuple[str, ...] = field(default_factory=tuple)  # natural key, for docs/tests


UOMS = ("EA", "KG", "G", "M", "CM")

SOURCES: dict[str, Source] = {
    s.name: s
    for s in [
        Source(
            "plants",
            (Col("plant_id", "text"), Col("plant_name", "text"), Col("city", "text"), Col("state", "text")),
            keys=("plant_id",),
        ),
        Source(
            "production_lines",
            (Col("line_id", "text"), Col("plant_id", "text"), Col("line_name", "text")),
            keys=("line_id",),
        ),
        Source(
            "suppliers",
            (
                Col("supplier_id", "text"),
                Col("supplier_name", "text"),
                Col("payment_terms_days", "int", min=0),
                Col("country", "text"),
            ),
            keys=("supplier_id",),
        ),
        Source(
            "materials",
            (
                Col("material_id", "text"),
                Col("material_desc", "text"),
                Col("category", "text"),
                Col("base_uom", "text", allowed=UOMS),
                Col("primary_supplier_id", "text"),
                Col("lead_time_days", "int", min=0),
            ),
            keys=("material_id",),
        ),
        Source(
            "products",
            (
                Col("product_id", "text"),
                Col("product_name", "text"),
                Col("family", "text"),
                Col("line_id", "text"),
                Col("plant_id", "text"),
                Col("lot_min", "int", min=1),
                Col("lot_max", "int", min=1),
            ),
            keys=("product_id",),
        ),
        Source(
            "subassemblies", (Col("subassembly_id", "text"), Col("subassembly_name", "text")), keys=("subassembly_id",)
        ),
        Source(
            "bom",
            (
                Col("parent_id", "text"),
                Col("parent_type", "text", allowed=("PRODUCT", "SUBASSEMBLY")),
                Col("bom_line", "int", min=1),
                Col("component_id", "text"),
                Col("component_type", "text", allowed=("MATERIAL", "SUBASSEMBLY")),
                Col("qty_per", "num", gt=0),
                Col("uom", "text", allowed=UOMS),
                Col("scrap_allowance_pct", "num", min=0, max=0.5),
            ),
            keys=("parent_id", "bom_line"),
        ),
        Source(
            "standard_costs",
            (
                Col("item_type", "text", allowed=("MATERIAL", "LINE", "PRODUCT")),
                Col("item_id", "text"),
                Col("cost_component", "text"),
                Col("std_value", "num", min=0),
                Col("uom", "text"),
                Col("effective_from", "date"),
                Col("effective_to", "date"),
                Col("version", "text"),
            ),
            keys=("item_type", "item_id", "cost_component", "effective_from"),
        ),
        Source(
            "uom_conversions",
            (Col("from_uom", "text"), Col("to_uom", "text"), Col("factor", "num", gt=0)),
            keys=("from_uom",),
        ),
        Source(
            "gl_accounts",
            (
                Col("account", "text"),
                Col("account_name", "text"),
                Col("account_type", "text"),
                Col("is_inventory", "bool"),
            ),
            keys=("account",),
        ),
        Source(
            "fiscal_calendar",
            (
                Col("period_id", "text"),
                Col("fiscal_year", "int"),
                Col("fiscal_month", "int"),
                Col("period_start", "date"),
                Col("period_end", "date"),
                Col("business_day_1", "date"),
                Col("close_date", "date"),
            ),
            keys=("period_id",),
        ),
        Source(
            "production_orders",
            (
                Col("order_id", "int"),
                Col("product_id", "text"),
                Col("line_id", "text"),
                Col("plant_id", "text"),
                Col("planned_qty", "int", gt=0),
                Col("completed_qty", "int", nullable=True, min=0),
                Col("status", "text", allowed=("RELEASED", "COMPLETED")),
                Col("actual_start", "ts"),
                Col("actual_end", "ts", nullable=True),
                Col("extract_ts", "ts"),
            ),
            keys=("order_id", "status"),
        ),
        Source(
            "material_issues",
            (
                Col("issue_id", "int"),
                Col("order_id", "int"),
                Col("material_id", "text"),
                Col("issue_qty", "num", gt=0),
                Col("uom", "text", allowed=UOMS),
                Col("issue_date", "date"),
                Col("plant_id", "text"),
                Col("line_id", "text"),
            ),
            partition_by="issue_date",
            keys=("issue_id",),
        ),
        Source(
            "labor_entries",
            (
                Col("labor_entry_id", "int"),
                Col("order_id", "int"),
                Col("employee_id", "text"),
                Col("work_date", "date"),
                Col("posting_date", "date"),
                Col("hours", "num", gt=0, max=24),
                Col("hourly_rate", "num", gt=0, max=500),
                Col("overtime_flag", "bool"),
                Col("plant_id", "text"),
                Col("line_id", "text"),
            ),
            partition_by="posting_date",
            keys=("labor_entry_id",),
        ),
        Source(
            "scrap_records",
            (
                Col("scrap_id", "int"),
                Col("order_id", "int"),
                Col("material_id", "text"),
                Col("scrap_qty", "num", gt=0),
                Col("uom", "text", allowed=UOMS),
                Col("reason_code", "text"),
                Col("scrap_date", "date"),
                Col("plant_id", "text"),
                Col("line_id", "text"),
            ),
            keys=("scrap_id",),
        ),
        Source(
            "shipments",
            (
                Col("shipment_id", "int"),
                Col("order_id", "int"),
                Col("product_id", "text"),
                Col("plant_id", "text"),
                Col("ship_qty", "int", gt=0),
                Col("ship_date", "date"),
            ),
            keys=("shipment_id",),
        ),
        Source(
            "opening_inventory",
            (
                Col("plant_id", "text"),
                Col("material_id", "text"),
                Col("qty", "num", min=0),
                Col("uom", "text", allowed=UOMS),
                Col("as_of_date", "date"),
            ),
            keys=("plant_id", "material_id"),
        ),
        Source(
            "purchase_order_lines",
            (
                Col("po_id", "text"),
                Col("po_line", "int", min=1),
                Col("supplier_id", "text"),
                Col("plant_id", "text"),
                Col("order_date", "date"),
                Col("material_id", "text"),
                Col("po_qty", "num", gt=0),
                Col("uom", "text", allowed=UOMS),
                Col("unit_price", "num", gt=0),
            ),
            keys=("po_id", "po_line"),
        ),
        Source(
            "goods_receipts",
            (
                Col("gr_id", "text"),
                Col("po_id", "text"),
                Col("po_line", "int", min=1),
                Col("material_id", "text"),
                Col("plant_id", "text"),
                Col("receipt_qty", "num", gt=0),
                Col("uom", "text", allowed=UOMS),
                Col("receipt_date", "date"),
            ),
            keys=("gr_id",),
        ),
        Source(
            "invoice_lines",
            (
                Col("invoice_id", "int"),
                Col("invoice_line", "int", min=1),
                Col("invoice_number", "text"),
                Col("supplier_id", "text"),
                Col("plant_id", "text"),
                Col("po_id", "text", nullable=True),
                Col("po_line", "int", nullable=True, min=1),
                Col("material_id", "text"),
                Col("invoice_qty", "num", gt=0),
                Col("uom", "text", allowed=UOMS),
                Col("invoice_price", "num", gt=0),
                Col("invoice_date", "date"),
            ),
            keys=("invoice_id", "invoice_line"),
        ),
        Source(
            "inventory_snapshots",
            (
                Col("plant_id", "text"),
                Col("material_id", "text"),
                Col("snapshot_date", "date"),
                Col("system_qty", "num"),
                Col("uom", "text", allowed=UOMS),
            ),
            keys=("plant_id", "material_id", "snapshot_date"),
        ),
        Source(
            "cycle_counts",
            (
                Col("count_id", "int"),
                Col("plant_id", "text"),
                Col("material_id", "text"),
                Col("count_date", "date"),
                Col("counted_qty", "num", min=0),
                Col("uom", "text", allowed=UOMS),
                Col("counted_by", "text"),
            ),
            keys=("count_id",),
        ),
        Source(
            "gl_journal_entries",
            (
                Col("je_id", "text"),
                Col("je_line", "int", min=1),
                Col("je_date", "date"),
                Col("period_id", "text"),
                Col("plant_id", "text"),
                Col("account", "text"),
                Col("debit", "num", min=0),
                Col("credit", "num", min=0),
                Col("source_type", "text"),
                Col("description", "text"),
                Col("posted_at", "ts"),
            ),
            keys=("je_id", "je_line"),
        ),
    ]
}

PG_TYPES = {"int": "bigint", "num": "numeric", "text": "text", "date": "date", "ts": "timestamp", "bool": "boolean"}
