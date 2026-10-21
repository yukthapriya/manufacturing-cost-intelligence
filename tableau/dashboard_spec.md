# Tableau dashboard specification

Build these in Tableau Desktop or Tableau Public from the extracts written by
`python -m exporter.tableau_export --out tableau/extracts --hyper`:
open `tableau/extracts/mci.hyper` (every table in one file), or connect to the CSVs, or
point Tableau at the Postgres `marts`, `recon`, `dq` and `close` schemas live.

## Data model (relationships, not joins)

| Logical table | Source | Related to |
|---|---|---|
| Production Cost | `fct_production_cost` | Product (`product_id`), Line (`line_id`), Date (`completion_date` = `date_day`) |
| Variance | `fct_cost_variance` | Production Cost (`order_id`), Material (`material_id`), Line, Date |
| Transactions | `fct_cost_transactions` | Production Cost (`order_id`), Material (`material_id`) |
| Unit Cost | `fct_unit_cost` | Product, Line |
| Scrap | `fct_scrap` | Line |
| Inventory | `fct_inventory_discrepancy` | Material, Plant |
| Purchase Price | `fct_purchase_price` | Supplier, Material |
| Reconciliation | `recon_subledger_to_gl`, `recon_inventory_balance`, `recon_wip_rollforward`, `recon_three_way_match`, `recon_exceptions` | Plant |
| Data Quality | `latest_test_results`, `layer_check_results` | none |
| Close | `period_status`, `fct_period_close_snapshot` | `period_id` |

Global filters on every dashboard: **Period** (`period_id`, multi-select, default = latest
complete month), **Plant**, **Line**. Apply to all worksheets using related data sources.

## Calculated fields

```
// Variance %
SUM([Variance Amount]) / SUM([Std Cost])

// Favorable / Unfavorable label
IF SUM([Variance Amount]) > 0 THEN "Unfavorable" ELSE "Favorable" END

// Scrap Rate
SUM([Scrap Value]) / SUM([Issued Value])

// Unit Cost Gap
SUM([Total Actual Cost]) / SUM([Completed Qty]) - SUM([Total Std Cost]) / SUM([Completed Qty])

// Cost Element Sort (waterfall order)
CASE [Cost Element]
  WHEN "material_price" THEN 1 WHEN "material_usage" THEN 2 WHEN "scrap" THEN 3
  WHEN "labor_rate" THEN 4 WHEN "labor_efficiency" THEN 5 WHEN "overhead_efficiency" THEN 6 END

// Running Variance (waterfall): table calc, running sum of SUM([Variance Amount]) along Cost Element
RUNNING_SUM(SUM([Variance Amount]))

// DQ Pass Rate
SUM(IF [Status] = "pass" THEN 1 ELSE 0 END) / COUNT([Unique Id])

// Close Readiness
IF MAX([Status]) = "signed_off" THEN "Closed" ELSEIF MAX([Status]) = "blocked" THEN "Blocked" ELSE "Open" END
```

## 1. Unit Cost Overview

| Sheet | Build | Notes |
|---|---|---|
| KPI tiles | Total actual cost, total standard cost, total variance, variance %, units completed | `fct_production_cost`, completed orders only |
| Unit cost trend | Line: `period_id` × actual unit cost and standard unit cost (dual axis, synced) | from `fct_unit_cost`, weighted by units |
| Unit cost by product | Bar: product × Unit Cost Gap, colored Favorable/Unfavorable | sort descending |
| Cost mix | Stacked bar: family × material / labor / overhead per unit | `actual_*_per_unit` |
| Order table | Order, product, line, completed qty, actual vs. std, variance | **drill-through** |

Actions: select a product → filter the trend; click an order → **Go to Sheet "Transaction Detail"**.

## 2. Manufacturing Variance

| Sheet | Build | Notes |
|---|---|---|
| Variance waterfall | Gantt bar: Cost Element (sorted by Cost Element Sort) × Running Variance, size = −SUM(Variance Amount) | price → usage → scrap → labor rate → labor efficiency → overhead |
| Line × month heatmap | Square marks: `line_id` × `period_id`, color = Variance % (diverging, centered at 0) | FRE1-L2 lights up red every month |
| Top drivers | Bar: material (or element) × SUM(Variance Amount), Top N parameter (default 10) | |
| PPV trend | Line: supplier × price index vs. standard (`fct_purchase_price`) | supplier S007 jumps ~20 pts in July |

Actions: click a heatmap cell → filter top drivers to that line and month; click a driver →
Transaction Detail filtered to `order_id` IN the selected rows.

## 3. Scrap & Yield

| Sheet | Build | Notes |
|---|---|---|
| Scrap rate trend | Line: `period_id` × Scrap Rate per line | RNO1-L1 spikes in Apr–May |
| Reason Pareto | Bar: reason × scrap value, descending, line = cumulative % (table calc) | |
| Scrap vs. allowance | Bar: line × SUM(Variance Amount) where Cost Element = "scrap" | scrap beyond the BOM allowance |
| Yield to plan | Histogram of `yield_to_plan` from `fct_production_cost` | |

## 4. Inventory Discrepancies + Data Quality

| Sheet | Build | Notes |
|---|---|---|
| Discrepancy summary | Text table: plant × count of negative qty, ERP≠perpetual, count variances; sum of values | `fct_inventory_discrepancy` flags |
| Shrink by plant | Bar: plant × SUM(`count_vs_system_value`) where < 0 | |
| Discrepancy detail | Table of flagged rows: perpetual, system, counted, value | |
| DQ test pass rate | Big number DQ Pass Rate; bar: layer × status counts | `latest_test_results` |
| Warnings | Table: test_name × failures for severity WARN | injected source problems are visible here |
| Layer checks | Table: check_name, subject, observed vs. expected, status | `layer_check_results` |

## 5. Close Readiness

| Sheet | Build | Notes |
|---|---|---|
| Period status strip | Square per `period_id`, color by Close Readiness | green Closed, red Blocked, grey Open |
| Blocking reasons | Text: `blocked_reasons` for the selected period | |
| Subledger-to-GL | Table: account × plant × source with subledger, GL, diff, status, root cause, aging bucket | non-matched rows highlighted |
| WIP roll-forward | Waterfall: beginning → issued → labor → overhead → (completions) → (scrap) → (settlement) → ending, with a "ties" badge | `recon_wip_rollforward` |
| Three-way match | Bar: root cause × amount at risk; aging bucket stacked | `recon_three_way_match` status = exception |
| Exception queue | Table from `recon_exceptions`, critical first | |

## Transaction Detail (drill-through target, hidden from navigation)

Source `fct_cost_transactions`. Columns: txn_type, txn_id, txn_date, order_id, material_id,
qty, uom, unit std cost, std value, unit actual cost, actual value, flags (UOM converted,
late posting), reason code, employee. Filtered by the calling action on `order_id`
(and `material_id` for material rows). Every variance row also carries `source_txn_ids`
(comma-separated) for direct lookup.

## Publishing

Publish to Tableau Public (File → Save to Tableau Public) and put the link and three
screenshots (Variance, Scrap, Close Readiness) in the README.
