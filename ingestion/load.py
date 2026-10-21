"""Validate raw extracts and load them into the Postgres ``raw`` schema.

Idempotent by design: each file is identified by its key and SHA-256. Re-loading a file
that is already in ``audit.load_log`` with the same checksum is a no-op; a changed file
(or ``--force``) replaces that file's rows atomically (delete by _source_file + COPY in
one transaction). So re-running a day never duplicates data.

    python -m ingestion.load --init-db
    python -m ingestion.load --date 2025-03-04 [--force]
    python -m ingestion.load --all [--since 2025-01-01] [--until 2025-06-30]
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
import uuid
from dataclasses import dataclass

import pandas as pd
from psycopg2.extras import execute_values

from common.config import raw_uri
from common.db import connect
from common.logging_setup import get_logger
from common.storage import open_storage, sha256
from ingestion.ddl import all_ddl
from ingestion.schemas import SOURCES
from ingestion.validate import SchemaError, validate

log = get_logger("ingestion.load")


@dataclass
class LoadResult:
    key: str
    status: str  # loaded | skipped | failed
    rows_read: int = 0
    rows_loaded: int = 0
    rows_rejected: int = 0


def init_db() -> None:
    with connect() as conn, conn.cursor() as cur:
        for stmt in all_ddl():
            cur.execute(stmt)
    log.info("warehouse DDL applied", extra={"tables": len(SOURCES)})


def parse_key(key: str) -> tuple[str, str] | None:
    parts = key.split("/")
    if len(parts) != 3 or not parts[2].endswith(".csv") or parts[0] not in SOURCES:
        return None
    return parts[0], parts[1]


def load_file(storage, key: str, batch_id: str, force: bool = False) -> LoadResult:
    source_name, part_date = parse_key(key)
    source = SOURCES[source_name]
    data = storage.read_bytes(key)
    checksum = sha256(data)

    with connect() as conn, conn.cursor() as cur:
        cur.execute("select pg_advisory_xact_lock(hashtext(%s))", (key,))
        cur.execute("select checksum from audit.load_log where source_file = %s", (key,))
        row = cur.fetchone()
        if row and row[0] == checksum and not force:
            return LoadResult(key, "skipped")

        df = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False)
        try:
            valid, rejects, warnings = validate(df, source)
        except SchemaError as e:
            log.error("schema error, file not loaded", extra={"file": key, "error": str(e)})
            return LoadResult(key, "failed", rows_read=len(df))
        for w in warnings:
            log.warning(w, extra={"file": key})

        cur.execute(f"delete from raw.{source_name} where _source_file = %s", (key,))
        cur.execute("delete from raw.rejects where _source_file = %s", (key,))

        valid = valid.assign(_batch_id=batch_id, _source_file=key)
        buf = io.StringIO()
        valid.to_csv(buf, index=False, header=False, date_format="%Y-%m-%d %H:%M:%S")
        buf.seek(0)
        cols = ", ".join(valid.columns)
        cur.copy_expert(f"copy raw.{source_name} ({cols}) from stdin with (format csv, null '')", buf)

        if len(rejects):
            execute_values(
                cur,
                "insert into raw.rejects (source, _source_file, _batch_id, row_num, reason, payload) values %s",
                [
                    (source_name, key, batch_id, int(r.row_num), r.reason, json.dumps(r.payload))
                    for r in rejects.itertuples()
                ],
            )
        cur.execute(
            """insert into audit.load_log (source_file, source, partition_date, batch_id, checksum, rows_read,
                                           rows_loaded, rows_rejected, warnings, loaded_at)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
               on conflict (source_file) do update set batch_id = excluded.batch_id, checksum = excluded.checksum,
                 rows_read = excluded.rows_read, rows_loaded = excluded.rows_loaded,
                 rows_rejected = excluded.rows_rejected, warnings = excluded.warnings, loaded_at = now()""",
            (
                key,
                source_name,
                part_date,
                batch_id,
                checksum,
                len(df),
                len(valid),
                len(rejects),
                "\n".join(warnings) or None,
            ),
        )
    return LoadResult(key, "loaded", len(df), len(valid), len(rejects))


def keys_for(storage, date: str | None, since: str | None = None, until: str | None = None) -> list[str]:
    keys = [k for k in storage.list() if parse_key(k)]
    if date:
        keys = [k for k in keys if parse_key(k)[1] == date]
    if since:
        keys = [k for k in keys if parse_key(k)[1] >= since]
    if until:
        keys = [k for k in keys if parse_key(k)[1] <= until]
    # master data first so it is present before transactions in the same run
    return sorted(keys, key=lambda k: (SOURCES[parse_key(k)[0]].partition_by is not None, k))


def run(date: str | None, force: bool, since: str | None = None, until: str | None = None) -> list[LoadResult]:
    storage = open_storage(raw_uri())
    batch_id = f"{date or 'all'}-{uuid.uuid4().hex[:8]}"
    t0 = time.perf_counter()
    results = [load_file(storage, k, batch_id, force) for k in keys_for(storage, date, since, until)]
    summary = {
        "batch_id": batch_id,
        "date": date,
        "files": len(results),
        "loaded": sum(r.status == "loaded" for r in results),
        "skipped": sum(r.status == "skipped" for r in results),
        "failed": sum(r.status == "failed" for r in results),
        "rows_loaded": sum(r.rows_loaded for r in results),
        "rows_rejected": sum(r.rows_rejected for r in results),
        "seconds": round(time.perf_counter() - t0, 2),
    }
    log.info("load finished", extra=summary)
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--init-db", action="store_true")
    g.add_argument("--date", help="partition date YYYY-MM-DD")
    g.add_argument("--all", action="store_true")
    ap.add_argument("--force", action="store_true", help="reload even if checksum unchanged")
    ap.add_argument("--since", help="with --all: only partitions on/after YYYY-MM-DD")
    ap.add_argument("--until", help="with --all: only partitions on/before YYYY-MM-DD")
    args = ap.parse_args(argv)
    if args.init_db:
        init_db()
        return 0
    results = run(None if args.all else args.date, args.force, args.since, args.until)
    return 1 if any(r.status == "failed" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
