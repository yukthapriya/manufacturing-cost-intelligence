"""Exact money arithmetic for the generator.

The ERP rounds every transaction value to cents (half-up). Postgres ``round(numeric, 2)``
does the same, so if the generator computes values in integer arithmetic from the exact
quantities and prices it writes to CSV, the GL it posts and the subledger dbt rebuilds
tie to the cent. Floats would drift by a cent here and there.
"""

from __future__ import annotations

import numpy as np

QTY_SCALE = 1_000  # quantities carry at most 3 decimals
PRICE_SCALE = 10_000  # unit prices / standard costs carry at most 4 decimals
RATE_SCALE = 100  # hours and hourly rates carry 2 decimals


def to_int(values, scale: int) -> np.ndarray:
    return np.rint(np.asarray(values, dtype=np.float64) * scale).astype(np.int64)


def ext_cents(qty, price) -> np.ndarray:
    """round(qty * price, 2) in integer cents, qty 3dp and price 4dp, values >= 0."""
    q = to_int(qty, QTY_SCALE)
    p = to_int(price, PRICE_SCALE)
    raw = q * p  # units of 1e-7 dollars
    return (raw + 50_000) // 100_000


def hours_cents(hours, rate) -> np.ndarray:
    """round(hours * rate, 2) in integer cents, both 2dp, values >= 0."""
    raw = to_int(hours, RATE_SCALE) * to_int(rate, RATE_SCALE)  # 1e-4 dollars
    return (raw + 50) // 100


def dollars(cents) -> np.ndarray:
    return np.asarray(cents, dtype=np.int64) / 100.0
