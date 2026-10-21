"""Warehouse DDL: schemas, append-only raw tables, rejects, load audit, monthly partitions."""

from __future__ import annotations

from datetime import date

from ingestion.schemas import PG_TYPES, SOURCES

PARTITION_FROM = date(2024, 1, 1)
PARTITION_TO = date(2028, 1, 1)


def _months(a: date, b: date):
    while a < b:
        nxt = date(a.year + (a.month == 12), a.month % 12 + 1, 1)
        yield a, nxt
        a = nxt


def raw_table_ddl(name: str) -> list[str]:
    src = SOURCES[name]
    cols = ",\n  ".join(f"{c.name} {PG_TYPES[c.type]}" for c in src.columns)
    meta = "_batch_id text not null,\n  _source_file text not null,\n  _loaded_at timestamptz not null default now()"
    stmts = []
    if src.partition_by:
        stmts.append(
            f"create table if not exists raw.{name} (\n  {cols},\n  {meta}\n) partition by range ({src.partition_by});"
        )
        for a, b in _months(PARTITION_FROM, PARTITION_TO):
            stmts.append(
                f"create table if not exists raw.{name}_{a:%Y%m} partition of raw.{name} "
                f"for values from ('{a}') to ('{b}');"
            )
        stmts.append(f"create table if not exists raw.{name}_default partition of raw.{name} default;")
    else:
        stmts.append(f"create table if not exists raw.{name} (\n  {cols},\n  {meta}\n);")
    stmts.append(f"create index if not exists ix_{name}_source_file on raw.{name} (_source_file);")
    return stmts


def all_ddl() -> list[str]:
    stmts = [
        "create schema if not exists raw;",
        "create schema if not exists audit;",
        "create schema if not exists dq;",
        "create schema if not exists close;",
        """create table if not exists raw.rejects (
  source text not null,
  _source_file text not null,
  _batch_id text not null,
  row_num int not null,
  reason text not null,
  payload jsonb,
  _loaded_at timestamptz not null default now()
);""",
        "create index if not exists ix_rejects_source_file on raw.rejects (_source_file);",
        """create table if not exists audit.load_log (
  source_file text primary key,
  source text not null,
  partition_date date,
  batch_id text not null,
  checksum text not null,
  rows_read int not null,
  rows_loaded int not null,
  rows_rejected int not null,
  warnings text,
  loaded_at timestamptz not null default now()
);""",
    ]
    for name in SOURCES:
        stmts.extend(raw_table_ddl(name))
    return stmts
