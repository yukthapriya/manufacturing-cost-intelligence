"""Quick preview of the dashboards without Tableau.

    pip install streamlit plotly
    streamlit run app/streamlit_app.py

Reads the warehouse directly (WAREHOUSE_* env vars).
"""

from __future__ import annotations

import sys
from pathlib import Path

import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.db import query_df  # noqa: E402

st.set_page_config(page_title="Manufacturing Cost Intelligence", layout="wide")


@st.cache_data(ttl=300)
def q(sql: str, params: tuple | None = None):
    return query_df(sql, params)


periods = q("select distinct period_id from marts.fct_production_cost where period_id is not null order by 1")
plants = q("select plant_id from marts.dim_plant order by 1")
with st.sidebar:
    st.title("Filters")
    sel_periods = st.multiselect("Period", periods["period_id"].tolist(), default=periods["period_id"].tolist())
    sel_plants = st.multiselect("Plant", plants["plant_id"].tolist(), default=plants["plant_id"].tolist())
p_list = tuple(sel_periods) or ("",)
pl_list = tuple(sel_plants) or ("",)

st.title("Manufacturing Cost Review")
st.markdown(
    "Compares what each product **should** have cost (standard cost: bill of materials at planned prices plus "
    "planned labor) with what it **did** cost, and checks that the accounting books agree with the factory "
    "records. Positive variance = cost more than planned. Synthetic data. For the written summary, run "
    "`python -m exporter.static_report` and open `docs/index.html`."
)

tab1, tab2, tab3, tab4, tab5 = st.tabs(["Unit Cost", "Variance", "Scrap & Yield", "Inventory & DQ", "Close Readiness"])

with tab1:
    st.info(
        "**How to read this:** the four numbers are the totals for the filters on the left. Each small chart is "
        "one product family: if the *actual* line sits above *standard*, that family cost more to build than planned."
    )
    k = q(
        """select sum(total_actual_cost) a, sum(total_std_cost) s, sum(total_variance) v, sum(completed_qty) u
             from marts.fct_production_cost where is_completed and period_id in %s and plant_id in %s""",
        (p_list, pl_list),
    ).iloc[0]
    c = st.columns(4)
    c[0].metric("Actual cost", f"${(k.a or 0):,.0f}")
    c[1].metric("Standard cost", f"${(k.s or 0):,.0f}")
    c[2].metric(
        "Variance", f"${(k.v or 0):,.0f}", f"{100 * (k.v or 0) / (k.s or 1):.2f}% vs std", delta_color="inverse"
    )
    c[3].metric("Units completed", f"{(k.u or 0):,.0f}")
    uc = q(
        """select family, period_id, sum(total_actual_cost)/sum(units_completed) actual,
                     sum(total_std_cost)/sum(units_completed) standard
              from marts.fct_unit_cost where period_id in %s and plant_id in %s group by 1, 2 order by 2""",
        (p_list, pl_list),
    )
    st.plotly_chart(
        px.line(
            uc,
            x="period_id",
            y=["actual", "standard"],
            facet_col="family",
            facet_col_wrap=4,
            title="Unit cost: actual vs. standard",
        ),
        width="stretch",
    )

with tab2:
    st.info(
        "**How to read this:** the waterfall splits the total overrun into six causes that add up exactly to it "
        "(price = paid more than planned, usage = used more material, scrap = scrapped more than allowed, then "
        "labor and overhead). In the heatmap, each square is a line in a month; a full red row means a line is "
        "over plan every month, which points to a process problem rather than a bad week."
    )
    el = q(
        """select cost_element, sum(variance_amount) amount from marts.fct_cost_variance
              where period_id in %s and plant_id in %s group by 1""",
        (p_list, pl_list),
    )
    order = ["material_price", "material_usage", "scrap", "labor_rate", "labor_efficiency", "overhead_efficiency"]
    el = el.set_index("cost_element").reindex(order).fillna(0).reset_index()
    import plotly.graph_objects as go

    fig = go.Figure(go.Waterfall(x=el["cost_element"], y=el["amount"], measure=["relative"] * len(el)))
    fig.update_layout(title="Variance bridge (positive = unfavorable)")
    st.plotly_chart(fig, width="stretch")
    hm = q(
        """select line_id, period_id, sum(variance_amount)/nullif(sum(std_cost),0) pct
              from marts.fct_cost_variance where period_id in %s and plant_id in %s group by 1, 2""",
        (p_list, pl_list),
    )
    st.plotly_chart(
        px.density_heatmap(
            hm,
            x="period_id",
            y="line_id",
            z="pct",
            histfunc="sum",
            color_continuous_scale="RdBu_r",
            title="Variance % by line and month",
        ),
        width="stretch",
    )

with tab3:
    st.info(
        "**How to read this:** scrap rate = value of material thrown away ÷ material issued. Look for a line that "
        "jumps away from the others. The bar chart shows which logged reason accounts for most scrap."
    )
    sc = q(
        """select line_id, period_id, max(line_scrap_rate) rate from marts.fct_scrap
              where period_id in %s and plant_id in %s group by 1, 2 order by 2""",
        (p_list, pl_list),
    )
    st.plotly_chart(px.line(sc, x="period_id", y="rate", color="line_id", title="Scrap rate by line"), width="stretch")
    pr = q(
        """select reason_code, sum(scrap_value) value from marts.fct_scrap
              where period_id in %s and plant_id in %s group by 1 order by 2 desc""",
        (p_list, pl_list),
    )
    st.plotly_chart(px.bar(pr, x="reason_code", y="value", title="Scrap by reason (Pareto)"), width="stretch")

with tab4:
    st.info(
        "**How to read this:** the table compares three inventory counts per plant: the ERP's figure, the figure "
        "rebuilt from transactions, and a physical count. Shrink = stock the system says exists but the count did "
        "not find. The chart shows how many automated data checks passed; warnings are known source-data problems "
        "that are tracked on purpose."
    )
    inv = q(
        """select plant_id, count(*) filter (where flag_negative_system_qty) negative_qty,
                      count(*) filter (where flag_system_break) erp_vs_perpetual,
                      count(*) filter (where flag_count_variance) count_variances,
                      sum(count_vs_system_value) filter (where count_vs_system_value < 0) shrink_value
               from marts.fct_inventory_discrepancy where period_id in %s and plant_id in %s group by 1""",
        (p_list, pl_list),
    )
    st.dataframe(inv, width="stretch")
    dq = q("select layer, status, count(*) n from dq.latest_test_results group by 1, 2 order by 1, 2")
    st.plotly_chart(px.bar(dq, x="layer", y="n", color="status", title="dbt tests, latest build"), width="stretch")

with tab5:
    st.info(
        "**How to read this:** a month can only be closed (signed off and locked) when the general ledger agrees "
        "with the factory records. 'blocked' lists why. The WIP roll-forward must tie: opening balance + material + "
        "labor + overhead − finished goods − scrap = closing balance. The exception queue is the to-do list."
    )
    ps = q("select period_id, status, locked, blocked_reasons from close.period_status order by 1")
    st.dataframe(ps, width="stretch")
    rf = q(
        """select plant_id, period_id, beginning_wip, material_issued, labor, overhead, completions, scrap,
                     settlement, ending_wip_rollforward, ending_open_orders, ties_out, gl_diff
              from recon.recon_wip_rollforward where period_id in %s and plant_id in %s order by 2, 1""",
        (p_list, pl_list),
    )
    st.subheader("WIP roll-forward")
    st.dataframe(rf, width="stretch")
    ex = q(
        """select recon_type, period_id, plant_id, description, amount, root_cause, aging_bucket, is_critical
              from recon.recon_exceptions where period_id in %s and plant_id in %s
              order by is_critical desc, abs(amount) desc nulls last limit 500""",
        (p_list, pl_list),
    )
    st.subheader("Exception queue")
    st.dataframe(ex, width="stretch")
