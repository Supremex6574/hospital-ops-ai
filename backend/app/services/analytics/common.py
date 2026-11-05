"""
Helpers shared by every analytics service (dashboard, patient flow, resources, and later bottlenecks).

Conventions used everywhere
- "Latest" / "today" are relative to the data, not the wall clock: the as-of moment is the newest timestamp
  inside the selected range, so historical datasets still show meaningful numbers.
- Hospital-wide bed figures only count departments that have beds (OPD is outpatient and has none).
- Waiting time is averaged weighted by arrivals, so a busy hour counts for more than a quiet one.
- Comparison tables/charts always cover every department; the department filter only scopes time series.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import DEFAULT_THRESHOLDS
from app.models import AppSetting, Department, DerivedMetric, HospitalData

HOURLY_MAX_DAYS = 3  # ranges up to this many days are charted hourly, longer ranges daily

COLUMNS = [
    HospitalData.timestamp, HospitalData.department_id, Department.name.label("department"),
    HospitalData.arrivals, HospitalData.admissions, HospitalData.discharges, HospitalData.avg_wait_min,
    HospitalData.avg_los_hours,
    HospitalData.total_beds, HospitalData.occupied_beds, HospitalData.available_beds,
    HospitalData.doctors_available, HospitalData.nurses_available,
    HospitalData.appointments_scheduled, HospitalData.appointments_completed,
    HospitalData.lab_tests_ordered, HospitalData.lab_capacity,
    HospitalData.equipment_available, HospitalData.equipment_total,
    DerivedMetric.bed_occupancy_pct, DerivedMetric.resource_util_pct, DerivedMetric.patients_per_doctor,
    DerivedMetric.patients_per_nurse, DerivedMetric.workload_index, DerivedMetric.lab_util_pct,
    DerivedMetric.equipment_util_pct,
]


def num(v, digits: int | None = 1):
    """JSON-safe number: NaN/inf/None -> None."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(f):
        return None
    return round(f, digits) if digits is not None else f


def change(cur, prev) -> float | None:
    """Percentage change from prev to cur; None when it cannot be computed."""
    if cur is None or prev is None or prev == 0:
        return None
    return round((cur - prev) / abs(prev) * 100, 1)


def kpi(value, previous=None, digits: int = 1) -> dict:
    v, p = num(value, digits), num(previous, digits)
    return {"value": v, "previous": p, "delta_pct": change(v, p)}


def load_frame(db: Session, date_from: date | None, date_to: date | None, department_id: int | None = None) -> pd.DataFrame:
    stmt = (
        select(*COLUMNS)
        .join(Department, Department.id == HospitalData.department_id)
        .join(DerivedMetric, DerivedMetric.hospital_data_id == HospitalData.id)
        .order_by(HospitalData.timestamp, HospitalData.department_id)
    )
    if date_from:
        stmt = stmt.where(HospitalData.timestamp >= datetime.combine(date_from, time.min))
    if date_to:
        stmt = stmt.where(HospitalData.timestamp < datetime.combine(date_to + timedelta(days=1), time.min))
    if department_id:
        stmt = stmt.where(HospitalData.department_id == department_id)
    df = pd.read_sql(stmt, db.connection())
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def window(df: pd.DataFrame, date_from: date | None, date_to: date | None) -> pd.DataFrame:
    """Rows whose timestamp falls on a day inside [date_from, date_to] (either bound may be open)."""
    if date_from:
        df = df[df["timestamp"] >= pd.Timestamp(date_from)]
    if date_to:
        df = df[df["timestamp"] < pd.Timestamp(date_to) + pd.Timedelta(days=1)]
    return df


def previous_window(date_from: date | None, date_to: date | None) -> tuple[date, date] | None:
    """The equally long period immediately before the selected one (needs both bounds)."""
    if not (date_from and date_to):
        return None
    days = (date_to - date_from).days + 1
    return date_from - timedelta(days=days), date_from - timedelta(days=1)


def get_thresholds(db: Session) -> dict[str, float]:
    """Operational thresholds from the settings table, falling back to the built-in defaults."""
    out = {k: float(v[0]) for k, v in DEFAULT_THRESHOLDS.items()}
    for row in db.scalars(select(AppSetting)).all():
        try:
            out[row.key] = float(row.value)
        except ValueError:
            continue
    return out


def department_types(db: Session) -> dict[str, str]:
    return {d.name: d.type for d in db.scalars(select(Department)).all()}


def is_hourly(df: pd.DataFrame) -> bool:
    span = (df["timestamp"].max().normalize() - df["timestamp"].min().normalize()).days + 1
    return span <= HOURLY_MAX_DAYS


def bucket(df: pd.DataFrame, hourly: bool) -> pd.Series:
    return df["timestamp"].dt.floor("h") if hourly else df["timestamp"].dt.normalize()


def label(ts: pd.Timestamp, hourly: bool) -> str:
    return ts.strftime("%Y-%m-%dT%H:00") if hourly else ts.strftime("%Y-%m-%d")


def weighted_wait(df: pd.DataFrame) -> float | None:
    """Arrival-weighted mean waiting time (minutes)."""
    if df.empty:
        return None
    w = df["arrivals"].to_numpy(dtype=float)
    if w.sum() > 0:
        return float(np.average(df["avg_wait_min"].to_numpy(dtype=float), weights=w))
    return float(df["avg_wait_min"].mean())


def hospital_occupancy(df: pd.DataFrame) -> pd.Series:
    """Hospital-wide occupancy % per timestamp over departments with beds. Empty when no beds exist."""
    beds = df[df["total_beds"] > 0]
    if beds.empty:
        return pd.Series(dtype=float)
    g = beds.groupby("timestamp")[["occupied_beds", "total_beds"]].sum()
    return g["occupied_beds"] / g["total_beds"] * 100


def peak_heatmap(scope: pd.DataFrame) -> dict:
    """Average hospital arrivals per hour for each weekday x hour-of-day cell (Mon=0)."""
    per_ts = scope.groupby("timestamp")["arrivals"].sum().reset_index()
    per_ts["dow"] = per_ts["timestamp"].dt.dayofweek
    per_ts["hour"] = per_ts["timestamp"].dt.hour
    grid = per_ts.groupby(["dow", "hour"])["arrivals"].mean()
    cells = [
        {"dow": int(d), "hour": int(h), "avg_arrivals": num(grid.get((d, h)), 2)}
        for d in range(7) for h in range(24)
    ]
    vals = [c["avg_arrivals"] for c in cells if c["avg_arrivals"] is not None]
    return {"cells": cells, "max": max(vals) if vals else None}


def same_weekday_baseline(daily: pd.Series) -> pd.Series:
    """
    Typical value for each day: the median of the same weekday over the surrounding four weeks on each side
    (the day itself excluded). Needs at least 3 such days, otherwise NaN. Because a surge lasts a few days at
    most, it can only ever touch one same-weekday neighbour, so the median ignores it.
    """
    vals = daily.to_dict()
    out = {}
    for d in daily.index:
        neigh = [vals[n] for k in (-4, -3, -2, -1, 1, 2, 3, 4) if (n := d + pd.Timedelta(days=7 * k)) in vals]
        out[d] = float(np.median(neigh)) if len(neigh) >= 3 else np.nan
    return pd.Series(out, dtype=float)
