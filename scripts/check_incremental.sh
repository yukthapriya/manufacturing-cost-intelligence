#!/usr/bin/env bash
# Proves the incremental models give the same answer as a full rebuild.
#
#   1. load partitions up to SPLIT_DATE, dbt build (first build = full)
#   2. load the rest (including late-arriving labor for already-built orders), dbt run (incremental)
#   3. copy the incremental results aside, dbt run --full-refresh, compare both ways with EXCEPT
#
# Needs an empty warehouse database (WAREHOUSE_DB) and RAW_URI already landed.
# lookback_days=0 so the incremental run really only sees the second batch.
set -euo pipefail
SPLIT_DATE="${SPLIT_DATE:-2025-11-30}"
VARS='{lookback_days: 0}'
TABLES="intermediate.int_material_issues intermediate.int_labor_entries intermediate.int_order_material_actuals marts.fct_cost_variance marts.fct_production_cost"

psql_() { python - "$@" <<'PY'
import sys
from common.db import connect
with connect() as c, c.cursor() as cur:
    cur.execute(sys.argv[1])
    if cur.description:
        for r in cur.fetchall():
            print(*r, sep="|")
PY
}

python -m ingestion.load --init-db
python -m ingestion.load --all --until "$SPLIT_DATE"
dbt run --project-dir dbt --profiles-dir dbt --vars "$VARS" -q
python -m ingestion.load --all --since "$(date -d "$SPLIT_DATE + 1 day" +%F)"
dbt run --project-dir dbt --profiles-dir dbt --vars "$VARS"  | grep -E "incremental model|Done"

psql_ "create schema if not exists incr_check"
for t in $TABLES; do
  psql_ "drop table if exists incr_check.${t#*.}; create table incr_check.${t#*.} as select * from $t"
done
dbt run --project-dir dbt --profiles-dir dbt --full-refresh -q

status=0
for t in $TABLES; do
  name=${t#*.}
  cols=$(psql_ "select string_agg(column_name, ', ' order by ordinal_position) from information_schema.columns
                where table_schema = 'incr_check' and table_name = '$name' and column_name not like '\_%'")
  a=$(psql_ "select count(*) from (select $cols from incr_check.$name except select $cols from $t) d")
  b=$(psql_ "select count(*) from (select $cols from $t except select $cols from incr_check.$name) d")
  n=$(psql_ "select count(*) from $t")
  printf '%-45s rows=%-8s incremental-only=%-4s full-only=%s\n' "$t" "$n" "$a" "$b"
  [ "$a" = "0" ] && [ "$b" = "0" ] || status=1
done
[ $status -eq 0 ] && echo "incremental == full refresh" || echo "MISMATCH"
exit $status
