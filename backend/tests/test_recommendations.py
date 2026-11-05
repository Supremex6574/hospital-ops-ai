"""Recommendation engine: rule arithmetic, an end-to-end scenario with injected problems, and the accept/dismiss lifecycle."""
import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models import Alert, DerivedMetric, Forecast, HospitalData, ModelResult, Recommendation, Upload
from app.services.decision import recommendations as R

API = "/api/v1"
ROOT = Path(__file__).resolve().parents[2]


def test_hours_text_and_priority():
    assert R._hours_text([9, 10, 11, 15]) == "09:00-12:00 and 15:00-16:00"
    assert R._hours_text([23]) == "23:00-24:00"
    assert R._pr(2, 4) == "high" and R._pr(2, 1) == "medium" and R._pr(1, 3) == "medium" and R._pr(1, 1) == "low"


def _staff_frame():
    # load = patients per doctor x doctors on duty
    return pd.DataFrame([
        {"department": "A", "doctors_available": 2, "patients_per_doctor": 12.0, "doc_norm": 7.0},   # load 24 -> needs ceil(24/7)=4, has 2 -> needs 2
        {"department": "B", "doctors_available": 6, "patients_per_doctor": 3.0, "doc_norm": 4.0},    # load 18 -> min doctors ceil(18/(4*.95))=5 -> spare 1
        {"department": "C", "doctors_available": 4, "patients_per_doctor": 5.0, "doc_norm": 4.0},    # load 20 -> min ceil(20/3.8)=6 -> no spare
    ])


def test_staff_transfer_arithmetic():
    t = R._staff_transfer(_staff_frame(), "A", "doctors")
    assert t["need"] == 2 and t["donor"]["donor"] == "B" and t["donor"]["spare"] == 1 and t["move"] == 1


def test_staff_transfer_nobody_can_lend():
    f = _staff_frame().iloc[[0, 2]]
    t = R._staff_transfer(f, "A", "doctors")
    assert t["need"] == 2 and t["donor"] is None and t["move"] == 0


def test_staff_transfer_not_needed():
    f = _staff_frame()
    f.loc[0, "patients_per_doctor"] = 6.0   # load 12, norm 7 -> needs 2, has 2
    assert R._staff_transfer(f, "A", "doctors") is None


@pytest.fixture(scope="module")
def headers(client):
    return {"Authorization": "Bearer " + client.post(f"{API}/auth/login", json={"username": "admin", "password": "Admin@123"}).json()["access_token"]}


@pytest.fixture(scope="module")
def scenario(client, headers):
    """200 normal days, then the last 12 hours are made bad in known ways."""
    with SessionLocal() as db:
        for m in (Recommendation, Forecast, ModelResult, Alert, DerivedMetric, HospitalData, Upload):
            db.execute(delete(m))
        db.commit()
    spec = importlib.util.spec_from_file_location("gen_rec", ROOT / "data" / "generate_synthetic.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gen_rec"] = mod
    spec.loader.exec_module(mod)
    df = mod.generate("2026-01-01", 200, seed=7)[0]
    last = df["date"].max()
    late = (df["date"] == last) & (df["time"] >= "12:00")
    for dept in ("General Ward", "ICU", "Pediatrics"):
        m = late & (df["department"] == dept)
        df.loc[m, "occupied_beds"] = (df.loc[m, "total_beds"] * 0.98).astype(int)
        df.loc[m, "available_beds"] = df.loc[m, "total_beds"] - df.loc[m, "occupied_beds"]
    m = late & (df["department"] == "Emergency")
    df.loc[m, "doctors_available"] = 1
    m = late & (df["department"] == "Surgery")
    df.loc[m, "lab_tests_ordered"] = (df.loc[m, "lab_capacity"] * 1.5).astype(int)
    r = client.post(f"{API}/data/upload", headers=headers, files={"file": ("s.csv", df.to_csv(index=False).encode(), "text/csv")})
    assert r.status_code == 201, r.text
    return df


def _items(client, headers, **p):
    r = client.get(f"{API}/recommendations", headers=headers, params=p)
    assert r.status_code == 200, r.text
    return r.json()


def test_auth_and_validation(client, headers):
    assert client.get(f"{API}/recommendations").status_code == 401
    assert client.get(f"{API}/recommendations", headers=headers, params={"status": "bogus"}).status_code == 422
    assert client.patch(f"{API}/recommendations/999999", headers=headers, json={"status": "accepted"}).status_code == 404
    assert client.patch(f"{API}/recommendations/1", headers=headers, json={"status": "bogus"}).status_code == 422


def test_injected_problems_produce_the_right_recommendations(client, headers, scenario):
    j = _items(client, headers)
    by = {(i["rule"], i["department"]): i for i in j["items"]}
    # beds: three wards at 98% for 12 hours, so high priority, with the arithmetic in the impact line
    for dept in ("General Ward", "ICU", "Pediatrics"):
        i = by[("beds_now", dept)]
        assert i["priority"] == "high" and i["confidence"] == "high" and "6 of the last 6 hours" in i["reason"]
        assert "Freeing" in i["impact"] and i["horizon"] == "Now"
    gw = scenario[(scenario.department == "General Ward")].iloc[-1]
    n_expected = int(gw.occupied_beds) - (-(-int(gw.total_beds) * 85 // 100) - 1)   # beds above the most that can stay occupied below 85%
    assert f"Freeing {n_expected} bed" in by[("beds_now", "General Ward")]["impact"]
    # three departments critical together -> hospital level escalation
    assert ("hospital_surge", None) in by and by[("hospital_surge", None)]["priority"] == "high"
    # one doctor on duty in Emergency
    d = by[("doctor_load", "Emergency")]
    assert d["priority"] == "high" and any(e["label"] == "Doctors on duty" and e["value"] == "1" for e in d["evidence"])
    assert "Move" in d["action"] or "on-call" in d["action"]
    # lab overload in Surgery
    assert by[("lab_overload", "Surgery")]["priority"] in ("high", "medium")
    # every item is explainable: action, reason, impact, evidence, and no clinical wording
    for i in j["items"]:
        assert i["action"] and i["reason"] and i["impact"] and i["evidence"] and i["confidence"] in ("high", "medium")
        assert not any(w in (i["action"] + i["title"]).lower() for w in ("diagnos", "prescri", "medication", "treat "))
    assert j["counts"]["high"] >= 5 and j["disclaimer"]
    # sorted: high priority first
    order = [i["priority"] for i in j["items"]]
    assert order == sorted(order, key=lambda p: R.PRIORITY_ORDER[p])


def test_lifecycle_accept_dismiss_and_refresh_keep_choices(client, headers, scenario):
    items = _items(client, headers)["items"]
    a, b = items[0], items[1]
    assert client.patch(f"{API}/recommendations/{a['id']}", headers=headers, json={"status": "accepted"}).json()["status"] == "accepted"
    assert client.patch(f"{API}/recommendations/{b['id']}", headers=headers, json={"status": "dismissed"}).status_code == 200
    again = _items(client, headers)["items"]
    assert b["id"] not in {i["id"] for i in again}                       # dismissed ones leave the active list
    assert {i["id"]: i["status"] for i in again}[a["id"]] == "accepted"
    r = client.post(f"{API}/recommendations/refresh", headers=headers).json()   # regenerating must not undo the choices
    assert {i["id"]: i["status"] for i in r["items"]}.get(a["id"]) == "accepted"
    assert b["id"] not in {i["id"] for i in r["items"]}
    assert b["id"] in {i["id"] for i in _items(client, headers, status="dismissed")["items"]}


def test_persist_retires_cleared_conditions():
    base = dict(department_id=None, category="Staffing", priority="high", title="t", action="a", reason="r", impact="i",
                horizon="Now", confidence="high", evidence=[])
    with SessionLocal() as db:
        db.execute(delete(Recommendation)); db.commit()
        R._persist(db, [{**base, "rule": "x"}, {**base, "rule": "y"}, {**base, "rule": "z"}], pd.Timestamp("2026-01-01").to_pydatetime())
        rows = {r.trigger_rule: r for r in db.scalars(select(Recommendation)).all()}
        rows["y:hospital"].status, rows["z:hospital"].status = "accepted", "dismissed"
        db.commit()
        R._persist(db, [{**base, "rule": "x", "priority": "low"}], pd.Timestamp("2026-01-02").to_pydatetime())   # y and z conditions cleared
        now = {r.trigger_rule: r for r in db.scalars(select(Recommendation)).all()}
        assert set(now) == {"x:hospital", "y:hospital"}
        assert now["x:hospital"].priority == "low" and now["y:hospital"].status == "resolved"
        R._persist(db, [{**base, "rule": "y"}], pd.Timestamp("2026-01-03").to_pydatetime())                       # y comes back
        assert {r.trigger_rule: r.status for r in db.scalars(select(Recommendation)).all()} == {"y:hospital": "new"}
        db.execute(delete(Recommendation)); db.commit()


def test_empty_database(client, headers):
    with SessionLocal() as db:
        for m in (Recommendation, Forecast, ModelResult, Alert, DerivedMetric, HospitalData, Upload):
            db.execute(delete(m))
        db.commit()
    assert _items(client, headers) == {"has_data": False, "items": []}
