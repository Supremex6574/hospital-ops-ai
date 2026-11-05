"""Bottleneck rules validated against the generator's surge episodes; alerts lifecycle; settings validation."""
import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import delete

from app.database import SessionLocal
from app.models import Alert, AppSetting, DerivedMetric, HospitalData, Upload

API = "/api/v1"
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def generated():
    spec = importlib.util.spec_from_file_location("gen_bn", ROOT / "data" / "generate_synthetic.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gen_bn"] = mod
    spec.loader.exec_module(mod)
    df, surges = mod.generate("2025-10-01", 365, seed=42)
    return df, surges


@pytest.fixture(scope="module")
def loaded(client, generated):
    df, _ = generated
    h = {"Authorization": "Bearer " + client.post(f"{API}/auth/login", json={"username": "admin", "password": "Admin@123"}).json()["access_token"]}
    with SessionLocal() as db:
        for m in (Alert, DerivedMetric, HospitalData, Upload):
            db.execute(delete(m))
        db.commit()
    r = client.post(f"{API}/data/upload", headers=h, files={"file": ("y.csv", df.to_csv(index=False).encode(), "text/csv")})
    assert r.status_code == 201, r.text
    return h


def test_require_auth(client):
    for p in ("bottlenecks", "alerts", "alerts/summary", "settings/thresholds"):
        assert client.get(f"{API}/{p}").status_code == 401
    assert client.post(f"{API}/alerts/scan").status_code == 401


def test_bottleneck_hours_concentrate_on_surge_days(client, loaded, generated):
    _, surges = generated
    j = client.get(f"{API}/bottlenecks", headers=loaded, params={"from": "2025-10-01", "to": "2026-09-30"}).json()
    assert j["has_data"] and {c["key"] for c in j["conditions"]} >= {"occupancy", "wait", "arrivals"}
    trend = {t["t"]: t["flagged"] for t in j["trend"]}
    surge_days = set()
    for _, e in surges.iterrows():
        surge_days |= {d.strftime("%Y-%m-%d") for d in pd.date_range(e.start, e.end)}
    on = [v for d, v in trend.items() if d in surge_days]
    off = [v for d, v in trend.items() if d not in surge_days]
    assert sum(on) / len(on) > 1.5 * (sum(off) / len(off)), (sum(on) / len(on), sum(off) / len(off))
    # sanity: even off-surge, the rules must not flag most department-hours (occupancy is genuinely high in some wards)
    assert sum(off) / len(off) / (24 * 6) < 0.5
    assert j["episodes"] and all(e["hours"] >= 3 for e in j["episodes"])


def test_status_and_filters(client, loaded):
    j = client.get(f"{API}/bottlenecks", headers=loaded, params={"from": "2026-09-01", "to": "2026-09-30"}).json()
    assert len(j["status"]) == 6 and {s["severity"] for s in j["status"]} <= {"normal", "warning", "critical"}
    assert len(j["matrix"]) == 6
    assert client.get(f"{API}/bottlenecks", headers=loaded, params={"from": "2026-02-02", "to": "2026-02-01"}).status_code == 422


def test_alerts_scan_dedupes_and_acknowledges(client, loaded):
    # upload already scanned once; scanning again must update, not duplicate
    before = client.get(f"{API}/alerts", headers=loaded, params={"status": "all"}).json()
    s = client.post(f"{API}/alerts/scan", headers=loaded).json()
    after = client.get(f"{API}/alerts", headers=loaded, params={"status": "all"}).json()
    assert s["created"] == 0 and len(after) == len(before)
    summ = client.get(f"{API}/alerts/summary", headers=loaded).json()
    assert summ["open"] == summ["critical"] + summ["warning"] == len([a for a in after if not a["acknowledged"]])
    if after:
        a = after[0]
        assert a["message"] and a["department"] and a["severity"] in ("warning", "critical")
        r = client.post(f"{API}/alerts/{a['id']}/acknowledge", headers=loaded)
        assert r.status_code == 200 and r.json()["acknowledged"] is True
    assert client.post(f"{API}/alerts/999999/acknowledge", headers=loaded).status_code == 404
    client.post(f"{API}/alerts/acknowledge-all", headers=loaded)
    assert client.get(f"{API}/alerts/summary", headers=loaded).json()["open"] == 0
    # once acknowledged, a still-active condition raises a fresh alert on the next scan
    assert client.post(f"{API}/alerts/scan", headers=loaded).status_code == 200


def test_thresholds_read_and_validation(client, loaded):
    cur = {t["key"]: t for t in client.get(f"{API}/settings/thresholds", headers=loaded).json()}
    assert cur["occupancy_warning_pct"]["value"] == 85
    put = lambda v: client.put(f"{API}/settings/thresholds", headers=loaded, json={"values": v})  # noqa: E731
    assert put({"nope": 1}).status_code == 422
    assert put({"occupancy_warning_pct": 120}).status_code == 422
    assert put({"occupancy_warning_pct": 95}).status_code == 422       # not below critical (90)
    assert put({"weight_wait": 0.5}).status_code == 422                # weights no longer sum to 1
    assert put({}).status_code == 422


def test_threshold_change_changes_detection(client, loaded):
    p = {"from": "2026-09-01", "to": "2026-09-30"}
    base = client.get(f"{API}/bottlenecks", headers=loaded, params=p).json()["summary"]["flagged_hours"]
    assert client.put(f"{API}/settings/thresholds", headers=loaded, json={"values": {"occupancy_warning_pct": 60, "occupancy_critical_pct": 70}}).status_code == 200
    stricter = client.get(f"{API}/bottlenecks", headers=loaded, params=p).json()["summary"]["flagged_hours"]
    assert stricter > base
    with SessionLocal() as db:
        db.execute(delete(AppSetting).where(AppSetting.key.in_(["occupancy_warning_pct", "occupancy_critical_pct"])))
        db.commit()
    assert client.get(f"{API}/bottlenecks", headers=loaded, params=p).json()["summary"]["flagged_hours"] == base
