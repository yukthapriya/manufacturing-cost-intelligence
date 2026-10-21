"""Checks against a warehouse the full pipeline has run on (CI runs these after `dbt build`).

The generator writes an answer key of the problems it injected; the pipeline must find
every one of them, with the right root cause, and everything else must tie to the cent.
"""

import json
import os

import pytest

from common.config import source_uri
from common.db import query_df
from common.storage import open_storage

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def answer_key():
    return json.loads(open_storage(os.environ.get("SOURCE_URI", source_uri())).read_bytes("_answer_key.json"))


def test_every_injected_gl_break_is_detected_with_the_right_root_cause(answer_key):
    expected = {
        "missing_posting": "missing_gl_posting",
        "duplicate_posting": "duplicate_gl_posting",
        "misposted_plant": "misposted_plant",
        "timing": "timing_cutoff",
    }
    breaks = query_df("select je_date::text as je_date, plant_id, source_type, root_cause from recon.recon_gl_daily")
    for b in answer_key["gl_breaks"]:
        plant = b.get("plant_id") or b.get("from_plant")
        hit = breaks[
            (breaks.je_date == b["je_date"]) & (breaks.plant_id == plant) & (breaks.source_type == b["source_type"])
        ]
        assert not hit.empty, f"break not detected: {b}"
        assert set(hit.root_cause) == {expected[b["type"]]}, f"wrong root cause for {b}: {set(hit.root_cause)}"


def test_no_unexplained_breaks_beyond_the_injected_ones(answer_key):
    n = query_df("select count(*) as n from recon.recon_gl_daily where root_cause = 'unexplained'")["n"].iloc[0]
    assert n == 0


def test_wip_rollforward_ties_everywhere():
    df = query_df(
        "select count(*) filter (where not ties_out) as broken, count(*) as total from recon.recon_wip_rollforward"
    )
    assert df["total"].iloc[0] > 0 and df["broken"].iloc[0] == 0


def test_variance_components_reconcile_to_total():
    df = query_df(
        """select max(abs(total_actual_cost - total_std_cost - total_variance)) as gap
           from marts.fct_production_cost where is_completed"""
    )
    assert float(df["gap"].iloc[0]) < 0.01


def test_duplicates_and_rejects_match_what_was_injected(answer_key):
    dq = answer_key["data_quality"]
    dups = query_df("select count(*) as n from staging.stg_invoice_lines where is_duplicate")["n"].iloc[0]
    assert dups == dq["duplicate_invoice_lines"]
    rej = query_df("select source, count(*) as n from raw.rejects group by 1").set_index("source")["n"].to_dict()
    assert rej.get("material_issues") == dq["issue_reject_rows"]
    assert rej.get("labor_entries") == dq["labor_reject_rows"]
    grams = query_df("select count(*) as n from staging.stg_material_issues where uom_converted")["n"].iloc[0]
    assert grams == dq["issues_in_grams"]


def test_no_failing_dbt_tests_in_latest_build():
    df = query_df("select count(*) as n from dq.latest_test_results where status in ('fail', 'error')")
    assert df["n"].iloc[0] == 0
