"""Optimization: greedy allocation maths, API behaviour and consistency with the what-if engine."""
import importlib.util
import sys
from pathlib import Path

import pytest
from sqlalchemy import delete

from app.database import SessionLocal
from app.models import Alert, DerivedMetric, Forecast, HospitalData, ModelResult, Recommendation, SimulationResult, Upload
from app.services.decision import optimization as O

API = "/api/v1"
ROOT = Path(__file__).resolve().parents[2]


def test_greedy_balances_pressure():
    demand = {"A": 30.0, "B": 10.0}
    x = O._greedy(demand, {"A": 5, "B": 5}, 10, {"A": 1, "B": 1}, {"A": 9, "B": 9})
    assert x == {"A": 8, "B": 2} or x == {"A": 7, "B": 3}
    assert sum(x.values()) == 10
    # no single transfer can lower the maximum pressure further
    best = max(demand[k] / x[k] for k in x)
    for a, b in (("A", "B"), ("B", "A")):
        if x[b] > 1:
            y = dict(x); y[a] += 1; y[b] -= 1
            assert max(demand[k] / y[k] for k in y) >= best - 1e-9


def test_greedy_respects_bounds():
    x = O._greedy({"A": 100.0, "B": 1.0}, {"A": 5, "B": 5}, 10, {"A": 4, "B": 4}, {"A": 6, "B": 6})
    assert x == {"A": 6, "B": 4}


def test_moves_pair_donors_and_receivers():
    m = O._moves({"A": 3, "B": -2, "C": -1, "D": 1}, "beds")
    assert sum(x["count"] for x in m if x["to"] == "A") == 3
    assert {(x["from"], x["to"], x["count"]) for x in m if x["from"]} == {("B", "A", 2), ("C", "A", 1)}
    assert any(x["from"] is None and x["to"] == "D" and x["count"] == 1 for x in m)


@pytest.fixture(scope="module")
def headers(client):
    return {"Authorization": "Bearer " + client.post(f"{API}/auth/login", json={"username": "admin", "password": "Admin@123"}).json()["access_token"]}


@pytest.fixture(scope="module")
def loaded(client, headers):
    with SessionLocal() as db:
        for m in (SimulationResult, Recommendation, Forecast, ModelResult, Alert, DerivedMetric, HospitalData, Upload):
            db.execute(delete(m))
        db.commit()
    spec = importlib.util.spec_from_file_location("gen_opt", ROOT / "data" / "generate_synthetic.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gen_opt"] = mod
    spec.loader.exec_module(mod)
    df = mod.generate("2026-01-01", 120, seed=5)[0]
    assert client.post(f"{API}/data/upload", headers=headers, files={"file": ("s.csv", df.to_csv(index=False).encode(), "text/csv")}).status_code == 201


def run(client, headers, **b):
    return client.post(f"{API}/optimization/run", headers=headers, json=b)


def test_auth_and_validation(client, headers):
    assert client.post(f"{API}/optimization/run", json={"resource": "beds"}).status_code == 401
    for b in ({"resource": "icu"}, {"resource": "beds", "extra": -1}, {"resource": "beds", "max_change_pct": 90}, {}):
        assert run(client, headers, **b).status_code == 422


def test_no_data(client, headers):
    with SessionLocal() as db:
        for m in (SimulationResult, Recommendation, Forecast, ModelResult, Alert, DerivedMetric, HospitalData, Upload):
            db.execute(delete(m))
        db.commit()
    r = run(client, headers, resource="beds")
    assert r.status_code == 422 and "Upload" in r.json()["detail"]


@pytest.mark.parametrize("res", ["beds", "doctors", "nurses"])
def test_pool_is_conserved_and_pressure_not_worse(client, headers, loaded, res):
    r = run(client, headers, resource=res)
    assert r.status_code == 200, r.text
    j = r.json()
    assert sum(r["change"] for r in j["rows"]) == 0
    assert all(r["proposed"] >= 1 for r in j["rows"])
    assert j["pressure_worst_after"] <= j["pressure_worst_before"]
    assert j["simulation"]["departments"]
    assert "diagnos" not in str(j).lower()


def test_beds_only_move_between_wards(client, headers, loaded):
    j = run(client, headers, resource="beds").json()
    assert {r["department"] for r in j["rows"]} == {"General Ward", "Pediatrics", "Surgery"}


def test_extra_capacity_adds_to_total_and_lowers_pressure(client, headers, loaded):
    base = run(client, headers, resource="beds").json()
    j = run(client, headers, resource="beds", extra=20).json()
    assert sum(r["change"] for r in j["rows"]) == 20
    assert j["pressure_worst_after"] < base["pressure_worst_after"]
    assert sum(m["count"] for m in j["moves"] if m["from"] is None) >= 20


def test_change_limit_is_respected(client, headers, loaded):
    j = run(client, headers, resource="doctors", extra=10, max_change_pct=10).json()
    for r in j["rows"]:
        assert r["proposed"] <= -(-r["current"] * 110 // 100) and r["proposed"] >= int(r["current"] * 0.9)


def test_simulation_matches_what_if(client, headers, loaded):
    j = run(client, headers, resource="beds", extra=15).json()
    s = client.post(f"{API}/simulation/run", headers=headers, json={"save": False, **j["scenario"]}).json()
    assert s["hospital"]["scenario"] == j["simulation"]["hospital"]["scenario"]
