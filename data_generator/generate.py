"""Generate a realistic, deliberately messy manufacturing cost dataset.

Usage:
    python -m data_generator.generate --start 2025-01-01 --months 12 --scale 1.0 --seed 42 --out ./data/source_drop

Output layout (local folder or s3://bucket/prefix):
    <source>/<YYYY-MM-DD>/<source>.csv     one partition per posting/extract date
    _answer_key.json                       injected problems, for tests and the README (never loaded)

At --scale 1.0 a 12-month run is ~9k production orders and ~210k material issue lines.
Scale is linear in order volume: --scale 50 gives ~10M material issue lines.
"""

from __future__ import annotations

import argparse
import io
import json
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from common.fiscal_calendar import fiscal_calendar
from common.logging_setup import get_logger
from common.storage import LocalStorage, open_storage
from data_generator.ledger import build_gl, inventory_observations
from data_generator.master_data import build_master
from data_generator.transactions import (
    _add_months,
    build_issues_and_scrap,
    build_labor,
    build_orders,
    build_purchasing,
    build_shipments,
)

log = get_logger("generator")

MASTER_TABLES = [
    "plants",
    "production_lines",
    "suppliers",
    "materials",
    "products",
    "subassemblies",
    "bom",
    "standard_costs",
    "uom_conversions",
    "gl_accounts",
    "fiscal_calendar",
]


def generate(start: date, months: int, scale: float, seed: int) -> tuple[dict[str, pd.DataFrame], dict]:
    if months < 1 or months > 12 or _add_months(start, months - 1).year != start.year:
        raise ValueError("window must be 1-12 months inside one fiscal (calendar) year; standards are annual")
    rng = np.random.default_rng(seed)
    end = _add_months(start, months) - timedelta(days=1)
    t0 = time.perf_counter()

    master = build_master(rng, start)
    cal = fiscal_calendar(start, months)
    orders = build_orders(rng, master, start, end, scale)
    issues, scrap = build_issues_and_scrap(rng, master, orders, start, end)
    labor = build_labor(rng, master, orders, start, end)
    shipments = build_shipments(rng, orders, end)
    opening, po_lines, receipts, invoices, inv_gl, rec_gl = build_purchasing(rng, master, issues, start, end, months)
    snapshots, cycle_counts = inventory_observations(rng, opening, receipts, issues, cal, end)
    gl, gl_key = build_gl(
        rng, master, cal, start, end, opening, rec_gl, inv_gl, issues, labor, scrap, orders, shipments, months
    )
    log.info(
        "clean data generated",
        extra={"seconds": round(time.perf_counter() - t0, 1), "orders": len(orders), "material_issues": len(issues)},
    )

    # ---- inject source-system data quality problems into the raw extracts ----
    dq_key: dict[str, int] = {}
    invoices, dq_key["duplicate_invoice_lines"], dq_key["invoice_lines_missing_po"] = _dirty_invoices(rng, invoices)
    issues, dq_key["issues_in_grams"], dq_key["issue_reject_rows"] = _dirty_issues(rng, issues)
    labor, dq_key["labor_reject_rows"] = _dirty_labor(rng, labor)
    snapshots, dq_key["snapshot_offsets"], dq_key["negative_snapshots"] = _dirty_snapshots(rng, snapshots)
    dq_key["late_labor_entries"] = int((labor["posting_date"] - labor["work_date"] > pd.Timedelta(days=4)).sum())

    tables = {k: master[k] for k in MASTER_TABLES if k in master}
    tables["fiscal_calendar"] = cal
    tables.update(
        production_orders=_order_events(orders),
        material_issues=issues,
        labor_entries=labor,
        scrap_records=scrap,
        shipments=shipments,
        opening_inventory=opening[["plant_id", "material_id", "qty", "uom", "as_of_date"]],
        purchase_order_lines=po_lines,
        goods_receipts=receipts,
        invoice_lines=invoices,
        inventory_snapshots=snapshots,
        cycle_counts=cycle_counts,
        gl_journal_entries=gl,
    )
    answer_key = {
        "params": {"start": str(start), "months": months, "scale": scale, "seed": seed, "end": str(end)},
        "gl_breaks": gl_key,
        "data_quality": dq_key,
        "row_counts": {k: int(len(v)) for k, v in tables.items()},
    }
    return tables, answer_key


def _order_events(orders: pd.DataFrame) -> pd.DataFrame:
    """CDC-style order extract: a RELEASED row at start, a COMPLETED row at completion."""
    cols = ["order_id", "product_id", "line_id", "plant_id", "planned_qty", "actual_start"]
    rel = orders[cols].copy()
    rel["status"] = "RELEASED"  # completed_qty / actual_end absent -> null after concat
    rel["extract_ts"] = rel["actual_start"]
    done = orders[orders["is_completed"]][cols + ["completed_qty", "actual_end"]].copy()
    done["status"] = "COMPLETED"
    done["extract_ts"] = done["actual_end"]
    ev = pd.concat([rel, done], ignore_index=True)
    ev["completed_qty"] = pd.array(ev["completed_qty"], dtype="Int64")
    return ev[
        [
            "order_id",
            "product_id",
            "line_id",
            "plant_id",
            "planned_qty",
            "completed_qty",
            "status",
            "actual_start",
            "actual_end",
            "extract_ts",
        ]
    ]


def _dirty_invoices(rng, inv: pd.DataFrame):
    inv = inv.copy()
    dup_mask = rng.random(len(inv)) < 0.015
    dups = inv[dup_mask].copy()
    dups["invoice_id"] = np.arange(7_000_001, 7_000_001 + len(dups))
    dups["invoice_line"] = 1
    dups["invoice_date"] = dups["invoice_date"] + pd.to_timedelta(rng.integers(2, 11, len(dups)), unit="D")
    missing = rng.random(len(inv)) < 0.02
    inv["po_line"] = pd.array(inv["po_line"], dtype="Int64")
    inv.loc[missing, ["po_id"]] = None
    inv.loc[missing, "po_line"] = pd.NA
    dups["po_line"] = pd.array(dups["po_line"], dtype="Int64")
    out = pd.concat([inv, dups], ignore_index=True)
    return out, int(dup_mask.sum()), int(missing.sum())


def _dirty_issues(rng, iss: pd.DataFrame):
    iss = iss.copy()
    kg = (iss["uom"] == "KG").to_numpy()
    grams = kg & (rng.random(len(iss)) < 0.015)
    iss["issue_qty"] = iss["issue_qty"].astype(object)
    iss.loc[grams, "issue_qty"] = (np.rint(iss.loc[grams, "issue_qty"].astype(float) * 1000)).astype(np.int64)
    iss.loc[grams, "uom"] = "G"
    n_bad = max(3, int(len(iss) * 0.0005))
    bad = iss.sample(n_bad, random_state=int(rng.integers(1e9))).copy()
    bad["issue_id"] = np.arange(59_000_001, 59_000_001 + n_bad)
    bad["issue_qty"] = -bad["issue_qty"].astype(float).abs() - 1  # negative quantity -> rejected at load
    out = pd.concat([iss, bad], ignore_index=True)
    return out, int(grams.sum()), n_bad


def _dirty_labor(rng, lab: pd.DataFrame):
    n_bad = max(3, int(len(lab) * 0.0005))
    bad = lab.sample(n_bad, random_state=int(rng.integers(1e9))).copy()
    bad["labor_entry_id"] = np.arange(89_000_001, 89_000_001 + n_bad)
    bad["hours"] = rng.uniform(25, 40, n_bad).round(2)  # > 24h in a day -> rejected at load
    return pd.concat([lab, bad], ignore_index=True), n_bad


def _dirty_snapshots(rng, snap: pd.DataFrame):
    snap = snap.copy()
    off = rng.random(len(snap)) < 0.004
    snap.loc[off, "system_qty"] = np.round(snap.loc[off, "system_qty"] * rng.uniform(0.92, 1.08, off.sum()), 3)
    neg_idx = rng.choice(np.flatnonzero(~off), size=min(5, int((~off).sum())), replace=False)
    snap.loc[neg_idx, "system_qty"] = -np.round(rng.uniform(1, 50, len(neg_idx)), 0)
    return snap, int(off.sum()), len(neg_idx)


# partition column per transactional source (the date the record lands in the source system)
PARTITION_COLUMN = {
    "material_issues": "issue_date",
    "labor_entries": "posting_date",
    "scrap_records": "scrap_date",
    "shipments": "ship_date",
    "opening_inventory": "as_of_date",
    "purchase_order_lines": "order_date",
    "goods_receipts": "receipt_date",
    "invoice_lines": "invoice_date",
    "inventory_snapshots": "snapshot_date",
    "cycle_counts": "count_date",
    "gl_journal_entries": "je_date",
    "production_orders": "extract_ts",
}


def write_tables(tables: dict[str, pd.DataFrame], answer_key: dict, out: str, start: date) -> int:
    storage = open_storage(out)
    n_files = 0
    for name, df in tables.items():
        if name in PARTITION_COLUMN:
            part = pd.to_datetime(df[PARTITION_COLUMN[name]]).dt.strftime("%Y-%m-%d")
            groups = df.groupby(part, sort=True)
        else:
            groups = [(start.isoformat(), df)]
        for day, g in groups:
            key = f"{name}/{day}/{name}.csv"
            if isinstance(storage, LocalStorage):
                path = storage.local_path(key)
                path.parent.mkdir(parents=True, exist_ok=True)
                g.to_csv(path, index=False, date_format="%Y-%m-%d %H:%M:%S")
            else:
                buf = io.StringIO()
                g.to_csv(buf, index=False, date_format="%Y-%m-%d %H:%M:%S")
                storage.write_bytes(key, buf.getvalue().encode())
            n_files += 1
    storage.write_bytes("_answer_key.json", json.dumps(answer_key, indent=2).encode())
    return n_files


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default="2025-01-01", type=date.fromisoformat)
    ap.add_argument("--months", default=12, type=int)
    ap.add_argument("--scale", default=1.0, type=float, help="order volume multiplier (50 ~= 10M issue lines)")
    ap.add_argument("--seed", default=42, type=int)
    ap.add_argument("--out", default=None, help="local folder or s3://bucket/prefix (default: $SOURCE_URI)")
    args = ap.parse_args(argv)
    from common.config import source_uri

    out = args.out or source_uri()
    t0 = time.perf_counter()
    tables, key = generate(args.start, args.months, args.scale, args.seed)
    t1 = time.perf_counter()
    n = write_tables(tables, key, out, args.start)
    log.info(
        "generation complete",
        extra={
            "out": str(Path(out)) if not out.startswith("s3://") else out,
            "files": n,
            "generate_s": round(t1 - t0, 1),
            "write_s": round(time.perf_counter() - t1, 1),
            "rows": key["row_counts"],
        },
    )


if __name__ == "__main__":
    main()
