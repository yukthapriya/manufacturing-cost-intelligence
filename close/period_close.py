"""Month-end close for one fiscal period.

    python -m close.period_close --period 2025-03              # preliminary snapshot + readiness report
    python -m close.period_close --period 2025-03 --sign-off   # final: lock the period if the gate passes

What it does
  1. Evaluates the sign-off gate for the period:
       - no critical reconciliation exceptions (subledger-to-GL activity breaks above
         MATERIALITY_USD, or a WIP roll-forward that does not tie)
       - the WIP roll-forward ties out for every plant
       - the latest dbt build has no failed error-severity tests
  2. Writes close.fct_period_close_snapshot (variance summary, reconciliation summary,
     WIP roll-forward, exception counts) and close.period_exceptions_snapshot.
     Preliminary snapshots are replaced on every run; a final snapshot is immutable,
     enforced by a database trigger, so a signed-off period can never be rewritten.
  3. With --sign-off: gate passed -> period status 'signed_off' and locked;
     gate failed -> status 'blocked' with reasons, exit code 2.

Late-arriving transactions never reopen a locked period: the period-lock routing rule
(common/fiscal_calendar.py, dbt macro accounting_period) books anything posted after a
period's close date into the open period and flags it.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from common.config import materiality_usd
from common.db import connect
from common.logging_setup import get_logger
from quality.alerts import send_alert

log = get_logger("close.period_close")

EXIT_BLOCKED = 2

DDL = """
create schema if not exists close;

create table if not exists close.period_status (
  period_id text primary key,
  status text not null check (status in ('open', 'blocked', 'signed_off')),
  locked boolean not null default false,
  last_run_at timestamptz,
  signed_off_at timestamptz,
  signed_off_by text,
  gate_results jsonb,
  blocked_reasons text[]
);

create table if not exists close.fct_period_close_snapshot (
  snapshot_id text not null,
  snapshot_type text not null check (snapshot_type in ('preliminary', 'final')),
  snapshot_ts timestamptz not null,
  period_id text not null,
  section text not null,
  plant_id text,
  dimension text,
  metric text not null,
  value numeric,
  status text
);
create index if not exists ix_close_snapshot_period on close.fct_period_close_snapshot (period_id, snapshot_type);

create table if not exists close.period_exceptions_snapshot (
  snapshot_id text not null,
  snapshot_type text not null,
  snapshot_ts timestamptz not null,
  period_id text not null,
  recon_type text, exception_key text, plant_id text, description text, amount numeric,
  status text, root_cause text, age_days int, aging_bucket text, is_critical boolean
);

-- Immutability of signed-off periods: final snapshot rows can't be updated or deleted.
create or replace function close.forbid_final_snapshot_change() returns trigger language plpgsql as $$
begin
  if old.snapshot_type = 'final' then
    raise exception 'period % is closed: final close snapshots are immutable', old.period_id;
  end if;
  return case when tg_op = 'DELETE' then old else new end;
end $$;

drop trigger if exists trg_final_snapshot_immutable on close.fct_period_close_snapshot;
create trigger trg_final_snapshot_immutable before update or delete on close.fct_period_close_snapshot
  for each row execute function close.forbid_final_snapshot_change();
drop trigger if exists trg_final_exceptions_immutable on close.period_exceptions_snapshot;
create trigger trg_final_exceptions_immutable before update or delete on close.period_exceptions_snapshot
  for each row execute function close.forbid_final_snapshot_change();
"""

SNAPSHOT_SQL = {
    # section -> SQL returning (plant_id, dimension, metric, value, status)
    "variance_summary": """
        select plant_id, cost_element, 'variance_amount', round(sum(variance_amount), 2), null
        from marts.fct_cost_variance where period_id = %(p)s group by 1, 2""",
    "production_summary": """
        select plant_id, null, m.metric, m.value, null
        from (select plant_id, count(*) as orders, sum(completed_qty) as units, sum(total_actual_cost) as actual,
                     sum(total_std_cost) as std, sum(total_variance) as variance
              from marts.fct_production_cost where period_id = %(p)s group by 1) f
        cross join lateral (values ('orders_completed', f.orders), ('units_completed', f.units),
                                   ('total_actual_cost', round(f.actual, 2)), ('total_std_cost', round(f.std, 2)),
                                   ('total_variance', round(f.variance, 2))) m(metric, value)""",
    "subledger_to_gl": """
        select plant_id, account || ' ' || source_type, 'diff', diff, status
        from recon.recon_subledger_to_gl where period_id = %(p)s and status <> 'matched'
        union all
        select plant_id, account, 'gl_vs_subledger_balance_diff', gl_vs_subledger_diff, status
        from recon.recon_inventory_balance where period_id = %(p)s""",
    "wip_rollforward": """
        select plant_id, null, m.metric, m.value, case when ties_out then 'ties' else 'break' end
        from recon.recon_wip_rollforward r
        cross join lateral (values ('beginning_wip', r.beginning_wip), ('material_issued', r.material_issued),
                                   ('labor', r.labor), ('overhead', r.overhead), ('completions', r.completions),
                                   ('scrap', r.scrap), ('settlement', r.settlement),
                                   ('ending_wip', r.ending_wip_rollforward),
                                   ('ending_open_orders', r.ending_open_orders),
                                   ('gl_ending_wip', r.gl_ending_wip)) m(metric, value)
        where r.period_id = %(p)s""",
    "exceptions": """
        select plant_id, recon_type || ':' || coalesce(root_cause, ''), 'open_exceptions', count(*),
               case when bool_or(is_critical) then 'critical' else 'open' end
        from recon.recon_exceptions where period_id = %(p)s group by 1, 2""",
    "late_arrivals": """
        select plant_id, work_period_id, 'late_labor_entries_routed_in', count(*), null
        from intermediate.int_labor_entries where period_id = %(p)s and is_late_posting group by 1, 2""",
}


@dataclass
class Gate:
    passed: bool = True
    reasons: list[str] = field(default_factory=list)
    results: dict = field(default_factory=dict)

    def fail(self, reason: str) -> None:
        self.passed = False
        self.reasons.append(reason)


def _prior_period(period: str) -> str:
    y, m = int(period[:4]), int(period[5:])
    return f"{y - (m == 1):04d}-{(m - 2) % 12 + 1:02d}"


def evaluate_gate(cur, period: str, materiality: float) -> Gate:
    g = Gate()
    # periods close in order: the prior period must be signed off first (if it had activity)
    prior = _prior_period(period)
    cur.execute(
        """select exists (select 1 from marts.fct_production_cost where period_id = %s),
                  (select status from close.period_status where period_id = %s)""",
        (prior, prior),
    )
    prior_active, prior_status = cur.fetchone()
    g.results["prior_period"] = {"period": prior, "had_activity": prior_active, "status": prior_status}
    if prior_active and prior_status != "signed_off":
        g.fail(f"prior period {prior} is not signed off ({prior_status or 'never run'})")

    cur.execute(
        """select count(*), coalesce(sum(abs(diff)), 0) from recon.recon_subledger_to_gl
           where period_id = %s and status = 'exception' and abs(diff) > %s""",
        (period, materiality),
    )
    n, amt = cur.fetchone()
    g.results["material_gl_breaks"] = {"count": n, "abs_amount": float(amt)}
    if n:
        cur.execute(
            """select plant_id, account, source_type, diff, root_cause from recon.recon_subledger_to_gl
               where period_id = %s and status = 'exception' and abs(diff) > %s order by abs(diff) desc""",
            (period, materiality),
        )
        for plant, acct, src, diff, cause in cur.fetchall():
            g.fail(f"GL break {plant} {acct} {src}: {float(diff):,.2f} ({cause})")

    cur.execute(
        "select count(*), count(*) filter (where not ties_out) from recon.recon_wip_rollforward where period_id = %s",
        (period,),
    )
    total, broken = cur.fetchone()
    g.results["wip_rollforward"] = {"plants": total, "not_tying": broken}
    if total == 0:
        g.fail("no WIP roll-forward rows for period (has dbt run?)")
    if broken:
        g.fail(f"WIP roll-forward does not tie for {broken} plant(s)")

    cur.execute("select to_regclass('dq.latest_test_results') is not null")
    if cur.fetchone()[0]:
        cur.execute("""select count(*) filter (where status in ('fail', 'error')), count(*)
                       from dq.latest_test_results""")
        failed, tests = cur.fetchone()
        g.results["dbt_tests"] = {"tests": tests, "failed": failed}
        if failed:
            g.fail(f"{failed} dbt test(s) failing in the latest build")
    else:
        g.results["dbt_tests"] = {"tests": 0, "failed": None}
        g.fail("no published dbt test results (run quality.publish_dq)")

    cur.execute(
        """select count(*), coalesce(sum(abs(gl_vs_subledger_diff)), 0) from recon.recon_inventory_balance
           where period_id = %s and is_material""",
        (period,),
    )
    n, amt = cur.fetchone()
    # informational: cumulative balance breaks carry forward until a correcting entry is posted
    g.results["material_balance_breaks_carried"] = {"count": n, "abs_amount": float(amt)}
    return g


def write_snapshot(cur, period: str, snapshot_type: str) -> str:
    snap_id = f"{period}-{snapshot_type}-{uuid.uuid4().hex[:8]}"
    ts = datetime.now(UTC)
    # preliminary snapshots are working copies: replaced on every run, dropped at sign-off
    cur.execute(
        "delete from close.fct_period_close_snapshot where period_id = %s and snapshot_type = 'preliminary'", (period,)
    )
    cur.execute(
        "delete from close.period_exceptions_snapshot where period_id = %s and snapshot_type = 'preliminary'", (period,)
    )
    for section, sql in SNAPSHOT_SQL.items():
        cur.execute(sql, {"p": period})
        rows = cur.fetchall()
        cur.executemany(
            """insert into close.fct_period_close_snapshot
               (snapshot_id, snapshot_type, snapshot_ts, period_id, section, plant_id, dimension, metric, value, status)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            [(snap_id, snapshot_type, ts, period, section, *r) for r in rows],
        )
    cur.execute(
        """insert into close.period_exceptions_snapshot
           select %s, %s, %s, period_id, recon_type, exception_key, plant_id, description, amount, status,
                  root_cause, age_days, aging_bucket, is_critical
           from recon.recon_exceptions where period_id = %s""",
        (snap_id, snapshot_type, ts, period),
    )
    return snap_id


def run(period: str, sign_off: bool, signed_off_by: str) -> int:
    materiality = materiality_usd()
    with connect() as conn, conn.cursor() as cur:
        cur.execute(DDL)
        cur.execute("select status, locked from close.period_status where period_id = %s for update", (period,))
        row = cur.fetchone()
        if row and row[1]:
            log.info("period already closed and locked; nothing to do", extra={"period": period, "status": row[0]})
            return 0

        gate = evaluate_gate(cur, period, materiality)
        final = sign_off and gate.passed
        snap_id = write_snapshot(cur, period, "final" if final else "preliminary")
        status = "signed_off" if final else ("blocked" if sign_off else (row[0] if row else "open"))
        cur.execute(
            """insert into close.period_status (period_id, status, locked, last_run_at, signed_off_at, signed_off_by,
                                                gate_results, blocked_reasons)
               values (%s, %s, %s, now(), %s, %s, %s, %s)
               on conflict (period_id) do update set status = excluded.status, locked = excluded.locked,
                 last_run_at = now(), signed_off_at = excluded.signed_off_at, signed_off_by = excluded.signed_off_by,
                 gate_results = excluded.gate_results, blocked_reasons = excluded.blocked_reasons""",
            (
                period,
                status,
                final,
                datetime.now(UTC) if final else None,
                signed_off_by if final else None,
                json.dumps(gate.results),
                gate.reasons or None,
            ),
        )

    extra = {
        "period": period,
        "status": status,
        "snapshot_id": snap_id,
        "gate_passed": gate.passed,
        "reasons": gate.reasons,
        "gate": gate.results,
    }
    if sign_off and not gate.passed:
        log.error("close sign-off BLOCKED", extra=extra)
        send_alert(f"Close sign-off blocked for {period}", "\n".join(f"- {r}" for r in gate.reasons))
        return EXIT_BLOCKED
    log.info("close run complete", extra=extra)
    if final:
        send_alert(f"Period {period} signed off and locked", f"snapshot {snap_id}", level="info")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--period", required=True, help="YYYY-MM")
    ap.add_argument("--sign-off", action="store_true", help="attempt final sign-off and lock")
    ap.add_argument("--signed-off-by", default="pipeline")
    args = ap.parse_args(argv)
    return run(args.period, args.sign_off, args.signed_off_by)


if __name__ == "__main__":
    sys.exit(main())
