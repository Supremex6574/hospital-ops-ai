"""SHAP explanations: additivity (the whole point of SHAP), plausibility on a known pattern, API contract."""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import delete

from app.database import SessionLocal
from app.models import Alert, DerivedMetric, Forecast, HospitalData, ModelResult, Upload
from app.services.ml.explain import GROUPS, _shap_values, group_of
from app.services.ml.forecasting import _models, make_features

API = "/api/v1"
ROOT = Path(__file__).resolve().parents[2]


def _series():
    idx = pd.date_range("2026-01-01", periods=200, freq="D")
    rng = np.random.default_rng(3)
    return pd.Series(100 + 30 * (idx.dayofweek < 5) + rng.normal(0, 3, 200), index=idx)


@pytest.mark.parametrize("name", ["ridge", "random_forest", "gradient_boosting"])
def test_shap_is_additive_and_finds_the_weekday_pattern(name):
    y = _series()
    X = make_features(y).dropna()
    model = _models()[name].fit(X, y.loc[X.index])
    sv, base = _shap_values(model, X, X.tail(60), name)
    assert np.allclose(base + sv.sum(axis=1), model.predict(X.tail(60)), atol=0.5 if name != "ridge" else 1e-6)
    groups = np.array([group_of(f) for f in X.columns])
    imp = {g: np.abs(sv[:, groups == g].sum(axis=1)).mean() for g in GROUPS}
    # the series is driven by weekday vs weekend. Two groups can carry that pattern (the weekday flag itself, and the
    # same-weekday history, which encodes the same thing), so together they must dominate while unrelated groups stay small
    weekly = imp["weekday"] + imp["history"]
    assert weekly > 5 * (imp["season"] + imp["trend"]), imp


def test_group_mapping_covers_every_feature():
    cols = make_features(_series()).columns
    assert {group_of(c) for c in cols} == set(GROUPS)


@pytest.fixture(scope="module")
def headers(client):
    return {"Authorization": "Bearer " + client.post(f"{API}/auth/login", json={"username": "admin", "password": "Admin@123"}).json()["access_token"]}


@pytest.fixture(scope="module")
def loaded(client, headers):
    with SessionLocal() as db:
        for m in (Forecast, ModelResult, Alert, DerivedMetric, HospitalData, Upload):
            db.execute(delete(m))
        db.commit()
    spec = importlib.util.spec_from_file_location("gen_ex", ROOT / "data" / "generate_synthetic.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gen_ex"] = mod
    spec.loader.exec_module(mod)
    df = mod.generate("2026-01-01", 200, seed=7)[0]
    r = client.post(f"{API}/data/upload", headers=headers, files={"file": ("d.csv", df.to_csv(index=False).encode(), "text/csv")})
    assert r.status_code == 201, r.text
    return df


def test_auth_and_validation(client, headers):
    assert client.get(f"{API}/explain/forecast").status_code == 401
    assert client.get(f"{API}/explain/forecast", headers=headers, params={"target": "x"}).status_code == 422


@pytest.mark.parametrize("target", ["admissions", "bed_occupancy"])
def test_explanation_contract_and_additivity(client, headers, loaded, target):
    fc = client.get(f"{API}/forecast/overview", headers=headers, params={"target": target}).json()
    j = client.get(f"{API}/explain/forecast", headers=headers, params={"target": target}).json()
    assert j["has_data"] and j["model"] == fc["best_model"]
    if not j["explainable"]:           # a baseline rule won: nothing to decompose, and the page says so
        assert "rule" in j["message"] or "average" in j["message"]
        return
    assert abs(sum(g["share_pct"] for g in j["groups"]) - 100) < 0.6
    assert [g["mean_abs"] for g in j["groups"]] == sorted((g["mean_abs"] for g in j["groups"]), reverse=True)
    assert len(j["days"]) == 7 and [d["date"] for d in j["days"]] == [f["date"] for f in fc["forecast"]]
    for d, f in zip(j["days"], fc["forecast"]):
        # baseline plus every driver's effect gives exactly the model output (rounding only)
        assert d["baseline"] + sum(x["effect"] for x in d["drivers"]) == pytest.approx(d["model_output"], abs=0.1)
        assert d["predicted"] == f["predicted"] and d["model_output"] == pytest.approx(f["predicted"], abs=0.1 + (0 if f["predicted"] > 0 else 1e9))
        assert all(x["sentence"] for x in d["drivers"])
    assert len(j["weekday_effect"]) == 7 and len(j["features"]) <= 10 and j["backtest_days"] > 0


def test_no_explanation_for_departments_without_beds(client, headers, loaded):
    opd = next(d["id"] for d in client.get(f"{API}/departments", headers=headers).json() if d["name"] == "OPD")
    j = client.get(f"{API}/explain/forecast", headers=headers, params={"target": "bed_occupancy", "department_id": opd}).json()
    assert j["has_data"] is False and j["explainable"] is False and "no beds" in j["message"]
