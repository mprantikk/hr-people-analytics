import pandas as pd
import pytest

from people import metrics as M
from people.generate import generate, roughen
from people.quality import accuracy, clean, consistency, issues


@pytest.fixture(scope="module")
def data():
    c, r = generate(seed=5)
    raw = roughen(c, seed=5).astype(str).replace({"None": "", "nan": ""})
    raw["manager_id"] = raw.manager_id.replace("", None)
    return c, r, raw


def test_rules_catch_each_defect():
    df = pd.DataFrame([
        {"employee_id": "E1", "department": "Engineering", "grade": "G2", "manager_id": None, "location": "Dhaka HQ",
         "hire_date": "2023-01-05", "exit_date": "", "exit_reason": "", "status": "Active", "email": "e1@example.com"},
        {"employee_id": "E2", "department": "Engg", "grade": "", "manager_id": "E999", "location": "DHAKA HQ ",
         "hire_date": "05/01/2023", "exit_date": "2022-01-01", "exit_reason": "", "status": "Active", "email": "e2 at x.com"},
    ])
    row = issues(df).iloc[1]
    for rule in ["non_standard_department", "non_iso_date", "status_conflicts_with_exit", "exit_before_hire",
                 "missing_grade", "unknown_manager", "invalid_email", "untidy_text"]:
        assert row[rule], rule
    assert not issues(df).iloc[0].any()


def test_cleaning_improves_quality_without_losing_people(data):
    clean_truth, _, raw = data
    fixed, log = clean(raw)
    assert accuracy(fixed) > accuracy(raw)
    assert consistency(fixed) == 100.0
    assert fixed.employee_id.is_unique
    assert set(fixed.employee_id) == set(clean_truth.employee_id)
    assert len(log) >= 6


def test_status_is_derived_from_exit_date(data):
    fixed, _ = clean(data[2])
    assert (fixed.status.eq("Exited") == fixed.exit_date.ne("")).all()


def test_monthly_headcount_balances(data):
    df = M.prep(clean(data[2])[0])
    m = M.monthly(df)
    # headcount change = hires - exits, month over month
    delta = m.headcount.diff().iloc[1:]
    assert (delta == (m.hires - m.exits).iloc[1:]).all()


def test_attrition_and_calibration_are_sane(data):
    _, ratings, raw = data
    df = M.prep(clean(raw)[0])
    for y in (2022, 2023, 2024, 2025):
        assert 5 < M.annual_attrition(df, y) < 80
    cal = M.calibration(ratings)
    assert set(cal.flag.astype(str)) <= {"harsh", "in line", "lenient"}
    assert abs(cal.deviation.mean()) < 0.5
    assert 0 <= M.early_attrition(df) <= 100
