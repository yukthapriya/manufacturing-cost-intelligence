"""Operational transactions: production orders, material issues, labor, scrap, shipments, purchasing."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from common.fiscal_calendar import is_production_day
from data_generator.master_data import (
    METAL_CATEGORIES,
    OVERUSE_LINE,
    SCRAP_SPIKE_LINE,
    SPIKE_SUPPLIER,
    UOM_DECIMALS,
)

SCRAP_REASONS = ["DIM_OUT_OF_SPEC", "DAMAGED_HANDLING", "MACHINE_FAULT", "OPERATOR_ERROR", "MATERIAL_DEFECT"]


def _round_uom(qty: np.ndarray, uom: pd.Series) -> np.ndarray:
    dec = uom.map(UOM_DECIMALS).to_numpy()
    out = np.where(dec == 0, np.rint(qty), np.where(dec == 2, np.round(qty, 2), np.round(qty, 3)))
    return np.maximum(out, 0)


def month_index(dates: pd.Series, start: date) -> np.ndarray:
    d = pd.to_datetime(dates)
    return ((d.dt.year - start.year) * 12 + d.dt.month - start.month).to_numpy()


def build_orders(rng, master, start: date, end: date, scale: float) -> pd.DataFrame:
    products = master["_products_full"]
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    prod_days = [d for d in days if is_production_day(d)]
    line_products = products.groupby("line_id")["product_id"].apply(list).to_dict()

    rows_line, rows_day = [], []
    for line_id in sorted(line_products):
        counts = rng.poisson(5 * scale, len(prod_days))
        for d, c in zip(prod_days, counts, strict=True):
            rows_line.extend([line_id] * int(c))
            rows_day.extend([d] * int(c))
    n = len(rows_line)
    o = pd.DataFrame({"line_id": rows_line, "day": pd.to_datetime(rows_day)})
    o["product_id"] = [
        line_products[ln][k % len(line_products[ln])]
        for ln, k in zip(o["line_id"], rng.integers(0, 1000, n), strict=True)
    ]
    p = products.set_index("product_id")
    lo = o["product_id"].map(p["lot_min"]).to_numpy()
    hi = o["product_id"].map(p["lot_max"]).to_numpy()
    o["planned_qty"] = rng.integers(lo, hi)
    o["actual_start"] = o["day"] + pd.to_timedelta(rng.uniform(6, 18, n), unit="h")
    duration_h = rng.uniform(6, 40, n)
    o["actual_end"] = o["actual_start"] + pd.to_timedelta(duration_h, unit="h")
    o["duration_h"] = duration_h
    o["actual_start"] = o["actual_start"].dt.floor("min")
    o["actual_end"] = o["actual_end"].dt.floor("min")

    completed = np.floor(o["planned_qty"] * rng.uniform(0.93, 1.0, n))
    over = rng.random(n) < 0.03
    completed = np.where(over, np.ceil(o["planned_qty"] * rng.uniform(1.0, 1.05, n)), completed)
    window_end = pd.Timestamp(end) + pd.Timedelta(days=1)
    o["is_completed"] = o["actual_end"] < window_end
    o["completed_qty"] = np.where(o["is_completed"], completed, np.nan)
    o["plant_id"] = o["line_id"].str[:4]
    o = o.sort_values(["actual_start", "line_id"]).reset_index(drop=True)
    o["order_id"] = np.arange(1_000_001, 1_000_001 + len(o))
    return o


def build_issues_and_scrap(rng, master, orders: pd.DataFrame, start: date, end: date):
    ex = master["_exploded"]
    mats = master["_materials_full"].set_index("material_id")
    bom_allow = (ex["std_qty_incl_scrap"] / ex["qty_per"] - 1).rename("allowance")
    ex = ex.assign(allowance=bom_allow)

    o = orders[["order_id", "product_id", "line_id", "plant_id", "actual_start", "actual_end", "planned_qty"]].copy()
    # kitting basis: completed qty for finished orders, ~97% of plan for orders still running
    o["basis"] = orders["completed_qty"].fillna(np.floor(orders["planned_qty"] * 0.97))
    iss = o.merge(ex, on="product_id")
    n = len(iss)
    iss["uom"] = iss["material_id"].map(mats["base_uom"])
    base = iss["qty_per"].to_numpy() * iss["basis"].to_numpy()

    factor = rng.normal(1.0, 0.012, n)
    factor += np.where(iss["line_id"].to_numpy() == OVERUSE_LINE, 0.06, 0.0)
    good = _round_uom(base * factor, iss["uom"])

    mi = month_index(iss["actual_start"], start)
    spike = (iss["line_id"].to_numpy() == SCRAP_SPIKE_LINE) & np.isin(mi, [3, 4])
    scrap_mult = rng.lognormal(np.log(1.1), 0.25, n) * np.where(spike, 3.0, 1.0)
    expected = base * iss["allowance"].to_numpy() * scrap_mult
    # scrap is lumpy: ~20% of issue lines see a scrap event, sized so the expected total
    # stays at allowance x multiplier
    p_event = 0.2
    event = rng.random(n) < p_event
    lam = np.where(event, expected / p_event, 0.0)
    is_ea = iss["uom"].to_numpy() == "EA"
    scrap = np.where(is_ea, rng.poisson(np.where(is_ea, lam, 0)), lam * rng.lognormal(-0.06, 0.35, n))
    scrap = _round_uom(scrap, iss["uom"])
    iss["issue_qty"] = _round_uom(good + scrap, iss["uom"])
    iss["scrap_qty"] = np.minimum(scrap, iss["issue_qty"])
    iss = iss[iss["issue_qty"] > 0].reset_index(drop=True)
    iss["issue_date"] = iss["actual_start"].dt.normalize()
    iss["issue_id"] = np.arange(50_000_001, 50_000_001 + len(iss))

    # scrap records: one per issue line with scrap, dated inside the order window
    sc = iss[iss["scrap_qty"] > 0].copy()
    frac = rng.uniform(0, 1, len(sc))
    sc["scrap_ts"] = sc["actual_start"] + (sc["actual_end"] - sc["actual_start"]) * frac
    sc["scrap_date"] = sc["scrap_ts"].dt.normalize()
    sc = sc[sc["scrap_date"] <= pd.Timestamp(end)]
    sc_mi = month_index(sc["scrap_date"], start)
    sc_spike = (sc["line_id"].to_numpy() == SCRAP_SPIKE_LINE) & np.isin(sc_mi, [3, 4])
    normal_reason = rng.choice(SCRAP_REASONS, len(sc), p=[0.32, 0.22, 0.14, 0.18, 0.14])
    sc["reason_code"] = np.where(sc_spike & (rng.random(len(sc)) < 0.75), "MACHINE_FAULT", normal_reason)
    sc = sc.reset_index(drop=True)
    sc["scrap_id"] = np.arange(70_000_001, 70_000_001 + len(sc))
    scrap = sc[
        ["scrap_id", "order_id", "material_id", "scrap_qty", "uom", "reason_code", "scrap_date", "plant_id", "line_id"]
    ]

    issues = iss[["issue_id", "order_id", "material_id", "issue_qty", "uom", "issue_date", "plant_id", "line_id"]]
    return issues, scrap


def build_labor(rng, master, orders: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    p = master["_products_full"].set_index("product_id")
    lines = master["_lines_full"].set_index("line_id")
    o = orders.copy()
    o["basis"] = o["completed_qty"].fillna(np.floor(o["planned_qty"] * 0.97))
    std_h = o["product_id"].map(p["std_labor_hours"]).to_numpy()
    eff = rng.normal(1.03, 0.06, len(o))
    total_h = std_h * o["basis"].to_numpy() * eff
    # one time booking per employee shift: ~8h each, never more than 12h
    n_ent = np.maximum(1, np.ceil(total_h / 8)).astype(int)

    rep = np.repeat(np.arange(len(o)), n_ent)
    lab = o.iloc[rep][["order_id", "line_id", "plant_id", "actual_start", "actual_end"]].reset_index(drop=True)
    per_entry = total_h[rep] / n_ent[rep]
    lab["hours"] = np.clip(np.round(per_entry * rng.uniform(0.85, 1.15, len(lab)), 2), 0.25, 12.0)
    k = pd.Series(rep).groupby(rep).cumcount().to_numpy()
    span = (lab["actual_end"] - lab["actual_start"]).to_numpy()
    lab["work_date"] = (lab["actual_start"] + span * (k / n_ent[rep])).dt.normalize()

    rate = lab["line_id"].map(lines["std_labor_rate"]).to_numpy() * rng.normal(1.0, 0.025, len(lab))
    mi = month_index(lab["work_date"], start)
    ot_prob = np.where(np.isin(mi, [8, 9]), 0.25, 0.10)  # overtime push in Sep/Oct
    lab["overtime_flag"] = rng.random(len(lab)) < ot_prob
    lab["hourly_rate"] = np.round(np.where(lab["overtime_flag"], rate * 1.5, rate), 2)

    late = rng.random(len(lab)) < 0.03
    lag = np.where(late, rng.integers(5, 21, len(lab)), np.where(rng.random(len(lab)) < 0.2, 1, 0))
    lab["posting_date"] = lab["work_date"] + pd.to_timedelta(lag, unit="D")
    lab = lab[lab["work_date"] <= pd.Timestamp(end)].reset_index(drop=True)
    plant_base = {"AUS1": 10000, "FRE1": 20000, "RNO1": 30000}
    lab["employee_id"] = [
        f"E{plant_base[pl] + int(x)}" for pl, x in zip(lab["plant_id"], rng.integers(0, 400, len(lab)), strict=True)
    ]
    lab["labor_entry_id"] = np.arange(80_000_001, 80_000_001 + len(lab))
    return lab[
        [
            "labor_entry_id",
            "order_id",
            "employee_id",
            "work_date",
            "posting_date",
            "hours",
            "hourly_rate",
            "overtime_flag",
            "plant_id",
            "line_id",
        ]
    ]


def build_shipments(rng, orders: pd.DataFrame, end: date) -> pd.DataFrame:
    c = orders[orders["is_completed"]].copy()
    c["ship_date"] = c["actual_end"].dt.normalize() + pd.to_timedelta(rng.integers(1, 8, len(c)), unit="D")
    c = c[c["ship_date"] <= pd.Timestamp(end)].reset_index(drop=True)
    c["shipment_id"] = np.arange(90_000_001, 90_000_001 + len(c))
    c["ship_qty"] = c["completed_qty"].astype(int)
    return c[["shipment_id", "order_id", "product_id", "plant_id", "ship_qty", "ship_date"]]


def build_purchasing(rng, master, issues: pd.DataFrame, start: date, end: date, months: int):
    """Opening stock, purchase orders, goods receipts and supplier invoices.

    Purchases are planned from actual consumption so inventory stays positive.
    Returns clean frames plus an 'answer key' of injected problems.
    """
    mats = master["_materials_full"].set_index("material_id")
    iss = issues.assign(m=month_index(issues["issue_date"], start))
    cons = iss.groupby(["plant_id", "material_id", "m"], as_index=False)["issue_qty"].sum()

    first = cons[cons["m"] == 0].set_index(["plant_id", "material_id"])["issue_qty"]
    keys = cons[["plant_id", "material_id"]].drop_duplicates()
    opening = keys.copy()
    opening["qty"] = keys.set_index(["plant_id", "material_id"]).index.map(first).fillna(0).to_numpy()
    opening["qty"] = opening["qty"] * rng.uniform(0.9, 1.3, len(opening))
    opening["uom"] = opening["material_id"].map(mats["base_uom"])
    opening["qty"] = _round_uom(opening["qty"].to_numpy(), opening["uom"])
    opening["as_of_date"] = pd.Timestamp(start)

    # one or more PO lines per plant/material/month
    cons["target"] = cons["issue_qty"] * rng.uniform(1.0, 1.06, len(cons))
    cons["n_lines"] = rng.integers(1, 4, len(cons))
    rep = np.repeat(np.arange(len(cons)), cons["n_lines"].to_numpy())
    po = cons.iloc[rep].reset_index(drop=True)
    po["uom"] = po["material_id"].map(mats["base_uom"])
    po["po_qty"] = _round_uom((po["target"] / po["n_lines"]).to_numpy(), po["uom"])
    po = po[po["po_qty"] > 0].reset_index(drop=True)
    month_start = pd.to_datetime([_add_months(start, int(m)) for m in po["m"]])
    days_in_month = month_start.days_in_month.to_numpy()
    recv_day = rng.integers(0, np.minimum(20, days_in_month))
    po["receipt_date"] = month_start + pd.to_timedelta(recv_day, unit="D")
    po["lead"] = po["material_id"].map(mats["lead_time_days"]).to_numpy()
    po["order_date"] = po["receipt_date"] - pd.to_timedelta(po["lead"], unit="D")
    po["supplier_id"] = po["material_id"].map(mats["primary_supplier_id"])
    po["category"] = po["material_id"].map(mats["category"])
    std = po["material_id"].map(mats["std_price"]).to_numpy()
    drift = np.where(po["category"].isin(METAL_CATEGORIES), 1 + 0.004 * po["m"].to_numpy(), 1.0)
    po["po_price"] = np.round(std * drift * rng.normal(1.0, 0.02, len(po)), 4)

    # PO numbers: one PO per supplier/plant/order_date, lines numbered within it
    po = po.sort_values(["order_date", "supplier_id", "plant_id"]).reset_index(drop=True)
    hdr = po[["order_date", "supplier_id", "plant_id"]].drop_duplicates().reset_index(drop=True)
    hdr["po_id"] = [f"PO{4500000 + i}" for i in range(len(hdr))]
    po = po.merge(hdr, on=["order_date", "supplier_id", "plant_id"])
    po["po_line"] = po.groupby("po_id").cumcount() + 1

    n = len(po)
    short = rng.random(n) < 0.015
    no_receipt = (~short) & (rng.random(n) < 0.005)
    po["receipt_qty"] = np.where(
        short, _round_uom(po["po_qty"].to_numpy() * rng.uniform(0.85, 0.95, n), po["uom"]), po["po_qty"]
    )
    receipts = po[~no_receipt & (po["receipt_date"] <= pd.Timestamp(end))].copy()
    receipts["gr_id"] = [f"GR{5000000 + i}" for i in range(len(receipts))]

    # invoices: invoice for the ordered qty, a few days after receipt
    inv = po[po["receipt_date"] <= pd.Timestamp(end)].copy()
    inv["invoice_date"] = inv["receipt_date"] + pd.to_timedelta(rng.integers(0, 7, len(inv)), unit="D")
    inv = inv[inv["invoice_date"] <= pd.Timestamp(end)].reset_index(drop=True)
    m_inv = month_index(inv["invoice_date"], start)
    spike = (inv["supplier_id"] == SPIKE_SUPPLIER).to_numpy() & (m_inv >= months // 2)
    other_exc = rng.random(len(inv)) < 0.01
    price_factor = rng.normal(1.0, 0.004, len(inv)) * np.where(spike, 1.18, 1.0) * np.where(other_exc, 1.07, 1.0)
    inv["invoice_price"] = np.round(inv["po_price"].to_numpy() * price_factor, 4)
    inv["invoice_qty"] = inv["po_qty"]
    inv_hdr = inv[["po_id", "invoice_date"]].drop_duplicates().reset_index(drop=True)
    inv_hdr["invoice_id"] = np.arange(6_000_001, 6_000_001 + len(inv_hdr))
    inv = inv.merge(inv_hdr, on=["po_id", "invoice_date"])
    inv["invoice_line"] = inv.groupby("invoice_id").cumcount() + 1
    inv["invoice_number"] = inv["supplier_id"] + "-" + inv["invoice_id"].astype(str).str[-6:]

    po_lines = po[
        ["po_id", "po_line", "supplier_id", "plant_id", "order_date", "material_id", "po_qty", "uom", "po_price"]
    ].rename(columns={"po_price": "unit_price"})
    gr = receipts[["gr_id", "po_id", "po_line", "material_id", "plant_id", "receipt_qty", "uom", "receipt_date"]]
    invoices = inv[
        [
            "invoice_id",
            "invoice_line",
            "invoice_number",
            "supplier_id",
            "plant_id",
            "po_id",
            "po_line",
            "material_id",
            "invoice_qty",
            "uom",
            "invoice_price",
            "invoice_date",
        ]
    ]
    # po_price kept alongside for GL posting (GRNI clears at PO price)
    inv_for_gl = inv[
        ["invoice_id", "invoice_line", "plant_id", "invoice_date", "invoice_qty", "invoice_price", "po_price"]
    ]
    rec_for_gl = receipts[["gr_id", "plant_id", "material_id", "receipt_qty", "receipt_date", "po_price"]]
    return opening, po_lines, gr, invoices, inv_for_gl, rec_for_gl


def _add_months(d: date, m: int) -> date:
    y, mm = d.year + (d.month - 1 + m) // 12, (d.month - 1 + m) % 12 + 1
    return date(y, mm, 1)
