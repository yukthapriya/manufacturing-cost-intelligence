"""Publish dbt test results to dq.dbt_test_results for the Data Quality dashboard.

    python -m quality.publish_dq --run-results dbt/target/run_results.json [--manifest dbt/target/manifest.json]

Exit code 1 when any error-severity test failed or errored (warn-severity findings are
recorded but don't fail the pipeline), so orchestration can stop before publishing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from common.db import connect
from common.logging_setup import get_logger
from quality.alerts import send_alert

log = get_logger("quality.publish_dq")

DDL = """
create schema if not exists dq;
create table if not exists dq.dbt_test_results (
  invocation_id text not null,
  generated_at timestamptz not null,
  unique_id text not null,
  test_name text not null,
  test_type text not null,
  model text,
  layer text,
  severity text,
  status text not null,
  failures bigint,
  execution_seconds numeric,
  message text,
  primary key (invocation_id, unique_id)
);
create or replace view dq.latest_test_results as
select r.* from dq.dbt_test_results r
where r.invocation_id = (select invocation_id from dq.dbt_test_results order by generated_at desc limit 1);
"""


def parse(run_results: dict, manifest: dict | None) -> list[dict]:
    nodes = (manifest or {}).get("nodes", {})
    unit_tests = (manifest or {}).get("unit_tests", {})
    rows = []
    for r in run_results.get("results", []):
        uid = r["unique_id"]
        if not (uid.startswith("test.") or uid.startswith("unit_test.")):
            continue
        node = nodes.get(uid) or unit_tests.get(uid) or {}
        depends = node.get("depends_on", {}).get("nodes", [])
        model = next((d.split(".")[-1] for d in depends if d.startswith("model.")), None)
        if uid.startswith("unit_test."):
            model = node.get("model", model)
        layer = None
        if model:
            for prefix, name in (
                ("stg_", "staging"),
                ("int_", "intermediate"),
                ("fct_", "marts"),
                ("dim_", "marts"),
                ("recon_", "reconciliation"),
            ):
                if model.startswith(prefix):
                    layer = name
        rows.append(
            {
                "unique_id": uid,
                "test_name": node.get("name", uid.split(".")[-2] if uid.count(".") > 2 else uid),
                "test_type": "unit"
                if uid.startswith("unit_test.")
                else (
                    "singular"
                    if "generic" not in node.get("original_file_path", "") and not node.get("test_metadata")
                    else "generic"
                ),
                "model": model,
                "layer": layer,
                "severity": (node.get("config") or {}).get("severity", "ERROR").upper(),
                "status": r["status"],
                "failures": r.get("failures"),
                "execution_seconds": round(r.get("execution_time") or 0, 3),
                "message": (r.get("message") or "")[:1000],
            }
        )
    return rows


def publish(run_results_path: Path, manifest_path: Path | None) -> tuple[int, int, int]:
    rr = json.loads(run_results_path.read_text())
    manifest = json.loads(manifest_path.read_text()) if manifest_path and manifest_path.exists() else None
    meta = rr.get("metadata", {})
    rows = parse(rr, manifest)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(DDL)
        cur.executemany(
            """insert into dq.dbt_test_results
               (invocation_id, generated_at, unique_id, test_name, test_type, model, layer, severity, status,
                failures, execution_seconds, message)
               values (%(inv)s, %(gen)s, %(unique_id)s, %(test_name)s, %(test_type)s, %(model)s, %(layer)s,
                       %(severity)s, %(status)s, %(failures)s, %(execution_seconds)s, %(message)s)
               on conflict (invocation_id, unique_id) do nothing""",
            [{**r, "inv": meta.get("invocation_id"), "gen": meta.get("generated_at")} for r in rows],
        )
    failed = [r for r in rows if r["status"] in ("fail", "error")]
    warned = [r for r in rows if r["status"] == "warn"]
    log.info(
        "dbt test results published",
        extra={
            "tests": len(rows),
            "failed": len(failed),
            "warned": len(warned),
            "invocation_id": meta.get("invocation_id"),
        },
    )
    if failed:
        send_alert(
            "dbt tests failed",
            "\n".join(f"- {r['test_name']} ({r['model']}): {r['failures']} rows" for r in failed[:20]),
        )
    return len(rows), len(failed), len(warned)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-results", default="dbt/target/run_results.json", type=Path)
    ap.add_argument("--manifest", default=None, type=Path)
    args = ap.parse_args(argv)
    manifest = args.manifest or args.run_results.with_name("manifest.json")
    _, failed, _ = publish(args.run_results, manifest)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
