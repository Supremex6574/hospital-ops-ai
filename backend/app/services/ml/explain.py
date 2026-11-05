"""
Explainability for the forecasts (SHAP).

SHAP splits each prediction into a baseline (the model's average output) plus one contribution per input; the
contributions add up exactly to the prediction. The inputs are grouped into plain-language drivers (weekday pattern,
same-weekday history, recent average, time of year, trend) by summing the contributions in each group, which is valid
because SHAP values are additive.

SHAP explains what the MODEL relies on. It does not prove what causes demand in the hospital.
"""
from __future__ import annotations

import joblib
import numpy as np
import pandas as pd
import shap
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import HospitalData
from app.services.ml.forecasting import ARTIFACT_DIR, HORIZON, MODEL_LABELS, TARGETS, daily_series, get_forecast, make_features

GROUPS = {
    "weekday": "Day of the week",
    "history": "Same weekday in recent weeks",
    "recent": "Recent average level",
    "season": "Time of year",
    "trend": "Long-term trend",
}
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
FEATURE_LABELS = {
    "lag_7": "Same weekday last week", "lag_14": "Same weekday 2 weeks ago", "lag_21": "Same weekday 3 weeks ago",
    "lag_28": "Same weekday 4 weeks ago", "lag_median": "Typical same-weekday value (median of 4 weeks)",
    "roll_7": "Average of the 7 days ending a week ago", "roll_28": "Average of the 28 days ending a week ago",
    "trend": "Long-term trend", "season_sin": "Time of year (seasonal cycle, part 1)", "season_cos": "Time of year (seasonal cycle, part 2)",
    **{f"dow_{i}": f"Day is {d}" for i, d in enumerate(WEEKDAYS)},
}
_CACHE: dict = {}


def group_of(feature: str) -> str:
    if feature.startswith("dow_"):
        return "weekday"
    if feature.startswith("lag_"):
        return "history"
    if feature.startswith("roll_"):
        return "recent"
    return "season" if feature.startswith("season_") else "trend"


def _shap_values(model, X_background: pd.DataFrame, X_rows: pd.DataFrame, name: str):
    if name == "ridge":
        scaler, ridge = model[0], model[-1]
        ex = shap.LinearExplainer(ridge, scaler.transform(X_background))
        return np.asarray(ex.shap_values(scaler.transform(X_rows))), float(np.ravel(ex.expected_value)[0])
    ex = shap.TreeExplainer(model)
    return np.asarray(ex.shap_values(X_rows)), float(np.ravel(ex.expected_value)[0])


def _unit(target: str) -> str:
    return "patients" if target == "admissions" else "percentage points"


def _digits(target: str) -> int:
    return 1  # effects are often well under one patient, so one decimal for both targets


def _sentence(group_label: str, value: float, target: str) -> str:
    d = _digits(target)
    return f"{group_label} {'raises' if value > 0 else 'lowers'} the forecast by {abs(value):.{d}f} {_unit(target)}"


def explain_forecast(db: Session, target: str, department_id: int | None) -> dict:
    fc = get_forecast(db, target, department_id)  # trains and stores on first use
    if not fc.get("enough"):
        return {"has_data": fc.get("has_data", False), "explainable": False, "message": fc.get("message"), "target": target}
    best = fc["best_model"]
    key = (db.scalar(select(func.count(HospitalData.id))), db.scalar(select(func.max(HospitalData.id))), target, department_id, best)
    if _CACHE.get("key") == key and _CACHE.get("slot") == (target, department_id) and best not in ("ridge", "random_forest", "gradient_boosting") or (
            _CACHE.get("key") == key and _CACHE.get("slot") == (target, department_id) and (ARTIFACT_DIR / f"{target}_{department_id or 'hospital'}.joblib").exists()):
        return _CACHE["out"]

    base_info = {"has_data": True, "target": target, "label": TARGETS[target]["label"], "unit": _unit(target), "model": best, "model_label": MODEL_LABELS[best]}
    if best in ("seasonal_naive", "moving_average"):
        out = {**base_info, "explainable": False,
               "message": "The selected model is a simple rule, so there is nothing hidden to explain. "
                          + ("It repeats the value from the same weekday last week." if best == "seasonal_naive" else "It averages the 7 days ending a week ago.")}
        _CACHE.update(key=key, slot=(target, department_id), out=out)
        return out

    path = ARTIFACT_DIR / f"{target}_{department_id or 'hospital'}.joblib"
    if not path.exists():  # saved model was removed: retrain once, which saves it again
        get_forecast(db, target, department_id, force=True)
    art = joblib.load(path)
    model, feats = art["model"], art["features"]
    y = daily_series(db, target, department_id)
    ext = pd.date_range(y.index[0], y.index[-1] + pd.Timedelta(days=HORIZON), freq="D")
    X = make_features(y.reindex(ext))
    known = X.loc[y.index].dropna()[feats]
    back = known.iloc[-fc["test_days"]:]
    fut = X.loc[ext[-HORIZON:], feats]

    sv, base = _shap_values(model, known, pd.concat([back, fut]), best)
    sv_back, sv_fut = sv[: len(back)], sv[len(back):]
    groups_of = np.array([group_of(f) for f in feats])

    # global importance (mean absolute contribution over the backtest days), by group and by feature
    g_imp = {g: float(np.abs(sv_back[:, groups_of == g].sum(axis=1)).mean()) for g in GROUPS if (groups_of == g).any()}
    total = sum(g_imp.values()) or 1.0
    groups = sorted(({"group": g, "label": GROUPS[g], "mean_abs": round(v, 3), "share_pct": round(v / total * 100, 1)} for g, v in g_imp.items()),
                    key=lambda r: -r["mean_abs"])
    f_imp = np.abs(sv_back).mean(axis=0)
    features = sorted(({"feature": f, "label": FEATURE_LABELS.get(f, f), "group": GROUPS[group_of(f)], "mean_abs": round(float(v), 3)}
                       for f, v in zip(feats, f_imp)), key=lambda r: -r["mean_abs"])[:10]

    # how much each weekday moves the forecast on average (weekday group only)
    wd_cols = groups_of == "weekday"
    wd_eff = pd.Series(sv_back[:, wd_cols].sum(axis=1), index=back.index)
    weekday_effect = [{"day": WEEKDAYS[d][:3], "effect": round(float(wd_eff[wd_eff.index.dayofweek == d].mean()), 2)} for d in range(7)]

    # day-by-day explanation of the next 7 days
    days = []
    for i, d in enumerate(fut.index):
        row, contrib = fut.iloc[i], sv_fut[i]
        pred = base + float(contrib.sum())
        gvals = {g: float(contrib[groups_of == g].sum()) for g in g_imp}
        drivers = []
        for g, v in sorted(gvals.items(), key=lambda kv: -abs(kv[1])):
            idx = np.where(groups_of == g)[0]
            top = sorted(idx, key=lambda j: -abs(contrib[j]))[:3]
            drivers.append({
                "group": g, "label": GROUPS[g], "effect": round(v, 2), "sentence": _sentence(GROUPS[g], v, target),
                "details": [{"label": FEATURE_LABELS.get(feats[j], feats[j]), "effect": round(float(contrib[j]), 2),
                             "value": None if feats[j].startswith(("dow_", "season_")) else round(float(row.iloc[j]), 2)} for j in top if abs(contrib[j]) > 1e-9],
            })
        fc_row = fc["forecast"][i]
        days.append({"date": d.strftime("%Y-%m-%d"), "weekday": WEEKDAYS[d.dayofweek], "predicted": fc_row["predicted"],
                     "model_output": round(pred, 2), "baseline": round(base, 2), "drivers": drivers})

    top = groups[0]
    summary = [
        f"The {MODEL_LABELS[best].lower()} bases its forecasts mainly on \"{top['label'].lower()}\" ({top['share_pct']:.0f}% of the total influence).",
        "Influence is the average size of a driver's push on the forecast, in either direction, over the backtest days.",
        "This shows what the model relies on. It does not show what causes demand in the hospital.",
    ]
    out = {**base_info, "explainable": True, "baseline": round(base, 2), "groups": groups, "features": features, "weekday_effect": weekday_effect,
           "days": days, "summary": summary, "backtest_days": int(len(back)),
           "method": "SHAP (TreeExplainer)" if best != "ridge" else "SHAP (LinearExplainer)"}
    _CACHE.update(key=key, slot=(target, department_id), out=out)
    return out
