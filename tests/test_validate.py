import pandas as pd
import pytest

from ingestion.load import parse_key
from ingestion.schemas import SOURCES
from ingestion.validate import SchemaError, validate


def _issues(rows):
    cols = ["issue_id", "order_id", "material_id", "issue_qty", "uom", "issue_date", "plant_id", "line_id"]
    return pd.DataFrame(rows, columns=cols).astype(str)


def test_valid_rows_are_typed():
    df = _issues([["1", "10", "M1", "2.5", "KG", "2025-03-04", "AUS1", "AUS1-L1"]])
    valid, rejects, warnings = validate(df, SOURCES["material_issues"])
    assert len(valid) == 1 and rejects.empty and not warnings
    assert str(valid["issue_id"].dtype) == "Int64"
    assert valid["issue_qty"].iloc[0] == 2.5


def test_bad_rows_are_rejected_with_reasons():
    df = _issues(
        [
            ["1", "10", "M1", "-4", "KG", "2025-03-04", "AUS1", "AUS1-L1"],  # negative qty
            ["2", "x", "M1", "1", "KG", "2025-03-04", "AUS1", "AUS1-L1"],  # bad int
            ["3", "10", "M1", "1", "LB", "2025-03-04", "AUS1", "AUS1-L1"],  # unknown uom
            ["4", "10", "", "1", "KG", "not-a-date", "AUS1", "AUS1-L1"],  # null + bad date
            ["5", "10", "M1", "1", "G", "2025-03-04", "AUS1", "AUS1-L1"],  # grams are allowed
        ]
    )
    valid, rejects, _ = validate(df, SOURCES["material_issues"])
    assert valid["issue_id"].tolist() == [5]
    reasons = dict(zip(rejects["row_num"], rejects["reason"], strict=True))
    assert "issue_qty: must be > 0" in reasons[2]
    assert "order_id: not a valid int" in reasons[3]
    assert "uom: not in" in reasons[4]
    assert "material_id: null" in reasons[5] and "issue_date: not a valid date" in reasons[5]


def test_labor_hours_over_24_rejected():
    cols = [c.name for c in SOURCES["labor_entries"].columns]
    row = ["1", "10", "E1", "2025-03-04", "2025-03-04", "30", "40.00", "false", "AUS1", "AUS1-L1"]
    _, rejects, _ = validate(pd.DataFrame([row], columns=cols), SOURCES["labor_entries"])
    assert rejects["reason"].iloc[0] == "hours: above 24"


def test_missing_column_fails_whole_file():
    df = _issues([["1", "10", "M1", "2", "KG", "2025-03-04", "AUS1", "AUS1-L1"]]).drop(columns=["uom"])
    with pytest.raises(SchemaError):
        validate(df, SOURCES["material_issues"])


def test_extra_column_is_a_warning_not_an_error():
    df = _issues([["1", "10", "M1", "2", "KG", "2025-03-04", "AUS1", "AUS1-L1"]]).assign(new_col="x")
    valid, _, warnings = validate(df, SOURCES["material_issues"])
    assert len(valid) == 1 and "schema drift" in warnings[0]


def test_nullable_po_reference_on_invoices():
    cols = [c.name for c in SOURCES["invoice_lines"].columns]
    row = ["1", "1", "S001-1", "S001", "AUS1", "", "", "M1", "5", "EA", "2.5", "2025-03-04"]
    valid, rejects, _ = validate(pd.DataFrame([row], columns=cols), SOURCES["invoice_lines"])
    assert len(valid) == 1 and rejects.empty


def test_parse_key():
    assert parse_key("material_issues/2025-03-04/material_issues.csv") == ("material_issues", "2025-03-04")
    assert parse_key("gl_journal_entries/2025-04-02/gl_journal_entries_corrections_2025-03.csv") == (
        "gl_journal_entries",
        "2025-04-02",
    )
    assert parse_key("_answer_key.json") is None
    assert parse_key("unknown_source/2025-03-04/x.csv") is None
