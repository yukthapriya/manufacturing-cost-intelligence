"""Build a self-contained, plain-English cost report (one HTML file, no server needed).

    python -m exporter.static_report --out docs/index.html

Every chart has a headline that says what it shows and why it matters, written from the
data so the text stays true when the data changes. Publish docs/ with GitHub Pages and
the report has a public link anyone can open.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from close.propose_corrections import propose
from common.db import query_df
from common.logging_setup import get_logger

log = get_logger("exporter.static_report")

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
ELEMENT_LABELS = {
    "material_usage": "Material usage",
    "scrap": "Scrap above allowance",
    "material_price": "Material price",
    "labor_rate": "Labor rate",
    "overhead_efficiency": "Overhead",
    "labor_efficiency": "Labor efficiency",
}
ELEMENT_MEANING = {
    "material_usage": "used more material per unit than the bill of materials allows",
    "scrap": "scrapped more than the planned scrap allowance",
    "material_price": "paid suppliers more than the standard price",
    "labor_rate": "paid a higher hourly rate (mostly overtime)",
    "overhead_efficiency": "overhead charged on the extra hours",
    "labor_efficiency": "took more hours than standard",
}
CAUSE_LABELS = {
    "missing_gl_posting": ("Missing posting", "A day of material issues never reached the ledger."),
    "duplicate_gl_posting": ("Duplicate posting", "A day of goods receipts was posted to the ledger twice."),
    "misposted_plant": ("Wrong plant", "Labor cost was booked to another plant."),
    "timing_cutoff": ("Cutoff timing", "Shipments from the last day of the month landed in the next month."),
    "gl_without_subledger": ("Unsupported entry", "A ledger entry with no transactions behind it."),
    "unexplained": ("Unexplained", "No known pattern."),
}
MATCH_LABELS = {
    "missing_po_reference": "Invoice has no PO number",
    "invoice_missing_po_reference": "Receipt waiting on an invoice that has no PO number",
    "duplicate_invoice": "Supplier sent the same invoice twice",
    "no_receipt": "Invoiced but never received",
    "price_variance": "Invoice price more than 5% off the PO",
    "qty_mismatch": "Invoiced quantity differs from received",
    "receipt_not_invoiced": "Received but not invoiced after 30 days",
}


def _month(period: str) -> str:
    return MONTHS[int(period[5:7]) - 1]


def _f(x) -> float:
    return float(x) if x is not None else 0.0


def collect() -> dict:
    lines = query_df("select line_id, line_name, plant_id from marts.dim_line order by line_id")
    plants = dict(query_df("select plant_id, plant_name from marts.dim_plant").values.tolist())
    line_label = {r.line_id: f"{plants[r.plant_id].split()[0]} line {r.line_id[-1]}" for r in lines.itertuples()}

    k = query_df(
        """select sum(total_std_cost) std, sum(total_actual_cost) act, sum(total_variance) var,
                  count(*) orders, sum(completed_qty) units, min(period_id) p0, max(period_id) p1
           from marts.fct_production_cost where is_completed"""
    ).iloc[0]

    el = query_df("select cost_element, sum(variance_amount) amt from marts.fct_cost_variance group by 1")
    elements = sorted(
        [
            {
                "key": r.cost_element,
                "label": ELEMENT_LABELS[r.cost_element],
                "meaning": ELEMENT_MEANING[r.cost_element],
                "amount": _f(r.amt),
            }
            for r in el.itertuples()
        ],
        key=lambda e: -e["amount"],
    )

    lm = query_df(
        """with o as (select line_id, period_id, sum(variance_amount) v, sum(std_cost) s
                      from marts.fct_cost_variance where cost_element = 'material_usage' group by 1, 2)
           select line_id, period_id, v, s, v / nullif(s, 0) pct from o order by 1, 2"""
    )
    for c in ("v", "s", "pct"):
        lm[c] = lm[c].astype(float)
    heat = [
        {"line": line_label[r.line_id], "month": _month(r.period_id), "pct": r.pct, "amount": r.v}
        for r in lm.itertuples()
    ]
    by_line = lm.groupby("line_id").agg(
        v=("v", "sum"), s=("s", "sum"), months_over=("pct", lambda x: int((x > 0.01).sum()))
    )
    top = by_line["v"].idxmax()
    usage_line = {
        "line": line_label[top],
        "amount": float(by_line.loc[top, "v"]),
        "pct": float(by_line.loc[top, "v"] / by_line.loc[top, "s"]),
        "months_over": int(by_line.loc[top, "months_over"]),
        "others_amount": float(by_line.drop(top)["v"].sum()),
    }

    sp = query_df(
        """select f.supplier_id, s.supplier_name, f.period_id,
                  sum(invoice_qty * invoice_price) / sum(invoice_qty * std_price) * 100 idx, sum(ppv_vs_std) ppv
           from marts.fct_purchase_price f join marts.dim_supplier s using (supplier_id)
           group by 1, 2, 3 order by 1, 3"""
    )
    sp["jump"] = sp.groupby("supplier_id")["idx"].diff()
    worst = sp.loc[sp["jump"].astype(float).idxmax()]
    sup_id = worst.supplier_id
    after = sp[(sp.supplier_id == sup_id) & (sp.period_id >= worst.period_id)]
    supplier = {
        "id": sup_id,
        "name": worst.supplier_name,
        "month": _month(worst.period_id),
        "before": float(sp[(sp.supplier_id == sup_id) & (sp.period_id < worst.period_id)]["idx"].astype(float).mean()),
        "after": float(after["idx"].astype(float).mean()),
        "extra_cost": float(after["ppv"].astype(float).sum()),
        "series": [
            {"supplier": r.supplier_id, "name": r.supplier_name, "month": _month(r.period_id), "index": _f(r.idx)}
            for r in sp.itertuples()
        ],
    }

    sc = query_df("select distinct line_id, period_id, line_scrap_rate r from marts.fct_scrap order by 1, 2")
    sc["r"] = sc["r"].astype(float)
    peak = sc.loc[sc["r"].idxmax()]
    normal = float(sc[sc.line_id != peak.line_id]["r"].mean())
    spike_months = sc[(sc.line_id == peak.line_id) & (sc.r > 2 * normal)]["period_id"].tolist()
    reason = query_df(
        """select reason_code, sum(scrap_value) v from marts.fct_scrap
           where line_id = %s and period_id = any(%s) group by 1 order by 2 desc""",
        (peak.line_id, spike_months),
    )
    scrap = {
        "line": line_label[peak.line_id],
        "peak": float(peak.r),
        "normal": normal,
        "months": [_month(p) for p in spike_months],
        "reason": reason.iloc[0].reason_code.replace("_", " ").lower(),
        "reason_share": float(reason.iloc[0].v / reason["v"].sum()),
        "series": [{"line": line_label[r.line_id], "month": _month(r.period_id), "rate": r.r} for r in sc.itertuples()],
        "highlight": line_label[peak.line_id],
    }

    gd = query_df(
        """select root_cause, min(je_date)::text d0, max(je_date)::text d1, min(period_id) period,
                  string_agg(distinct plant_id, ', ') plants, string_agg(distinct source_type, ', ') src,
                  max(abs(diff)) amt
           from recon.recon_gl_daily group by root_cause order by min(je_date)"""
    )
    plant_short = {p: n.split()[0] for p, n in plants.items()}
    breaks = [
        {
            "cause": CAUSE_LABELS[r.root_cause][0],
            "what": CAUSE_LABELS[r.root_cause][1],
            "month": _month(r.period),
            "period": r.period,
            "plants": ", ".join(plant_short[p.strip()] for p in r.plants.split(",")),
            "amount": _f(r.amt),
        }
        for r in gd.itertuples()
    ]

    corrections = 0
    for b in breaks:
        je = propose(b["period"], None)
        corrections += int(je["je_id"].nunique()) if len(je) else 0

    wip = query_df("select count(*) n, count(*) filter (where ties_out) t from recon.recon_wip_rollforward").iloc[0]
    close = query_df("select period_id, status, blocked_reasons from close.period_status order by 1")
    close_rows = []
    for r in close.itertuples():
        reasons = list(r.blocked_reasons or [])
        own = [x for x in reasons if not x.startswith("prior period")]
        close_rows.append(
            {
                "month": _month(r.period_id),
                "status": r.status,
                "why": "Waiting on the month before"
                if reasons and not own
                else ("Ledger does not match the cost records" if own else ""),
            }
        )

    tw = query_df(
        """select status, root_cause, count(*) n, sum(amount_at_risk) amt
           from recon.recon_three_way_match group by 1, 2"""
    )
    three_way = {
        "total": int(tw["n"].sum()),
        "clean": int(tw[tw.status != "exception"]["n"].sum()),
        "exceptions": [
            {"label": MATCH_LABELS.get(r.root_cause, r.root_cause), "count": int(r.n), "amount": _f(r.amt)}
            for r in tw[tw.status == "exception"].sort_values("amt", ascending=False).itertuples()
        ],
    }

    inv = query_df(
        """select plant_id, sum(count_vs_system_value) filter (where count_vs_system_value < 0) shrink,
                  count(*) filter (where counted_qty is not null) counts
           from marts.fct_inventory_discrepancy group by 1 order by 2"""
    )
    inventory = [
        {"plant": plant_short[r.plant_id], "shrink": -_f(r.shrink), "counts": int(r.counts)} for r in inv.itertuples()
    ]

    dq = query_df(
        """select count(*) n, count(*) filter (where status = 'pass') p, count(*) filter (where status = 'warn') w,
                  count(*) filter (where status in ('fail', 'error')) f from dq.latest_test_results"""
    ).iloc[0]
    rejects = int(query_df("select count(*) n from raw.rejects")["n"].iloc[0])
    raw_rows = int(query_df("select sum(rows_read) n from audit.load_log")["n"].iloc[0])
    dupes = int(query_df("select count(*) n from staging.stg_invoice_lines where is_duplicate")["n"].iloc[0])
    grams = int(query_df("select count(*) n from staging.stg_material_issues where uom_converted")["n"].iloc[0])
    late = int(query_df("select count(*) n from intermediate.int_labor_entries where is_late_posting")["n"].iloc[0])

    return {
        "generated": datetime.now(UTC).strftime("%d %b %Y"),
        "kpi": {
            "std": _f(k["std"]),
            "act": _f(k["act"]),
            "var": _f(k["var"]),
            "pct": _f(k["var"]) / _f(k["std"]),
            "orders": int(k.orders),
            "units": int(k.units),
            "from": _month(k.p0) + " " + k.p0[:4],
            "to": _month(k.p1) + " " + k.p1[:4],
        },
        "elements": elements,
        "heat": heat,
        "lines": [line_label[x] for x in lines.line_id],
        "usage_line": usage_line,
        "supplier": supplier,
        "scrap": scrap,
        "breaks": breaks,
        "corrections": corrections,
        "wip": {"total": int(wip.n), "ties": int(wip.t)},
        "close": close_rows,
        "three_way": three_way,
        "inventory": inventory,
        "quality": {
            "tests": int(dq.n),
            "passed": int(dq.p),
            "warned": int(dq.w),
            "failed": int(dq.f),
            "rows": raw_rows,
            "rejects": rejects,
            "dupes": dupes,
            "grams": grams,
            "late": late,
        },
    }


def render(data: dict, fragment: bool) -> str:
    template = Path(__file__).with_name("report_template.html").read_text(encoding="utf-8")
    html = template.replace("/*__DATA__*/null", json.dumps(data, separators=(",", ":"), default=float))
    if fragment:
        return html
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        "</head>\n<body>\n" + html + "\n</body>\n</html>\n"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="docs/index.html", type=Path)
    ap.add_argument("--fragment", action="store_true", help="omit <html>/<head>/<body> (for hosts that add them)")
    ap.add_argument("--repo-url", default=None, help="GitHub repository link shown in the footer")
    args = ap.parse_args(argv)
    data = collect()
    data["repo"] = args.repo_url
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(data, args.fragment), encoding="utf-8")
    log.info("report written", extra={"out": str(args.out)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
