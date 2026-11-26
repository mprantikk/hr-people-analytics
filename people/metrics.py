"""Workforce metrics from the cleaned HRIS table and appraisal history."""

from __future__ import annotations

import pandas as pd

AS_OF = pd.Timestamp("2025-12-31")


def prep(hris: pd.DataFrame) -> pd.DataFrame:
    df = hris.copy()
    df["hire_date"] = pd.to_datetime(df.hire_date)
    df["exit_date"] = pd.to_datetime(df.exit_date.replace("", None))
    df["exit_reason"] = df.exit_reason.replace("", None)
    return df


def monthly(df: pd.DataFrame, start="2022-01", end="2025-12") -> pd.DataFrame:
    """Headcount at month end, hires, exits and monthly attrition rate."""
    rows = []
    for m in pd.period_range(start, end, freq="M"):
        m_start, m_end = m.start_time, m.end_time
        active = (df.hire_date <= m_end) & (df.exit_date.isna() | (df.exit_date > m_end))
        active_start = (df.hire_date < m_start) & (df.exit_date.isna() | (df.exit_date >= m_start))
        exits = df.exit_date.between(m_start, m_end).sum()
        avg_hc = (active.sum() + active_start.sum()) / 2
        rows.append({"month": str(m), "headcount": int(active.sum()), "hires": int(df.hire_date.between(m_start, m_end).sum()),
                     "exits": int(exits), "attrition_pct": round(100 * exits / avg_hc, 2) if avg_hc else 0.0})
    return pd.DataFrame(rows)


def annual_attrition(df: pd.DataFrame, year: int) -> float:
    m = monthly(df, f"{year}-01", f"{year}-12")
    avg_hc = m.headcount.mean()
    return round(100 * m.exits.sum() / avg_hc, 1)


def attrition_by(df: pd.DataFrame, col: str, year: int) -> pd.DataFrame:
    out = []
    for key, g in df.groupby(col):
        m = monthly(g, f"{year}-01", f"{year}-12")
        out.append({col: key, "avg_headcount": round(m.headcount.mean(), 1), "exits": int(m.exits.sum()),
                    "attrition_pct": round(100 * m.exits.sum() / m.headcount.mean(), 1) if m.headcount.mean() else 0})
    return pd.DataFrame(out).sort_values("attrition_pct", ascending=False).reset_index(drop=True)


def early_attrition(df: pd.DataFrame) -> float:
    """Share of leavers who left within 6 months of joining (hires since 2022)."""
    leavers = df[df.exit_date.notna() & (df.hire_date >= "2022-01-01")]
    return round(100 * ((leavers.exit_date - leavers.hire_date).dt.days < 183).mean(), 1)


def exit_reasons(df: pd.DataFrame) -> pd.Series:
    return df.exit_reason.dropna().value_counts(normalize=True).mul(100).round(1)


def calibration(ratings: pd.DataFrame, min_ratings: int = 15) -> pd.DataFrame:
    """Each manager's average rating vs the company mean; flags lenient and harsh raters."""
    company = ratings.rating.mean()
    sd = ratings.rating.std()
    g = ratings.dropna(subset=["manager_id"]).groupby("manager_id").rating.agg(["count", "mean"])
    g = g[g["count"] >= min_ratings].copy()
    g["deviation"] = (g["mean"] - company).round(2)
    g["flag"] = pd.cut(g.deviation, [-9, -0.5 * sd, 0.5 * sd, 9], labels=["harsh", "in line", "lenient"])
    return g.sort_values("deviation").round(2)


def rating_vs_exit(df: pd.DataFrame, ratings: pd.DataFrame) -> pd.DataFrame:
    """Leave rate within 12 months of an appraisal, by rating."""
    r = ratings.merge(df[["employee_id", "exit_date"]], on="employee_id")
    year = r.cycle.str[:4].astype(int)
    r["cycle_end"] = pd.to_datetime(year.astype(str) + r.cycle.str[-2:].map({"H1": "-06-30", "H2": "-12-31"}))
    r = r[r.cycle_end <= AS_OF - pd.DateOffset(months=12)]
    r["left_12m"] = r.exit_date.notna() & (r.exit_date > r.cycle_end) & (r.exit_date <= r.cycle_end + pd.DateOffset(months=12))
    return r.groupby("rating").agg(appraisals=("left_12m", "size"), leave_rate_pct=("left_12m", "mean")) \
            .assign(leave_rate_pct=lambda x: (x.leave_rate_pct * 100).round(1))


def manager_effect(df: pd.DataFrame, ratings: pd.DataFrame, cal: pd.DataFrame) -> pd.DataFrame:
    """Attrition of teams under harsh vs other managers (since 2023)."""
    team = df[df.manager_id.isin(cal.index)].merge(cal[["flag"]], left_on="manager_id", right_index=True)
    out = []
    for flag, g in team.groupby("flag", observed=True):
        m = monthly(g, "2023-01", "2025-12")
        out.append({"manager_style": str(flag), "people": len(g),
                    "annualised_attrition_pct": round(100 * m.exits.sum() / m.headcount.mean() / 3, 1)})
    return pd.DataFrame(out)
