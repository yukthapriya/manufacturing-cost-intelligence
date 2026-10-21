# Data dictionary: source extracts

Generated from `ingestion/schemas.py` by `scripts/gen_data_dictionary.py`. Every raw table also has
`_batch_id`, `_source_file` and `_loaded_at`. Rows failing these rules go to `raw.rejects` with a reason.

Files land as `<source>/<YYYY-MM-DD>/<source>.csv`, partitioned by the date the record reaches the source
system (issue date, posting date, invoice date, ...). Master data lands once, on the window start date.

## plants

Manufacturing plants.

Natural key: `plant_id`.

| column | type | nullable | rule |
|---|---|---|---|
| `plant_id` | text | no |  |
| `plant_name` | text | no |  |
| `city` | text | no |  |
| `state` | text | no |  |

## production_lines

Production lines, two per plant.

Natural key: `line_id`.

| column | type | nullable | rule |
|---|---|---|---|
| `line_id` | text | no |  |
| `plant_id` | text | no |  |
| `line_name` | text | no |  |

## suppliers

Raw material suppliers.

Natural key: `supplier_id`.

| column | type | nullable | rule |
|---|---|---|---|
| `supplier_id` | text | no |  |
| `supplier_name` | text | no |  |
| `payment_terms_days` | bigint | no | >= 0 |
| `country` | text | no |  |

## materials

Purchased materials with base unit of measure and primary supplier.

Natural key: `material_id`.

| column | type | nullable | rule |
|---|---|---|---|
| `material_id` | text | no |  |
| `material_desc` | text | no |  |
| `category` | text | no |  |
| `base_uom` | text | no | one of EA, KG, G, M, CM |
| `primary_supplier_id` | text | no |  |
| `lead_time_days` | bigint | no | >= 0 |

## products

Finished goods; each is built on one line.

Natural key: `product_id`.

| column | type | nullable | rule |
|---|---|---|---|
| `product_id` | text | no |  |
| `product_name` | text | no |  |
| `family` | text | no |  |
| `line_id` | text | no |  |
| `plant_id` | text | no |  |
| `lot_min` | bigint | no | >= 1 |
| `lot_max` | bigint | no | >= 1 |

## subassemblies

Phantom subassemblies (exploded into their materials, never stocked).

Natural key: `subassembly_id`.

| column | type | nullable | rule |
|---|---|---|---|
| `subassembly_id` | text | no |  |
| `subassembly_name` | text | no |  |

## bom

Two-level bill of materials: product -> material | subassembly, subassembly -> material, with a standard scrap allowance per material line.

Natural key: `parent_id, bom_line`.

| column | type | nullable | rule |
|---|---|---|---|
| `parent_id` | text | no |  |
| `parent_type` | text | no | one of PRODUCT, SUBASSEMBLY |
| `bom_line` | bigint | no | >= 1 |
| `component_id` | text | no |  |
| `component_type` | text | no | one of MATERIAL, SUBASSEMBLY |
| `qty_per` | numeric | no | > 0 |
| `uom` | text | no | one of EA, KG, G, M, CM |
| `scrap_allowance_pct` | numeric | no | >= 0; <= 0.5 |

## standard_costs

Versioned standards (long format): material STD_PRICE, line LABOR_RATE / OVERHEAD_RATE, product LABOR_HOURS / UNIT_COST. Joined on transaction date between effective_from and effective_to.

Natural key: `item_type, item_id, cost_component, effective_from`.

| column | type | nullable | rule |
|---|---|---|---|
| `item_type` | text | no | one of MATERIAL, LINE, PRODUCT |
| `item_id` | text | no |  |
| `cost_component` | text | no |  |
| `std_value` | numeric | no | >= 0 |
| `uom` | text | no |  |
| `effective_from` | date | no |  |
| `effective_to` | date | no |  |
| `version` | text | no |  |

## uom_conversions

Unit conversions to base UOM (G -> KG, CM -> M).

Natural key: `from_uom`.

| column | type | nullable | rule |
|---|---|---|---|
| `from_uom` | text | no |  |
| `to_uom` | text | no |  |
| `factor` | numeric | no | > 0 |

## gl_accounts

Chart of accounts used by the cost subledger.

Natural key: `account`.

| column | type | nullable | rule |
|---|---|---|---|
| `account` | text | no |  |
| `account_name` | text | no |  |
| `account_type` | text | no |  |
| `is_inventory` | boolean | no |  |

## fiscal_calendar

Monthly periods; close_date is the posting cutoff (day before business day 1 of the next month). Postings after it route to the open period.

Natural key: `period_id`.

| column | type | nullable | rule |
|---|---|---|---|
| `period_id` | text | no |  |
| `fiscal_year` | bigint | no |  |
| `fiscal_month` | bigint | no |  |
| `period_start` | date | no |  |
| `period_end` | date | no |  |
| `business_day_1` | date | no |  |
| `close_date` | date | no |  |

## production_orders

CDC events: a RELEASED row at start and a COMPLETED row (with completed_qty, actual_end) at completion. Staging keeps the current state.

Natural key: `order_id, status`.

| column | type | nullable | rule |
|---|---|---|---|
| `order_id` | bigint | no |  |
| `product_id` | text | no |  |
| `line_id` | text | no |  |
| `plant_id` | text | no |  |
| `planned_qty` | bigint | no | > 0 |
| `completed_qty` | bigint | yes | >= 0 |
| `status` | text | no | one of RELEASED, COMPLETED |
| `actual_start` | timestamp | no |  |
| `actual_end` | timestamp | yes |  |
| `extract_ts` | timestamp | no |  |

## material_issues

Goods issued to orders (kitting at order start). Some terminals book kilogram materials in grams (uom = G). Junk rows with negative quantities are rejected at load.

Natural key: `issue_id`; raw table range-partitioned monthly on `issue_date`.

| column | type | nullable | rule |
|---|---|---|---|
| `issue_id` | bigint | no |  |
| `order_id` | bigint | no |  |
| `material_id` | text | no |  |
| `issue_qty` | numeric | no | > 0 |
| `uom` | text | no | one of EA, KG, G, M, CM |
| `issue_date` | date | no |  |
| `plant_id` | text | no |  |
| `line_id` | text | no |  |

## labor_entries

Time bookings per employee shift. posting_date can lag work_date (late postings); partitioned by posting_date because that is when they arrive.

Natural key: `labor_entry_id`; raw table range-partitioned monthly on `posting_date`.

| column | type | nullable | rule |
|---|---|---|---|
| `labor_entry_id` | bigint | no |  |
| `order_id` | bigint | no |  |
| `employee_id` | text | no |  |
| `work_date` | date | no |  |
| `posting_date` | date | no |  |
| `hours` | numeric | no | > 0; <= 24 |
| `hourly_rate` | numeric | no | > 0; <= 500 |
| `overtime_flag` | boolean | no |  |
| `plant_id` | text | no |  |
| `line_id` | text | no |  |

## scrap_records

Material scrapped against an order, with reason code.

Natural key: `scrap_id`.

| column | type | nullable | rule |
|---|---|---|---|
| `scrap_id` | bigint | no |  |
| `order_id` | bigint | no |  |
| `material_id` | text | no |  |
| `scrap_qty` | numeric | no | > 0 |
| `uom` | text | no | one of EA, KG, G, M, CM |
| `reason_code` | text | no |  |
| `scrap_date` | date | no |  |
| `plant_id` | text | no |  |
| `line_id` | text | no |  |

## shipments

Finished goods shipped (relieves finished goods inventory to COGS).

Natural key: `shipment_id`.

| column | type | nullable | rule |
|---|---|---|---|
| `shipment_id` | bigint | no |  |
| `order_id` | bigint | no |  |
| `product_id` | text | no |  |
| `plant_id` | text | no |  |
| `ship_qty` | bigint | no | > 0 |
| `ship_date` | date | no |  |

## opening_inventory

Raw material stock at the start of the window.

Natural key: `plant_id, material_id`.

| column | type | nullable | rule |
|---|---|---|---|
| `plant_id` | text | no |  |
| `material_id` | text | no |  |
| `qty` | numeric | no | >= 0 |
| `uom` | text | no | one of EA, KG, G, M, CM |
| `as_of_date` | date | no |  |

## purchase_order_lines

Purchase order lines with agreed unit price.

Natural key: `po_id, po_line`.

| column | type | nullable | rule |
|---|---|---|---|
| `po_id` | text | no |  |
| `po_line` | bigint | no | >= 1 |
| `supplier_id` | text | no |  |
| `plant_id` | text | no |  |
| `order_date` | date | no |  |
| `material_id` | text | no |  |
| `po_qty` | numeric | no | > 0 |
| `uom` | text | no | one of EA, KG, G, M, CM |
| `unit_price` | numeric | no | > 0 |

## goods_receipts

Receipts against PO lines (some short receipts; some never received).

Natural key: `gr_id`.

| column | type | nullable | rule |
|---|---|---|---|
| `gr_id` | text | no |  |
| `po_id` | text | no |  |
| `po_line` | bigint | no | >= 1 |
| `material_id` | text | no |  |
| `plant_id` | text | no |  |
| `receipt_qty` | numeric | no | > 0 |
| `uom` | text | no | one of EA, KG, G, M, CM |
| `receipt_date` | date | no |  |

## invoice_lines

Supplier invoice lines from the AP feed. Contains resubmitted duplicates and lines without a PO reference.

Natural key: `invoice_id, invoice_line`.

| column | type | nullable | rule |
|---|---|---|---|
| `invoice_id` | bigint | no |  |
| `invoice_line` | bigint | no | >= 1 |
| `invoice_number` | text | no |  |
| `supplier_id` | text | no |  |
| `plant_id` | text | no |  |
| `po_id` | text | yes |  |
| `po_line` | bigint | yes | >= 1 |
| `material_id` | text | no |  |
| `invoice_qty` | numeric | no | > 0 |
| `uom` | text | no | one of EA, KG, G, M, CM |
| `invoice_price` | numeric | no | > 0 |
| `invoice_date` | date | no |  |

## inventory_snapshots

ERP month-end on-hand quantity (contains a few posting errors and negative balances).

Natural key: `plant_id, material_id, snapshot_date`.

| column | type | nullable | rule |
|---|---|---|---|
| `plant_id` | text | no |  |
| `material_id` | text | no |  |
| `snapshot_date` | date | no |  |
| `system_qty` | numeric | no |  |
| `uom` | text | no | one of EA, KG, G, M, CM |

## cycle_counts

Physical counts of a sample of plant/material combinations at month end.

Natural key: `count_id`.

| column | type | nullable | rule |
|---|---|---|---|
| `count_id` | bigint | no |  |
| `plant_id` | text | no |  |
| `material_id` | text | no |  |
| `count_date` | date | no |  |
| `counted_qty` | numeric | no | >= 0 |
| `uom` | text | no | one of EA, KG, G, M, CM |
| `counted_by` | text | no |  |

## gl_journal_entries

General ledger, summarised by day, plant, source type and account (as an ERP posts to the ledger). Contains four injected breaks.

Natural key: `je_id, je_line`.

| column | type | nullable | rule |
|---|---|---|---|
| `je_id` | text | no |  |
| `je_line` | bigint | no | >= 1 |
| `je_date` | date | no |  |
| `period_id` | text | no |  |
| `plant_id` | text | no |  |
| `account` | text | no |  |
| `debit` | numeric | no | >= 0 |
| `credit` | numeric | no | >= 0 |
| `source_type` | text | no |  |
| `description` | text | no |  |
| `posted_at` | timestamp | no |  |
