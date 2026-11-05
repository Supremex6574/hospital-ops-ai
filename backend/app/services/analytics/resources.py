"""
Resource utilization: beds, doctors, nurses, lab and equipment, per department and over time.
Staff load is judged against the planning norms in config.py (assumptions for this prototype, not clinical standards).
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.services.analytics.common import (
    bucket, department_types, get_thresholds, is_hourly, kpi, label, load_frame, num, previous_window,
    hospital_occupancy, window,
)
from app.services.ingestion.features import norms_for

KINDS = ("beds", "doctors", "nurses", "lab")


def _status(value, warn, crit) -> str:
    if value is None:
        return "unknown"
    return "critical" if value >= crit else "warning" if value >= warn else "normal"


def _with_norms(df: pd.DataFrame, types: dict[str, str]) -> pd.DataFrame:
    n = {d: norms_for(d, types.get(d)) for d in df["department"].unique()}
    df = df.copy()
    df["doc_norm"] = df["department"].map(lambda d: n[d][0])
    df["nurse_norm"] = df["department"].map(lambda d: n[d][1])
    df["doc_pct"] = df["patients_per_doctor"] / df["doc_norm"] * 100
    df["nurse_pct"] = df["patients_per_nurse"] / df["nurse_norm"] * 100
    return df


def _share(mask: pd.Series) -> float | None:
    return float(mask.mean() * 100) if len(mask) else None


def compute_compare(db: Session, date_from: date | None, date_to: date | None) -> dict:
    """One row per department with every resource side by side (the cross-department comparison)."""
    full = load_frame(db, date_from, date_to)
    if full.empty:
        return {"has_data": False}
    th, types = get_thresholds(db), department_types(db)
    df = _with_norms(full, types)
    rows = []
    for name, g in df.groupby("department"):
        has_beds = bool((g["total_beds"] > 0).any())
        occ = g["bed_occupancy_pct"] if has_beds else pd.Series(dtype=float)
        rows.append({
            "department_id": int(g["department_id"].iloc[0]), "department": name, "has_beds": has_beds,
            "bed_occupancy_pct": num(occ.mean()) if has_beds else None,
            "doctor_load_pct": num(g["doc_pct"].mean(), 0), "nurse_load_pct": num(g["nurse_pct"].mean(), 0),
            "lab_util_pct": num(g.loc[g["lab_capacity"] > 0, "lab_util_pct"].mean()),
            "equipment_util_pct": num(g.loc[g["equipment_total"] > 0, "equipment_util_pct"].mean()),
            "resource_util_pct": num(g["resource_util_pct"].mean()),
            "workload_index": num(g["workload_index"].mean(), 0),
            "status": _status(float(g["workload_index"].mean()), 60, 80),
        })
    rows.sort(key=lambda r: -(r["workload_index"] or 0))
    return {
        "has_data": True, "departments": rows,
        "notes": {
            "load_pct": "100% = the planning norm for that department (patients per doctor or nurse).",
            "workload": "Workload index 0-100 blends bed, doctor, nurse and waiting-time pressure; 60 and 80 mark warning and critical.",
        },
        "thresholds": {"occupancy_warning_pct": th["occupancy_warning_pct"], "occupancy_critical_pct": th["occupancy_critical_pct"],
                       "lab_overload_pct": th["lab_overload_pct"]},
    }


def compute_detail(db: Session, kind: str, date_from: date | None, date_to: date | None, department_id: int | None) -> dict:
    full = load_frame(db, date_from, date_to)
    if full.empty:
        return {"has_data": False}
    th, types = get_thresholds(db), department_types(db)
    df = _with_norms(full, types)
    scope = df if not department_id else df[df["department_id"] == department_id]
    if scope.empty:
        return {"has_data": False}
    hourly = is_hourly(scope)

    prev_scope = None
    win = previous_window(date_from, date_to)
    if win:
        p = _with_norms(load_frame(db, win[0], win[1]), types)
        p = p if not department_id else p[p["department_id"] == department_id]
        prev_scope = p if not p.empty else None

    # which column carries the "utilization" for this resource, and where overload begins
    if kind == "beds":
        col, warn, crit, unit = "bed_occupancy_pct", th["occupancy_warning_pct"], th["occupancy_critical_pct"], "%"
        base = scope[scope["total_beds"] > 0]
        pbase = None if prev_scope is None else prev_scope[prev_scope["total_beds"] > 0]
    elif kind in ("doctors", "nurses"):
        col = "doc_pct" if kind == "doctors" else "nurse_pct"
        warn, crit, unit = 100.0, 130.0, "% of norm"
        base, pbase = scope, prev_scope
    else:
        col, warn, crit, unit = "lab_util_pct", th["lab_overload_pct"], th["lab_overload_pct"] + 10, "%"
        base = scope[scope["lab_capacity"] > 0]
        pbase = None if prev_scope is None else prev_scope[prev_scope["lab_capacity"] > 0]
    if base.empty:
        return {"has_data": True, "kind": kind, "applicable": False,
                "message": "The selected scope has no " + {"beds": "beds", "lab": "lab capacity"}.get(kind, "staff data") + "."}

    def mean_of(d):
        return None if d is None or d.empty else float(d[col].mean())

    # the series the page charts: hospital-wide beds use true occupancy (occupied / total), the rest the mean across departments
    if kind == "beds":
        series_src = hospital_occupancy(scope) if not department_id else base.set_index("timestamp")[col]
    else:
        series_src = base.groupby("timestamp")[col].mean()

    kpis = {
        "average": kpi(mean_of(base), mean_of(pbase), 1),
        "peak": num(series_src.max()),
        "hours_over_warning": int((series_src >= warn).sum()),
        "hours_over_critical": int((series_src >= crit).sum()),
        "total_hours": int(len(series_src)),
    }
    if kind == "beds":
        last_ts = base["timestamp"].max()
        last = base[base["timestamp"] == last_ts]
        kpis["current"] = {"occupied": int(last["occupied_beds"].sum()), "total": int(last["total_beds"].sum()),
                           "available": int(last["available_beds"].sum()), "as_of": last_ts.strftime("%Y-%m-%dT%H:00")}
    elif kind in ("doctors", "nurses"):
        staff = "doctors_available" if kind == "doctors" else "nurses_available"
        kpis["avg_on_duty"] = num(base.groupby("timestamp")[staff].sum().mean(), 1)
    else:
        kpis["avg_equipment_util_pct"] = num(scope.loc[scope["equipment_total"] > 0, "equipment_util_pct"].mean())

    s = series_src.to_frame("v").reset_index()
    s["_b"] = bucket(s, hourly)
    series = [{"t": label(t, hourly), "value": num(v)} for t, v in s.groupby("_b")["v"].mean().items()]
    if kind == "lab":
        eq = scope[scope["equipment_total"] > 0].groupby("timestamp")["equipment_util_pct"].mean().to_frame("v").reset_index()
        eq["_b"] = bucket(eq, hourly)
        eqm = eq.groupby("_b")["v"].mean()
        for row, (t, v) in zip(series, eqm.reindex(pd.to_datetime([r["t"] for r in series])).items()):
            row["equipment"] = num(v)

    # per-department table (always all departments)
    tab = []
    for name, g in df.groupby("department"):
        if kind == "beds":
            g = g[g["total_beds"] > 0]
        elif kind == "lab":
            g = g[g["lab_capacity"] > 0]
        if g.empty:
            continue
        m = float(g[col].mean())
        row = {"department_id": int(g["department_id"].iloc[0]), "department": name, "average": num(m),
               "peak": num(g[col].max()), "hours_over_warning": int((g[col] >= warn).sum()),
               "hours_over_critical": int((g[col] >= crit).sum()),
               "share_over_warning_pct": num(_share(g[col] >= warn)), "status": _status(m, warn, crit)}
        if kind == "beds":
            row.update(total_beds=int(g["total_beds"].max()), avg_available=num(g["available_beds"].mean(), 1))
        elif kind in ("doctors", "nurses"):
            staff = "doctors_available" if kind == "doctors" else "nurses_available"
            row.update(avg_on_duty=num(g[staff].mean(), 1),
                       norm=g["doc_norm" if kind == "doctors" else "nurse_norm"].iloc[0])
        else:
            row.update(equipment_util_pct=num(g.loc[g["equipment_total"] > 0, "equipment_util_pct"].mean()))
        tab.append(row)
    tab.sort(key=lambda r: -(r["average"] or 0))

    # when does pressure build? average per hour of day for the selected scope
    hp = base.groupby(base["timestamp"].dt.hour)[col].mean()
    hours = [{"hour": h, "value": num(hp.get(h))} for h in range(24)]

    return {
        "has_data": True, "kind": kind, "applicable": True, "unit": unit, "granularity": "hour" if hourly else "day",
        "thresholds": {"warning": warn, "critical": crit},
        "kpis": kpis, "series": series, "departments": tab, "hours": hours,
    }
