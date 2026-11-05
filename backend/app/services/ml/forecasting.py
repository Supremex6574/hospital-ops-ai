"""
Daily forecasting of hospital admissions and bed occupancy, 7 days ahead.

Design (simple and honest rather than clever)
- One daily series per target and scope (hospital-wide or one department).
- Every feature is known at forecast time for any day up to 7 days ahead: calendar (weekday, time of year, trend)
  and values from 7 or more days earlier (lags 7/14/21/28 and rolling means of them). So one model serves the whole
  7-day horizon with no recursive guessing.
- Five models compete in a rolling backtest over the latest 28-112 days (up to four 28-day folds, each predicted by
  models trained only on earlier days): seasonal naive, 7-day moving average, ridge regression, random forest, gradient
  boosting. Selection is by lowest pooled RMSE. The two baselines are there so a complex model has to earn its place.
- The winner is refitted on all data to forecast. The range around each forecast is the 10th-90th percentile of the
  winner's backtest errors (a rough 80% range).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import Department, Forecast, HospitalData, ModelResult
from app.services.analytics.common import load_frame

HORIZON = 7
TEST_DAYS = 28
MAX_FOLDS = 4
MIN_TRAIN = 28         # the earliest backtest fold still trains on at least this many days
MIN_DAYS = 90          # 34 days are consumed by lags, then at least 28 train and 28 test
ARTIFACT_DIR = Path(__file__).resolve().parents[3] / "ml_artifacts"
TARGETS = {
    "admissions": {"label": "Admissions per day", "unit": "patients", "lo": 0.0, "hi": None},
    "bed_occupancy": {"label": "Bed occupancy", "unit": "%", "lo": 0.0, "hi": 100.0},
}
MODEL_LABELS = {
    "seasonal_naive": "Seasonal naive (same weekday last week)",
    "moving_average": "7-day moving average",
    "ridge": "Ridge regression",
    "random_forest": "Random forest",
    "gradient_boosting": "Gradient boosting",
}
_CACHE: dict = {}


# ------------------------------------------------------------------------------------------ data
def daily_series(db: Session, target: str, department_id: int | None) -> pd.Series:
    df = load_frame(db, None, None, department_id)
    if df.empty:
        return pd.Series(dtype=float)
    if target == "admissions":
        s = df.groupby(df["timestamp"].dt.normalize())["admissions"].sum().astype(float)
    else:
        beds = df[df["total_beds"] > 0]
        if beds.empty:
            return pd.Series(dtype=float)
        g = beds.groupby("timestamp")[["occupied_beds", "total_beds"]].sum()
        s = (g["occupied_beds"] / g["total_beds"] * 100).groupby(g.index.normalize()).mean()
    full = pd.date_range(s.index.min(), s.index.max(), freq="D")
    return s.reindex(full).interpolate(limit_direction="both")


def make_features(y: pd.Series) -> pd.DataFrame:
    """Feature table for a daily series (may extend into the future with NaN values). Only lags >= 7 days are used."""
    X = pd.DataFrame(index=y.index)
    for d in range(7):
        X[f"dow_{d}"] = (y.index.dayofweek == d).astype(float)
    doy = y.index.dayofyear / 365.25 * 2 * np.pi
    X["season_sin"], X["season_cos"] = np.sin(doy), np.cos(doy)
    X["trend"] = (y.index - y.index[0]).days / 365.0
    for k in (7, 14, 21, 28):
        X[f"lag_{k}"] = y.shift(k)
    X["lag_median"] = X[["lag_7", "lag_14", "lag_21", "lag_28"]].median(axis=1, skipna=False)  # same weekday, ignores one surge week
    X["roll_7"] = y.shift(7).rolling(7).mean()
    X["roll_28"] = y.shift(7).rolling(28).mean()
    return X


def _models() -> dict:
    return {
        "ridge": make_pipeline(StandardScaler(), Ridge(alpha=3.0)),
        "random_forest": RandomForestRegressor(n_estimators=200, min_samples_leaf=3, random_state=42, n_jobs=1),
        "gradient_boosting": GradientBoostingRegressor(n_estimators=200, max_depth=3, learning_rate=0.05, subsample=0.8, random_state=42),
    }


def metrics(actual: np.ndarray, pred: np.ndarray) -> dict:
    nz = actual != 0
    return {
        "mae": float(mean_absolute_error(actual, pred)),
        "rmse": float(np.sqrt(mean_squared_error(actual, pred))),
        "r2": float(r2_score(actual, pred)) if np.var(actual) > 0 else None,
        "mape": float(np.mean(np.abs((actual[nz] - pred[nz]) / actual[nz])) * 100) if nz.any() else None,
    }


def _clip(v, target):
    t = TARGETS[target]
    return np.clip(v, t["lo"], t["hi"] if t["hi"] is not None else np.inf)


# ------------------------------------------------------------------------------------------ training
def train(y: pd.Series, target: str) -> dict:
    """
    Rolling backtest, then refit the winner and forecast the next 7 days. Pure function.
    The last 28 x folds days (up to 4 folds) are predicted fold by fold, each by models trained only on earlier days;
    all predictions are pooled before scoring, so no model ever sees the days it is scored on.
    """
    ext_idx = pd.date_range(y.index[0], y.index[-1] + timedelta(days=HORIZON), freq="D")
    X = make_features(y.reindex(ext_idx))
    known = X.loc[y.index].dropna()
    yk = y.loc[known.index]
    n = len(known)
    folds = max(1, min(MAX_FOLDS, (n - MIN_TRAIN) // TEST_DAYS))
    test_len = folds * TEST_DAYS

    pooled: dict[str, list] = {k: [] for k in MODEL_LABELS}
    for f in range(folds):
        lo = n - test_len + f * TEST_DAYS
        tr_X, tr_y, te_X = known.iloc[:lo], yk.iloc[:lo], known.iloc[lo:lo + TEST_DAYS]
        pooled["seasonal_naive"].append(te_X["lag_7"].to_numpy())
        pooled["moving_average"].append(te_X["roll_7"].to_numpy())
        for name, m in _models().items():
            pooled[name].append(m.fit(tr_X, tr_y).predict(te_X))
    preds = {k: _clip(np.concatenate(v).astype(float), target) for k, v in pooled.items()}
    actual = yk.iloc[-test_len:]

    rows = [{"model": k, "label": MODEL_LABELS[k], **metrics(actual.to_numpy(), p)} for k, p in preds.items()]
    naive_rmse = next(r["rmse"] for r in rows if r["model"] == "seasonal_naive")
    best = min(rows, key=lambda r: r["rmse"])["model"]
    for r in rows:
        r["selected"] = r["model"] == best
        r["vs_naive_pct"] = round((naive_rmse - r["rmse"]) / naive_rmse * 100, 1) if naive_rmse else None

    # the winner's backtest errors give a rough 80% range
    err = actual.to_numpy() - preds[best]
    q_lo, q_hi = np.percentile(err, [10, 90])

    # refit the winner on every known row and forecast the future days
    fut_X = X.loc[ext_idx[-HORIZON:]]
    if best in ("seasonal_naive", "moving_average"):
        final, fut = None, fut_X["lag_7" if best == "seasonal_naive" else "roll_7"].to_numpy()
    else:
        final = _models()[best].fit(known, yk)
        fut = final.predict(fut_X)
    fut = _clip(np.asarray(fut, float), target)
    forecast = [{"date": d.strftime("%Y-%m-%d"), "predicted": round(float(v), 2),
                 "lower": round(float(_clip(v + q_lo, target)), 2), "upper": round(float(_clip(v + q_hi, target)), 2)}
                for d, v in zip(ext_idx[-HORIZON:], fut)]
    return {
        "models": rows, "best": best, "final_model": final, "features": list(known.columns),
        "test": [{"date": d.strftime("%Y-%m-%d"), "actual": round(float(a), 2), "predicted": round(float(p), 2)}
                 for d, a, p in zip(actual.index, actual.to_numpy(), preds[best])],
        "forecast": forecast, "folds": folds, "test_days": test_len, "train_days": int(n - test_len),
        "interval": {"lower_offset": round(float(q_lo), 2), "upper_offset": round(float(q_hi), 2)},
    }


# ------------------------------------------------------------------------------------------ service
def _scope(col, department_id):
    return col.is_(None) if department_id is None else col == department_id


def _persist(db: Session, target: str, department_id: int | None, res: dict) -> None:
    old = db.scalars(select(ModelResult.id).where(ModelResult.target == target, _scope(ModelResult.department_id, department_id))).all()
    if old:
        db.execute(delete(Forecast).where(Forecast.model_id.in_(old)))
        db.execute(delete(ModelResult).where(ModelResult.id.in_(old)))
    ids = {}
    params = json.dumps({"folds": res["folds"], "test_days": res["test_days"], "horizon_days": HORIZON})
    for r in res["models"]:
        m = ModelResult(target=target, department_id=department_id, model_name=r["model"], mae=r["mae"], rmse=r["rmse"], r2=r["r2"],
                        mape=r["mape"], is_selected=r["selected"], params_json=params)
        db.add(m)
        db.flush()
        ids[r["model"]] = m.id
    if res["final_model"] is not None:
        ARTIFACT_DIR.mkdir(exist_ok=True)
        path = ARTIFACT_DIR / f"{target}_{department_id or 'hospital'}.joblib"
        joblib.dump({"model": res["final_model"], "features": res["features"], "name": res["best"]}, path)
        db.get(ModelResult, ids[res["best"]]).artifact_path = path.name
    for i, f in enumerate(res["forecast"], start=1):
        db.add(Forecast(target=target, department_id=department_id, forecast_time=datetime.fromisoformat(f["date"]), horizon_h=24 * i,
                        predicted_value=f["predicted"], lower_ci=f["lower"], upper_ci=f["upper"], model_id=ids[res["best"]]))
    db.commit()


def get_forecast(db: Session, target: str, department_id: int | None, force: bool = False) -> dict:
    meta = {"target": target, "label": TARGETS[target]["label"], "unit": TARGETS[target]["unit"], "horizon_days": HORIZON}
    if department_id is not None and db.get(Department, department_id) is None:
        return {**meta, "has_data": False}
    y = daily_series(db, target, department_id)
    if y.empty:
        reason = "The selected department has no beds, so there is no occupancy to forecast." if target == "bed_occupancy" and department_id else None
        return {**meta, "has_data": False, "message": reason}
    if len(y) < MIN_DAYS:
        return {**meta, "has_data": True, "enough": False, "days": int(len(y)),
                "message": f"Forecasting needs at least {MIN_DAYS} days of data; {len(y)} are loaded."}
    key = (db.scalar(select(func.count(HospitalData.id))), db.scalar(select(func.max(HospitalData.id))))
    slot = (target, department_id)
    stored = db.scalar(select(func.count(ModelResult.id)).where(ModelResult.target == target, _scope(ModelResult.department_id, department_id)))
    if force or not stored or _CACHE.get(slot, {}).get("key") != key:  # also retrain if the stored results were removed
        res = train(y, target)
        _persist(db, target, department_id, res)
        _CACHE[slot] = {"key": key, "res": {k: v for k, v in res.items() if k != "final_model"}}
    res = _CACHE[slot]["res"]
    hist = y.iloc[-60:]
    return {
        **meta, "has_data": True, "enough": True, "last_data_date": y.index[-1].strftime("%Y-%m-%d"), "history_days": int(len(y)),
        "history": [{"date": d.strftime("%Y-%m-%d"), "actual": round(float(v), 2)} for d, v in hist.items()],
        "models": res["models"], "best_model": res["best"], "best_label": MODEL_LABELS[res["best"]],
        "test": res["test"], "forecast": res["forecast"], "train_days": res["train_days"], "test_days": res["test_days"], "folds": res["folds"],
        "interval": res["interval"],
        "notes": [
            f"Models are scored on a rolling backtest of the latest {res['test_days']} days ({res['folds']} fold{'s' if res['folds'] > 1 else ''} of {TEST_DAYS} days). Each fold is predicted by models trained only on earlier days; the winner has the lowest RMSE.",
            "The range is the 10th to 90th percentile of the winner's backtest errors, a rough 80% range.",
            "All inputs are known at forecast time (calendar and values from 7 or more days earlier), so the same model covers all 7 days.",
        ],
    }
