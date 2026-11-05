"""
EHR / HIS feeds.

Real hospital systems expose event-level or system-of-record data, not our hourly table. These adapters accept
ANONYMISED feeds and aggregate them into the canonical hourly department rows:

- EHR events: one record per operational event (arrival, admission, discharge) with a timestamp and department, plus the
  waiting time of an arrival or the length of stay of a discharge. There is deliberately no field for a patient
  identifier; unknown fields are rejected, so identifiers cannot slip in.
- HIS snapshots: the hospital information system's resource state per department and hour (beds, staff on duty, lab,
  equipment, appointments).

Aggregated rows then go through exactly the same pipeline as a file upload (cleaning, derived metrics, storage).
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

MAX_EVENTS = 20000
MAX_SNAPSHOTS = 5000


class EhrEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_type: Literal["arrival", "admission", "discharge"]
    timestamp: datetime
    department: str = Field(min_length=1, max_length=60)
    wait_min: float | None = Field(None, ge=0, le=1440)       # for arrivals
    los_hours: float | None = Field(None, ge=0, le=24 * 120)  # for discharges


class HisSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timestamp: datetime
    department: str = Field(min_length=1, max_length=60)
    total_beds: int | None = Field(None, ge=0, le=5000)
    occupied_beds: int | None = Field(None, ge=0, le=5000)
    doctors_available: int | None = Field(None, ge=0, le=1000)
    nurses_available: int | None = Field(None, ge=0, le=2000)
    appointments_scheduled: int | None = Field(None, ge=0, le=5000)
    appointments_completed: int | None = Field(None, ge=0, le=5000)
    lab_tests_ordered: int | None = Field(None, ge=0, le=5000)
    lab_capacity: int | None = Field(None, ge=0, le=5000)
    equipment_available: int | None = Field(None, ge=0, le=5000)
    equipment_total: int | None = Field(None, ge=0, le=5000)


class Feed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: list[EhrEvent] = Field(default_factory=list, max_length=MAX_EVENTS)
    snapshots: list[HisSnapshot] = Field(default_factory=list, max_length=MAX_SNAPSHOTS)


def aggregate(feed: Feed) -> tuple[pd.DataFrame, str]:
    """Hourly canonical frame (strings/NaN, ready for the cleaner) and the source tag ('ehr' if events are present)."""
    frames = []
    if feed.events:
        ev = pd.DataFrame([e.model_dump() for e in feed.events])
        ev["timestamp"] = pd.to_datetime(ev["timestamp"]).dt.tz_localize(None).dt.floor("h")
        g = ev.groupby(["timestamp", "department"])
        agg = pd.DataFrame({
            "arrivals": g["event_type"].apply(lambda s: int((s == "arrival").sum())),
            "admissions": g["event_type"].apply(lambda s: int((s == "admission").sum())),
            "discharges": g["event_type"].apply(lambda s: int((s == "discharge").sum())),
        })
        arr = ev[ev["event_type"] == "arrival"].groupby(["timestamp", "department"])["wait_min"].mean()
        dis = ev[ev["event_type"] == "discharge"].groupby(["timestamp", "department"])["los_hours"].mean()
        agg["avg_wait_min"], agg["avg_los_hours"] = arr, dis
        frames.append(agg.reset_index())
    if feed.snapshots:
        sn = pd.DataFrame([s.model_dump() for s in feed.snapshots])
        sn["timestamp"] = pd.to_datetime(sn["timestamp"]).dt.tz_localize(None).dt.floor("h")
        frames.append(sn.sort_values("timestamp").drop_duplicates(["timestamp", "department"], keep="last"))
    if not frames:
        return pd.DataFrame(), "ehr"
    out = frames[0] if len(frames) == 1 else frames[0].merge(frames[1], on=["timestamp", "department"], how="outer")
    out["timestamp"] = out["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return out, ("ehr" if feed.events else "his")


# ---- IoT sensors ------------------------------------------------------------------------------------------------

MAX_READINGS = 50000


class SensorReading(BaseModel):
    """
    One reading from a department sensor. `device_id` is the sensor / bed-tag / equipment-tag code (letters, digits,
    dash, underscore); there is no field for a patient, and unknown fields are rejected.
    bed:       value 1 = bed occupied, 0 = free
    equipment: value 1 = in use, 0 = idle, 2 = out of service
    footfall:  value = people counted entering the department since the previous reading
    """
    model_config = ConfigDict(extra="forbid")
    sensor_type: Literal["bed", "equipment", "footfall"]
    device_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")
    department: str = Field(min_length=1, max_length=60)
    timestamp: datetime
    value: float = Field(ge=0, le=1000)


class SensorBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    readings: list[SensorReading] = Field(min_length=1, max_length=MAX_READINGS)


def aggregate_sensors(batch: SensorBatch) -> pd.DataFrame:
    """
    Hourly department rows from sensor readings. For every hour the LAST reading of each device counts:
    occupied beds = bed sensors reading 1; total beds = distinct bed sensors seen; equipment_total = distinct equipment
    sensors seen, equipment_available = those idle (0); arrivals = sum of footfall counts.
    Total beds therefore equals the number of SENSORED beds, so partial coverage understates capacity.
    """
    df = pd.DataFrame([r.model_dump() for r in batch.readings])
    df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
    df["hour"] = df["timestamp"].dt.floor("h")
    out = None

    def merge(a, b):
        return b if a is None else a.merge(b, on=["timestamp", "department"], how="outer")

    last = df.sort_values("timestamp").groupby(["hour", "department", "sensor_type", "device_id"], as_index=False).last()
    beds = last[last["sensor_type"] == "bed"]
    if len(beds):
        g = beds.groupby(["hour", "department"])["value"]
        b = pd.DataFrame({"total_beds": g.size(), "occupied_beds": g.apply(lambda s: int((s >= 1).sum()))}).reset_index()
        b["available_beds"] = b["total_beds"] - b["occupied_beds"]
        out = merge(out, b.rename(columns={"hour": "timestamp"}))
    eq = last[last["sensor_type"] == "equipment"]
    if len(eq):
        g = eq.groupby(["hour", "department"])["value"]
        e = pd.DataFrame({"equipment_total": g.size(), "equipment_available": g.apply(lambda s: int((s == 0).sum()))}).reset_index()
        out = merge(out, e.rename(columns={"hour": "timestamp"}))
    ff = df[df["sensor_type"] == "footfall"]
    if len(ff):
        a = ff.groupby(["hour", "department"])["value"].sum().round().astype(int).rename("arrivals").reset_index()
        out = merge(out, a.rename(columns={"hour": "timestamp"}))
    if "arrivals" not in out.columns:
        out["arrivals"] = float("nan")  # the pipeline needs a volume column; unknown values are reported as filled
    out["timestamp"] = out["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return out


def source_conflicts(db, frame: pd.DataFrame, source: str) -> int:
    """How many (hour, department) rows in `frame` already exist from a DIFFERENT source (they would be counted twice)."""
    from sqlalchemy import select

    from app.models import Department, HospitalData

    if frame.empty:
        return 0
    ts = pd.to_datetime(frame["timestamp"])
    rows = db.execute(
        select(HospitalData.timestamp, Department.name)
        .join(Department, Department.id == HospitalData.department_id)
        .where(HospitalData.source != source, HospitalData.timestamp >= ts.min().to_pydatetime(), HospitalData.timestamp <= ts.max().to_pydatetime())
    ).all()
    have = {(pd.Timestamp(t), n) for t, n in rows}
    return sum(1 for t, d in zip(ts, frame["department"]) if (t, d) in have)
