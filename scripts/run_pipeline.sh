#!/usr/bin/env bash
# End-to-end batch run (what the Airflow DAGs do, in one go, for demos and CI):
#   init warehouse -> land + load every partition -> dbt build + DQ publish
#   -> layer checks -> close every period in order -> close packages -> Tableau extracts
#
# Uses SOURCE_URI / RAW_URI / WAREHOUSE_* from the environment. Run from the repo root.
set -euo pipefail

SIGN_OFF="${SIGN_OFF:-1}"     # attempt sign-off for each period (0 = preliminary snapshots only)
STEP() { printf '\n==> %s\n' "$*"; }

STEP "init warehouse"
python -m ingestion.load --init-db

STEP "land all partitions into the raw zone"
python -m ingestion.land --all

STEP "validate + load raw"
python -m ingestion.load --all

STEP "dbt build (models + tests)"
set +e
dbt build --project-dir dbt --profiles-dir dbt
DBT_RC=$?
set -e
python -m quality.publish_dq --run-results dbt/target/run_results.json || true
if [ "$DBT_RC" -ne 0 ]; then echo "dbt build failed (critical tests)"; exit "$DBT_RC"; fi

LAST_DATE=$(python -m ingestion.list_dates --src "${RAW_URI:-./data/raw}" --source material_issues | tail -1)
STEP "layer checks for ${LAST_DATE}"
python -m quality.layer_checks --date "${LAST_DATE}" || true

STEP "month-end close, period by period"
PERIODS=$(python -c "from common.db import query_df; print(' '.join(query_df('select distinct period_id from marts.fct_production_cost where period_id is not null order by 1')['period_id']))")
for p in $PERIODS; do
  if [ "$SIGN_OFF" = "1" ]; then
    python -m close.period_close --period "$p" --sign-off && echo "  $p signed off" || echo "  $p BLOCKED (exit $?)"
  else
    python -m close.period_close --period "$p"
  fi
  python -m exporter.close_package --period "$p" --out exports/close >/dev/null
done

STEP "Tableau extracts"
python -m exporter.tableau_export --out tableau/extracts ${HYPER:+--hyper}

STEP "cost review report (docs/index.html)"
python -m exporter.static_report --out docs/index.html

STEP "done"
