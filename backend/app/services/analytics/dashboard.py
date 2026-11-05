"""
Dashboard analytics. Loads the filtered slice of stored data into pandas once and derives every KPI and
chart series from it, so the numbers on the page always agree with each other.

Conventions
- "Today" / "latest" are relative to the data, not the wall clock: the as-of moment is the newest
  timestamp inside the selected range. Historical datasets therefore still show meaningful KPIs.
- Hospital-wide occupancy only counts departments that have beds (OPD is outpatient and has none).
- Waiting time is averaged weighted by arrivals, so a busy hour counts for more than a quiet one.
- Comparison charts (departments) always show every department; the department filter only highlights.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy.orm import Session

from app.services.analytics.common import (
    bucket, change, hospital_occupancy, is_hourly, kpi, label, load_frame, num, peak_heatmap, previous_window,
    weighted_wait,
)


# ------------------------------------------------------------------------------------------ KPIs
def compute_kpis(db: Session, date_from: date | None, date_to: date | None, department_id: int | None) -> dict:
    df = load_frame(db, date_from, date_to, department_id)
    if df.empty:
        return {"has_data": False, "as_of": None}

    prev_df = None
    win = previous_window(date_from, date_to)
    if win:
        prev_df = load_frame(db, win[0], win[1], department_id)
        if prev_df.empty:
            prev_df = None

    as_of = df["timestamp"].max()
    day = as_of.normalize()
    today = df[df["timestamp"].dt.normalize() == day]
    yesterday = df[df["timestamp"].dt.normalize() == day - pd.Timedelta(days=1)]
    now_rows = df[df["timestamp"] == as_of]
    now_beds = now_rows[now_rows["total_beds"] > 0]

    # current bed state at the as-of hour
    occ_now = (now_beds["occupied_beds"].sum() / now_beds["total_beds"].sum() * 100) if len(now_beds) else None
    occ_series = hospital_occupancy(df)
    occ_avg = float(occ_series.mean()) if len(occ_series) else None
    prev_occ = hospital_occupancy(prev_df) if prev_df is not None else pd.Series(dtype=float)

    by_dept = df.groupby(["department_id", "department"])["workload_index"].mean().sort_values(ascending=False)
    top = by_dept.index[0] if len(by_dept) else None

    def prev_sum(col):
        return float(prev_df[col].sum()) if prev_df is not None else None

    return {
        "has_data": True,
        "as_of": as_of.isoformat(),
        "as_of_date": day.date().isoformat(),
        "range": {"from": df["timestamp"].min().isoformat(), "to": as_of.isoformat()},
        "total_patients": kpi(df["arrivals"].sum(), prev_sum("arrivals"), 0),
        "admissions_today": kpi(today["admissions"].sum(), yesterday["admissions"].sum() if len(yesterday) else None, 0),
        "discharges_today": kpi(today["discharges"].sum(), yesterday["discharges"].sum() if len(yesterday) else None, 0),
        "bed_occupancy_pct": {**kpi(occ_now, None), "range_avg": num(occ_avg),
                              "previous_avg": num(prev_occ.mean()) if len(prev_occ) else None},
        "avg_wait_min": kpi(weighted_wait(df), weighted_wait(prev_df) if prev_df is not None else None),
        "highest_workload": (
            {"department_id": int(top[0]), "department": top[1], "workload_index": num(by_dept.iloc[0])} if top else None
        ),
        "available_beds": {"value": int(now_beds["available_beds"].sum()) if len(now_beds) else None,
                           "total_beds": int(now_beds["total_beds"].sum()) if len(now_beds) else None},
        "resource_util_pct": kpi(df["resource_util_pct"].mean(), prev_df["resource_util_pct"].mean() if prev_df is not None else None),
    }


# ----------------------------------------------------------------------------------------- summary
def department_table(df: pd.DataFrame) -> list[dict]:
    rows = []
    for (did, name), g in df.groupby(["department_id", "department"]):
        has_beds = (g["total_beds"] > 0).any()
        rows.append({
            "department_id": int(did),
            "department": name,
            "arrivals": int(g["arrivals"].sum()),
            "workload_index": num(g["workload_index"].mean()),
            "resource_util_pct": num(g["resource_util_pct"].mean()),
            "bed_occupancy_pct": num(g["bed_occupancy_pct"].mean()) if has_beds else None,
            "avg_wait_min": num(weighted_wait(g)),
            "patients_per_doctor": num(g["patients_per_doctor"].mean(), 2),
            "patients_per_nurse": num(g["patients_per_nurse"].mean(), 2),
            "lab_util_pct": num(g["lab_util_pct"].mean()),
        })
    return sorted(rows, key=lambda r: r["department_id"])


def compute_summary(db: Session, date_from: date | None, date_to: date | None, department_id: int | None) -> dict:
    everything = load_frame(db, date_from, date_to, None)  # comparisons always cover every department
    if everything.empty:
        return {"has_data": False}
    scope = everything[everything["department_id"] == department_id] if department_id else everything
    if scope.empty:
        return {"has_data": False}

    hourly = is_hourly(scope)

    b = bucket(scope, hourly)
    flow = scope.groupby(b)[["arrivals", "admissions", "discharges"]].sum()
    flow_rows = [
        {"t": label(t, hourly), "arrivals": int(r.arrivals), "admissions": int(r.admissions), "discharges": int(r.discharges)}
        for t, r in flow.iterrows()
    ]

    occ = hospital_occupancy(scope)
    occ_rows = []
    if len(occ):
        ob = occ.groupby(occ.index.floor("h") if hourly else occ.index.normalize()).mean()
        occ_rows = [{"t": label(t, hourly), "occupancy_pct": num(v)} for t, v in ob.items()]

    wait_rows = []
    for t, g in scope.groupby(b):
        wait_rows.append({"t": label(t, hourly), "avg_wait_min": num(weighted_wait(g))})

    return {
        "has_data": True,
        "granularity": "hourly" if hourly else "daily",
        "department_id": department_id,
        "flow": flow_rows,
        "occupancy": occ_rows,
        "wait": wait_rows,
        "departments": department_table(everything),
        "heatmap": peak_heatmap(scope),
    }
