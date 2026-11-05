"""Forecasting: no-leakage unit test, metric correctness, selection logic, API contract, persistence, edge cases."""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models import Alert, DerivedMetric, Forecast, HospitalData, ModelResult, Upload
from app.services.ml.forecasting import HORIZON, make_features, metrics, train

API = "/api/v1"
ROOT = Path(__file__).resolve().parents[2]


def _gen(days, seed=7, start="2026-01-01"):
    spec = importlib.util.spec_from_file_location("gen_fc", ROOT / "data" / "generate_synthetic.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gen_fc"] = mod
    spec.loader.exec_module(mod)
    return mod.generate(start, days, seed=seed)[0]


def _reset(db):
    for m in (Forecast, ModelResult, Alert, DerivedMetric, HospitalData, Upload):
        db.execute(delete(m))
    db.commit()


@pytest.fixture(scope="module")
def headers(client):
    return {"Authorization": "Bearer " + client.post(f"{API}/auth/login", json={"username": "admin", "password": "Admin@123"}).json()["access_token"]}


@pytest.fixture(scope="module")
def loaded(client, headers):
    with SessionLocal() as db:
        _reset(db)
    df = _gen(200)
    r = client.post(f"{API}/data/upload", headers=headers, files={"file": ("d.csv", df.to_csv(index=False).encode(), "text/csv")})
    assert r.status_code == 201, r.text
    return df


def test_features_never_use_the_last_six_days():
    """Changing a day's value must not change the features of the next 6 days (that is what makes a 7-day horizon honest)."""
    idx = pd.date_range("2026-01-01", periods=80, freq="D")
    y = pd.Series(np.random.default_rng(0).normal(100, 10, 80), index=idx)
    base = make_features(y)
    y2 = y.copy()
    y2.iloc[60] += 1000
    new = make_features(y2)
    same = np.isclose(new.to_numpy(), base.to_numpy(), equal_nan=True).all(axis=1)
    first = base.index[~same].min()
    assert first >= idx[60] + pd.Timedelta(days=7)


def test_metrics_against_hand_calculation():
    a, p = np.array([100.0, 120.0, 80.0, 0.0]), np.array([110.0, 100.0, 80.0, 5.0])
    m = metrics(a, p)
    assert m["mae"] == pytest.approx((10 + 20 + 0 + 5) / 4)
    assert m["rmse"] == pytest.approx(np.sqrt((100 + 400 + 0 + 25) / 4))
    assert m["mape"] == pytest.approx((10 / 100 + 20 / 120 + 0) / 3 * 100)  # zero actuals are skipped
    assert m["r2"] == pytest.approx(1 - 525 / ((a - a.mean()) ** 2).sum())
    assert metrics(np.array([5.0, 5.0]), np.array([4.0, 6.0]))["r2"] is None  # constant actuals


def test_train_selects_lowest_rmse_and_forecasts_next_week():
    idx = pd.date_range("2026-01-01", periods=150, freq="D")
    y = pd.Series(100 + 15 * (idx.dayofweek < 5) + np.random.default_rng(1).normal(0, 2, 150), index=idx)
    res = train(y, "admissions")
    best = min(res["models"], key=lambda r: r["rmse"])
    assert best["model"] == res["best"] and sum(r["selected"] for r in res["models"]) == 1
    assert {r["model"] for r in res["models"]} == {"seasonal_naive", "moving_average", "ridge", "random_forest", "gradient_boosting"}
    assert [f["date"] for f in res["forecast"]] == [(idx[-1] + pd.Timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, HORIZON + 1)]
    wk = {pd.Timestamp(f["date"]).dayofweek: f["predicted"] for f in res["forecast"]}
    assert wk[0] > wk[6] + 5  # learned the weekday/weekend pattern
    assert res["folds"] >= 1 and len(res["test"]) == res["test_days"]


def test_require_auth_and_bad_input(client, headers):
    assert client.get(f"{API}/forecast/overview").status_code == 401
    assert client.get(f"{API}/forecast/overview", headers=headers, params={"target": "mortality"}).status_code == 422
    assert client.get(f"{API}/forecast/overview", headers=headers, params={"department_id": 0}).status_code == 422


def test_api_contract_and_metrics_consistency(client, headers, loaded):
    j = client.get(f"{API}/forecast/overview", headers=headers, params={"target": "admissions"}).json()
    assert j["has_data"] and j["enough"]
    last = pd.Timestamp(loaded.date.max())
    assert j["last_data_date"] == last.strftime("%Y-%m-%d")
    assert [f["date"] for f in j["forecast"]] == [(last + pd.Timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, 8)]
    assert all(f["lower"] <= f["predicted"] <= f["upper"] and f["predicted"] >= 0 for f in j["forecast"])
    # the selected model's backtest metrics must match what the pooled test predictions give
    t = pd.DataFrame(j["test"])
    sel = next(m for m in j["models"] if m["selected"])
    assert sel["mae"] == pytest.approx((t.actual - t.predicted).abs().mean(), abs=0.05)
    assert sel["rmse"] == min(m["rmse"] for m in j["models"])
    # history actuals match the stored data
    daily = loaded.groupby("date").admissions.sum()
    assert j["history"][-1]["actual"] == daily.iloc[-1]


def test_occupancy_bounds_scope_and_persistence(client, headers, loaded):
    j = client.get(f"{API}/forecast/overview", headers=headers, params={"target": "bed_occupancy"}).json()
    assert all(0 <= f["lower"] <= f["predicted"] <= f["upper"] <= 100 for f in j["forecast"])
    deps = {d["name"]: d["id"] for d in client.get(f"{API}/departments", headers=headers).json()}
    opd = client.get(f"{API}/forecast/overview", headers=headers, params={"target": "bed_occupancy", "department_id": deps["OPD"]}).json()
    assert opd["has_data"] is False and "no beds" in opd["message"]
    icu = client.get(f"{API}/forecast/overview", headers=headers, params={"target": "admissions", "department_id": deps["ICU"]}).json()
    assert icu["enough"] and icu["history"] != j["history"]
    with SessionLocal() as db:
        rows = db.scalars(select(ModelResult).where(ModelResult.target == "bed_occupancy", ModelResult.department_id.is_(None))).all()
        assert len(rows) == 5 and sum(r.is_selected for r in rows) == 1
        fc = db.scalars(select(Forecast).where(Forecast.target == "bed_occupancy", Forecast.department_id.is_(None))).all()
        assert len(fc) == 7 and {f.model_id for f in fc} == {r.id for r in rows if r.is_selected}


def test_retrain_replaces_instead_of_duplicating(client, headers, loaded):
    assert client.post(f"{API}/forecast/retrain", headers=headers, params={"target": "admissions"}).status_code == 200
    with SessionLocal() as db:
        rows = db.scalars(select(ModelResult).where(ModelResult.target == "admissions", ModelResult.department_id.is_(None))).all()
        assert len(rows) == 5


def test_not_enough_data_and_empty(client, headers):
    with SessionLocal() as db:
        _reset(db)
    assert client.get(f"{API}/forecast/overview", headers=headers).json()["has_data"] is False
    df = _gen(40)
    assert client.post(f"{API}/data/upload", headers=headers, files={"file": ("s.csv", df.to_csv(index=False).encode(), "text/csv")}).status_code == 201
    j = client.get(f"{API}/forecast/overview", headers=headers).json()
    assert j["has_data"] and j["enough"] is False and "at least" in j["message"]
