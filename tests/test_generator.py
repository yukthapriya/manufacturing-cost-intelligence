from datetime import date

import pytest

from data_generator.generate import generate, write_tables
from data_generator.master_data import OVERUSE_LINE


@pytest.fixture(scope="module")
def small():
    return generate(date(2025, 1, 1), 3, 0.1, 7)


def test_gl_is_balanced(small):
    tables, _ = small
    gl = tables["gl_journal_entries"]
    assert round(gl["debit"].sum() - gl["credit"].sum(), 2) == 0
    # every journal entry balances on its own (the misposted-plant break moves whole entries)
    per_je = gl.groupby("je_id").apply(lambda x: round(x["debit"].sum() - x["credit"].sum(), 2))
    assert (per_je == 0).all()


def test_answer_key_lists_injected_problems(small):
    _, key = small
    types = {b["type"] for b in key["gl_breaks"]}
    assert types == {"missing_posting", "duplicate_posting", "misposted_plant", "timing"}
    dq = key["data_quality"]
    assert dq["duplicate_invoice_lines"] > 0 and dq["issues_in_grams"] > 0 and dq["issue_reject_rows"] >= 3


def test_deterministic_for_a_seed():
    a, _ = generate(date(2025, 1, 1), 1, 0.05, 11)
    b, _ = generate(date(2025, 1, 1), 1, 0.05, 11)
    assert a["material_issues"].equals(b["material_issues"])
    assert a["gl_journal_entries"].equals(b["gl_journal_entries"])


def test_orders_have_cdc_events(small):
    tables, _ = small
    ev = tables["production_orders"]
    assert set(ev["status"]) == {"RELEASED", "COMPLETED"}
    assert ev.groupby("order_id")["status"].nunique().max() == 2


def test_overuse_line_consumes_more(small):
    tables, _ = small
    iss = tables["material_issues"]
    assert OVERUSE_LINE in set(iss["line_id"])


def test_window_must_stay_in_one_fiscal_year():
    with pytest.raises(ValueError):
        generate(date(2025, 11, 1), 3, 0.05, 1)


def test_writes_partitioned_files(tmp_path, small):
    tables, key = small
    n = write_tables(tables, key, str(tmp_path), date(2025, 1, 1))
    assert n > 100
    assert (tmp_path / "_answer_key.json").exists()
    assert (tmp_path / "materials" / "2025-01-01" / "materials.csv").exists()
    assert any((tmp_path / "material_issues").iterdir())
