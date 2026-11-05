"""What-if simulation: model arithmetic, direction of effects, validation and persistence."""
import importlib.util
import sys
from pathlib import Path

import pytest
from sqlalchemy import delete

from app.database import SessionLocal
from app.models import Alert, DerivedMetric, Forecast, HospitalData, ModelResult, Recommendation, SimulationResult, Upload

API = "/api/v1"
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def headers(client):
    return {"Authorization": "Bearer " + client.post(f"{API}/auth/login", json={"username": "admin", "password": "Admin@123"}).json()["access_token"]}


@pytest.fixture(scope="module")
def loaded(client, headers):
    with SessionLocal() as db:
        for m in (SimulationResult, Recommendation, Forecast, ModelResult, Alert, DerivedMetric, HospitalData, Upload):
            db.execute(delete(m))
        db.commit()
    spec = importlib.util.spec_from_file_location("gen_sim", ROOT / "data" / "generate_synthetic.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gen_sim"] = mod
    spec.loader.exec_module(mod)
    df = mod.generate("2026-01-01", 120, seed=11)[0]
    r = client.post(f"{API}/data/upload", headers=headers, files={"file": ("s.csv", df.to_csv(index=False).encode(), "text/csv")})
    assert r.status_code == 201, r.text


def run(client, headers, **body):
    body.setdefault("save", False)
    return client.post(f"{API}/simulation/run", headers=headers, json=body)


def dept(res, name):
    return next(d for d in res["departments"] if d["department"] == name)


def test_auth_required(client):
    assert client.post(f"{API}/simulation/run", json={}).status_code == 401
    assert client.get(f"{API}/simulation/baseline").status_code == 401


def test_no_data_message(client, headers):
    with SessionLocal() as db:
        for m in (SimulationResult, Recommendation, Forecast, ModelResult, Alert, DerivedMetric, HospitalData, Upload):
            db.execute(delete(m))
        db.commit()
    r = run(client, headers)
    assert r.status_code == 422 and "Upload" in r.json()["detail"]


def test_baseline_lists_departments(client, headers, loaded):
    j = client.get(f"{API}/simulation/baseline", headers=headers).json()
    names = {d["department"] for d in j["departments"]}
    assert {"Emergency", "OPD", "ICU", "General Ward", "Pediatrics", "Surgery"} <= names
    assert next(d for d in j["departments"] if d["department"] == "OPD")["has_beds"] is False


def test_unchanged_scenario_reproduces_baseline(client, headers, loaded):
    j = run(client, headers).json()
    h = j["hospital"]
    assert h["baseline"] == h["scenario"]
    for d in j["departments"]:
        assert d["baseline"] == d["scenario"]


def test_more_beds_lowers_occupancy_and_overflow(client, headers, loaded):
    base = run(client, headers).json()
    j = run(client, headers, departments=[{"department": "General Ward", "beds_delta": 30}]).json()
    b, s = dept(j, "General Ward")["baseline"], dept(j, "General Ward")["scenario"]
    assert s["beds"] == b["beds"] + 30
    assert s["demand_pct"] < b["demand_pct"]
    assert s["overflow_patients_avg"] <= b["overflow_patients_avg"]
    # other departments are untouched
    assert dept(j, "ICU")["scenario"] == dept(base, "ICU")["scenario"]


def test_occupancy_arithmetic(client, headers, loaded):
    j = run(client, headers, arrivals_change_pct=20, los_change_pct=10).json()
    w = dept(j, "General Ward")
    # census scales by 1.2 x 1.1 = 1.32 (average of a linear scaling, so exact on demand %)
    assert w["scenario"]["demand_pct"] == pytest.approx(w["baseline"]["demand_pct"] * 1.32, rel=0.01)
    assert w["scenario"]["occupancy_pct"] <= 100


def test_overflow_when_demand_exceeds_beds(client, headers, loaded):
    j = run(client, headers, arrivals_change_pct=60, los_change_pct=40).json()
    w = dept(j, "General Ward")["scenario"]
    assert w["overflow_patients_avg"] > 0 and w["occupancy_pct"] <= 100 < w["peak_demand_pct"] or w["demand_pct"] > 100


def test_more_arrivals_raise_wait_and_staff_load(client, headers, loaded):
    j = run(client, headers, arrivals_change_pct=30).json()
    e = dept(j, "Emergency")
    assert e["scenario"]["wait_min"] > e["baseline"]["wait_min"]
    assert e["scenario"]["doctor_load_pct"] > e["baseline"]["doctor_load_pct"]
    assert j["hospital"]["delta"]["wait_min"] > 0


def test_more_doctors_lower_wait(client, headers, loaded):
    j = run(client, headers, departments=[{"department": "Emergency", "doctors_delta": 2, "nurses_delta": 2}]).json()
    e = dept(j, "Emergency")
    assert e["scenario"]["wait_min"] < e["baseline"]["wait_min"]
    assert e["scenario"]["doctor_load_pct"] < e["baseline"]["doctor_load_pct"]


def test_fewer_staff_raise_wait(client, headers, loaded):
    j = run(client, headers, departments=[{"department": "Emergency", "doctors_delta": -1}]).json()
    e = dept(j, "Emergency")
    assert e["scenario"]["wait_min"] > e["baseline"]["wait_min"]


def test_wait_model_is_reported_and_bounded(client, headers, loaded):
    j = run(client, headers).json()
    for d in j["departments"]:
        m = d["wait_model"]
        assert m["source"] in ("fitted", "fitted+floor", "default")
        assert 0 <= m["staff_elasticity"] <= 2.5 and 0 <= m["bed_elasticity"] <= 2.5
    assert dept(j, "OPD")["wait_model"]["bed_elasticity"] == 0


def test_opd_has_no_bed_fields(client, headers, loaded):
    j = run(client, headers, arrivals_change_pct=10).json()
    assert "occupancy_pct" not in dept(j, "OPD")["scenario"]
    assert dept(j, "OPD")["scenario"]["arrivals_per_hour"] > dept(j, "OPD")["baseline"]["arrivals_per_hour"]


def test_needs_are_sufficient(client, headers, loaded):
    j = run(client, headers, arrivals_change_pct=25).json()
    need = dept(j, "General Ward")["needs"]["beds_for_warning"]
    k = run(client, headers, arrivals_change_pct=25, departments=[{"department": "General Ward", "beds_delta": need - int(dept(j, "General Ward")["scenario"]["beds"])}]).json()
    # with the suggested beds, the busiest 5% of hours sit at or under the warning level (rounding allowance)
    assert dept(k, "General Ward")["scenario"]["peak_demand_pct"] <= 85.5


def test_summary_mentions_status_change(client, headers, loaded):
    j = run(client, headers, arrivals_change_pct=50, los_change_pct=30).json()
    assert any(s["kind"] == "worse" for s in j["summary"])
    assert j["summary"][-1]["kind"] == "note"


@pytest.mark.parametrize("body,code", [
    ({"arrivals_change_pct": 500}, 422),
    ({"los_change_pct": -90}, 422),
    ({"baseline_days": 3}, 422),
    ({"departments": [{"department": "Nowhere", "beds_delta": 1}]}, 422),
    ({"departments": [{"department": "OPD", "beds_delta": 5}]}, 422),
    ({"departments": [{"department": "ICU", "beds_delta": -20}]}, 422),
    ({"departments": [{"department": "ICU", "beds_delta": 1}, {"department": "ICU", "beds_delta": 2}]}, 422),
    ({"departments": [{"department": "Emergency", "doctors_delta": -30}]}, 422),
    ({"departments": [{"department": "Emergency", "beds_delta": 999}]}, 422),
])
def test_invalid_scenarios_rejected(client, headers, loaded, body, code):
    r = run(client, headers, **body)
    assert r.status_code == code
    assert "Traceback" not in r.text


def test_save_history_and_delete(client, headers, loaded):
    r = run(client, headers, save=True, arrivals_change_pct=10, departments=[{"department": "ICU", "beds_delta": 2}])
    assert r.status_code == 200
    rid = r.json()["id"]
    hist = client.get(f"{API}/simulation/history", headers=headers).json()
    assert hist[0]["id"] == rid and hist[0]["scenario"]["arrivals_change_pct"] == 10
    full = client.get(f"{API}/simulation/history/{rid}", headers=headers).json()
    assert full["departments"] and full["id"] == rid
    assert client.delete(f"{API}/simulation/history/{rid}", headers=headers).status_code == 204
    assert client.get(f"{API}/simulation/history/{rid}", headers=headers).status_code == 404


def test_unsaved_run_not_stored(client, headers, loaded):
    before = len(client.get(f"{API}/simulation/history", headers=headers).json())
    run(client, headers, arrivals_change_pct=5)
    assert len(client.get(f"{API}/simulation/history", headers=headers).json()) == before


def test_no_clinical_language(client, headers, loaded):
    text = run(client, headers, arrivals_change_pct=40, los_change_pct=20).text.lower()
    for w in ("diagnos", "treatment", "prescri", "disease"):
        assert w not in text
