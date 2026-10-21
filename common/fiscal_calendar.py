"""Fiscal calendar, business days and the period-lock routing rule.

The routing rule lives here (Python, used by the generator to post the GL) and in
``dbt/macros/accounting_period.sql`` (SQL, used by the cost model). Both must agree,
otherwise the subledger and GL drift apart; ``tests/test_calendar.py`` pins it down.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

# Posting cutoff: a period accepts postings up to the day before business day 1 of the
# following month. The daily pipeline loads that day overnight and the close runs on the
# morning of business day 1, so nothing can land in a period after it was evaluated.


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    return d + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    d = nxt - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def us_holidays(year: int) -> set[date]:
    """Company holidays (a simplified US set; observed dates ignored for brevity)."""
    return {
        date(year, 1, 1),
        _last_weekday(year, 5, 0),  # Memorial Day
        date(year, 7, 4),
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        _nth_weekday(year, 11, 3, 4) + timedelta(days=1),
        date(year, 12, 24),
        date(year, 12, 25),
    }


def is_business_day(d: date) -> bool:
    return d.weekday() < 5 and d not in us_holidays(d.year)


def is_production_day(d: date) -> bool:
    """Plants run Monday to Saturday, closed on company holidays."""
    return d.weekday() < 6 and d not in us_holidays(d.year)


def nth_business_day(year: int, month: int, n: int) -> date:
    d = date(year, month, 1)
    count = 0
    while True:
        if is_business_day(d):
            count += 1
            if count == n:
                return d
        d += timedelta(days=1)


@dataclass(frozen=True)
class Period:
    period_id: str  # 'YYYY-MM'
    start: date
    end: date
    close_date: date
    business_day_1: date

    @staticmethod
    def of(d: date) -> Period:
        start = date(d.year, d.month, 1)
        nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        return Period(
            period_id=f"{d.year:04d}-{d.month:02d}",
            start=start,
            end=nxt - timedelta(days=1),
            close_date=nth_business_day(nxt.year, nxt.month, 1) - timedelta(days=1),
            business_day_1=nth_business_day(d.year, d.month, 1),
        )


def accounting_period(transaction_date: date, posting_date: date) -> str:
    """Period a transaction is booked in.

    Normally the period of the transaction date. If it is posted after that period
    closed (posting_date > close_date), the closed period is locked, so the
    transaction is routed to the period of its posting date and flagged as late.
    """
    p = Period.of(transaction_date)
    return p.period_id if posting_date <= p.close_date else Period.of(posting_date).period_id


def fiscal_calendar(start: date, months: int, extra_months: int = 2) -> pd.DataFrame:
    """One row per period, including a couple of periods after the window for late postings."""
    rows = []
    y, m = start.year, start.month
    for _ in range(months + extra_months):
        p = Period.of(date(y, m, 1))
        rows.append(
            {
                "period_id": p.period_id,
                "fiscal_year": y,
                "fiscal_month": m,
                "period_start": p.start,
                "period_end": p.end,
                "business_day_1": p.business_day_1,
                "close_date": p.close_date,
            }
        )
        y, m = y + (m == 12), m % 12 + 1
    return pd.DataFrame(rows)


def accounting_period_vec(transaction_dates: pd.Series, posting_dates: pd.Series, cal: pd.DataFrame) -> pd.Series:
    """Vectorised accounting_period() using a calendar frame."""
    td = pd.to_datetime(transaction_dates)
    pdt = pd.to_datetime(posting_dates)
    tx_period = td.dt.strftime("%Y-%m")
    post_period = pdt.dt.strftime("%Y-%m")
    close = tx_period.map(dict(zip(cal["period_id"], pd.to_datetime(cal["close_date"]), strict=True)))
    if close.isna().any():
        raise ValueError("transaction outside fiscal calendar")
    return tx_period.where(pdt <= close, post_period)
