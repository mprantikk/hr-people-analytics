"""HRIS data quality: measure, fix what can be fixed safely, and re-measure.

Accuracy here = share of employee records with no open data-quality issue.
"""

from __future__ import annotations

import re

import pandas as pd

from .generate import DEPTS

DEPT_LOOKUP = {re.sub(r"[^a-z]", "", v.lower()): canon for canon, (variants, *_) in DEPTS.items() for v in variants}
VALID_GRADES = {"G1", "G2", "G3", "G4", "G5"}
EMAIL = r"^[\w.+-]+@[\w-]+\.[\w.]+$"
AS_OF = pd.Timestamp("2025-12-31")


def _parse_dates(s: pd.Series) -> pd.Series:
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%b-%Y"):
        m = out.isna()
        out[m] = pd.to_datetime(s[m], format=fmt, errors="coerce")
    return out


def issues(df: pd.DataFrame) -> pd.DataFrame:
    """One boolean column per rule; True = the record has that problem."""
    hire = _parse_dates(df.hire_date.fillna("").astype(str))
    exit_ = _parse_dates(df.exit_date.fillna("").astype(str))
    has_exit_text = df.exit_date.fillna("").astype(str).str.strip().ne("")
    ids = set(df.employee_id)
    return pd.DataFrame({
        "duplicate_record": df.duplicated(keep="first"),
        "non_standard_department": ~df.department.isin(DEPTS),
        "non_iso_date": ~df.hire_date.astype(str).str.match(r"^\d{4}-\d{2}-\d{2}$")
                         | (has_exit_text & ~df.exit_date.astype(str).str.match(r"^\d{4}-\d{2}-\d{2}$")),
        "unparseable_date": hire.isna() | (has_exit_text & exit_.isna()),
        "status_conflicts_with_exit": (df.status.eq("Active") & has_exit_text) | (df.status.eq("Exited") & ~has_exit_text),
        "exit_before_hire": exit_.notna() & hire.notna() & (exit_ < hire),
        "missing_grade": ~df.grade.fillna("").isin(VALID_GRADES),
        "unknown_manager": df.manager_id.notna() & df.manager_id.ne("") & ~df.manager_id.isin(ids),
        "invalid_email": ~df.email.fillna("").str.match(EMAIL),
        "untidy_text": df.location.ne(df.location.str.strip().str.title().str.replace("Hq", "HQ")),
    }, index=df.index)


# Accuracy: is the record right? Consistency: is it in the standard format?
ACCURACY_RULES = ["duplicate_record", "unparseable_date", "status_conflicts_with_exit", "exit_before_hire",
                  "missing_grade", "unknown_manager", "invalid_email"]
CONSISTENCY_RULES = ["non_standard_department", "non_iso_date", "untidy_text"]


def accuracy(df: pd.DataFrame) -> float:
    """Share of records with no accuracy issue."""
    return round(100 * (~issues(df)[ACCURACY_RULES].any(axis=1)).mean(), 1)


def consistency(df: pd.DataFrame) -> float:
    """Share of records already in standard format."""
    return round(100 * (~issues(df)[CONSISTENCY_RULES].any(axis=1)).mean(), 1)


def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Apply safe, rule-based fixes. Problems that need a human are left and flagged."""
    log = []
    out = df.drop_duplicates().copy()
    log.append(f"removed {len(df) - len(out)} duplicate records")
    norm = out.department.map(lambda d: DEPT_LOOKUP.get(re.sub(r"[^a-z]", "", str(d).lower()), d))
    log.append(f"standardised {int((norm != out.department).sum())} department names to {norm.nunique()} departments")
    out["department"] = norm
    for col in ("hire_date", "exit_date"):
        parsed = _parse_dates(out[col].fillna("").astype(str))
        out[col] = parsed.dt.strftime("%Y-%m-%d").fillna("")
    log.append("converted all dates to ISO format (YYYY-MM-DD)")
    derived = out.exit_date.ne("").map({True: "Exited", False: "Active"})
    log.append(f"corrected {int((derived != out.status).sum())} statuses from the exit date")
    out["status"] = derived
    tidy = out.location.str.strip().str.title().str.replace("Hq", "HQ")
    log.append(f"tidied {int((tidy != out.location).sum())} location values")
    out["location"] = tidy
    # not auto-fixable: missing grade, unknown manager, malformed email -> routed to HR ops
    remaining = issues(out)
    for rule in ("missing_grade", "unknown_manager", "invalid_email"):
        log.append(f"flagged {int(remaining[rule].sum())} records for HR ops review: {rule.replace('_', ' ')}")
    return out.reset_index(drop=True), log


def rule_summary(before: pd.DataFrame, after: pd.DataFrame) -> pd.DataFrame:
    b, a = issues(before).sum(), issues(after).sum()
    return pd.DataFrame({"rule": b.index, "before": b.values, "after": a.reindex(b.index).values})
