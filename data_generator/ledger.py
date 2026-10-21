"""Inventory observations (ERP snapshots, cycle counts) and the general ledger feed.

The GL is posted from *clean* transactions, the way an ERP would post it. The raw
extracts the pipeline ingests are noisier (duplicates, unit mix-ups, junk rows),
so the reconciliations only tie if the pipeline cleans the data correctly, plus a
handful of deliberately injected GL breaks that the reconciliations must catch.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from common.fiscal_calendar import Period, accounting_period_vec
from data_generator.money import ext_cents, hours_cents
from data_generator.transactions import _round_uom


def inventory_observations(rng, opening, receipts, issues, cal: pd.DataFrame, end: date):
    """Month-end ERP stock snapshots and periodic physical cycle counts."""

    def _flow(df: pd.DataFrame, date_col: str, qty: pd.Series) -> pd.DataFrame:
        # explicit ns datetimes: pandas 2.1 can't concat mixed datetime resolutions
        return pd.DataFrame(
            {
                "plant_id": df["plant_id"].to_numpy(),
                "material_id": df["material_id"].to_numpy(),
                "d": pd.to_datetime(df[date_col]).astype("datetime64[ns]").to_numpy(),
                "q": qty.to_numpy(),
            }
        )

    flows = pd.concat(
        [
            _flow(opening, "as_of_date", opening["qty"]),
            _flow(receipts, "receipt_date", receipts["receipt_qty"]),
            _flow(issues, "issue_date", -issues["issue_qty"]),
        ],
        ignore_index=True,
    )
    flows["period_id"] = pd.to_datetime(flows["d"]).dt.strftime("%Y-%m")
    periods = cal[pd.to_datetime(cal["period_end"]) <= pd.Timestamp(end)]
    by_p = flows.groupby(["plant_id", "material_id", "period_id"])["q"].sum().unstack(fill_value=0.0)
    by_p = by_p.reindex(columns=periods["period_id"], fill_value=0.0).cumsum(axis=1)
    snap = by_p.stack().rename("system_qty").reset_index()
    snap = snap.merge(periods[["period_id", "period_end"]], on="period_id")
    uom = issues.drop_duplicates("material_id").set_index("material_id")["uom"]
    snap["uom"] = snap["material_id"].map(uom).fillna("EA")
    snap["system_qty"] = np.round(snap["system_qty"], 3)
    snap = snap.rename(columns={"period_end": "snapshot_date"})

    counts = snap[rng.random(len(snap)) < 0.15].copy()
    r = rng.random(len(counts))
    factor = np.where(
        r < 0.85, 1.0, np.where(r < 0.97, rng.uniform(0.96, 0.995, len(counts)), rng.uniform(1.005, 1.03, len(counts)))
    )
    counts["counted_qty"] = _round_uom(np.maximum(counts["system_qty"].to_numpy(), 0) * factor, counts["uom"])
    counts["count_date"] = [_last_business_day(pd.Timestamp(d).date()) for d in counts["snapshot_date"]]
    counts["count_id"] = np.arange(95_000_001, 95_000_001 + len(counts))
    counts["counted_by"] = rng.choice(["CC-TEAM-A", "CC-TEAM-B", "CC-TEAM-C"], len(counts))
    cycle_counts = counts[["count_id", "plant_id", "material_id", "count_date", "counted_qty", "uom", "counted_by"]]
    snapshots = snap[["plant_id", "material_id", "snapshot_date", "system_qty", "uom"]].reset_index(drop=True)
    return snapshots, cycle_counts


def _last_business_day(d: date) -> date:
    from common.fiscal_calendar import is_business_day

    while not is_business_day(d):
        d -= timedelta(days=1)
    return d


def _postings(
    frame: pd.DataFrame,
    source: str,
    dr: str,
    cr: str,
    cents: np.ndarray,
    tx_col: str,
    post_col: str,
    order_col: str | None = None,
) -> pd.DataFrame:
    base = pd.DataFrame(
        {
            "tx_date": pd.to_datetime(frame[tx_col]).astype("datetime64[ns]").to_numpy(),
            "posting_date": pd.to_datetime(frame[post_col]).astype("datetime64[ns]").to_numpy(),
            "plant_id": frame["plant_id"].to_numpy(),
            "source_type": source,
            "order_id": frame[order_col].to_numpy() if order_col else -1,
        }
    )
    a = base.assign(account=dr, cents=cents)
    b = base.assign(account=cr, cents=-cents)
    return pd.concat([a, b], ignore_index=True)


def build_gl(
    rng,
    master,
    cal,
    start: date,
    end: date,
    opening,
    rec_gl,
    inv_gl,
    issues,
    labor,
    scrap,
    orders,
    shipments,
    months: int,
):
    mats = master["_materials_full"].set_index("material_id")
    lines = master["_lines_full"].set_index("line_id")
    std = master["standard_costs"]
    unit_cost = std[
        (std["item_type"] == "PRODUCT") & (std["cost_component"] == "UNIT_COST") & (std["version"] == f"FY{start.year}")
    ].set_index("item_id")["std_value"]

    parts = []
    c = ext_cents(opening["qty"], opening["material_id"].map(mats["std_price"]))
    parts.append(_postings(opening, "OPENING", "1300", "3900", c, "as_of_date", "as_of_date"))

    std_c = ext_cents(rec_gl["receipt_qty"], rec_gl["material_id"].map(mats["std_price"]))
    grni_c = ext_cents(rec_gl["receipt_qty"], rec_gl["po_price"])
    parts.append(_postings(rec_gl, "RECEIPT", "1300", "2110", std_c, "receipt_date", "receipt_date"))
    parts.append(_postings(rec_gl, "RECEIPT", "5100", "2110", grni_c - std_c, "receipt_date", "receipt_date"))

    clear_c = ext_cents(inv_gl["invoice_qty"], inv_gl["po_price"])
    ap_c = ext_cents(inv_gl["invoice_qty"], inv_gl["invoice_price"])
    parts.append(_postings(inv_gl, "INVOICE", "2110", "2100", clear_c, "invoice_date", "invoice_date"))
    parts.append(_postings(inv_gl, "INVOICE", "5100", "2100", ap_c - clear_c, "invoice_date", "invoice_date"))

    c = ext_cents(issues["issue_qty"], issues["material_id"].map(mats["std_price"]))
    parts.append(_postings(issues, "ISSUE", "1400", "1300", c, "issue_date", "issue_date", "order_id"))

    c = hours_cents(labor["hours"], labor["hourly_rate"])
    parts.append(_postings(labor, "LABOR", "1400", "2200", c, "work_date", "posting_date", "order_id"))
    c = hours_cents(labor["hours"], labor["line_id"].map(lines["overhead_rate"]))
    parts.append(_postings(labor, "OVERHEAD", "1400", "5900", c, "work_date", "posting_date", "order_id"))

    c = ext_cents(scrap["scrap_qty"], scrap["material_id"].map(mats["std_price"]))
    parts.append(_postings(scrap, "SCRAP", "5300", "1400", c, "scrap_date", "scrap_date", "order_id"))

    done = orders[orders["is_completed"]].assign(end_date=lambda x: x["actual_end"].dt.normalize())
    c = ext_cents(done["completed_qty"], done["product_id"].map(unit_cost))
    parts.append(_postings(done, "COMPLETION", "1500", "1400", c, "end_date", "end_date", "order_id"))

    c = ext_cents(shipments["ship_qty"], shipments["product_id"].map(unit_cost))
    parts.append(_postings(shipments, "SHIPMENT", "5000", "1500", c, "ship_date", "ship_date"))

    post = pd.concat(parts, ignore_index=True)
    post["period_id"] = accounting_period_vec(post["tx_date"], post["posting_date"], cal).to_numpy()

    settle = _settlements(post, orders, cal)
    post = pd.concat([post, settle], ignore_index=True)

    gl = (
        post.groupby(["posting_date", "period_id", "plant_id", "source_type", "account"], as_index=False)["cents"]
        .sum()
        .rename(columns={"posting_date": "je_date"})
    )
    gl = gl[gl["cents"] != 0]
    gl, key = _inject_gl_breaks(rng, gl, cal, start, months)
    return _format_gl(gl), key


def _settlements(post: pd.DataFrame, orders: pd.DataFrame, cal: pd.DataFrame) -> pd.DataFrame:
    """Period-end settlement of completed orders' residual WIP to manufacturing variance.

    For each completed order: in the first accounting period at or after its completion
    period, the whole accumulated WIP balance is settled; in any later period (late
    labor postings) that period's activity is settled. Open orders are never settled.
    """
    wip = post[(post["account"] == "1400") & (post["order_id"] >= 0)]
    act = wip.groupby(["order_id", "period_id"], as_index=False)["cents"].sum()
    done = orders[orders["is_completed"]][["order_id", "plant_id", "actual_end"]].copy()
    done["completion_period"] = done["actual_end"].dt.strftime("%Y-%m")
    act = act.merge(done, on="order_id")
    act = act.sort_values(["order_id", "period_id"])
    act["cum"] = act.groupby("order_id")["cents"].cumsum()
    after = act["period_id"] >= act["completion_period"]
    prev_period = act.groupby("order_id")["period_id"].shift().fillna("")
    first_after = after & ~(prev_period >= act["completion_period"])
    act["settle"] = np.where(first_after, act["cum"], np.where(after, act["cents"], 0))
    s = act[act["settle"] != 0]
    period_end = dict(zip(cal["period_id"], pd.to_datetime(cal["period_end"]).astype("datetime64[ns]"), strict=True))
    base = pd.DataFrame(
        {
            "tx_date": s["period_id"].map(period_end).to_numpy(),
            "posting_date": s["period_id"].map(period_end).to_numpy(),
            "plant_id": s["plant_id"].to_numpy(),
            "source_type": "SETTLEMENT",
            "order_id": s["order_id"].to_numpy(),
            "period_id": s["period_id"].to_numpy(),
        }
    )
    return pd.concat(
        [
            base.assign(account="5200", cents=s["settle"].to_numpy()),
            base.assign(account="1400", cents=-s["settle"].to_numpy()),
        ],
        ignore_index=True,
    )


def _inject_gl_breaks(rng, gl: pd.DataFrame, cal, start: date, months: int):
    """Inject four realistic GL problems. Returns (gl, answer_key)."""
    pids = [p for p in cal["period_id"]][:months]
    key: list[dict] = []

    def pick_day(period: str, plant: str, source: str) -> pd.Timestamp | None:
        cand = gl[(gl["period_id"] == period) & (gl["plant_id"] == plant) & (gl["source_type"] == source)]
        days = sorted(cand["je_date"].unique())
        return pd.Timestamp(days[int(rng.integers(0, len(days)))]) if days else None

    def amount(rows: pd.DataFrame, account: str) -> float:
        return float(rows.loc[rows["account"] == account, "cents"].sum()) / 100

    # 1) missing posting: one day's ISSUE batch for FRE1 never reached the GL
    p = pids[min(2, months - 1)]
    d = pick_day(p, "FRE1", "ISSUE")
    m = (gl["je_date"] == d) & (gl["plant_id"] == "FRE1") & (gl["source_type"] == "ISSUE")
    key.append(
        {
            "type": "missing_posting",
            "period_id": p,
            "plant_id": "FRE1",
            "source_type": "ISSUE",
            "je_date": str(d.date()),
            "amount_1400": amount(gl[m], "1400"),
        }
    )
    gl = gl[~m]

    # 2) duplicate posting: one RECEIPT batch at AUS1 posted twice
    p = pids[min(4, months - 1)]
    d = pick_day(p, "AUS1", "RECEIPT")
    m = (gl["je_date"] == d) & (gl["plant_id"] == "AUS1") & (gl["source_type"] == "RECEIPT")
    dup = gl[m].copy()
    dup["_dup"] = True
    key.append(
        {
            "type": "duplicate_posting",
            "period_id": p,
            "plant_id": "AUS1",
            "source_type": "RECEIPT",
            "je_date": str(d.date()),
            "amount_1300": amount(dup, "1300"),
        }
    )
    gl = pd.concat([gl, dup], ignore_index=True)

    # 3) misposted plant: one day of AUS1 LABOR booked to RNO1
    p = pids[min(7, months - 1)]
    d = pick_day(p, "AUS1", "LABOR")
    m = (gl["je_date"] == d) & (gl["plant_id"] == "AUS1") & (gl["source_type"] == "LABOR")
    key.append(
        {
            "type": "misposted_plant",
            "period_id": p,
            "from_plant": "AUS1",
            "to_plant": "RNO1",
            "source_type": "LABOR",
            "je_date": str(d.date()),
            "amount_1400": amount(gl[m], "1400"),
        }
    )
    gl.loc[m, "plant_id"] = "RNO1"

    # 4) timing: last SHIPMENT batch of a month at RNO1 posted on day 1 of the next period
    if months >= 2:
        idx = min(9, months - 2)
        p, nxt = pids[idx], pids[idx + 1]
        cand = gl[(gl["period_id"] == p) & (gl["plant_id"] == "RNO1") & (gl["source_type"] == "SHIPMENT")]
        d = pd.Timestamp(cand["je_date"].max())
        m = (gl["je_date"] == d) & (gl["plant_id"] == "RNO1") & (gl["source_type"] == "SHIPMENT")
        key.append(
            {
                "type": "timing",
                "period_id": p,
                "reverses_in": nxt,
                "plant_id": "RNO1",
                "source_type": "SHIPMENT",
                "je_date": str(d.date()),
                "amount_1500": amount(gl[m], "1500"),
            }
        )
        gl.loc[m, "je_date"] = pd.Timestamp(Period.of(d.date()).end + timedelta(days=1))
        gl.loc[m, "period_id"] = nxt
    return gl, key


def _format_gl(gl: pd.DataFrame) -> pd.DataFrame:
    gl = gl.sort_values(["je_date", "plant_id", "source_type", "account"]).reset_index(drop=True)
    gl["_dup"] = gl.get("_dup", pd.Series(False, index=gl.index)).fillna(False).astype(bool)
    hdr = gl[["je_date", "plant_id", "source_type", "_dup"]].drop_duplicates().reset_index(drop=True)
    hdr["je_id"] = [f"JE{10_000_000 + i}" for i in range(len(hdr))]
    gl = gl.merge(hdr, on=["je_date", "plant_id", "source_type", "_dup"])
    gl["je_line"] = gl.groupby("je_id").cumcount() + 1
    gl["debit"] = np.where(gl["cents"] > 0, gl["cents"], 0) / 100
    gl["credit"] = np.where(gl["cents"] < 0, -gl["cents"], 0) / 100
    gl["description"] = gl["source_type"].str.title() + " summary " + gl["plant_id"]
    gl["posted_at"] = pd.to_datetime(gl["je_date"]) + pd.Timedelta(hours=23)
    return gl[
        [
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
    ]
