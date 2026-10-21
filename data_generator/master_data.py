"""Master data: plants, lines, suppliers, materials, products, BOM and standard costs."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

PLANTS = [
    ("AUS1", "Austin Assembly", "Austin", "TX"),
    ("FRE1", "Fremont Assembly", "Fremont", "CA"),
    ("RNO1", "Reno Components", "Reno", "NV"),
]

# category: (base uom, price range USD per uom, qty-per-unit range)
CATEGORIES = {
    "Battery Cell": ("EA", (3.2, 7.5), (24, 96)),
    "Steel Sheet": ("KG", (1.10, 2.40), (0.8, 18.0)),
    "Aluminum Extrusion": ("KG", (2.80, 4.60), (0.5, 12.0)),
    "Copper Busbar": ("KG", (8.50, 11.20), (0.1, 2.5)),
    "Fastener": ("EA", (0.02, 0.65), (4, 60)),
    "Electronic Module": ("EA", (4.0, 140.0), (1, 4)),
    "Injection Resin": ("KG", (1.6, 4.2), (0.2, 6.0)),
    "Wire": ("M", (0.30, 2.60), (1.0, 35.0)),
    "Structural Adhesive": ("KG", (8.0, 26.0), (0.05, 1.2)),
    "Glass Panel": ("EA", (22.0, 95.0), (1, 2)),
    "Foam": ("KG", (3.0, 7.0), (0.2, 3.0)),
    "Rubber Seal": ("EA", (0.5, 6.5), (1, 8)),
}
METAL_CATEGORIES = {"Steel Sheet", "Aluminum Extrusion", "Copper Busbar"}
UOM_DECIMALS = {"EA": 0, "KG": 3, "M": 2}

PRODUCT_FAMILIES = [
    "Battery Module",
    "Drive Unit",
    "Seat Assembly",
    "Door Module",
    "HVAC Module",
    "Charge Port Assembly",
    "Front Subframe",
    "Main Wiring Harness",
]
SUBASSEMBLY_NAMES = [
    "Cell Carrier",
    "Inverter Board",
    "Seat Frame",
    "Window Regulator",
    "Blower Motor",
    "Latch Assembly",
    "Cooling Plate",
    "Sensor Cluster",
    "Busbar Kit",
    "Trim Panel",
]
SUPPLIER_WORDS_A = ["Apex", "Granite", "Summit", "Pioneer", "Vector", "Keystone", "Meridian", "Atlas", "Redwood"]
SUPPLIER_WORDS_B = ["Metals", "Components", "Polymers", "Electronics", "Industrial", "Fastening", "Materials"]

SPIKE_SUPPLIER = "S007"  # starts surcharging invoices mid-year (story for the PPV dashboard)
OVERUSE_LINE = "FRE1-L2"  # chronic material overuse
SCRAP_SPIKE_LINE = "RNO1-L1"  # machine fault scrap spike for two months


def build_master(rng: np.random.Generator, start: date) -> dict[str, pd.DataFrame]:
    plants = pd.DataFrame(PLANTS, columns=["plant_id", "plant_name", "city", "state"])

    lines = []
    for plant_id, *_ in PLANTS:
        for n in (1, 2):
            lines.append({"line_id": f"{plant_id}-L{n}", "plant_id": plant_id, "line_name": f"{plant_id} Line {n}"})
    lines = pd.DataFrame(lines)
    lines["std_labor_rate"] = np.round(rng.uniform(32, 44, len(lines)), 2)
    lines["overhead_rate"] = np.round(rng.uniform(45, 85, len(lines)), 2)

    n_sup = 25
    suppliers = pd.DataFrame(
        {
            "supplier_id": [f"S{i:03d}" for i in range(1, n_sup + 1)],
            "supplier_name": [
                f"{SUPPLIER_WORDS_A[i % len(SUPPLIER_WORDS_A)]} "
                f"{SUPPLIER_WORDS_B[(i * 3) % len(SUPPLIER_WORDS_B)]} {i:02d}"
                for i in range(1, n_sup + 1)
            ],
            "payment_terms_days": rng.choice([30, 45, 60], n_sup),
            "country": rng.choice(["US", "US", "US", "MX", "CA", "KR", "JP"], n_sup),
        }
    )

    # --- materials -------------------------------------------------------------
    n_mat = 300
    cats = list(CATEGORIES)
    mat_cat = rng.choice(cats, n_mat, p=_cat_weights(cats))
    materials = pd.DataFrame(
        {
            "material_id": [f"M{10001 + i}" for i in range(n_mat)],
            "category": mat_cat,
        }
    )
    materials["material_desc"] = [f"{c} {chr(65 + i % 26)}{100 + i}" for i, c in enumerate(mat_cat)]
    materials["base_uom"] = materials["category"].map(lambda c: CATEGORIES[c][0])
    lo = materials["category"].map(lambda c: CATEGORIES[c][1][0])
    hi = materials["category"].map(lambda c: CATEGORIES[c][1][1])
    materials["std_price"] = np.round(rng.uniform(lo, hi), 4)
    # each supplier specialises in a few categories
    materials["primary_supplier_id"] = [
        f"S{(cats.index(c) * 2 + int(rng.integers(0, 3))) % n_sup + 1:03d}" for c in mat_cat
    ]
    materials["lead_time_days"] = rng.integers(3, 15, n_mat)

    # --- products & subassemblies ----------------------------------------------
    n_prod = 40
    line_ids = lines["line_id"].tolist()
    products = pd.DataFrame(
        {
            "product_id": [f"FG-{2001 + i}" for i in range(n_prod)],
            "family": [PRODUCT_FAMILIES[i % len(PRODUCT_FAMILIES)] for i in range(n_prod)],
            "line_id": [line_ids[i % len(line_ids)] for i in range(n_prod)],
        }
    )
    products["product_name"] = [f"{f} Gen{1 + i % 3} V{i:02d}" for i, f in enumerate(products["family"])]
    products["plant_id"] = products["line_id"].str[:4]
    products["std_labor_hours"] = np.round(rng.uniform(0.05, 0.6, n_prod), 3)  # 3-36 min per unit
    products["lot_min"] = rng.integers(20, 60, n_prod)
    products["lot_max"] = products["lot_min"] + rng.integers(40, 120, n_prod)

    subs = pd.DataFrame(
        {
            "subassembly_id": [f"SA-{3001 + i}" for i in range(len(SUBASSEMBLY_NAMES))],
            "subassembly_name": SUBASSEMBLY_NAMES,
        }
    )

    # --- BOM (two levels: FG -> material | subassembly -> material) ------------
    mat_ids = materials["material_id"].to_numpy()
    sub_pool = rng.choice(mat_ids, 60, replace=False)  # materials reserved for subassemblies
    direct_pool = np.setdiff1d(mat_ids, sub_pool)
    bom_rows = []
    for sa in subs["subassembly_id"]:
        for m in rng.choice(sub_pool, int(rng.integers(4, 9)), replace=False):
            bom_rows.append((sa, "SUBASSEMBLY", m, "MATERIAL"))
    sub_ids = subs["subassembly_id"].to_numpy()
    for p in products["product_id"]:
        for m in rng.choice(direct_pool, int(rng.integers(10, 19)), replace=False):
            bom_rows.append((p, "PRODUCT", m, "MATERIAL"))
        for s in rng.choice(sub_ids, int(rng.integers(0, 3)), replace=False):
            bom_rows.append((p, "PRODUCT", s, "SUBASSEMBLY"))
    bom = pd.DataFrame(bom_rows, columns=["parent_id", "parent_type", "component_id", "component_type"])
    mat_lookup = materials.set_index("material_id")
    is_mat = bom["component_type"] == "MATERIAL"
    cat = bom["component_id"].map(mat_lookup["category"])
    qty = np.where(
        is_mat,
        [rng.uniform(*CATEGORIES[c][2]) if isinstance(c, str) else 0 for c in cat],
        rng.integers(1, 4, len(bom)),
    )
    uom = np.where(is_mat, bom["component_id"].map(mat_lookup["base_uom"]), "EA")
    dec = pd.Series(uom).map(UOM_DECIMALS).to_numpy()
    # EA quantities are whole numbers; KG/M carry up to 4 decimals per unit
    bom["qty_per"] = np.where(dec == 0, np.round(qty), np.round(qty, 4))
    bom["uom"] = uom
    bom["scrap_allowance_pct"] = np.where(is_mat, np.round(rng.uniform(0.005, 0.03, len(bom)), 3), 0.0)
    bom["bom_line"] = bom.groupby("parent_id").cumcount() + 1

    exploded = explode_bom(bom)
    std = standard_costs(materials, lines, products, exploded, start)
    return {
        "plants": plants,
        "production_lines": lines[["line_id", "plant_id", "line_name"]],
        "suppliers": suppliers,
        "materials": materials[
            ["material_id", "material_desc", "category", "base_uom", "primary_supplier_id", "lead_time_days"]
        ],
        "products": products[["product_id", "product_name", "family", "line_id", "plant_id", "lot_min", "lot_max"]],
        "subassemblies": subs,
        "bom": bom[
            [
                "parent_id",
                "parent_type",
                "bom_line",
                "component_id",
                "component_type",
                "qty_per",
                "uom",
                "scrap_allowance_pct",
            ]
        ],
        "standard_costs": std,
        "uom_conversions": pd.DataFrame(
            [("KG", "KG", 1.0), ("G", "KG", 0.001), ("EA", "EA", 1.0), ("M", "M", 1.0), ("CM", "M", 0.01)],
            columns=["from_uom", "to_uom", "factor"],
        ),
        "gl_accounts": pd.DataFrame(
            [
                ("1300", "Raw Materials Inventory", "ASSET", True),
                ("1400", "Work in Process", "ASSET", True),
                ("1500", "Finished Goods Inventory", "ASSET", True),
                ("2100", "Accounts Payable", "LIABILITY", False),
                ("2110", "Goods Received Not Invoiced", "LIABILITY", False),
                ("2200", "Accrued Payroll", "LIABILITY", False),
                ("3900", "Opening Balance Equity", "EQUITY", False),
                ("5000", "Cost of Goods Sold", "EXPENSE", False),
                ("5100", "Purchase Price Variance", "EXPENSE", False),
                ("5200", "Manufacturing Variance", "EXPENSE", False),
                ("5300", "Scrap Expense", "EXPENSE", False),
                ("5900", "Overhead Applied", "EXPENSE", False),
                ("1999", "Reconciliation Suspense", "ASSET", False),
            ],
            columns=["account", "account_name", "account_type", "is_inventory"],
        ),
        # internal helpers used by the generator, not written out
        "_materials_full": materials,
        "_lines_full": lines,
        "_products_full": products,
        "_exploded": exploded,
    }


def _cat_weights(cats: list[str]) -> np.ndarray:
    w = np.array([3 if c in ("Fastener", "Electronic Module", "Wire") else 1.5 for c in cats], dtype=float)
    return w / w.sum()


def explode_bom(bom: pd.DataFrame) -> pd.DataFrame:
    """Flatten the 2-level BOM to product -> material with path quantities."""
    top = bom[bom["parent_type"] == "PRODUCT"]
    direct = top[top["component_type"] == "MATERIAL"][["parent_id", "component_id", "qty_per", "scrap_allowance_pct"]]
    via = top[top["component_type"] == "SUBASSEMBLY"].merge(
        bom[bom["parent_type"] == "SUBASSEMBLY"],
        left_on="component_id",
        right_on="parent_id",
        suffixes=("", "_sub"),
    )
    via = pd.DataFrame(
        {
            "parent_id": via["parent_id"],
            "component_id": via["component_id_sub"],
            "qty_per": via["qty_per"] * via["qty_per_sub"],
            "scrap_allowance_pct": via["scrap_allowance_pct_sub"],
        }
    )
    ex = pd.concat([direct, via], ignore_index=True)
    ex["std_qty_incl_scrap"] = ex["qty_per"] * (1 + ex["scrap_allowance_pct"])
    ex = (
        ex.groupby(["parent_id", "component_id"], as_index=False)
        .agg(qty_per=("qty_per", "sum"), std_qty_incl_scrap=("std_qty_incl_scrap", "sum"))
        .rename(columns={"parent_id": "product_id", "component_id": "material_id"})
    )
    return ex


def standard_costs(
    materials: pd.DataFrame, lines: pd.DataFrame, products: pd.DataFrame, exploded: pd.DataFrame, start: date
) -> pd.DataFrame:
    """Long-format, versioned standards. Current FY version plus the prior-year version."""
    fy_start = date(start.year, 1, 1)
    fy_end = date(start.year, 12, 31)
    prior_start, prior_end = date(start.year - 1, 1, 1), date(start.year - 1, 12, 31)

    ex = exploded.merge(materials[["material_id", "std_price"]], on="material_id")
    ex["ext"] = ex["std_qty_incl_scrap"] * ex["std_price"]
    mat_cost = ex.groupby("product_id")["ext"].sum()
    p = products.merge(lines[["line_id", "std_labor_rate", "overhead_rate"]], on="line_id")
    p["std_unit_cost"] = np.round(
        p["product_id"].map(mat_cost) + p["std_labor_hours"] * (p["std_labor_rate"] + p["overhead_rate"]), 4
    )

    rows = []
    for m in materials.itertuples():
        rows.append(("MATERIAL", m.material_id, "STD_PRICE", m.std_price, m.base_uom))
    for ln in lines.itertuples():
        rows.append(("LINE", ln.line_id, "LABOR_RATE", ln.std_labor_rate, "HR"))
        rows.append(("LINE", ln.line_id, "OVERHEAD_RATE", ln.overhead_rate, "HR"))
    for pr in p.itertuples():
        rows.append(("PRODUCT", pr.product_id, "LABOR_HOURS", pr.std_labor_hours, "EA"))
        rows.append(("PRODUCT", pr.product_id, "UNIT_COST", pr.std_unit_cost, "EA"))
    cur = pd.DataFrame(rows, columns=["item_type", "item_id", "cost_component", "std_value", "uom"])
    cur["effective_from"], cur["effective_to"], cur["version"] = fy_start, fy_end, f"FY{start.year}"

    prior = cur.copy()
    prior["std_value"] = np.where(
        prior["cost_component"] == "LABOR_HOURS",
        prior["std_value"],
        np.round(prior["std_value"] / 1.03, 4),
    )
    prior["effective_from"], prior["effective_to"], prior["version"] = prior_start, prior_end, f"FY{start.year - 1}"
    return pd.concat([prior, cur], ignore_index=True)
