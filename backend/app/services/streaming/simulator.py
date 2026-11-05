"""
Simulated near-real-time stream.

There is no live hospital feed in an academic prototype, so each "tick" produces the NEXT HOUR of operational data for
every department and stores it through the same cleaning / derived-metrics / storage pipeline as an upload. The hour is
built by replaying the same weekday-and-hour from the last few weeks with small random variation, and the bed census
moves smoothly from the previous hour. Alerts are re-scanned after every tick, so the Alerts page and bell update by
themselves. A "surge" can be injected into a department to demonstrate detection.

State is in memory (one stream per server process) and is not meant for multi-worker deployment.
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Department, HospitalData, Upload
from app.services.analytics.alerts import scan_alerts
from app.services.analytics.common import hospital_occupancy, load_frame
from app.services.ingestion.pipeline import ingest_rows

log = logging.getLogger("hospital_ops.stream")

HISTORY_DAYS = 35
SURGE_ARRIVALS, SURGE_WAIT, SURGE_BED_SHARE = 1.8, 1.6, 0.12
CARRY = 0.6  # weight of the previous hour's bed census when building the next one
MAX_HOURS_PER_STEP = 24
CANONICAL = ["timestamp", "department", "arrivals", "admissions", "discharges", "avg_wait_min", "avg_los_hours",
             "total_beds", "occupied_beds", "available_beds", "doctors_available", "nurses_available",
             "appointments_scheduled", "appointments_completed", "lab_tests_ordered", "lab_capacity",
             "equipment_available", "equipment_total"]

_lock = threading.RLock()
_stop = threading.Event()
_thread: threading.Thread | None = None
_state = {"running": False, "interval": 3.0, "ticks": 0, "upload_id": None, "user_id": None, "injections": {}, "recent": deque(maxlen=24), "error": None}


class StreamError(ValueError):
    pass


def _jitter(rng, x, spread=0.12):
    return x * rng.uniform(1 - spread, 1 + spread)


def build_next_hour(db: Session, injections: dict[str, int] | None = None) -> pd.DataFrame:
    """Rows for the hour after the newest stored hour, one per department."""
    last_ts = db.scalar(select(func.max(HospitalData.timestamp)))
    if last_ts is None:
        raise StreamError("No data yet. Load or upload hospital data first, then start the stream.")
    last_ts = pd.Timestamp(last_ts)
    nxt = last_ts + pd.Timedelta(hours=1)
    hist = load_frame(db, (last_ts - timedelta(days=HISTORY_DAYS)).date(), last_ts.date())
    if hist.empty:
        raise StreamError("No recent data to base the stream on.")
    prev = hist[hist["timestamp"] == last_ts].set_index("department")
    rng = np.random.default_rng(int(nxt.value // 10**9) % (2**32))
    rows = []
    for dept, g in hist.groupby("department"):
        same = g[(g["timestamp"].dt.hour == nxt.hour) & (g["timestamp"].dt.dayofweek == nxt.dayofweek)]
        pool = same if len(same) else g[g["timestamp"].dt.hour == nxt.hour]
        if pool.empty:
            continue
        c = pool.iloc[int(rng.integers(len(pool)))]
        beds = int(c["total_beds"])
        arrivals = int(round(_jitter(rng, c["arrivals"]))) if c["arrivals"] > 0 else 0
        wait = float(_jitter(rng, c["avg_wait_min"])) if c["arrivals"] > 0 else 0.0
        occ = 0
        if beds > 0:
            p = float(prev.loc[dept, "occupied_beds"]) if dept in prev.index else float(c["occupied_beds"])
            occ = int(round(CARRY * p + (1 - CARRY) * float(c["occupied_beds"])))
        if injections and injections.get(dept, 0) > 0:
            arrivals = int(round(arrivals * SURGE_ARRIVALS))
            wait *= SURGE_WAIT
            if beds > 0:
                occ += int(round(SURGE_BED_SHARE * beds))
        occ = int(min(max(occ, 0), beds))
        rows.append({
            "timestamp": nxt.strftime("%Y-%m-%d %H:%M:%S"), "department": dept,
            "arrivals": arrivals, "admissions": int(c["admissions"]), "discharges": int(c["discharges"]),
            "avg_wait_min": round(wait, 1), "avg_los_hours": round(float(c["avg_los_hours"]), 1),
            "total_beds": beds, "occupied_beds": occ, "available_beds": beds - occ,
            "doctors_available": int(c["doctors_available"]), "nurses_available": int(c["nurses_available"]),
            "appointments_scheduled": int(c["appointments_scheduled"]), "appointments_completed": int(c["appointments_completed"]),
            "lab_tests_ordered": int(c["lab_tests_ordered"]), "lab_capacity": int(c["lab_capacity"]),
            "equipment_available": int(c["equipment_available"]), "equipment_total": int(c["equipment_total"]),
        })
    if not rows:
        raise StreamError("Could not build the next hour from the stored data.")
    return pd.DataFrame(rows, columns=CANONICAL)


def _session_upload(db: Session, user_id: int) -> Upload:
    up = db.get(Upload, _state["upload_id"]) if _state["upload_id"] else None
    if up is None:
        up = Upload(user_id=user_id, filename="live_stream (simulated)", status="success", report_json='{"source": "simulated stream"}')
        db.add(up)
        db.commit()
        _state["upload_id"] = up.id
    return up


def tick(db: Session, user_id: int) -> dict:
    """Advance the simulation by one hour: build, store, re-scan alerts. Returns a small summary of the hour."""
    with _lock:
        rows = build_next_hour(db, _state["injections"])
        up = _session_upload(db, user_id)
        try:
            clean_df, feats, _ = ingest_rows(db, up, rows, "stream")
            up.rows_total += len(clean_df)
            up.rows_valid += len(clean_df)
            db.commit()
        except Exception:
            db.rollback()
            raise
        for k in list(_state["injections"]):
            _state["injections"][k] -= 1
            if _state["injections"][k] <= 0:
                del _state["injections"][k]
        try:
            scan = scan_alerts(db)
        except Exception:  # noqa: BLE001 - alerts must never break the stream
            db.rollback()
            scan = {"created": 0, "updated": 0}
        beds = clean_df[clean_df["total_beds"] > 0]
        occ = float(beds["occupied_beds"].sum() / beds["total_beds"].sum() * 100) if len(beds) else None
        entry = {
            "timestamp": clean_df["timestamp"].iloc[0].strftime("%Y-%m-%dT%H:00"),
            "arrivals": int(clean_df["arrivals"].sum()), "occupancy_pct": round(occ, 1) if occ is not None else None,
            "avg_wait_min": round(float(np.average(clean_df["avg_wait_min"], weights=np.maximum(clean_df["arrivals"], 1e-9))), 1),
            "new_alerts": scan.get("created", 0), "open_alerts_updated": scan.get("updated", 0),
        }
        _state["ticks"] += 1
        _state["recent"].appendleft(entry)
        return entry


def _loop():
    while not _stop.wait(_state["interval"]):
        try:
            with SessionLocal() as db:
                tick(db, _state["user_id"])
            _state["error"] = None
        except Exception as e:  # noqa: BLE001
            _state["error"] = str(e) if isinstance(e, StreamError) else "The stream stopped because of an internal error."
            if not isinstance(e, StreamError):
                log.exception("stream tick failed")
            _state["running"] = False
            return


def start(user_id: int, interval: float) -> None:
    global _thread
    with _lock:
        if _state["running"]:
            _state["interval"] = interval
            return
        with SessionLocal() as db:  # fail fast if there is nothing to stream from
            build_next_hour(db, _state["injections"])
        _stop.clear()
        _state.update(running=True, interval=interval, user_id=user_id, error=None)
        _thread = threading.Thread(target=_loop, name="hospital-stream", daemon=True)
        _thread.start()


def stop() -> None:
    with _lock:
        _stop.set()
        _state["running"] = False


def inject_surge(db: Session, department: str, hours: int) -> None:
    if not db.scalar(select(Department.id).where(Department.name == department)):
        raise StreamError("Unknown department.")
    with _lock:
        _state["injections"][department] = hours


def status(db: Session) -> dict:
    last = db.scalar(select(func.max(HospitalData.timestamp)))
    with _lock:
        return {
            "running": _state["running"], "interval_seconds": _state["interval"], "ticks": _state["ticks"],
            "data_through": pd.Timestamp(last).strftime("%Y-%m-%dT%H:00") if last else None,
            "injections": dict(_state["injections"]), "recent": list(_state["recent"]), "error": _state["error"],
        }


def reset_for_tests() -> None:
    stop()
    with _lock:
        _state.update(ticks=0, upload_id=None, injections={}, error=None)
        _state["recent"].clear()
