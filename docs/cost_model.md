# Cost model and accounting design

## Standard costing flow

The plant runs a standard cost system. Each transaction is valued and rounded to the cent
on its own, the way an ERP does it, before anything is summed. This is why the subledger
rebuilt here ties to the GL exactly.

| Event | Debit | Credit | Value |
|---|---|---|---|
| Opening stock | 1300 Raw Materials | 3900 Opening Balance Equity | qty × std price |
| Goods receipt | 1300 Raw Materials (std) + 5100 PPV (PO − std) | 2110 GRNI (PO price) | receipt qty |
| Supplier invoice | 2110 GRNI (PO price) + 5100 PPV (invoice − PO) | 2100 AP (invoice price) | invoice qty |
| Material issue | 1400 WIP | 1300 Raw Materials | issued qty × std price |
| Labor booking | 1400 WIP | 2200 Accrued Payroll | hours × actual rate |
| Overhead applied | 1400 WIP | 5900 Overhead Applied | hours × line overhead rate |
| Scrap | 5300 Scrap Expense | 1400 WIP | scrap qty × std price |
| Completion | 1500 Finished Goods | 1400 WIP | completed qty × std unit cost |
| Settlement (period end) | 5200 Manufacturing Variance | 1400 WIP | residual WIP of completed orders |
| Shipment | 5000 COGS | 1500 Finished Goods | shipped qty × std unit cost |

The **standard unit cost** of a product is the BOM exploded through any number of
subassembly levels (recursive CTE): Σ material qty × (1 + scrap allowance) × std price, plus
std hours × (labor rate + overhead rate). The test `bom_rollup_matches_published_standard`
checks the published standard against this rollup.

## Variance decomposition (per completed order)

Notation: AQ actual qty issued (good + scrap), AS actual scrap qty, AP actual price, SP standard
price, SQg standard qty for good output (BOM qty × completed), SQa allowed scrap
(BOM qty × allowance × completed), SQ = SQg + SQa. AH actual hours, SH standard hours for the
output, SR standard labor rate, OHR overhead rate.

| Element | Formula | Meaning |
|---|---|---|
| material_price | (AP − SP) × AQ | paid more or less than standard for what was consumed |
| material_usage | (AQ − AS − SQg) × SP | used more or less good material than the BOM says |
| scrap | (AS − SQa) × SP | scrapped more or less than the allowance |
| labor_rate | actual labor cost − SR × AH | paid a different rate (overtime, mix) |
| labor_efficiency | (AH − SH) × SR | took more or less time than standard |
| overhead_efficiency | overhead applied − OHR × SH | overhead follows hours |

These sum exactly to total actual cost − total standard cost (AP·AQ + labor + overhead −
SP·SQ − SR·SH − OHR·SH). `assert_variance_components_reconcile` enforces this per order to $0.01.
A positive amount is unfavorable.

**Actual price** is the quantity-weighted average of de-duplicated supplier invoices for the plant,
material and month of issue. Months without invoices carry the last price forward, and a material
that was never invoiced falls back to standard (`price_source` says which applied).

### Why the GL variance accounts differ from the variance model

PPV in the GL (5100) is recognised at **receipt and invoice**, on what was bought. The material
price variance in the model is measured on what was **consumed**. Both are correct, but they answer
different questions. Scrap expense (5300) is booked at actual scrap, while completions relieve WIP
at a standard that already includes the scrap allowance. So 5200 + 5300 together equal the
usage + scrap + labor + overhead variances, while 5200 on its own runs favorable by the allowance.

## Period lock and late postings

- Each period accepts postings until its **posting cutoff**, the day before business day 1 of the following month. The daily pipeline loads the cutoff day overnight, and the close runs on the morning of business day 1.
- A transaction posted after its period's cutoff is booked to the period of its posting date and flagged `is_late_posting` (`int_labor_entries`). The rule lives in `common/fiscal_calendar.py` (used by the generator to post the GL) and in the dbt macro `accounting_period`, and `tests/test_calendar.py` pins it down.
- Settlement happens at each period end for orders completed by then. Labor posted late against an order that was already settled is settled in the period it lands in.

## Reconciliations

| Model | Grain | Compares |
|---|---|---|
| `recon_gl_daily` | day × plant × source × account | subledger postings vs. GL, with root-cause tag |
| `recon_subledger_to_gl` | period × plant × account × source | the same, with status, aging and materiality |
| `recon_inventory_balance` | period × plant × account | cumulative subledger vs. GL balance, plus an independent valuation (perpetual qty × std for 1300, open-order balances for 1400) |
| `recon_wip_rollforward` | period × plant | beginning + issued + labor + overhead − completions − scrap − settlement = ending, against the sum of open-order balances and the GL |
| `recon_three_way_match` | PO line | PO vs. receipts vs. invoices, with tolerances, root cause, amount at risk and aging; also matches un-referenced invoices to open receipts |
| `recon_exceptions` | exception | unified queue; `is_critical` blocks sign-off |

Statuses: `matched` (|diff| < $0.01), `within_tolerance` (≤ `recon_tolerance_usd`), `exception`.
Aging buckets: 0–30, 31–60, 61–90, 90+ days from period end (or invoice date).

## Sign-off gate (`close.period_close`)

A period can be signed off and locked only if all of the following hold:
1. The prior period is signed off (when it had activity).
2. There are no subledger-to-GL breaks above `MATERIALITY_USD` in the period's activity.
3. The WIP roll-forward ties for every plant.
4. The latest dbt build has no failing error-severity tests.

Cumulative balance breaks carried from earlier periods are reported but don't block. They clear
once the correcting entry is posted in the period where the break started.
