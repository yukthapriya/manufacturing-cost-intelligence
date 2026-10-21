"""Row-count and freshness checks between pipeline layers.

    python -m quality.layer_checks --date 2025-03-04 [--max-reject-rate 0.01] [--wallclock-hours 26]

Checks (results appended to dq.layer_check_results; exit 1 if any check fails):
  file_to_raw        rows read = rows loaded + rows rejected, and loaded = rows in raw (per file of that date)
  reject_rate        rejected / read below threshold per source for that date
  raw_to_staging     distinct business keys in raw = rows in staging (reloads de-duplicate, nothing lost)
  staging_to_int     staging rows = intermediate rows for incremental models (no dropped joins)
  freshness          every core transactional source has a partition loaded for the date (production days),
                     and optionally the newest load is less than N wall-clock hours old
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime

from common.db import connect
from common.fiscal_calendar import is_production_day
from common.logging_setup import get_logger
from quality.alerts import send_alert

log = get_logger("quality.layer_checks")

DDL = """
create schema if not exists dq;
create table if not exists dq.layer_check_results (
  run_ts timestamptz not null,
  check_date date not null,
  check_name text not null,
  subject text not null,
  status text not null check (status in ('pass', 'warn', 'fail')),
  observed numeric,
  expected numeric,
  details text
);
"""

RAW_TO_STAGING = {
    "material_issues": ("issue_id", "staging.stg_material_issues"),
    "labor_entries": ("labor_entry_id", "staging.stg_labor_entries"),
    "scrap_records": ("scrap_id", "staging.stg_scrap_records"),
    "invoice_lines": ("invoice_id, invoice_line", "staging.stg_invoice_lines"),
    "goods_receipts": ("gr_id", "staging.stg_goods_receipts"),
    "gl_journal_entries": ("je_id, je_line", "staging.stg_gl_journal_entries"),
    "production_orders": ("order_id", "staging.stg_production_orders"),
}
STAGING_TO_INT = {
    "staging.stg_material_issues": "intermediate.int_material_issues",
    "staging.stg_labor_entries": "intermediate.int_labor_entries",
}
CORE_DAILY_SOURCES = ["material_issues", "labor_entries", "gl_journal_entries"]


@dataclass
class Check:
    name: str
    subject: str
    status: str
    observed: float | None = None
    expected: float | None = None
    details: str = ""


def _scalar(cur, sql: str, params=None):
    cur.execute(sql, params)
    return cur.fetchone()[0]


def run_checks(check_date: date, max_reject_rate: float, wallclock_hours: float | None) -> list[Check]:
    out: list[Check] = []
    with connect() as conn, conn.cursor() as cur:
        cur.execute(DDL)
        cur.execute(
            "select source, source_file, rows_read, rows_loaded, rows_rejected "
            "from audit.load_log where partition_date = %s",
            (check_date,),
        )
        files = cur.fetchall()
        for source, key, read, loaded, rejected in files:
            in_raw = _scalar(cur, f"select count(*) from raw.{source} where _source_file = %s", (key,))
            ok = read == loaded + rejected and loaded == in_raw
            out.append(
                Check(
                    "file_to_raw",
                    key,
                    "pass" if ok else "fail",
                    in_raw,
                    loaded,
                    f"read={read} loaded={loaded} rejected={rejected} in_raw={in_raw}",
                )
            )

        by_source: dict[str, list[int]] = {}
        for source, _, read, _, rejected in files:
            agg = by_source.setdefault(source, [0, 0])
            agg[0] += read
            agg[1] += rejected
        for source, (read, rejected) in by_source.items():
            rate = rejected / read if read else 0.0
            status = "fail" if rate > max_reject_rate else ("warn" if rejected else "pass")
            out.append(
                Check(
                    "reject_rate",
                    source,
                    status,
                    round(rate, 5),
                    max_reject_rate,
                    f"{rejected} of {read} rows rejected",
                )
            )

        for source, (keys, stg) in RAW_TO_STAGING.items():
            raw_keys = _scalar(cur, f"select count(*) from (select distinct {keys} from raw.{source}) k")
            stg_rows = _scalar(cur, f"select count(*) from {stg}")
            out.append(Check("raw_to_staging", stg, "pass" if raw_keys == stg_rows else "fail", stg_rows, raw_keys))

        for stg, intm in STAGING_TO_INT.items():
            a = _scalar(cur, f"select count(*) from {stg}")
            b = _scalar(cur, f"select count(*) from {intm}")
            out.append(Check("staging_to_int", intm, "pass" if a == b else "fail", b, a))

        if is_production_day(check_date):
            for source in CORE_DAILY_SOURCES:
                n = _scalar(
                    cur,
                    "select count(*) from audit.load_log where source = %s and partition_date = %s",
                    (source, check_date),
                )
                out.append(
                    Check(
                        "freshness",
                        source,
                        "pass" if n else "fail",
                        n,
                        1,
                        "partition present" if n else f"no {source} partition loaded for {check_date}",
                    )
                )
        if wallclock_hours is not None:
            newest = _scalar(cur, "select max(loaded_at) from audit.load_log")
            age_h = (datetime.now(UTC) - newest).total_seconds() / 3600 if newest else float("inf")
            out.append(
                Check(
                    "freshness",
                    "wallclock",
                    "pass" if age_h <= wallclock_hours else "fail",
                    round(age_h, 2),
                    wallclock_hours,
                    "hours since newest load",
                )
            )

        now = datetime.now(UTC)
        cur.executemany(
            """insert into dq.layer_check_results
               (run_ts, check_date, check_name, subject, status, observed, expected, details)
               values (%s, %s, %s, %s, %s, %s, %s, %s)""",
            [(now, check_date, c.name, c.subject, c.status, c.observed, c.expected, c.details) for c in out],
        )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", required=True, type=date.fromisoformat)
    ap.add_argument("--max-reject-rate", type=float, default=0.01)
    ap.add_argument(
        "--wallclock-hours",
        type=float,
        default=None,
        help="also fail if the newest load is older than this (leave unset for backfills)",
    )
    args = ap.parse_args(argv)
    checks = run_checks(args.date, args.max_reject_rate, args.wallclock_hours)
    failed = [c for c in checks if c.status == "fail"]
    log.info(
        "layer checks complete",
        extra={
            "date": str(args.date),
            "checks": len(checks),
            "failed": len(failed),
            "warned": sum(c.status == "warn" for c in checks),
        },
    )
    for c in failed:
        log.error("layer check failed", extra=c.__dict__)
    if failed:
        send_alert(
            f"Layer checks failed for {args.date}",
            "\n".join(f"- {c.name} / {c.subject}: observed {c.observed}, expected {c.expected}" for c in failed),
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
