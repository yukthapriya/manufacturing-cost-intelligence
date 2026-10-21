"""Thin psycopg2 helpers for the warehouse."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pandas as pd
import psycopg2
import psycopg2.extensions

from common.config import warehouse


@contextmanager
def connect(autocommit: bool = False) -> Iterator[psycopg2.extensions.connection]:
    conn = psycopg2.connect(warehouse().dsn)
    conn.autocommit = autocommit
    try:
        yield conn
        if not autocommit:
            conn.commit()
    except Exception:
        if not autocommit:
            conn.rollback()
        raise
    finally:
        conn.close()


def query_df(sql: str, params: tuple | dict | None = None) -> pd.DataFrame:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [c.name for c in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=cols)


def execute(sql: str, params: tuple | dict | None = None) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
