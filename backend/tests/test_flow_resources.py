"""Patient flow and resource utilization, cross-checked against independent pandas calculations and against the
generator's known surge episodes."""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import delete

from app.database import SessionLocal
from app.models import DerivedMetric, HospitalData, Upload

API = "/api/v1"
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def generated():
    spec = importlib.util.spec_from_file_location("gen_flow", ROOT / "data" / "generate_synthetic.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gen_flow"] = mod
    spec.loader.exec_module(mod)
    df, surges = mod.generate("2025-10-01", 365, seed=42)
    df["timestamp"] = pd.to_datetime(df["date"] + " " + df["time"])
    return df, surges


@pytest.fixture(scope="module")
def loaded(client, generated):
    df, _ = generated
    h = {"Authorization": "Bearer " + client.post(f"{API}/auth/login", json={"username": "admin", "password": "Admin@123"}).json()["access_token"]}
    with SessionLocal() as db:
        db.execute(delete(DerivedMetric)); db.execute(delete(HospitalData)); db.execute(delete(Upload)); db.commit()
    csv = df.drop(columns=["timestamp"]).to_csv(index=False).encode()
    r = client.post(f"{API}/data/upload", headers=h, files={"file": ("y.csv", csv, "text/csv")})
    assert r.status_code == 201, r.text
    return df, h


def win(df, a, b):
    return df[(df.timestamp >= a) & (df.timestamp < pd.Timestamp(b) + pd.Timedelta(days=1))]


def test_require_auth(client):
    for p in ("flow/overview", "resources/compare", "resources/beds"):
        assert client.get(f"{API}/{p}").status_code == 401


def test_bad_inputs(client, loaded):
    _, h = loaded
    assert client.get(f"{API}/flow/overview", headers=h, params={"from": "2026-02-02", "to": "2026-02-01"}).status_code == 422
    assert client.get(f"{API}/resources/compare", headers=h, params={"from": "2026-02-02", "to": "2026-02-01"}).status_code == 422
    assert client.get(f"{API}/resources/pharmacy", headers=h).status_code == 422
    assert client.get(f"{API}/flow/overview", headers=h, params={"department_id": 0}).status_code == 422


def test_flow_kpis_match_pandas(client, loaded):
    src, h = loaded
    j = client.get(f"{API}/flow/overview", headers=h, params={"from": "2026-02-01", "to": "2026-02-28"}).json()
    cur, prev = win(src, "2026-02-01", "2026-02-28"), win(src, "2026-01-04", "2026-01-31")
    k = j["kpis"]
    assert k["arrivals"]["value"] == cur.arrivals.sum() and k["arrivals"]["previous"] == prev.arrivals.sum()
    assert k["admissions"]["value"] == cur.admissions.sum()
    assert k["discharges"]["value"] == cur.discharges.sum()
    assert k["avg_wait_min"]["value"] == pytest.approx(np.average(cur.avg_wait_min, weights=cur.arrivals), abs=0.06)
    ph = cur.groupby(cur.timestamp.dt.hour).arrivals.mean().idxmax()
    assert k["peak_hour"] == ph
    assert j["granularity"] == "day" and len(j["series"]) == 28
    assert sum(s["arrivals"] for s in j["series"]) == cur.arrivals.sum()
    assert sum(d["arrivals"] for d in j["departments"]) == cur.arrivals.sum()
    stages = {s["stage"]: s for s in j["journey"]}
    assert stages["pharmacy"]["available"] is False and stages["arrival"]["value"] == cur.arrivals.sum()


def test_flow_department_filter_and_hourly(client, loaded):
    src, h = loaded
    d = client.get(f"{API}/departments", headers=h).json()
    ed = next(x for x in d if x["name"] == "Emergency")["id"]
    j = client.get(f"{API}/flow/overview", headers=h, params={"from": "2026-02-01", "to": "2026-02-02", "department_id": ed}).json()
    cur = win(src[src.department == "Emergency"], "2026-02-01", "2026-02-02")
    assert j["granularity"] == "hour" and len(j["series"]) == 48
    assert j["kpis"]["arrivals"]["value"] == cur.arrivals.sum()
    assert len(j["departments"]) == 6  # comparison table keeps every department


def test_surge_detection_against_ground_truth(client, loaded, generated):
    _, h = loaded
    _, surges = generated
    j = client.get(f"{API}/flow/overview", headers=h, params={"from": "2025-10-01", "to": "2026-09-30"}).json()
    flagged = {a["date"] for a in j["anomalies"]}
    truth = set()
    episodes = []
    for _, e in surges.iterrows():
        days = {d.strftime("%Y-%m-%d") for d in pd.date_range(e.start, e.end)}
        truth |= days
        episodes.append(days)
    precision = len(flagged & truth) / len(flagged)
    recall = len(flagged & truth) / len(truth)
    assert precision >= 0.8, (precision, sorted(flagged - truth))
    assert recall >= 0.7, (recall, sorted(truth - flagged))
    # overlapping episodes merge, but each distinct surge window must be caught at least once
    assert all(flagged & ep for ep in episodes)
    a = j["anomalies"][0]
    assert a["increase_pct"] >= 15 and a["top_department"] and a["wait_min"] is not None


def test_no_surge_flags_in_flat_data(client, loaded):
    _, h = loaded
    # a quiet stretch with no known surge should report no anomalies
    j = client.get(f"{API}/flow/overview", headers=h, params={"from": "2025-12-01", "to": "2026-01-31"}).json()
    assert j["anomalies"] == []


def test_resources_compare_matches_pandas(client, loaded):
    src, h = loaded
    j = client.get(f"{API}/resources/compare", headers=h, params={"from": "2026-02-01", "to": "2026-02-28"}).json()
    cur = win(src, "2026-02-01", "2026-02-28")
    rows = {r["department"]: r for r in j["departments"]}
    assert set(rows) == set(src.department.unique())
    icu = cur[cur.department == "ICU"]
    assert rows["ICU"]["bed_occupancy_pct"] == pytest.approx((icu.occupied_beds / icu.total_beds * 100).mean(), abs=0.06)
    assert rows["OPD"]["has_beds"] is False and rows["OPD"]["bed_occupancy_pct"] is None
    assert [r["workload_index"] for r in j["departments"]] == sorted((r["workload_index"] for r in j["departments"]), reverse=True)


def test_resource_beds_detail(client, loaded):
    src, h = loaded
    j = client.get(f"{API}/resources/beds", headers=h, params={"from": "2026-02-01", "to": "2026-02-28"}).json()
    cur = win(src, "2026-02-01", "2026-02-28")
    beds = cur[cur.total_beds > 0]
    g = beds.groupby("timestamp")[["occupied_beds", "total_beds"]].sum()
    occ = g.occupied_beds / g.total_beds * 100
    assert j["kpis"]["average"]["value"] == pytest.approx(beds.assign(o=beds.occupied_beds / beds.total_beds * 100).o.mean(), abs=0.6)
    assert j["kpis"]["hours_over_warning"] == int((occ >= 85).sum())
    assert j["kpis"]["current"]["total"] == int(beds[beds.timestamp == beds.timestamp.max()].total_beds.sum())
    assert "OPD" not in {d["department"] for d in j["departments"]}
    assert len(j["hours"]) == 24


def test_resource_staff_and_lab(client, loaded):
    _, h = loaded
    for kind in ("doctors", "nurses", "lab"):
        j = client.get(f"{API}/resources/{kind}", headers=h, params={"from": "2026-02-01", "to": "2026-02-28"}).json()
        assert j["applicable"] and j["series"] and j["departments"]
        assert j["thresholds"]["critical"] > j["thresholds"]["warning"]
    d = client.get(f"{API}/departments", headers=h).json()
    opd = next(x for x in d if x["name"] == "OPD")["id"]
    j = client.get(f"{API}/resources/beds", headers=h, params={"department_id": opd}).json()
    assert j["applicable"] is False and "no beds" in j["message"]


def test_empty_database(client, loaded):
    _, h = loaded
    with SessionLocal() as db:
        db.execute(delete(DerivedMetric)); db.execute(delete(HospitalData)); db.execute(delete(Upload)); db.commit()
    assert client.get(f"{API}/flow/overview", headers=h).json() == {"has_data": False}
    assert client.get(f"{API}/resources/compare", headers=h).json() == {"has_data": False}
    assert client.get(f"{API}/resources/beds", headers=h).json() == {"has_data": False}
