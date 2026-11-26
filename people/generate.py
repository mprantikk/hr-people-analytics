"""Synthetic HRIS extract and appraisal history for a fast-growing tech company.

About 1,000 people across 2022-2025, with realistic hiring waves, attrition
that depends on tenure, rating and team, and two appraisal cycles a year.
The raw extract carries the defects HRIS exports usually have (duplicate
rows, free-text department names, mixed date formats, status fields that
contradict exit dates, managers who no longer exist).
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent.parent / "data"
START, END = date(2022, 1, 1), date(2025, 12, 31)
DEPTS = {  # canonical: (raw variants, hiring weight, base monthly exit hazard)
    "Engineering": (["Engineering", "Engg", "ENGINEERING", "Tech"], 0.22, 0.012),
    "Sales": (["Sales", "SALES", "Sales & BD", "sales"], 0.24, 0.022),
    "Operations": (["Operations", "Ops", "OPERATIONS"], 0.26, 0.018),
    "Customer Support": (["Customer Support", "CS", "Support", "customer support"], 0.14, 0.025),
    "Finance": (["Finance", "Finance & Accounts", "FIN"], 0.06, 0.008),
    "People": (["People", "HR", "Human Resources"], 0.05, 0.010),
    "Product": (["Product", "PRODUCT", "Product Mgmt"], 0.03, 0.011),
}
GRADES = ["G1", "G2", "G3", "G4", "G5"]
LOCATIONS = ["Dhaka HQ", "Dhaka HQ", "Dhaka HQ", "Chattogram", "Sylhet"]
EXIT_REASONS = ["Better offer", "Career growth", "Relocation", "Higher studies", "Performance", "Personal", "Workload"]
DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%b-%Y"]


def generate(seed: int = 42) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = random.Random(seed)
    people, ratings = [], []
    eid = 0
    managers: dict[str, list[int]] = {d: [] for d in DEPTS}

    def new_person(dept: str, hired: date, grade: str) -> dict:
        nonlocal eid
        eid += 1
        mgr = rng.choice(managers[dept]) if managers[dept] else None
        p = {"employee_id": f"E{eid:04d}", "dept": dept, "grade": grade, "hire_date": hired, "exit_date": None,
             "exit_reason": None, "manager": mgr, "location": rng.choice(LOCATIONS),
             "manager_bias": 0.0, "perf": rng.gauss(3.2, 0.6)}
        if grade in ("G4", "G5"):
            managers[dept].append(eid)
            p["manager_bias"] = rng.choice([0, 0, 0, 0.5, -0.4, 0.7])  # some managers rate leniently or harshly
        people.append(p)
        return p

    # founding team / leaders
    for dept in DEPTS:
        for _ in range(3):
            new_person(dept, START - timedelta(days=rng.randint(200, 1500)), rng.choice(["G4", "G5"]))
    for _ in range(320):
        dept = rng.choices(list(DEPTS), weights=[v[1] for v in DEPTS.values()])[0]
        new_person(dept, START - timedelta(days=rng.randint(30, 1200)), rng.choices(GRADES, weights=[30, 35, 20, 10, 5])[0])

    month = START
    by_id = {}
    while month <= END:
        # hiring wave: strong in 2022, freeze mid-2023, recovery 2024-25
        wave = {2022: 24, 2023: 10, 2024: 16, 2025: 19}[month.year]
        if month.year == 2023 and 4 <= month.month <= 9:
            wave = 3
        for _ in range(max(0, int(rng.gauss(wave, 3)))):
            dept = rng.choices(list(DEPTS), weights=[v[1] for v in DEPTS.values()])[0]
            new_person(dept, month + timedelta(days=rng.randint(0, 27)), rng.choices(GRADES, weights=[45, 33, 15, 5, 2])[0])
        # exits
        for p in people:
            if p["exit_date"] or p["hire_date"] > month:
                continue
            tenure_m = (month - p["hire_date"]).days / 30.4
            hazard = DEPTS[p["dept"]][2]
            hazard *= 1.7 if tenure_m < 6 else 1.25 if tenure_m < 12 else 1.0     # early attrition
            hazard *= 1.6 if p["perf"] < 2.6 else 1.3 if p["perf"] > 4.0 else 1.0  # low performers pushed, stars poached
            hazard *= 1.35 if p["manager_bias"] < 0 else 1.0                       # harsh managers lose people
            if month.year == 2022:
                hazard *= 1.3                                                      # hot market
            if rng.random() < hazard:
                p["exit_date"] = month + timedelta(days=rng.randint(0, 27))
                p["exit_reason"] = "Performance" if p["perf"] < 2.4 and rng.random() < 0.6 else \
                    rng.choices(EXIT_REASONS, weights=[30, 25, 8, 7, 3, 12, 15])[0]
        # appraisal cycles in June and December
        if month.month in (6, 12):
            cycle = f"{month.year}-H{1 if month.month == 6 else 2}"
            for p in people:
                if p["hire_date"] <= month - timedelta(days=90) and (not p["exit_date"] or p["exit_date"] > month):
                    mgr = by_id.get(p["manager"])
                    bias = mgr["manager_bias"] if mgr else 0
                    score = min(5, max(1, round(p["perf"] + bias + rng.gauss(0, 0.35))))
                    ratings.append({"employee_id": p["employee_id"], "cycle": cycle,
                                    "manager_id": f"E{p['manager']:04d}" if p["manager"] else None,
                                    "rating": score, "self_rating": min(5, max(1, round(p["perf"] + 0.5 + rng.gauss(0, 0.4))))})
        by_id = {int(p["employee_id"][1:]): p for p in people}
        month = date(month.year + (month.month == 12), month.month % 12 + 1, 1)

    clean = pd.DataFrame([{
        "employee_id": p["employee_id"], "department": p["dept"], "grade": p["grade"],
        "manager_id": f"E{p['manager']:04d}" if p["manager"] else None, "location": p["location"],
        "hire_date": p["hire_date"], "exit_date": p["exit_date"], "exit_reason": p["exit_reason"],
        "status": "Exited" if p["exit_date"] else "Active",
        "email": f"{p['employee_id'].lower()}@example.com",
    } for p in people])
    return clean, pd.DataFrame(ratings)


def roughen(clean: pd.DataFrame, seed: int = 7) -> pd.DataFrame:
    """Turn the clean table into a realistic messy HRIS export."""
    rng = random.Random(seed)
    raw = clean.copy().astype(object)
    raw["department"] = raw.department.map(lambda d: rng.choice(DEPTS[d][0]))
    for col in ("hire_date", "exit_date"):
        raw[col] = raw[col].map(lambda d: d.strftime(rng.choice(DATE_FORMATS)) if isinstance(d, date) else "")
    n = len(raw)
    idx = lambda k: rng.sample(range(n), k)
    for i in idx(int(n * 0.03)):                       # status not updated after exit
        if raw.at[i, "status"] == "Exited":
            raw.at[i, "status"] = "Active"
    for i in idx(int(n * 0.02)):
        raw.at[i, "grade"] = ""                         # missing grade
    for i in idx(int(n * 0.015)):
        raw.at[i, "manager_id"] = f"E{rng.randint(5000, 5999)}"   # manager not in system
    for i in idx(int(n * 0.01)):
        raw.at[i, "email"] = raw.at[i, "email"].replace("@", " at ")  # malformed email
    for i in idx(8):
        raw.at[i, "location"] = raw.at[i, "location"].upper() + " "
    dupes = raw.sample(n=int(n * 0.02), random_state=seed)            # double-entered records
    return pd.concat([raw, dupes], ignore_index=True)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    clean, ratings = generate()
    roughen(clean).to_csv(OUT / "hris_extract_raw.csv", index=False)
    ratings.to_csv(OUT / "appraisals.csv", index=False)
    print(f"employees={len(clean)} raw_rows={len(roughen(clean))} ratings={len(ratings)} "
          f"active_end={int((clean.status == 'Active').sum())}")


if __name__ == "__main__":
    main()
