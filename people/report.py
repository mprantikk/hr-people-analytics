"""Run the full pipeline and write charts, a self-contained HTML report and a JSON summary.

    python -m people.report
"""

from __future__ import annotations

import base64
import html
import io
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from . import metrics as M  # noqa: E402
from .quality import accuracy, clean, consistency, rule_summary  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BLUE, ORANGE, AQUA, GREY, RED = "#257de0", "#f47230", "#00b894", "#c2c2c2", "#dc3c3d"
INK, INK2 = "#191919", "#666666"
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": GREY,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.grid": True, "grid.color": "#ececec",
                     "axes.axisbelow": True, "figure.dpi": 150})


def _save(fig, name) -> str:
    (ROOT / "docs").mkdir(exist_ok=True)
    fig.savefig(ROOT / "docs" / name, bbox_inches="tight")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def chart_headcount(m: pd.DataFrame) -> str:
    fig, (top, bot) = plt.subplots(2, 1, figsize=(8, 4.6), sharex=True, gridspec_kw={"height_ratios": [1.3, 1]})
    x = list(range(len(m)))
    top.plot(x, m.headcount, color=BLUE, lw=2)
    top.text(x[-1], m.headcount.iloc[-1] * 1.03, f"{m.headcount.iloc[-1]}", ha="right", fontweight="bold", fontsize=9)
    top.set_ylim(0, m.headcount.max() * 1.15)
    top.set_title("Headcount (top) and monthly hires vs exits (bottom)", loc="left", fontweight="bold", color=INK)
    top.grid(axis="x", visible=False)
    bot.bar([i - 0.2 for i in x], m.hires, color=AQUA, width=0.4, label="Hires")
    bot.bar([i + 0.2 for i in x], m.exits, color=ORANGE, width=0.4, label="Exits")
    bot.legend(frameon=False, loc="upper right", ncol=2)
    bot.grid(axis="x", visible=False)
    bot.set_xticks(x[::6], m.month[::6])
    return _save(fig, "headcount_flow.png")


def chart_dept(d: pd.DataFrame, year: int, company: float) -> str:
    d = d.sort_values("attrition_pct")
    fig, ax = plt.subplots(figsize=(8, 3.6))
    bars = ax.barh(d.department, d.attrition_pct, color=[RED if v > company * 1.2 else BLUE for v in d.attrition_pct], height=0.6)
    ax.axvline(company, color=INK2, ls="--", lw=1)
    ax.text(company, len(d) - 0.4, f" company {company}%", color=INK2, fontsize=9)
    for b, v in zip(bars, d.attrition_pct):
        ax.text(v + 0.4, b.get_y() + b.get_height() / 2, f"{v}%", va="center", fontsize=9)
    ax.grid(axis="y", visible=False)
    ax.set_title(f"Attrition by department, {year}", loc="left", fontweight="bold", color=INK)
    return _save(fig, "attrition_by_department.png")


def chart_calibration(cal: pd.DataFrame, company_mean: float) -> str:
    c = cal.reset_index()
    fig, ax = plt.subplots(figsize=(8, 3.4))
    colors = c.flag.map({"harsh": ORANGE, "in line": GREY, "lenient": BLUE}).tolist()
    ax.bar(range(len(c)), c.deviation, color=colors, width=0.8)
    ax.axhline(0, color=INK2, lw=1)
    ax.set_xticks([])
    ax.set_xlabel("Managers (each bar = one manager with 15+ ratings)")
    ax.set_ylabel("Avg rating vs company")
    for label, color in [("harsh", ORANGE), ("in line", GREY), ("lenient", BLUE)]:
        ax.bar(0, 0, color=color, label=label)
    ax.legend(frameon=False, loc="upper left", ncol=3)
    ax.set_title(f"Appraisal calibration (company mean {company_mean:.2f} / 5)", loc="left", fontweight="bold", color=INK)
    return _save(fig, "calibration.png")


def run(year: int = 2025) -> dict:
    raw = pd.read_csv(ROOT / "data" / "hris_extract_raw.csv", dtype=str, keep_default_na=False).replace({"manager_id": {"": None}})
    ratings = pd.read_csv(ROOT / "data" / "appraisals.csv")
    cleaned, log = clean(raw)
    (ROOT / "reports").mkdir(exist_ok=True)
    cleaned.to_csv(ROOT / "reports" / "hris_clean.csv", index=False)
    df = M.prep(cleaned)
    m = M.monthly(df)
    dept = M.attrition_by(df, "department", year)
    cal = M.calibration(ratings)
    s = {
        "accuracy_before": accuracy(raw), "accuracy_after": accuracy(cleaned),
        "consistency_before": consistency(raw), "consistency_after": consistency(cleaned),
        "headcount_end": int(m.headcount.iloc[-1]),
        "attrition_by_year": {y: M.annual_attrition(df, y) for y in (2022, 2023, 2024, 2025)},
        "early_attrition_pct": M.early_attrition(df),
        "top_exit_reasons": M.exit_reasons(df).head(3).to_dict(),
        "highest_attrition_dept": dept.iloc[0].to_dict(),
        "manager_effect": M.manager_effect(df, ratings, cal).to_dict(orient="records"),
        "calibration_flags": cal.flag.value_counts().to_dict(),
        "rating_vs_exit": M.rating_vs_exit(df, ratings).reset_index().to_dict(orient="records"),
        "cleaning_log": log,
    }
    imgs = [chart_headcount(m), chart_dept(dept, year, s["attrition_by_year"][year]), chart_calibration(cal, ratings.rating.mean())]
    (ROOT / "reports" / "summary.json").write_text(json.dumps(s, indent=2, default=str))
    (ROOT / "reports" / "people_report.html").write_text(render(s, rule_summary(raw, cleaned), imgs, year))
    return s


def render(s, rules, imgs, year) -> str:
    me = {r["manager_style"]: r["annualised_attrition_pct"] for r in s["manager_effect"]}
    kpi = [(f"{s['headcount_end']}", "Headcount, Dec 2025"), (f"{s['attrition_by_year'][year]}%", f"Attrition {year}"),
           (f"{s['early_attrition_pct']}%", "of leavers left within 6 months"),
           (f"{s['accuracy_before']}% → {s['accuracy_after']}%", "HRIS record accuracy")]
    rows = "".join(f"<tr><td>{html.escape(r.rule.replace('_', ' '))}</td><td>{r.before}</td><td>{r.after}</td></tr>" for r in rules.itertuples())
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>People analytics report</title><style>
body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f5f6f8;color:#191919}}
header{{background:#0f172a;color:#fff;padding:24px 32px}} header p{{color:#94a3b8;margin:6px 0 0}}
main{{max-width:980px;margin:0 auto;padding:24px}} .k{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}}
.c{{background:#fff;border:1px solid #e6e6e6;border-radius:12px;padding:16px;margin-bottom:16px}} .v{{font-size:24px;font-weight:700}}
.l{{font-size:12px;color:#666;text-transform:uppercase;letter-spacing:.04em}} img{{max-width:100%}}
table{{border-collapse:collapse;width:100%;font-size:14px}} td,th{{padding:6px 8px;border-bottom:1px solid #eee;text-align:right}} td:first-child,th:first-child{{text-align:left}}
</style></head><body><header><h1 style="margin:0;font-size:22px">People analytics report</h1><p>HRIS data quality · headcount & attrition · appraisal calibration · synthetic data</p></header>
<main><div class="k">{''.join(f'<div class="c"><div class="v">{v}</div><div class="l">{l}</div></div>' for v, l in kpi)}</div>
<div class="c"><img src="data:image/png;base64,{imgs[0]}" alt="Headcount flow"></div>
<div class="c"><img src="data:image/png;base64,{imgs[1]}" alt="Attrition by department"></div>
<div class="c"><img src="data:image/png;base64,{imgs[2]}" alt="Calibration"><p>Teams under harsh raters lost people at <b>{me.get('harsh', '–')}%</b> a year vs <b>{me.get('in line', '–')}%</b> under in-line raters.</p></div>
<div class="c"><h2 style="font-size:16px">HRIS data quality, before and after cleaning</h2><table><tr><th>Rule</th><th>Before</th><th>After</th></tr>{rows}</table>
<ul>{''.join(f'<li>{html.escape(x)}</li>' for x in s['cleaning_log'])}</ul></div></main></body></html>"""


if __name__ == "__main__":
    out = run()
    print(json.dumps({k: v for k, v in out.items() if k != "cleaning_log"}, indent=1, default=str))
