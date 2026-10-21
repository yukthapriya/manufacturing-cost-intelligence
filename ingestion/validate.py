"""Vectorised schema validation. Bad rows are returned with a reason, never silently dropped."""

from __future__ import annotations

import pandas as pd

from ingestion.schemas import Col, Source


class SchemaError(Exception):
    """The file itself is unusable (e.g. a required column is missing)."""


_BOOL = {"true": True, "false": False, "1": True, "0": False, "t": True, "f": False}


def _coerce(col: Col, s: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Return (typed values, bad-type mask). Empty strings are nulls."""
    s = s.str.strip().replace("", pd.NA)
    present = s.notna()
    if col.type == "int":
        num = pd.to_numeric(s, errors="coerce")
        bad = present & (num.isna() | (num % 1 != 0))
        return num, bad
    if col.type == "num":
        num = pd.to_numeric(s, errors="coerce")
        return num, present & num.isna()
    if col.type == "date":
        d = pd.to_datetime(s, errors="coerce", format="mixed")
        bad = present & (d.isna() | (d.dt.normalize() != d))
        return d.dt.date, bad
    if col.type == "ts":
        d = pd.to_datetime(s, errors="coerce", format="mixed")
        return d, present & d.isna()
    if col.type == "bool":
        b = s.str.lower().map(_BOOL)
        return b, present & b.isna()
    return s, pd.Series(False, index=s.index)


def validate(df: pd.DataFrame, source: Source) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Validate a raw extract (all columns as strings).

    Returns (valid_rows_typed, rejects[row_num, reason, payload], warnings).
    """
    expected = [c.name for c in source.columns]
    missing = [c for c in expected if c not in df.columns]
    if missing:
        raise SchemaError(f"{source.name}: missing required columns {missing}")
    warnings = [
        f"{source.name}: unexpected column '{c}' ignored (schema drift)" for c in df.columns if c not in expected
    ]

    reasons = pd.Series("", index=df.index, dtype=object)
    out = pd.DataFrame(index=df.index)

    def flag(mask: pd.Series, msg: str) -> None:
        mask = mask.fillna(False).astype(bool)
        reasons.loc[mask] = reasons.loc[mask] + msg + "; "

    for col in source.columns:
        values, bad_type = _coerce(col, df[col.name].astype("string"))
        out[col.name] = values
        flag(bad_type, f"{col.name}: not a valid {col.type}")
        isnull = pd.Series(values, index=df.index).isna() & ~bad_type
        if not col.nullable:
            flag(isnull, f"{col.name}: null")
        if col.type in ("int", "num"):
            v = pd.to_numeric(pd.Series(values, index=df.index), errors="coerce")
            if col.min is not None:
                flag(v < col.min, f"{col.name}: below {col.min}")
            if col.max is not None:
                flag(v > col.max, f"{col.name}: above {col.max}")
            if col.gt is not None:
                flag(v <= col.gt, f"{col.name}: must be > {col.gt}")
        if col.allowed is not None:
            flag(
                ~pd.Series(values, index=df.index).isin(col.allowed) & ~isnull,
                f"{col.name}: not in {list(col.allowed)}",
            )

    bad = reasons != ""
    rejects = pd.DataFrame(
        {
            "row_num": df.index[bad] + 2,  # +1 header, +1 one-based -> matches the line in the file
            "reason": reasons[bad].str.rstrip("; "),
            "payload": df.loc[bad, [c for c in df.columns]].to_dict(orient="records"),
        }
    )
    valid = out.loc[~bad, expected].copy()
    for col in source.columns:
        if col.type == "int":
            valid[col.name] = pd.to_numeric(valid[col.name]).astype("Int64")
    return valid, rejects, warnings
