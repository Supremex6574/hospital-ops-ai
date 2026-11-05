"""
Derived KPIs (feature engineering). Pure function of a cleaned DataFrame, so the same code serves
file uploads, streamed records and what-if baselines.

Workload index (0-100):
    weighted mean of the components that exist for the row
      bed occupancy      -> occupancy fraction (0..1)
      doctor load        -> min(patients_per_doctor / norm, 1.5) / 1.5
      nurse load         -> min(patients_per_nurse / norm, 1.5) / 1.5
      waiting time       -> min(wait / (2 x department median wait), 1.5) / 1.5
    weights come from the `settings` table (defaults 0.4 / 0.3 / 0.2 / 0.1).
A department running exactly at its staffing norm scores about 67; 100 means 50% beyond the norm.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.config import DEPT_NORMS, TYPE_NORMS

DEFAULT_WEIGHTS = {"bed": 0.4, "doctor": 0.3, "nurse": 0.2, "wait": 0.1}
PEAK_TOP_SHARE = 0.25  # the busiest quarter of hours-of-day (per department) count as peak hours


def norms_for(department: str, dept_type: str | None = None) -> tuple[float, float]:
    if department in DEPT_NORMS:
        return DEPT_NORMS[department]
    return TYPE_NORMS.get(dept_type or "Ward", TYPE_NORMS["Ward"])


def _safe_div(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a / b.where(b > 0)).astype(float)


def compute_features(
    df: pd.DataFrame,
    dept_types: dict[str, str] | None = None,
    weights: dict[str, float] | None = None,
) -> pd.DataFrame:
    """
    df needs: timestamp, department and the canonical numeric columns (as produced by the cleaner).
    Returns a DataFrame aligned to df.index with the derived_metrics columns.
    """
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    dept_types = dept_types or {}
    out = pd.DataFrame(index=df.index)

    has_beds = df["total_beds"] > 0
    out["bed_occupancy_pct"] = (_safe_div(df["occupied_beds"], df["total_beds"]) * 100).clip(0, 100)

    # patient load: bed census where the department has beds, otherwise hourly arrivals (outpatient)
    load = df["occupied_beds"].where(has_beds, df["arrivals"]).astype(float)
    doc_norm = df["department"].map(lambda d: norms_for(d, dept_types.get(d))[0])
    nurse_norm = df["department"].map(lambda d: norms_for(d, dept_types.get(d))[1])

    out["patients_per_doctor"] = _safe_div(load, df["doctors_available"])
    out["patients_per_nurse"] = _safe_div(load, df["nurses_available"])

    doc_load = (out["patients_per_doctor"] / doc_norm).clip(upper=1.5)          # 0..1.5
    nurse_load = (out["patients_per_nurse"] / nurse_norm).clip(upper=1.5)

    out["equipment_util_pct"] = (_safe_div(df["equipment_total"] - df["equipment_available"], df["equipment_total"]) * 100).clip(0, 100)
    out["lab_util_pct"] = (_safe_div(df["lab_tests_ordered"], df["lab_capacity"]) * 100).clip(0, 200)

    # resource utilisation: mean of the utilisation percentages that exist for the row (each capped at 100)
    comps = pd.concat(
        [
            out["bed_occupancy_pct"],
            (doc_load * 100 / 1.0).clip(upper=100),
            (nurse_load * 100 / 1.0).clip(upper=100),
            out["equipment_util_pct"],
            out["lab_util_pct"].clip(upper=100),
        ],
        axis=1,
    )
    out["resource_util_pct"] = comps.mean(axis=1, skipna=True)

    # workload index
    wait_ref = 2 * df.groupby("department")["avg_wait_min"].transform(lambda s: s[s > 0].median() if (s > 0).any() else np.nan)
    wait_n = (_safe_div(df["avg_wait_min"], wait_ref) .clip(upper=1.5) / 1.5)
    parts = pd.concat(
        [
            (out["bed_occupancy_pct"] / 100).rename("bed"),
            (doc_load / 1.5).rename("doctor"),
            (nurse_load / 1.5).rename("nurse"),
            wait_n.rename("wait"),
        ],
        axis=1,
    )
    wts = pd.Series({k: w[k] for k in parts.columns})
    weighted = parts.mul(wts, axis=1)
    wsum = parts.notna().mul(wts, axis=1).sum(axis=1)
    out["workload_index"] = (weighted.sum(axis=1, skipna=True) / wsum.where(wsum > 0) * 100).clip(0, 100)
    idle = (df["arrivals"] == 0) & (load == 0)  # nothing happening (e.g. OPD closed overnight)
    out.loc[idle, "workload_index"] = 0.0

    out["is_peak_hour"] = _peak_hours(df)
    return out.round(3)


def _peak_hours(df: pd.DataFrame) -> pd.Series:
    """Flag hours of day in the top quarter of the department's average arrivals. Hourly data only."""
    ts = df["timestamp"]
    hourly = (ts.dt.minute == 0).mean() > 0.99 and ts.dt.hour.nunique() > 1
    if not hourly:
        return pd.Series(False, index=df.index)
    hour = ts.dt.hour
    prof = df.assign(_h=hour).groupby(["department", "_h"])["arrivals"].mean()
    thr = prof.groupby(level=0).transform(lambda s: s.quantile(1 - PEAK_TOP_SHARE))
    peak = (prof >= thr) & (prof > 0)
    keys = pd.MultiIndex.from_arrays([df["department"], hour])
    return pd.Series(peak.reindex(keys).fillna(False).to_numpy(), index=df.index)
