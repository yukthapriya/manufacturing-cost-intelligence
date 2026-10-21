# Runbook

Commands assume the repo root with `WAREHOUSE_*`, `SOURCE_URI` and `RAW_URI` set (or prefix
with `make ... ` targets, which run inside the Airflow container by default; `LOCAL=1` runs on the host).

## Rerun a failed day

The pipeline is idempotent at every step, so a rerun is always safe.

1. Find the failed task in Airflow (`manufacturing_cost_pipeline`, run for date D) and read its log.
   JSON log lines carry `file`, `batch_id`, `check_name` and similar fields.
2. Fix the cause (bad file replaced at the source, warehouse back up, and so on).
3. Clear the failed task **and downstream** in the Airflow UI, or from the CLI:
   ```
   airflow tasks clear manufacturing_cost_pipeline -s D -e D -t validate_and_load --downstream -y
   ```
4. What happens on rerun:
   - `land_raw` re-copies the same keys.
   - `validate_and_load` skips files whose SHA-256 is unchanged (`audit.load_log`) and atomically replaces files that changed. Use `--force` to reload regardless.
   - `dbt build` incremental models reprocess anything loaded since the newest `_max_loaded_at` minus `lookback_days`.

Without Airflow:
```
python -m ingestion.land --date D && python -m ingestion.load --date D [--force]
dbt build --project-dir dbt --profiles-dir dbt && python -m quality.publish_dq
python -m quality.layer_checks --date D
```

## Backfill a period

```
airflow dags backfill manufacturing_cost_pipeline -s 2025-03-01 -e 2025-03-31
```
Runs are sequential (`max_active_runs=1`). For a large backfill it is much faster to bulk load
and build once:
```
python -m ingestion.land --all
python -m ingestion.load --all --since 2025-03-01 --until 2025-03-31
dbt build --project-dir dbt --profiles-dir dbt && python -m quality.publish_dq
```
If standards, the BOM or the routing rule changed, rebuild everything: trigger the DAG with
`{"full_refresh": true}`, or run `dbt build --full-refresh`.

Locked (signed-off) periods are never rewritten. Their final close snapshots are protected by
a trigger, and late postings route into the open period. A backfill therefore changes the
live models, but not what was signed off.

## Investigate a reconciliation break

1. **Where:** `recon.recon_subledger_to_gl` gives period × plant × account × source with `diff`, `status` and `root_cause`.
2. **When:** `recon.recon_gl_daily` gives the same break by day, which is how the root cause is assigned:

   | root_cause | pattern at day grain | typical fix |
   |---|---|---|
   | `missing_gl_posting` | subledger posted, GL empty | post the missing batch |
   | `duplicate_gl_posting` | GL = 2 × subledger | reverse the duplicate |
   | `misposted_plant` | equal and opposite diffs, same day, two plants | reclass between plants |
   | `timing_cutoff` | equal and opposite diffs a few days apart across a period end | accrue/reverse, or accept if immaterial |
   | `gl_without_subledger` | GL posting with no source transactions | trace the manual JE |
   | `unexplained` | none of the above | drill into the transactions |
3. **What:** drill into the source transactions for that day, plant and source:
   ```sql
   select * from marts.fct_cost_transactions
   where txn_date = '2025-03-15' and plant_id = 'FRE1' and txn_type = 'ISSUE';
   ```
4. **Fix:** propose correcting entries, review the CSV, then post:
   ```
   python -m close.propose_corrections --period 2025-03            # writes exports/corrections/corrections_2025-03.csv
   python -m close.propose_corrections --period 2025-03 --post     # drops a GL file into RAW_URI
   python -m ingestion.load --all && dbt build --project-dir dbt --profiles-dir dbt && python -m quality.publish_dq
   python -m close.period_close --period 2025-03 --sign-off
   ```
   Any amount the reconciliation cannot see (for example the GRNI side of a duplicated receipt) is
   offset to `1999 Reconciliation Suspense`, so it shows up for someone to clear.

## WIP roll-forward does not tie

This is a critical control: sign-off is blocked and the dbt test on `recon_wip_rollforward.ties_out` fails.

- Compare `ending_wip_rollforward` with `ending_open_orders` by plant and period. The difference is an order whose activity is in WIP but which was neither settled nor counted as open.
- The usual cause is an order with a COMPLETED event but a missing completion standard, or activity dated before the order's release. Check:
  ```sql
  select * from intermediate.int_wip_activity a
  left join staging.stg_production_orders o using (order_id) where o.order_id is null;
  ```

## Month-end close

- `month_end_close` runs daily and acts on business day 1. It waits for the daily load of the posting cutoff day (the day before business day 1), refreshes the reconciliations, then attempts sign-off.
- Exit code 2 or a failed `period_close_sign_off` task means the close is **blocked**. The reasons are in `close.period_status.blocked_reasons`, on the Summary sheet of `exports/close/close_package_<period>.xlsx`, and in the Slack alert.
- Periods close in order: a blocked March blocks April until March is signed off.
- To re-attempt: fix the issue, then clear `refresh_reconciliations` and downstream, or run
  `python -m close.period_close --period P --sign-off`.

## Alerts

`SLACK_WEBHOOK_URL` enables Slack alerts for task failures, failed layer checks, failing dbt
tests, SLA misses and blocked closes. Without it, alerts are logged as JSON (`"logger": "alerts"`).
