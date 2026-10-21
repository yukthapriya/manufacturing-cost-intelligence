"""Propose (and optionally post) correcting journal entries for subledger-to-GL breaks.

    python -m close.propose_corrections --period 2025-03            # write a proposal CSV for review
    python -m close.propose_corrections --period 2025-03 --post     # also drop it into the raw landing zone

Each daily break in recon.recon_gl_daily gets a correcting line of -diff on the same
date, plant, account and source type, so the next pipeline run clears it:
  missing_gl_posting    -> books the posting that never reached the GL
  duplicate_gl_posting  -> reverses the duplicate
  misposted_plant       -> reclasses from the wrong plant to the right one
  timing_cutoff         -> accrues in the period it belongs to, reverses where it landed
Lines outside the reconciled accounts (e.g. the GRNI side of a duplicated receipt) are
not visible to the reconciliation, so any imbalance goes to 1999 Reconciliation Suspense
for the accounting team to clear. Posting writes a gl_journal_entries file into RAW_URI
under the correction date; the loader treats it like any other source file.
"""

from __future__ import annotations

import argparse
import io
import sys
import uuid
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from common.config import raw_uri
from common.db import query_df
from common.logging_setup import get_logger
from common.storage import open_storage

log = get_logger("close.propose_corrections")

SUSPENSE = "1999"


def propose(period: str, causes: list[str] | None) -> pd.DataFrame:
    breaks = query_df(
        """select je_date, period_id, plant_id, source_type, account, diff, root_cause
           from recon.recon_gl_daily
           where (period_id = %(p)s
                  or (root_cause in ('timing_cutoff', 'misposted_plant') and period_id >= %(p)s
                      and exists (select 1 from recon.recon_gl_daily x
                                  where x.period_id = %(p)s and x.root_cause = recon_gl_daily.root_cause
                                    and x.source_type = recon_gl_daily.source_type
                                    and abs(x.je_date - recon_gl_daily.je_date) <= 5)))
           order by je_date, plant_id, account""",
        {"p": period},
    )
    if causes:
        breaks = breaks[breaks["root_cause"].isin(causes)]
    return build_entries(breaks, period)


def build_entries(breaks: pd.DataFrame, period: str) -> pd.DataFrame:
    """Turn daily breaks into balanced correcting journal entries (pure function, unit tested).

    One entry per (date, period, source type, root cause): a plant reclass is a single
    entry with both plants' lines, so it balances without touching suspense.
    """
    if breaks.empty:
        return breaks
    # unique per proposal run: period + timestamp + random suffix (several periods can be posted in one second)
    stamp = f"{period.replace('-', '')}-{datetime.now(UTC):%Y%m%d%H%M%S}-{uuid.uuid4().hex[:6]}"
    keys = ["je_date", "period_id", "source_type", "root_cause"]
    lines = breaks.assign(amount=-breaks["diff"].astype(float))
    resid = lines.groupby(keys, as_index=False).agg(amount=("amount", "sum"), plant_id=("plant_id", "first"))
    resid = resid[resid["amount"].abs() >= 0.005].assign(account=SUSPENSE)
    resid["amount"] = -resid["amount"]
    lines = pd.concat([lines, resid], ignore_index=True)
    lines["je_id"] = [f"JC{stamp}-{g:03d}" for g in lines.groupby(keys, sort=True).ngroup()]
    lines = lines.sort_values(["je_id", "account", "plant_id"]).reset_index(drop=True)
    lines["je_line"] = lines.groupby("je_id").cumcount() + 1
    lines["debit"] = lines["amount"].clip(lower=0).round(2)
    lines["credit"] = (-lines["amount"]).clip(lower=0).round(2)
    lines["description"] = (
        "Correction: "
        + lines["root_cause"].str.replace("_", " ")
        + np.where(lines["account"] == SUSPENSE, " (suspense offset)", "")
    )
    lines["posted_at"] = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    cols = [
        "je_id",
        "je_line",
        "je_date",
        "period_id",
        "plant_id",
        "account",
        "debit",
        "credit",
        "source_type",
        "description",
        "posted_at",
    ]
    return lines[cols]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--period", required=True)
    ap.add_argument("--cause", action="append", help="only these root causes (repeatable)")
    ap.add_argument("--out", default="exports/corrections")
    ap.add_argument("--post", action="store_true", help="write the entries into the raw landing zone")
    args = ap.parse_args(argv)

    je = propose(args.period, args.cause)
    if je.empty:
        log.info("no breaks to correct", extra={"period": args.period})
        return 0
    from pathlib import Path

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    proposal = out / f"corrections_{args.period}.csv"
    je.to_csv(proposal, index=False)
    log.info(
        "correcting entries proposed",
        extra={
            "period": args.period,
            "file": str(proposal),
            "journal_entries": je["je_id"].nunique(),
            "lines": len(je),
            "debits": round(float(je["debit"].sum()), 2),
            "credits": round(float(je["credit"].sum()), 2),
        },
    )
    if args.post:
        storage = open_storage(raw_uri())
        post_date = datetime.now(UTC).strftime("%Y-%m-%d")
        key = f"gl_journal_entries/{post_date}/gl_journal_entries_corrections_{args.period}.csv"
        buf = io.StringIO()
        je.to_csv(buf, index=False)
        storage.write_bytes(key, buf.getvalue().encode())
        log.info("correcting entries posted to raw landing zone", extra={"key": key})
    return 0


if __name__ == "__main__":
    sys.exit(main())
