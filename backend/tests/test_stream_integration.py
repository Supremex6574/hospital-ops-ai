"""Simulated live stream and the EHR/HIS feed adapters."""
import importlib.util
import sys
import time
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import delete, func, select

from app.database import SessionLocal
from app.models import Alert, DerivedMetric, Forecast, HospitalData, ModelResult, Recommendation, SimulationResult, Upload
from app.services.ingestion.feeds import EhrEvent, Feed, HisSnapshot, aggregate
from app.services.streaming import simulator as sim

API = "/api/v1"
ROOT = Path(__file__).resolve().parents[2]


def _wipe():
    with SessionLocal() as db:
        for m in (SimulationResult, Recommendation, Forecast, ModelResult, Alert, DerivedMetric, HospitalData, Upload):
            db.execute(delete(m))
        db.commit()
    sim.reset_for_tests()


@pytest.fixture(scope="module")
def headers(client):
    return {"Authorization": "Bearer " + client.post(f"{API}/auth/login", json={"username": "admin", "password": "Admin@123"}).json()["access_token"]}


@pytest.fixture()
def loaded(client, headers):
    _wipe()
    spec = importlib.util.spec_from_file_location("gen_stream", ROOT / "data" / "generate_synthetic.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gen_stream"] = mod
    spec.loader.exec_module(mod)
    df = mod.generate("2026-01-01", 60, seed=3)[0]
    assert client.post(f"{API}/data/upload", headers=headers, files={"file": ("s.csv", df.to_csv(index=False).encode(), "text/csv")}).status_code == 201
    yield
    sim.stop()


def newest():
    with SessionLocal() as db:
        return pd.Timestamp(db.scalar(select(func.max(HospitalData.timestamp))))


# ---- feeds (pure) -----------------------------------------------------------------------------------------------

def test_aggregate_events_to_hours():
    f = Feed(events=[
        EhrEvent(event_type="arrival", timestamp="2026-10-01T09:05:00", department="Emergency", wait_min=20),
        EhrEvent(event_type="arrival", timestamp="2026-10-01T09:50:00", department="Emergency", wait_min=40),
        EhrEvent(event_type="admission", timestamp="2026-10-01T09:55:00", department="Emergency"),
        EhrEvent(event_type="discharge", timestamp="2026-10-01T10:10:00", department="Emergency", los_hours=50),
    ])
    out, src = aggregate(f)
    assert src == "ehr" and len(out) == 2
    h9 = out[out["timestamp"].str.contains(" 09:")].iloc[0]
    assert h9["arrivals"] == 2 and h9["admissions"] == 1 and h9["avg_wait_min"] == 30
    assert out[out["timestamp"].str.contains(" 10:")].iloc[0]["avg_los_hours"] == 50


def test_aggregate_snapshots_only_is_his():
    f = Feed(snapshots=[HisSnapshot(timestamp="2026-10-01T09:30:00", department="ICU", total_beds=20, occupied_beds=15)])
    out, src = aggregate(f)
    assert src == "his" and out.iloc[0]["total_beds"] == 20


def test_feed_rejects_identifier_fields(client, headers):
    r = client.post(f"{API}/integration/feed", headers=headers, json={"events": [
        {"event_type": "arrival", "timestamp": "2026-10-01T09:05:00", "department": "Emergency", "patient_id": "P-12345"}]})
    assert r.status_code == 422 and "P-12345" not in r.text


@pytest.mark.parametrize("ev", [
    {"event_type": "diagnosis", "timestamp": "2026-10-01T09:05:00", "department": "Emergency"},
    {"event_type": "arrival", "timestamp": "not a date", "department": "Emergency"},
    {"event_type": "arrival", "timestamp": "2026-10-01T09:05:00", "department": ""},
    {"event_type": "arrival", "timestamp": "2026-10-01T09:05:00", "department": "Emergency", "wait_min": -5},
])
def test_feed_validates_events(client, headers, ev):
    assert client.post(f"{API}/integration/feed", headers=headers, json={"events": [ev]}).status_code == 422


def test_feed_requires_auth_and_content(client, headers):
    assert client.post(f"{API}/integration/feed", json={"events": []}).status_code == 401
    assert client.post(f"{API}/integration/feed", headers=headers, json={}).status_code == 422


def test_feed_end_to_end_and_sources(client, headers, loaded):
    t0 = newest() + pd.Timedelta(hours=1)
    ev = [{"event_type": "arrival", "timestamp": (t0 + pd.Timedelta(minutes=m)).isoformat(), "department": "Emergency", "wait_min": 30 + m % 7} for m in range(0, 50, 5)]
    snap = [{"timestamp": t0.isoformat(), "department": "Emergency", "total_beds": 40, "occupied_beds": 30, "doctors_available": 6,
             "nurses_available": 17, "lab_tests_ordered": 10, "lab_capacity": 22, "equipment_available": 8, "equipment_total": 12}]
    r = client.post(f"{API}/integration/feed", headers=headers, json={"events": ev, "snapshots": snap})
    assert r.status_code == 201, r.text
    with SessionLocal() as db:
        row = db.scalars(select(HospitalData).where(HospitalData.source == "ehr")).one()
        assert row.arrivals == 10 and row.occupied_beds == 30
    src = {s["id"]: s for s in client.get(f"{API}/integration/sources", headers=headers).json()}
    assert src["ehr"]["rows"] == 1 and src["csv"]["rows"] > 1000 and src["iot"]["rows"] == 0
    assert "events" in client.get(f"{API}/integration/sample", headers=headers).json()


# ---- stream -----------------------------------------------------------------------------------------------------

def test_stream_needs_data(client, headers):
    _wipe()
    r = client.post(f"{API}/stream/step", headers=headers, json={"hours": 1})
    assert r.status_code == 422 and "data" in r.json()["detail"].lower()
    assert client.post(f"{API}/stream/start", headers=headers, json={}).status_code == 422


def test_step_adds_next_hours_for_every_department(client, headers, loaded):
    before = newest()
    with SessionLocal() as db:
        n_dept = db.scalar(select(func.count(func.distinct(HospitalData.department_id))))
    j = client.post(f"{API}/stream/step", headers=headers, json={"hours": 3}).json()
    assert newest() == before + pd.Timedelta(hours=3) and j["ticks"] == 3
    with SessionLocal() as db:
        rows = db.scalars(select(HospitalData).where(HospitalData.source == "stream")).all()
        assert len(rows) == 3 * n_dept
        assert all(0 <= r.occupied_beds <= r.total_beds and r.available_beds == r.total_beds - r.occupied_beds for r in rows)
        derived = db.scalar(select(func.count()).select_from(DerivedMetric).join(HospitalData, HospitalData.id == DerivedMetric.hospital_data_id).where(HospitalData.source == "stream"))
        assert derived == len(rows)
        assert db.scalar(select(func.count()).select_from(Upload).where(Upload.filename.like("live_stream%"))) == 1
    assert j["recent"][0]["timestamp"] > j["recent"][-1]["timestamp"]


def test_stream_continues_smoothly(client, headers, loaded):
    with SessionLocal() as db:
        last = db.scalars(select(HospitalData).where(HospitalData.timestamp == newest())).all()
    prev = {r.department_id: r.occupied_beds for r in last if r.total_beds}
    client.post(f"{API}/stream/step", headers=headers, json={"hours": 1})
    with SessionLocal() as db:
        nxt = db.scalars(select(HospitalData).where(HospitalData.source == "stream")).all()
    for r in nxt:
        if r.total_beds:
            assert abs(r.occupied_beds - prev[r.department_id]) <= 0.25 * r.total_beds


def test_surge_changes_the_hour_and_raises_alerts(client, headers, loaded):
    with SessionLocal() as db:
        plain = sim.build_next_hour(db, {}).set_index("department")
        surged = sim.build_next_hour(db, {"Emergency": 2}).set_index("department")
    e0, e1 = plain.loc["Emergency"], surged.loc["Emergency"]
    assert e1["arrivals"] >= round(e0["arrivals"] * 1.7) and e1["avg_wait_min"] > e0["avg_wait_min"] * 1.5
    assert e1["occupied_beds"] > e0["occupied_beds"]
    assert plain.loc["ICU"].equals(surged.loc["ICU"])  # other departments untouched

    assert client.post(f"{API}/stream/surge", headers=headers, json={"department": "Emergency", "hours": 3}).json()["injections"] == {"Emergency": 3}
    j = client.post(f"{API}/stream/step", headers=headers, json={"hours": 3}).json()
    assert j["injections"] == {}
    alerts = client.get(f"{API}/alerts", headers=headers).json()
    items = alerts["items"] if isinstance(alerts, dict) else alerts
    assert any(a.get("department") == "Emergency" for a in items)


def test_surge_validation(client, headers, loaded):
    assert client.post(f"{API}/stream/surge", headers=headers, json={"department": "Nowhere", "hours": 3}).status_code == 422
    assert client.post(f"{API}/stream/surge", headers=headers, json={"department": "ICU", "hours": 99}).status_code == 422
    assert client.post(f"{API}/stream/step", headers=headers, json={"hours": 99}).status_code == 422
    assert client.post(f"{API}/stream/start", headers=headers, json={"interval_seconds": 0}).status_code == 422


def test_background_stream_start_stop(client, headers, loaded):
    before = newest()
    assert client.post(f"{API}/stream/start", headers=headers, json={"interval_seconds": 1}).json()["running"] is True
    assert client.post(f"{API}/stream/step", headers=headers, json={"hours": 1}).status_code == 409
    time.sleep(2.8)
    j = client.post(f"{API}/stream/stop", headers=headers).json()
    assert j["running"] is False and j["ticks"] >= 1 and newest() > before
    n = j["ticks"]
    time.sleep(1.6)
    assert client.get(f"{API}/stream/status", headers=headers).json()["ticks"] <= n + 1  # at most one in-flight tick finishes


def test_stream_auth(client):
    for path in ("status",):
        assert client.get(f"{API}/stream/{path}").status_code == 401
    assert client.post(f"{API}/stream/step", json={}).status_code == 401


# ---- IoT sensors + overlap guard ----------------------------------------------------------------------------------

from app.services.ingestion.feeds import SensorBatch, aggregate_sensors  # noqa: E402


def _r(t, dev, dept, ts, v):
    return {"sensor_type": t, "device_id": dev, "department": dept, "timestamp": ts, "value": v}


def test_sensor_aggregation_uses_last_reading_per_device():
    b = SensorBatch(readings=[
        _r("bed", "B1", "ICU", "2026-10-01T09:05:00", 1), _r("bed", "B1", "ICU", "2026-10-01T09:50:00", 0),  # freed within the hour
        _r("bed", "B2", "ICU", "2026-10-01T09:10:00", 1), _r("bed", "B3", "ICU", "2026-10-01T09:20:00", 1),
        _r("equipment", "V1", "ICU", "2026-10-01T09:15:00", 1), _r("equipment", "V2", "ICU", "2026-10-01T09:16:00", 0),
        _r("equipment", "V3", "ICU", "2026-10-01T09:17:00", 2),
        _r("footfall", "D1", "Emergency", "2026-10-01T09:30:00", 4), _r("footfall", "D1", "Emergency", "2026-10-01T09:45:00", 3),
    ])
    out = aggregate_sensors(b).set_index("department")
    icu = out.loc["ICU"]
    assert icu["total_beds"] == 3 and icu["occupied_beds"] == 2 and icu["available_beds"] == 1
    assert icu["equipment_total"] == 3 and icu["equipment_available"] == 1  # idle only; in use and out of service are not available
    assert out.loc["Emergency"]["arrivals"] == 7


@pytest.mark.parametrize("bad", [
    {"device_id": "Patient John Smith"}, {"device_id": "x" * 41}, {"sensor_type": "camera"}, {"value": -1}, {"value": 5000},
    {"timestamp": "yesterday"}, {"patient": "P1"},
])
def test_sensor_validation(client, headers, bad):
    rec = {**_r("bed", "B1", "ICU", "2026-10-01T09:05:00", 1), **bad}
    r = client.post(f"{API}/integration/iot", headers=headers, json={"readings": [rec]})
    assert r.status_code == 422 and "John Smith" not in r.text


def test_iot_requires_auth_and_readings(client, headers):
    assert client.post(f"{API}/integration/iot", json={"readings": []}).status_code == 401
    assert client.post(f"{API}/integration/iot", headers=headers, json={"readings": []}).status_code == 422


def test_iot_end_to_end_and_overlap_guard(client, headers, loaded):
    t0 = newest() + pd.Timedelta(hours=1)
    ts = lambda m: (t0 + pd.Timedelta(minutes=m)).isoformat()  # noqa: E731
    readings = [_r("bed", f"ICU-B{i}", "ICU", ts(5 + i), 1 if i < 7 else 0) for i in range(10)] + [_r("footfall", "ED-D1", "Emergency", ts(30), 6)]
    r = client.post(f"{API}/integration/iot", headers=headers, json={"readings": readings})
    assert r.status_code == 201, r.text
    with SessionLocal() as db:
        row = db.execute(select(HospitalData).where(HospitalData.source == "iot", HospitalData.total_beds == 10)).scalars().one()
        assert row.occupied_beds == 7 and row.available_beds == 3
    src = {s["id"]: s for s in client.get(f"{API}/integration/sources", headers=headers).json()}
    assert src["iot"]["rows"] == 2 and src["iot"]["available"] is True
    # an hour that already exists from the csv upload must be refused, not double counted
    old = (newest() - pd.Timedelta(days=2)).replace(minute=0).isoformat()
    r = client.post(f"{API}/integration/iot", headers=headers, json={"readings": [_r("bed", "ICU-B1", "ICU", old, 1)]})
    assert r.status_code == 409 and "another source" in r.json()["detail"]
    assert "readings" in client.get(f"{API}/integration/iot-sample", headers=headers).json()
