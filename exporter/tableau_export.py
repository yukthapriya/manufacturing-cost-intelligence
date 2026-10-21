"""Export marts, reconciliation and DQ tables as Tableau extracts.

    python -m exporter.tableau_export --out tableau/extracts [--hyper]

Writes one CSV per table plus manifest.json (row counts, export time). With --hyper and
the `tableauhyperapi` package installed, also writes a single mci.hyper with every table,
which Tableau Desktop/Public opens directly.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from common.db import connect
from common.logging_setup import get_logger

log = get_logger("exporter.tableau")

TABLES = [
    "marts.dim_plant",
    "marts.dim_line",
    "marts.dim_product",
    "marts.dim_material",
    "marts.dim_supplier",
    "marts.dim_date",
    "marts.fct_production_cost",
    "marts.fct_cost_variance",
    "marts.fct_unit_cost",
    "marts.fct_scrap",
    "marts.fct_inventory_discrepancy",
    "marts.fct_purchase_price",
    "marts.fct_cost_transactions",
    "recon.recon_subledger_to_gl",
    "recon.recon_inventory_balance",
    "recon.recon_wip_rollforward",
    "recon.recon_three_way_match",
    "recon.recon_exceptions",
    "dq.latest_test_results",
    "dq.layer_check_results",
    "close.period_status",
    "close.fct_period_close_snapshot",
]


def export(out: Path, hyper: bool) -> dict[str, int]:
    out.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    frames: dict[str, pd.DataFrame] = {}
    with connect() as conn, conn.cursor() as cur:
        for table in TABLES:
            cur.execute("select to_regclass(%s) is not null", (table,))
            if not cur.fetchone()[0]:
                log.warning("table not found, skipped", extra={"table": table})
                continue
            name = table.split(".")[1]
            path = out / f"{name}.csv"
            with path.open("w", encoding="utf-8") as fh:
                cur.copy_expert(f"copy (select * from {table}) to stdout with (format csv, header true)", fh)
            cur.execute(f"select count(*) from {table}")
            counts[name] = cur.fetchone()[0]
            if hyper:
                frames[name] = pd.read_csv(path, low_memory=False)
    (out / "manifest.json").write_text(
        json.dumps({"exported_at": datetime.now(UTC).isoformat(), "tables": counts}, indent=2)
    )
    if hyper:
        _write_hyper(out / "mci.hyper", frames)
    log.info("tableau extracts written", extra={"out": str(out), "tables": len(counts), "rows": sum(counts.values())})
    return counts


def _write_hyper(path: Path, frames: dict[str, pd.DataFrame]) -> None:
    try:
        from tableauhyperapi import Connection, CreateMode, HyperProcess, Inserter, SqlType, TableDefinition, Telemetry
    except ImportError:
        log.warning("tableauhyperapi not installed; CSV extracts only (pip install tableauhyperapi)")
        return

    def sql_type(s: pd.Series):
        if pd.api.types.is_bool_dtype(s):
            return SqlType.bool()
        if pd.api.types.is_integer_dtype(s):
            return SqlType.big_int()
        if pd.api.types.is_float_dtype(s):
            return SqlType.double()
        return SqlType.text()

    with (
        HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hp,
        Connection(hp.endpoint, str(path), CreateMode.CREATE_AND_REPLACE) as conn,
    ):
        for name, df in frames.items():
            cols = [TableDefinition.Column(c, sql_type(df[c])) for c in df.columns]
            table = TableDefinition(table_name=name, columns=cols)
            conn.catalog.create_table(table)
            rows = df.astype(object).where(df.notna(), None).values.tolist()
            with Inserter(conn, table) as ins:
                ins.add_rows(rows)
                ins.execute()
    log.info("hyper extract written", extra={"path": str(path)})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="tableau/extracts", type=Path)
    ap.add_argument("--hyper", action="store_true")
    args = ap.parse_args(argv)
    export(args.out, args.hyper)
    return 0


if __name__ == "__main__":
    sys.exit(main())
