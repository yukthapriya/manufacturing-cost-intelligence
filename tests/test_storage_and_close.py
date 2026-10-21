from close.period_close import _prior_period
from common.storage import LocalStorage, open_storage, sha256


def test_local_storage_roundtrip(tmp_path):
    s = LocalStorage(str(tmp_path))
    s.write_bytes("a/2025-01-01/a.csv", b"x,y\n1,2\n")
    assert s.list() == ["a/2025-01-01/a.csv"]
    assert s.read_bytes("a/2025-01-01/a.csv") == b"x,y\n1,2\n"
    assert sha256(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_open_storage_picks_backend(tmp_path):
    assert isinstance(open_storage(str(tmp_path)), LocalStorage)


def test_prior_period():
    assert _prior_period("2025-03") == "2025-02"
    assert _prior_period("2025-01") == "2024-12"
    assert _prior_period("2025-12") == "2025-11"


def test_correcting_entries_balance_and_reclass_without_suspense():
    import pandas as pd

    from close.propose_corrections import SUSPENSE, build_entries

    breaks = pd.DataFrame(
        [
            # misposted: A short, B over -> one reclass entry, no suspense
            ("2025-08-14", "2025-08", "AUS1", "LABOR", "1400", -100.0, "misposted_plant"),
            ("2025-08-14", "2025-08", "RNO1", "LABOR", "1400", 100.0, "misposted_plant"),
            # duplicate receipt: only 1300 visible -> offset to suspense
            ("2025-05-11", "2025-05", "AUS1", "RECEIPT", "1300", 50.0, "duplicate_gl_posting"),
            # missing issue posting: both sides visible -> balanced
            ("2025-03-15", "2025-03", "FRE1", "ISSUE", "1300", 70.0, "missing_gl_posting"),
            ("2025-03-15", "2025-03", "FRE1", "ISSUE", "1400", -70.0, "missing_gl_posting"),
        ],
        columns=["je_date", "period_id", "plant_id", "source_type", "account", "diff", "root_cause"],
    )
    je = build_entries(breaks, "2025-08")
    by_je = je.groupby("je_id").apply(lambda x: round(x["debit"].sum() - x["credit"].sum(), 2))
    assert (by_je == 0).all() and len(by_je) == 3
    suspense = je[je["account"] == SUSPENSE]
    assert len(suspense) == 1 and suspense["plant_id"].iloc[0] == "AUS1" and suspense["debit"].iloc[0] == 50.0
    reclass = je[je["source_type"] == "LABOR"].set_index("plant_id")
    assert reclass.loc["AUS1", "debit"] == 100.0 and reclass.loc["RNO1", "credit"] == 100.0
