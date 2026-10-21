#!/usr/bin/env bash
# Scale benchmark: generate -> land -> load -> dbt build (models + tests) -> incremental no-op run.
#   bash benchmarks/run_benchmark.sh 50          # ~10M material issue lines
# Uses a separate database (mfg_bench) and folder (data/bench_<scale>). Appends a row
# to benchmarks/results.md. Host Postgres settings matter; record them with the result.
set -euo pipefail
SCALE="${1:-1}"
export WAREHOUSE_DB="${BENCH_DB:-mfg_bench}"
export SOURCE_URI="./data/bench_${SCALE}/source" RAW_URI="./data/bench_${SCALE}/raw" LOG_LEVEL=WARNING

t() { local s=$(date +%s); "$@" >/dev/null; echo $(( $(date +%s) - s )); }

python - <<PY
import psycopg2
from common.config import warehouse
w = warehouse()
c = psycopg2.connect(w.dsn.replace(f"dbname={w.dbname}", "dbname=postgres")); c.autocommit = True
c.cursor().execute("drop database if exists ${WAREHOUSE_DB}"); c.cursor().execute("create database ${WAREHOUSE_DB}")
PY
rm -rf "./data/bench_${SCALE}"

gen=$(t python -m data_generator.generate --start 2025-01-01 --months 12 --scale "$SCALE" --seed 42 --out "$SOURCE_URI")
python -m ingestion.load --init-db
land=$(t python -m ingestion.land --all)
load=$(t python -m ingestion.load --all)
build=$(t dbt build --project-dir dbt --profiles-dir dbt)
incr=$(t dbt run --project-dir dbt --profiles-dir dbt --select config.materialized:incremental --vars '{lookback_days: 0}')

counts=$(python - <<'PY'
from common.db import query_df
q = query_df("""select (select count(*) from raw.material_issues) issues, (select count(*) from raw.labor_entries) labor,
                       (select count(*) from marts.fct_cost_variance) variance_rows,
                       (select count(*) from marts.fct_production_cost) orders""")
print(*q.iloc[0].tolist())
PY
)
read -r issues labor vrows orders <<<"$counts"
fails=$(python -c "import json; r=json.load(open('dbt/target/run_results.json')); print(sum(x['status'] in ('fail','error') for x in r['results']))")

printf '| %s | %s | %s | %s | %s | %ss | %ss | %ss | %ss | %ss | %s |\n' \
  "$SCALE" "$issues" "$labor" "$orders" "$vrows" "$gen" "$land" "$load" "$build" "$incr" "$fails" | tee -a benchmarks/results.md
