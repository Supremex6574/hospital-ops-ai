"""
Cleaning and preprocessing. Input: DataFrame of strings with canonical column names.
Output: a typed, deduplicated, consistent DataFrame (one row per department per timestamp)
plus a report describing every fix, so nothing happens silently.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from app.services.ingestion.adapters import NUMERIC_COLUMNS
from app.services.ingestion.errors import IngestError

# Columns describing capacity/state: fill by carrying the nearest known value within the department.
STATE_COLS = ["total_beds", "occupied_beds", "available_beds", "doctors_available", "nurses_available",
              "lab_capacity", "equipment_total", "equipment_available"]
# Columns describing flow/intensity: fill with the department's typical value for that hour of day.
FLOW_COLS = ["arrivals", "admissions", "discharges", "appointments_scheduled", "appointments_completed",
             "lab_tests_ordered", "avg_wait_min", "avg_los_hours"]
# Extreme counts far above the department's norm are clipped (capacity is left alone). Waiting time is
# heavy-tailed by nature (congestion is exactly what we want to detect), so it only gets a hard physical cap.
OUTLIER_COLS = ["arrivals", "admissions", "discharges", "lab_tests_ordered"]
OUTLIER_IQR_MULT = 10.0
OUTLIER_P95_MULT = 5.0
OUTLIER_MIN_UPPER = 20.0
HARD_CAPS = {"avg_wait_min": 1440.0, "avg_los_hours": 24.0 * 365}  # a day of waiting / a year of stay

DEPT_ALIASES = {
    "emergency": "Emergency", "emergency department": "Emergency", "ed": "Emergency", "er": "Emergency",
    "a&e": "Emergency", "casualty": "Emergency", "accident & emergency": "Emergency",
    "opd": "OPD", "outpatient": "OPD", "out patient": "OPD", "outpatients": "OPD", "outpatient department": "OPD",
    "icu": "ICU", "intensive care": "ICU", "intensive care unit": "ICU", "critical care": "ICU",
    "general ward": "General Ward", "general": "General Ward", "ward": "General Ward", "medical ward": "General Ward",
    "pediatrics": "Pediatrics", "paediatrics": "Pediatrics", "pediatric": "Pediatrics", "paediatric": "Pediatrics",
    "paeds": "Pediatrics", "peds": "Pediatrics",
    "surgery": "Surgery", "surgical": "Surgery", "surgical ward": "Surgery", "general surgery": "Surgery",
}


def canonical_department(raw: object) -> str | None:
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        return None
    s = re.sub(r"\s+", " ", str(raw).strip())
    if not s:
        return None
    return DEPT_ALIASES.get(s.lower(), s)


def _build_timestamp(df: pd.DataFrame) -> pd.Series:
    # utc=True normalises mixed offsets; the timezone is then dropped so everything is naive wall-clock time
    if "timestamp" in df.columns:
        return pd.to_datetime(df["timestamp"], errors="coerce", format="mixed", utc=True).dt.tz_localize(None)
    date = pd.to_datetime(df["date"], errors="coerce", format="mixed", utc=True).dt.tz_localize(None).dt.normalize()
    if "time" in df.columns:
        t = df["time"].astype("string").str.strip()
        # accept "14:00", "14:00:00", "2 PM", or a bare hour "14"
        bare_hour = t.str.fullmatch(r"\d{1,2}").fillna(False)
        t = t.mask(bare_hour, t.str.zfill(2) + ":00")
        parsed = pd.to_datetime(t, errors="coerce", format="mixed")
        delta = (pd.to_timedelta(parsed.dt.hour, unit="h") + pd.to_timedelta(parsed.dt.minute, unit="m")
                 + pd.to_timedelta(parsed.dt.second, unit="s")).fillna(pd.Timedelta(0))
        bad_time = t.notna() & parsed.isna()  # a time was given but cannot be read -> row is invalid
        return (date + delta).mask(bad_time)
    return date


def _fill_flow(df: pd.DataFrame, col: str, hours: pd.Series) -> int:
    """Fill NaNs with the department median for the same hour of day, then the department median, then 0."""
    miss = df[col].isna()
    n = int(miss.sum())
    if n == 0:
        return 0
    by_hour = df.groupby(["department", hours])[col].transform("median")
    by_dept = df.groupby("department")[col].transform("median")
    df[col] = df[col].fillna(by_hour).fillna(by_dept).fillna(0)
    return n


def _fill_state(df: pd.DataFrame, col: str) -> int:
    miss = df[col].isna()
    n = int(miss.sum())
    if n == 0:
        return 0
    g = df.groupby("department")[col]
    df[col] = g.ffill()
    df[col] = df.groupby("department")[col].bfill()
    df[col] = df[col].fillna(df.groupby("department")[col].transform("median")).fillna(0)
    return n


def infer_granularity(df: pd.DataFrame) -> str:
    diffs = df.sort_values("timestamp").groupby("department")["timestamp"].diff().dropna()
    if diffs.empty:
        return "unknown"
    med = diffs.median()
    if med <= pd.Timedelta(minutes=90):
        return "hourly" if med >= pd.Timedelta(minutes=45) else "sub-hourly"
    if med <= pd.Timedelta(hours=30):
        return "daily"
    return "other"


def clean(df: pd.DataFrame, optional_missing: list[str] | None = None) -> tuple[pd.DataFrame, dict]:
    report: dict = {"rows_total": int(len(df))}
    df = df.copy()

    # ---- 1. timestamp and department -------------------------------------------------
    df["timestamp"] = _build_timestamp(df)
    df["department"] = df["department"].map(canonical_department)

    bad_ts = df["timestamp"].isna()
    bad_dept = df["department"].isna()
    dropped = {"invalid_or_missing_date": int(bad_ts.sum()), "missing_department": int((bad_dept & ~bad_ts).sum())}
    df = df[~(bad_ts | bad_dept)].copy()
    if df.empty:
        raise IngestError(
            "No usable rows: every row has an unreadable date or a missing department.", "no_valid_rows"
        )

    # ---- 2. numeric coercion ---------------------------------------------------------
    present_numeric = [c for c in NUMERIC_COLUMNS if c in df.columns]
    col_report: dict[str, dict] = {}
    for c in NUMERIC_COLUMNS:
        if c not in df.columns:
            df[c] = np.nan  # absent optional column: handled below
            col_report[c] = {"present": False}
            continue
        raw = df[c]
        num = pd.to_numeric(raw.astype("string").str.replace(",", "", regex=False).str.strip(), errors="coerce")
        type_errors = int((raw.notna() & num.isna()).sum())
        negatives = int((num < 0).sum())
        num = num.mask(num < 0)
        df[c] = num.astype(float)
        col_report[c] = {
            "present": True,
            "missing": int(raw.isna().sum()),
            "type_errors": type_errors,
            "negative_values": negatives,
        }

    # ---- 3. duplicates ---------------------------------------------------------------
    key = ["timestamp", "department"]
    exact = int(df.duplicated(keep="first").sum())
    df = df.drop_duplicates(keep="first")
    conflicts = int(df.duplicated(subset=key, keep="last").sum())
    df = df.drop_duplicates(subset=key, keep="last")  # same slot, different numbers: latest row wins

    df = df.sort_values(["department", "timestamp"]).reset_index(drop=True)
    hours = df["timestamp"].dt.hour

    # ---- 4. derive bed columns when only some are present ----------------------------
    if "total_beds" in present_numeric:
        pass
    elif "occupied_beds" in present_numeric and "available_beds" in present_numeric:
        df["total_beds"] = df["occupied_beds"] + df["available_beds"]
    if "occupied_beds" not in present_numeric and "total_beds" in present_numeric and "available_beds" in present_numeric:
        df["occupied_beds"] = df["total_beds"] - df["available_beds"]

    # ---- 5. missing values -----------------------------------------------------------
    filled: dict[str, int] = {}
    for c in STATE_COLS:
        if col_report[c]["present"] or df[c].notna().any():
            filled[c] = _fill_state(df, c)
        else:
            df[c] = 0.0
    for c in FLOW_COLS:
        if col_report[c]["present"] or df[c].notna().any():
            filled[c] = _fill_flow(df, c, hours)
        else:
            df[c] = 0.0
    # if only admissions was supplied, arrivals follow it (and vice versa)
    if not col_report["arrivals"]["present"] and col_report["admissions"]["present"]:
        df["arrivals"] = df["admissions"]
    if not col_report["admissions"]["present"] and col_report["arrivals"]["present"]:
        df["admissions"] = 0.0
    filled = {k: v for k, v in filled.items() if v}

    # ---- 6. consistency rules --------------------------------------------------------
    fixes: dict[str, int] = {}
    over = df["occupied_beds"] > df["total_beds"]
    fixes["occupied_beds_above_total_clipped"] = int(over.sum())
    df.loc[over, "occupied_beds"] = df.loc[over, "total_beds"]

    avail = (df["total_beds"] - df["occupied_beds"]).clip(lower=0)
    fixes["available_beds_recomputed"] = int(((df["available_beds"] - avail).abs() > 0.5).sum()) if col_report["available_beds"]["present"] else 0
    df["available_beds"] = avail

    over_eq = df["equipment_available"] > df["equipment_total"]
    fixes["equipment_available_above_total_clipped"] = int(over_eq.sum())
    df.loc[over_eq, "equipment_available"] = df.loc[over_eq, "equipment_total"]

    over_ap = df["appointments_completed"] > df["appointments_scheduled"]
    fixes["appointments_completed_above_scheduled_clipped"] = int(over_ap.sum())
    df.loc[over_ap, "appointments_completed"] = df.loc[over_ap, "appointments_scheduled"]

    # ---- 7. outliers -----------------------------------------------------------------
    clipped: dict[str, int] = {}
    for c in OUTLIER_COLS:
        q1 = df.groupby("department")[c].transform(lambda s: s.quantile(0.25))
        q3 = df.groupby("department")[c].transform(lambda s: s.quantile(0.75))
        iqr = q3 - q1
        p95 = df.groupby("department")[c].transform(lambda s: s.quantile(0.95))
        # The IQR of sparse hourly counts (mostly 0-1) is tiny, so a bare IQR rule would flag ordinary busy
        # hours. The bound is therefore never lower than 5x the 95th percentile (a single bad row cannot move it) or an absolute 20 per hour.
        upper = np.maximum(q3 + OUTLIER_IQR_MULT * iqr, np.maximum(OUTLIER_P95_MULT * p95, OUTLIER_MIN_UPPER))
        mask = (iqr > 0) & (df[c] > upper)
        if mask.any():
            clipped[c] = int(mask.sum())
            df.loc[mask, c] = upper[mask]

    for c, cap in HARD_CAPS.items():
        mask = df[c] > cap
        if mask.any():
            clipped[c] = int(mask.sum())
            df.loc[mask, c] = cap

    # ---- 8. final types --------------------------------------------------------------
    int_cols = [c for c in NUMERIC_COLUMNS if c not in ("avg_wait_min", "avg_los_hours")]
    df[int_cols] = df[int_cols].round().astype(int)
    df[["avg_wait_min", "avg_los_hours"]] = df[["avg_wait_min", "avg_los_hours"]].round(2)

    df = df[["timestamp", "department", *NUMERIC_COLUMNS]]

    report.update({
        "rows_valid": int(len(df)),
        "rows_dropped": int(report["rows_total"] - len(df) - exact - conflicts),
        "dropped_reasons": {k: v for k, v in dropped.items() if v},
        "duplicates_removed": exact,
        "key_conflicts_resolved": conflicts,
        "missing_filled": int(sum(filled.values())),
        "missing_by_column": filled,
        "columns": col_report,
        "consistency_fixes": {k: v for k, v in fixes.items() if v},
        "outliers_clipped": clipped,
        "optional_columns_missing": optional_missing or [],
        "granularity": infer_granularity(df),
        "date_range": {"from": df["timestamp"].min().isoformat(), "to": df["timestamp"].max().isoformat()},
        "departments": sorted(df["department"].unique().tolist()),
    })
    return df, report
