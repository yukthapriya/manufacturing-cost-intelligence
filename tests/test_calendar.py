from datetime import date

import pandas as pd
import pytest

from common.fiscal_calendar import (
    Period,
    accounting_period,
    accounting_period_vec,
    fiscal_calendar,
    is_business_day,
    nth_business_day,
    us_holidays,
)


def test_holidays_2025():
    h = us_holidays(2025)
    assert date(2025, 5, 26) in h  # Memorial Day (last Monday of May)
    assert date(2025, 9, 1) in h  # Labor Day
    assert date(2025, 11, 27) in h and date(2025, 11, 28) in h  # Thanksgiving + Friday


def test_business_day_1_skips_holiday_and_weekend():
    # 1 Jan 2025 is a holiday (Wednesday) -> business day 1 is Thursday 2 Jan
    assert nth_business_day(2025, 1, 1) == date(2025, 1, 2)
    # 1 Jun 2025 is a Sunday -> Monday 2 Jun
    assert nth_business_day(2025, 6, 1) == date(2025, 6, 2)
    assert not is_business_day(date(2025, 7, 4))


def test_posting_cutoff_is_day_before_next_business_day_1():
    p = Period.of(date(2025, 3, 15))
    assert p.period_id == "2025-03"
    assert p.end == date(2025, 3, 31)
    assert p.close_date == date(2025, 3, 31)  # BD1 of April is Tue 1 April
    # May 2025 ends on a Saturday; BD1 of June is Monday 2 June -> weekend postings still count for May
    assert Period.of(date(2025, 5, 10)).close_date == date(2025, 6, 1)
    # Dec 2025: 1 Jan is a holiday, BD1 is Fri 2 Jan -> cutoff 1 Jan
    assert Period.of(date(2025, 12, 5)).close_date == date(2026, 1, 1)


@pytest.mark.parametrize(
    "tx, posted, expected",
    [
        (date(2025, 3, 10), date(2025, 3, 10), "2025-03"),  # same day
        (date(2025, 5, 30), date(2025, 6, 1), "2025-05"),  # Sunday posting before BD1 -> still May
        (date(2025, 3, 31), date(2025, 4, 1), "2025-04"),  # posted on BD1 -> March already evaluated, routed
        (date(2025, 3, 20), date(2025, 4, 9), "2025-04"),  # late labor entry
        (date(2025, 12, 30), date(2026, 1, 12), "2026-01"),  # crosses the year end
    ],
)
def test_period_lock_routing(tx, posted, expected):
    assert accounting_period(tx, posted) == expected


def test_vectorised_routing_matches_scalar():
    cal = fiscal_calendar(date(2025, 1, 1), 12)
    tx = pd.Series(pd.date_range("2025-01-01", "2025-12-31", freq="3D"))
    posted = tx + pd.to_timedelta([(i * 7) % 23 for i in range(len(tx))], unit="D")
    vec = accounting_period_vec(tx, posted, cal)
    scalar = [accounting_period(a.date(), b.date()) for a, b in zip(tx, posted, strict=True)]
    assert vec.tolist() == scalar


def test_fiscal_calendar_has_extra_periods_for_late_postings():
    cal = fiscal_calendar(date(2025, 1, 1), 12)
    assert cal["period_id"].iloc[0] == "2025-01"
    assert cal["period_id"].iloc[-1] == "2026-02"
