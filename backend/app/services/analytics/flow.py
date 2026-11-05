"""
Patient flow analytics: how many patients arrive, wait, get admitted, stay and leave, plus unusual-volume days.
All figures are aggregate department counts (no patient-level data exists in the system).
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.services.analytics.common import (
    bucket, get_thresholds, is_hourly, kpi, label, load_frame, num, peak_heatmap, previous_window, same_weekday_baseline,
    weighted_wait, window,
)

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MIN_RATIO = 1.15       # a flagged day must also be at least 15% above its baseline
MAD_SCALE = 1.4826     # makes MAD comparable to a standard deviation for normal data
SCALE_FLOOR = 0.03     # smallest spread (log units) allowed, so very stable data does not flag tiny wiggles


def _los(df: pd.DataFrame) -> float | None:
    """Average length of stay (hours), weighted by discharges (ignores rows with no stay recorded)."""
    d = df[(df["avg_los_hours"] > 0) & (df["discharges"] > 0)]
    if d.empty:
        return None
    return float(np.average(d["avg_los_hours"], weights=d["discharges"]))


def detect_unusual_days(full: pd.DataFrame, z_threshold: float) -> pd.DataFrame:
    """
    Daily hospital arrivals vs. the typical value for that weekday (see same_weekday_baseline).
    The spread comes from the robust (median/MAD) deviation of log(actual/baseline) over the whole history,
    so ordinary variation sets the bar. Returns one row per day with expected, ratio, z and an `anomaly` flag.
    """
    daily = full.groupby(full["timestamp"].dt.normalize())["arrivals"].sum().astype(float)
    if daily.empty:
        return pd.DataFrame(columns=["date", "arrivals", "expected", "ratio", "z", "anomaly"])
    base = same_weekday_baseline(daily)
    ok = base.notna() & (base > 0) & (daily > 0)
    logr = pd.Series(np.nan, index=daily.index)
    logr[ok] = np.log(daily[ok] / base[ok])
    valid = logr.dropna()
    if len(valid) >= 5:
        med = float(valid.median())
        scale = max(float((valid - med).abs().median()) * MAD_SCALE, SCALE_FLOOR)
    else:
        med, scale = 0.0, SCALE_FLOOR
    z = (logr - med) / scale
    out = pd.DataFrame({"date": daily.index, "arrivals": daily.values, "expected": base.values,
                        "ratio": np.exp(logr.values), "z": z.values})
    out["anomaly"] = (out["z"] >= z_threshold) & (out["ratio"] >= MIN_RATIO)
    return out


def _anomaly_rows(full: pd.DataFrame, det: pd.DataFrame, lo: pd.Timestamp, hi: pd.Timestamp) -> list[dict]:
    flagged = det[det["anomaly"] & (det["date"] >= lo) & (det["date"] <= hi)]
    if flagged.empty:
        return []
    day = full["timestamp"].dt.normalize()
    # computed once: each department's daily arrivals with its same-weekday baseline, and hospital daily waiting time
    dept_daily = {}
    for name, g in full.groupby("department"):
        dd = g.groupby(g["timestamp"].dt.normalize())["arrivals"].sum().astype(float)
        dept_daily[name] = (dd, same_weekday_baseline(dd))
    wait_daily = full.assign(w=full["avg_wait_min"] * full["arrivals"]).groupby(day)[["w", "arrivals"]].sum()
    wait_daily = (wait_daily["w"] / wait_daily["arrivals"].where(wait_daily["arrivals"] > 0)).dropna()

    rows = []
    for _, r in flagged.iterrows():
        d = r["date"]
        best, best_inc = None, None
        for name, (dd, base) in dept_daily.items():
            b = base.get(d, np.nan)
            if d in dd.index and b and b > 0:
                inc = (dd[d] - b) / b * 100
                if best_inc is None or inc > best_inc:
                    best, best_inc = name, inc
        neigh = [d + pd.Timedelta(days=7 * k) for k in (-4, -3, -2, -1, 1, 2, 3, 4)]
        waits = [wait_daily[n] for n in neigh if n in wait_daily.index]
        rows.append({
            "date": d.strftime("%Y-%m-%d"), "weekday": WEEKDAYS[d.dayofweek],
            "arrivals": int(r["arrivals"]), "expected": num(r["expected"], 0),
            "increase_pct": num((r["ratio"] - 1) * 100, 0), "z": num(r["z"], 1),
            "wait_min": num(wait_daily.get(d)), "wait_normal_min": num(np.median(waits)) if len(waits) >= 3 else None,
            "top_department": best, "top_department_increase_pct": num(best_inc, 0),
        })
    return rows


def _journey(cur: pd.DataFrame, days: int) -> list[dict]:
    arrivals, adm, dis = float(cur["arrivals"].sum()), float(cur["admissions"].sum()), float(cur["discharges"].sum())
    wait, los = weighted_wait(cur), _los(cur)
    return [
        {"stage": "arrival", "label": "Arrival", "value": num(arrivals, 0), "unit": "patients",
         "secondary": f"{num(arrivals / days, 0):g} per day", "source": "arrivals", "available": True},
        {"stage": "wait", "label": "Waiting", "value": num(wait), "unit": "min average",
         "secondary": "arrival-weighted", "source": "avg_wait_min", "available": wait is not None},
        {"stage": "admission", "label": "Admission", "value": num(adm, 0), "unit": "patients",
         "secondary": f"{num(adm / arrivals * 100, 0):g}% of arrivals" if arrivals else None,
         "source": "admissions", "available": True},
        {"stage": "stay", "label": "Stay", "value": num(los, 0), "unit": "hours average",
         "secondary": "length of stay", "source": "avg_los_hours", "available": los is not None},
        {"stage": "discharge", "label": "Discharge", "value": num(dis, 0), "unit": "patients",
         "secondary": f"{num(dis / adm * 100, 0):g}% of admissions" if adm else None,
         "source": "discharges", "available": True},
        {"stage": "pharmacy", "label": "Pharmacy", "value": None, "unit": "", "secondary": "No pharmacy data in the dataset",
         "source": None, "available": False},
    ]


def compute_flow(db: Session, date_from: date | None, date_to: date | None, department_id: int | None) -> dict:
    full = load_frame(db, None, None, None)  # whole history: surge baselines need weeks on either side
    if full.empty:
        return {"has_data": False}
    thresholds = get_thresholds(db)
    cur_all = window(full, date_from, date_to)
    if cur_all.empty:
        return {"has_data": False}
    cur = cur_all if not department_id else cur_all[cur_all["department_id"] == department_id]
    if cur.empty:
        return {"has_data": False}

    lo, hi = cur_all["timestamp"].min().normalize(), cur_all["timestamp"].max().normalize()
    days = (hi - lo).days + 1

    prev = None
    win = previous_window(date_from, date_to)
    if win:
        p = window(full, win[0], win[1])
        p = p if not department_id else p[p["department_id"] == department_id]
        prev = p if not p.empty else None

    def tot(df, col):
        return None if df is None else float(df[col].sum())

    ts = cur.groupby("timestamp")["arrivals"].sum()
    peak_hour = int(cur.groupby(cur["timestamp"].dt.hour)["arrivals"].mean().idxmax())
    wk = cur.groupby(cur["timestamp"].dt.dayofweek)["arrivals"].sum()
    day_counts = cur.groupby(cur["timestamp"].dt.dayofweek)["timestamp"].apply(lambda s: s.dt.normalize().nunique())

    kpis = {
        "arrivals": kpi(tot(cur, "arrivals"), tot(prev, "arrivals"), 0),
        "avg_daily_arrivals": kpi(tot(cur, "arrivals") / days, None if prev is None else tot(prev, "arrivals") / days, 0),
        "admissions": kpi(tot(cur, "admissions"), tot(prev, "admissions"), 0),
        "discharges": kpi(tot(cur, "discharges"), tot(prev, "discharges"), 0),
        "avg_wait_min": kpi(weighted_wait(cur), None if prev is None else weighted_wait(prev), 1),
        "avg_los_hours": kpi(_los(cur), None if prev is None else _los(prev), 0),
        "peak_hour": peak_hour,
        "busiest_weekday": WEEKDAYS[int((wk / day_counts).idxmax())],
    }

    # arrivals series with the typical (same-weekday) level and flagged days
    det = detect_unusual_days(full, thresholds["arrival_zscore_threshold"])
    det_in = det[(det["date"] >= lo) & (det["date"] <= hi)].set_index("date")
    hourly = is_hourly(cur)
    b = cur.assign(_b=bucket(cur, hourly)).groupby("_b")["arrivals"].sum()
    series = []
    for t, v in b.items():
        row = {"t": label(t, hourly), "arrivals": int(v), "expected": None, "anomaly": False}
        d = t.normalize()
        if not hourly and not department_id and d in det_in.index:
            e = det_in.loc[d, "expected"]
            row["expected"] = num(e, 0)
            row["anomaly"] = bool(det_in.loc[d, "anomaly"])
        series.append(row)

    anomalies = _anomaly_rows(full, det, lo, hi)

    # per-department flow table (always every department)
    deps = []
    for name, g in cur_all.groupby("department"):
        arr, adm = float(g["arrivals"].sum()), float(g["admissions"].sum())
        deps.append({
            "department_id": int(g["department_id"].iloc[0]), "department": name,
            "arrivals": int(arr), "admissions": int(adm), "discharges": int(g["discharges"].sum()),
            "admission_rate_pct": num(adm / arr * 100) if arr else None,
            "avg_wait_min": num(weighted_wait(g)), "avg_los_hours": num(_los(g), 0),
            "share_pct": num(arr / float(cur_all["arrivals"].sum()) * 100) if cur_all["arrivals"].sum() else None,
        })
    deps.sort(key=lambda r: -r["arrivals"])

    weekday = [{"day": WEEKDAYS[d], "avg_arrivals": num(wk.get(d, np.nan) / day_counts.get(d, np.nan), 0)} for d in range(7)]
    hour_prof = cur.groupby(["timestamp"])["arrivals"].sum().groupby(lambda t: t.hour).mean()
    hours = [{"hour": h, "avg_arrivals": num(hour_prof.get(h), 1)} for h in range(24)]

    return {
        "has_data": True, "granularity": "hour" if hourly else "day",
        "range": {"from": lo.strftime("%Y-%m-%d"), "to": hi.strftime("%Y-%m-%d"), "days": days},
        "kpis": kpis, "journey": _journey(cur, days), "series": series,
        "anomalies": anomalies,
        "anomaly_note": (
            f"A day is flagged when its arrivals are at least {MIN_RATIO:.2f}x the typical level for that weekday and "
            f"{thresholds['arrival_zscore_threshold']:g} or more robust standard deviations above it."
        ),
        "anomaly_scope": "Hospital-wide; detection uses the full stored history as the baseline.",
        "departments": deps, "weekday": weekday, "hours": hours, "heatmap": peak_heatmap(cur),
    }
