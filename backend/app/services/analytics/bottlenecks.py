"""
Bottleneck detection. Transparent rules (no black box), all thresholds come from the settings table.

Each department-hour is checked for six conditions and given a severity of 0 (fine), 1 (warning) or 2 (critical):
  occupancy  bed occupancy >= warning / critical threshold                       (departments with beds only)
  wait       waiting time far above that department's own typical value for the same weekday and hour
             (robust z-score from median and MAD >= threshold, and at least 1.25x typical; critical at 2x)
  arrivals   arrivals over the last 3 hours >= growth ratio x the typical value for that weekday and hour
             (needs at least 6 patients; critical at 1.6x)
  doctors / nurses   patients per doctor or nurse >= 130% of the planning norm (critical at 150%)
  lab        lab tests ordered >= overload threshold % of capacity (critical at 100%)
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import HospitalData

from app.services.analytics.common import (
    bucket, department_types, get_thresholds, is_hourly, label, load_frame, num, window,
)
from app.services.analytics.resources import _with_norms

CONDITIONS = ["occupancy", "wait", "arrivals", "doctors", "nurses", "lab"]
LABELS = {"occupancy": "Bed occupancy", "wait": "Waiting time", "arrivals": "Arrival surge",
          "doctors": "Doctor load", "nurses": "Nurse load", "lab": "Lab overload"}
MAD_SCALE = 1.4826
WAIT_MIN_RATIO, WAIT_CRIT_RATIO = 1.25, 2.0
ARR_MIN_VOLUME, ARR_CRIT_RATIO = 6, 1.6
STAFF_WARN, STAFF_CRIT = 130.0, 150.0
MIN_EPISODE_HOURS = 3


def _sev(values: pd.Series, warn: float, crit: float) -> pd.Series:
    return np.where(values >= crit, 2, np.where(values >= warn, 1, 0))


def flag_frame(full: pd.DataFrame, th: dict[str, float], types: dict[str, str]) -> pd.DataFrame:
    """Adds severity columns sev_<condition> (0/1/2) plus the measures behind them. `full` = whole history."""
    df = _with_norms(full, types).sort_values(["department", "timestamp"]).reset_index(drop=True)
    df["dow"], df["hour"] = df["timestamp"].dt.dayofweek, df["timestamp"].dt.hour
    keys = ["department", "dow", "hour"]

    # occupancy
    occ = df["bed_occupancy_pct"].where(df["total_beds"] > 0)
    df["sev_occupancy"] = _sev(occ.fillna(-1), th["occupancy_warning_pct"], th["occupancy_critical_pct"])

    # waiting time vs the department's own same-weekday-and-hour typical value
    med = df.groupby(keys)["avg_wait_min"].transform("median")
    mad = (df["avg_wait_min"] - med).abs().groupby([df[k] for k in keys]).transform("median")
    scale = np.maximum.reduce([mad * MAD_SCALE, med * 0.1, np.ones(len(df))])
    df["wait_typical"] = med
    df["wait_z"] = (df["avg_wait_min"] - med) / scale
    ratio = df["avg_wait_min"] / med.where(med > 0)
    df["sev_wait"] = np.where((df["wait_z"] >= th["wait_zscore_threshold"]) & (ratio >= WAIT_MIN_RATIO),
                              np.where(ratio >= WAIT_CRIT_RATIO, 2, 1), 0)

    # arrival growth: 3-hour volume against the typical 3-hour volume for that weekday and hour
    roll = df.groupby("department")["arrivals"].transform(lambda s: s.rolling(3, min_periods=3).sum())
    base = roll.groupby([df[k] for k in keys]).transform("median")
    df["arrivals_3h"], df["arrivals_typical_3h"] = roll, base
    r = roll / base.where(base > 0)
    df["arrivals_ratio"] = r
    ok = (roll >= ARR_MIN_VOLUME) & (r >= th["arrival_growth_ratio"])
    df["sev_arrivals"] = np.where(ok, np.where(r >= ARR_CRIT_RATIO, 2, 1), 0)

    df["sev_doctors"] = _sev(df["doc_pct"].fillna(-1), STAFF_WARN, STAFF_CRIT)
    df["sev_nurses"] = _sev(df["nurse_pct"].fillna(-1), STAFF_WARN, STAFF_CRIT)
    lab = df["lab_util_pct"].where(df["lab_capacity"] > 0)
    df["sev_lab"] = _sev(lab.fillna(-1), th["lab_overload_pct"], 100.0)
    df["max_sev"] = df[[f"sev_{c}" for c in CONDITIONS]].max(axis=1)
    return df


def pressures(row) -> dict[str, float]:
    """How close each resource is to its warning level (1.0 = at the warning level). Used to name the limiting resource."""
    p = {}
    if row["total_beds"] > 0 and pd.notna(row["bed_occupancy_pct"]):
        p["occupancy"] = row["bed_occupancy_pct"] / row["_warn_occ"]
    if pd.notna(row["doc_pct"]):
        p["doctors"] = row["doc_pct"] / 100
    if pd.notna(row["nurse_pct"]):
        p["nurses"] = row["nurse_pct"] / 100
    if row["lab_capacity"] > 0 and pd.notna(row["lab_util_pct"]):
        p["lab"] = row["lab_util_pct"] / row["_warn_lab"]
    return p


def describe(cond: str, row, th) -> tuple[str, float | None, float | None]:
    """Plain-language message, measured value, threshold for one active condition."""
    sev = int(row[f"sev_{cond}"])
    if cond == "occupancy":
        return (f"Bed occupancy is {row['bed_occupancy_pct']:.0f}% ({int(row['occupied_beds'])} of {int(row['total_beds'])} beds)",
                float(row["bed_occupancy_pct"]), th["occupancy_critical_pct"] if sev == 2 else th["occupancy_warning_pct"])
    if cond == "wait":
        return (f"Waiting time is {row['avg_wait_min']:.0f} min, about {row['avg_wait_min'] / row['wait_typical']:.1f}x the usual {row['wait_typical']:.0f} min for this weekday and hour",
                float(row["avg_wait_min"]), float(row["wait_typical"]))
    if cond == "arrivals":
        return (f"Arrivals over the last 3 hours are {row['arrivals_3h']:.0f}, {row['arrivals_ratio']:.1f}x the usual {row['arrivals_typical_3h']:.0f}",
                float(row["arrivals_3h"]), float(row["arrivals_typical_3h"]))
    if cond in ("doctors", "nurses"):
        who, col, norm = ("doctor", "doc_pct", row["doc_norm"]) if cond == "doctors" else ("nurse", "nurse_pct", row["nurse_norm"])
        return (f"Load per {who} is {row[col]:.0f}% of the planning norm ({norm:g} patients per {who})", float(row[col]), STAFF_WARN)
    return (f"Lab tests ordered are {row['lab_util_pct']:.0f}% of lab capacity", float(row["lab_util_pct"]),
            th["lab_overload_pct"] if sev == 1 else 100.0)


def _episodes(flagged: pd.DataFrame, limit: int = 10) -> list[dict]:
    """Runs of consecutive flagged hours in one department (gaps of 1 hour are bridged), most critical hours first."""
    if flagged.empty:
        return []
    g = flagged.sort_values(["department", "timestamp"]).copy()
    new_run = (g["department"] != g["department"].shift()) | (g["timestamp"].diff() > pd.Timedelta(hours=2))
    g["run"] = new_run.cumsum()
    g["_crit"] = (g["max_sev"] == 2).astype(int)
    g["_occ"] = g["bed_occupancy_pct"].where(g["total_beds"] > 0)
    for c in CONDITIONS:
        g[f"_n_{c}"] = (g[f"sev_{c}"] > 0).astype(int)
    agg = g.groupby("run").agg(
        department=("department", "first"), start=("timestamp", "min"), end=("timestamp", "max"), hours=("timestamp", "size"),
        critical_hours=("_crit", "sum"), peak_wait=("avg_wait_min", "max"), peak_occ=("_occ", "max"),
        **{f"n_{c}": (f"_n_{c}", "sum") for c in CONDITIONS})
    agg = agg[agg["hours"] >= MIN_EPISODE_HOURS].sort_values(["critical_hours", "hours"], ascending=False).head(limit)
    out = []
    for _, r in agg.iterrows():
        conds = [c for c in CONDITIONS if r[f"n_{c}"] > 0]
        worst = max(conds, key=lambda c: r[f"n_{c}"])
        out.append({
            "department": r["department"], "start": r["start"].strftime("%Y-%m-%dT%H:00"), "end": r["end"].strftime("%Y-%m-%dT%H:00"),
            "hours": int(r["hours"]), "critical_hours": int(r["critical_hours"]),
            "conditions": [LABELS[c] for c in conds], "main_condition": LABELS[worst],
            "peak_wait_min": num(r["peak_wait"], 0), "peak_occupancy_pct": num(r["peak_occ"], 0),
        })
    return out


def current_status(df: pd.DataFrame, th) -> list[dict]:
    """Per department at the newest hour in `df`: active conditions, severity and the limiting resource."""
    rows = []
    last_ts = df["timestamp"].max()
    for _, r in df[df["timestamp"] == last_ts].iterrows():
        r = r.copy()
        r["_warn_occ"], r["_warn_lab"] = th["occupancy_warning_pct"], th["lab_overload_pct"]
        active = [{"condition": c, "label": LABELS[c], "severity": "critical" if r[f"sev_{c}"] == 2 else "warning",
                   "message": describe(c, r, th)[0]} for c in CONDITIONS if r[f"sev_{c}"] > 0]
        p = pressures(r)
        lim = max(p, key=p.get) if p else None
        rows.append({
            "department_id": int(r["department_id"]), "department": r["department"],
            "severity": "critical" if r["max_sev"] == 2 else "warning" if r["max_sev"] == 1 else "normal",
            "active": active, "limiting_resource": LABELS[lim] if lim else None,
            "pressure_pct": num(p[lim] * 100, 0) if lim else None,
        })
    order = {"critical": 0, "warning": 1, "normal": 2}
    rows.sort(key=lambda x: (order[x["severity"]], -(x["pressure_pct"] or 0)))
    return rows


_CACHE: dict = {}


def flagged_history(db: Session) -> tuple[pd.DataFrame, dict[str, float]]:
    """Flagged frame for the whole stored history, cached until the data or the thresholds change."""
    th = get_thresholds(db)
    key = (db.scalar(select(func.count(HospitalData.id))), db.scalar(select(func.max(HospitalData.id))),
           tuple(sorted(th.items())), tuple(sorted(department_types(db).items())))
    if _CACHE.get("key") != key:
        full = load_frame(db, None, None, None)
        _CACHE.clear()
        if full.empty:
            return full, th
        _CACHE.update(key=key, df=flag_frame(full, th, department_types(db)))
    return _CACHE["df"], th


def compute_bottlenecks(db: Session, date_from: date | None, date_to: date | None, department_id: int | None) -> dict:
    flagged_all, th = flagged_history(db)
    if flagged_all.empty:
        return {"has_data": False}
    cur = window(flagged_all, date_from, date_to)
    if cur.empty:
        return {"has_data": False}
    scoped = cur if not department_id else cur[cur["department_id"] == department_id]
    hourly = is_hourly(cur)

    # one row per department x condition: hours at warning / critical (all departments always)
    matrix = []
    for name, g in cur.groupby("department"):
        row = {"department_id": int(g["department_id"].iloc[0]), "department": name, "hours": int(len(g)),
               "flagged_hours": int((g["max_sev"] > 0).sum()), "critical_hours": int((g["max_sev"] == 2).sum())}
        row["flagged_pct"] = num(row["flagged_hours"] / len(g) * 100)
        for c in CONDITIONS:
            row[c] = int((g[f"sev_{c}"] > 0).sum())
        matrix.append(row)
    matrix.sort(key=lambda r: -r["flagged_hours"])

    # trend of flagged department-hours, and when in the day they cluster
    s = scoped.assign(_b=bucket(scoped, hourly)).groupby("_b").agg(
        flagged=("max_sev", lambda x: int((x > 0).sum())), critical=("max_sev", lambda x: int((x == 2).sum())))
    trend = [{"t": label(t, hourly), "flagged": int(r.flagged), "critical": int(r.critical)} for t, r in s.iterrows()]
    hp = scoped.groupby("hour")["max_sev"].apply(lambda x: (x > 0).mean() * 100)
    hours = [{"hour": h, "flagged_pct": num(hp.get(h, 0.0))} for h in range(24)]

    return {
        "has_data": True, "granularity": "hour" if hourly else "day",
        "as_of": cur["timestamp"].max().strftime("%Y-%m-%dT%H:00"),
        "status": current_status(cur, th),
        "summary": {"flagged_hours": int((scoped["max_sev"] > 0).sum()), "critical_hours": int((scoped["max_sev"] == 2).sum()),
                    "total_hours": int(len(scoped)),
                    "worst_department": matrix[0]["department"] if matrix and matrix[0]["flagged_hours"] else None},
        "matrix": matrix, "trend": trend, "hours": hours,
        "episodes": _episodes(scoped[scoped["max_sev"] > 0]),
        "conditions": [{"key": c, "label": LABELS[c]} for c in CONDITIONS],
        "rules": {
            "occupancy": f"Warning from {th['occupancy_warning_pct']:g}%, critical from {th['occupancy_critical_pct']:g}% bed occupancy",
            "wait": f"Waiting time at least {WAIT_MIN_RATIO}x the department's usual value for that weekday and hour and {th['wait_zscore_threshold']:g} or more robust standard deviations above it (critical at {WAIT_CRIT_RATIO:g}x)",
            "arrivals": f"Arrivals over 3 hours at least {th['arrival_growth_ratio']:g}x the usual, with at least {ARR_MIN_VOLUME} patients (critical at {ARR_CRIT_RATIO:g}x)",
            "doctors": f"Patients per doctor at least {STAFF_WARN:g}% of the planning norm (critical at {STAFF_CRIT:g}%)",
            "nurses": f"Patients per nurse at least {STAFF_WARN:g}% of the planning norm (critical at {STAFF_CRIT:g}%)",
            "lab": f"Lab tests ordered at least {th['lab_overload_pct']:g}% of capacity (critical at 100%)",
        },
    }
