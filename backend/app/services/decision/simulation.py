"""
What-if simulation.

The question answered: "if we add/remove beds or staff, or arrivals / length of stay change, what happens to
occupancy and waiting time?"  The method is deliberately simple and every step can be explained:

1. Baseline = the last N days of the real hourly data (default 28).
2. Demand: arrivals scale by the arrivals change; the bed census scales by arrivals x length-of-stay change
   (Little's law: census = admission rate x average stay).
3. Capacity: beds, doctors and nurses on duty are changed by the entered amounts.
4. Occupancy = census / beds. Patients above the bed count are reported as "overflow" (boarding) - occupancy
   itself is capped at 100 %, the uncapped demand is shown as "demand %".
5. Staff load = patients per doctor / per nurse relative to the planning norm, as elsewhere in the app.
   The waiting-time model uses the average of the doctor and nurse load, so both teams matter.
6. Waiting time: wait_new = wait_base x (staff-load ratio)^b1 x (bed-pressure ratio)^b2, where b1 and b2 are
   estimated per department from that department's own history (log-log regression, clipped to 0..2.5).
   Where the history cannot separate staffing from bed pressure the staff effect gets a floor of 0.3 ("fitted+floor");
   departments without enough history use defaults ("default").

It is a planning aid built on assumptions (listed in the response), not a forecast and not a clinical model.
Every row of the baseline window is transformed, so peak hours are scaled too.
"""
from __future__ import annotations

import json
import math
from datetime import timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SimulationResult
from app.services.analytics.common import department_types, get_thresholds, load_frame, num
from app.services.ingestion.features import norms_for

DEFAULT_DAYS = 28
FIT_DAYS = 120
DEFAULT_B_STAFF, DEFAULT_B_BED = 0.8, 0.3
MAX_B = 2.5
MIN_B_STAFF = 0.3
MIN_FIT_ROWS = 72
STAFF_WARN, STAFF_CRIT = 1.3, 1.5  # same as the bottleneck rules
RATIO_CAP = 10.0  # hours with nobody on duty count as a very high, not infinite, load

ASSUMPTIONS = [
    "Baseline is the recent average pattern of the real data; the hours of the day and weekdays keep their shape.",
    "Bed census changes with arrivals x length of stay (steady-state). Extra beds do not attract extra patients.",
    "Staff changes mean doctors/nurses on duty in every hour, not headcount on the payroll.",
    "Waiting time responds to staff load and bed pressure using each department's own historical relationship.",
    "Planning norms for patients per doctor/nurse are assumptions, not clinical standards.",
]


class ScenarioError(ValueError):
    pass


def _ratio_pow(new: pd.Series, old: pd.Series, b: float) -> pd.Series:
    return (new.clip(lower=0.05) / old.clip(lower=0.05)) ** b


def _prepare(df: pd.DataFrame, dept_types: dict[str, str]) -> pd.DataFrame:
    """Add load, norms and the load ratios used by the model to a department's rows."""
    d = df.copy()
    doc_norm, nurse_norm = norms_for(d["department"].iloc[0], dept_types.get(d["department"].iloc[0]))
    d["has_beds"] = d["total_beds"] > 0
    d["load"] = np.where(d["has_beds"], d["occupied_beds"], d["arrivals"]).astype(float)
    d["doc_norm"], d["nurse_norm"] = doc_norm, nurse_norm
    return d


def _ratios(load, doctors, nurses, doc_norm, nurse_norm):
    doc = (load / doctors.where(doctors > 0) / doc_norm).where(~((doctors <= 0) & (load <= 0)), 0.0)
    nur = (load / nurses.where(nurses > 0) / nurse_norm).where(~((nurses <= 0) & (load <= 0)), 0.0)
    return doc.fillna(RATIO_CAP).clip(0, RATIO_CAP), nur.fillna(RATIO_CAP).clip(0, RATIO_CAP)


def _fit_wait(d: pd.DataFrame) -> tuple[float, float, str]:
    """Elasticities of waiting time to staff load and bed pressure from one department's history."""
    doc, nur = _ratios(d["load"], d["doctors_available"], d["nurses_available"], d["doc_norm"], d["nurse_norm"])
    staff = ((doc + nur) / 2).clip(lower=0.05)
    ok = (d["avg_wait_min"] > 0) & (d["arrivals"] > 0)
    use_bed = bool(d["has_beds"].iloc[0])
    cols = [np.log(staff[ok])]
    if use_bed:
        occ = (d["occupied_beds"] / d["total_beds"].where(d["total_beds"] > 0)).clip(0.05, 1.5)
        cols.append(np.log(occ[ok]))
    if ok.sum() < MIN_FIT_ROWS:
        return DEFAULT_B_STAFF, DEFAULT_B_BED if use_bed else 0.0, "default"
    x = np.column_stack([np.ones(ok.sum())] + [c.to_numpy() for c in cols])
    if np.linalg.matrix_rank(x) < x.shape[1] or np.std(x[:, 1]) < 1e-6:
        return DEFAULT_B_STAFF, DEFAULT_B_BED if use_bed else 0.0, "default"
    y = np.log(d.loc[ok, "avg_wait_min"].to_numpy(dtype=float))
    coef, *_ = np.linalg.lstsq(x, y, rcond=None)
    b_staff = float(np.clip(coef[1], 0, MAX_B))
    b_bed = float(np.clip(coef[2], 0, MAX_B)) if use_bed else 0.0
    if b_staff < MIN_B_STAFF:
        # staff load and bed census move together in the history, so the data cannot always separate them;
        # never let a department look indifferent to staffing
        return MIN_B_STAFF, b_bed, "fitted+floor"
    return b_staff, b_bed, "fitted"


def _status(occ_pct: float | None, doc_ratio: float, nur_ratio: float, th: dict) -> str:
    worst_staff = max(doc_ratio, nur_ratio)
    if (occ_pct is not None and occ_pct >= th["occupancy_critical_pct"]) or worst_staff >= STAFF_CRIT:
        return "critical"
    if (occ_pct is not None and occ_pct >= th["occupancy_warning_pct"]) or worst_staff >= STAFF_WARN:
        return "warning"
    return "ok"


def _simulate_dept(d: pd.DataFrame, adj: dict, glob_arr: float, glob_los: float, th: dict, b_staff, b_bed) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (baseline rows, scenario rows) with the columns needed for summaries."""
    mult = (1 + glob_arr / 100) * (1 + adj.get("arrivals_change_pct", 0) / 100)
    los = 1 + glob_los / 100
    has_beds = bool(d["has_beds"].iloc[0])

    base = pd.DataFrame({"timestamp": d["timestamp"]})
    base["arrivals"] = d["arrivals"].astype(float)
    base["beds"] = d["total_beds"].astype(float)
    base["census"] = d["occupied_beds"].astype(float)
    base["load"] = d["load"]
    base["doctors"] = d["doctors_available"].astype(float)
    base["nurses"] = d["nurses_available"].astype(float)
    base["wait"] = d["avg_wait_min"].astype(float)

    sc = base.copy()
    sc["arrivals"] = base["arrivals"] * mult
    sc["beds"] = base["beds"] + adj.get("beds_delta", 0)
    sc["doctors"] = base["doctors"] + adj.get("doctors_delta", 0)
    sc["nurses"] = base["nurses"] + adj.get("nurses_delta", 0)
    if has_beds:
        sc["census"] = base["census"] * mult * los
        sc["load"] = sc["census"]
    else:
        sc["load"] = base["load"] * mult

    for frame in (base, sc):
        doc, nur = _ratios(frame["load"], frame["doctors"], frame["nurses"], d["doc_norm"], d["nurse_norm"])
        frame["doc_ratio"], frame["nur_ratio"] = doc, nur
        if has_beds:
            beds = frame["beds"].where(frame["beds"] > 0)
            frame["demand_pct"] = (frame["census"] / beds * 100).fillna(0)
            frame["placed"] = np.minimum(frame["census"], frame["beds"].clip(lower=0))
            frame["occupancy_pct"] = (frame["placed"] / beds * 100).fillna(0)
            frame["overflow"] = (frame["census"] - frame["placed"]).clip(lower=0)
            frame["bed_pressure"] = (frame["demand_pct"] / 100).clip(0.05, 1.2)
        else:
            frame["demand_pct"] = frame["occupancy_pct"] = np.nan
            frame["placed"] = frame["overflow"] = 0.0
            frame["bed_pressure"] = 1.0

    staff_old = (base["doc_ratio"] + base["nur_ratio"]) / 2
    staff_new = (sc["doc_ratio"] + sc["nur_ratio"]) / 2
    factor = _ratio_pow(staff_new, staff_old, b_staff)
    if has_beds:
        factor = factor * _ratio_pow(sc["bed_pressure"], base["bed_pressure"], b_bed)
    sc["wait"] = base["wait"] * factor
    return base, sc


def _summ(f: pd.DataFrame, has_beds: bool, th: dict) -> dict:
    w = f["arrivals"].to_numpy(dtype=float)
    wait = float(np.average(f["wait"], weights=w)) if w.sum() > 0 else float(f["wait"].mean())
    doc, nur = float(f["doc_ratio"].mean()), float(f["nur_ratio"].mean())
    out = {
        "arrivals_per_hour": num(f["arrivals"].mean(), 2),
        "wait_min": num(wait, 1),
        "doctor_load_pct": num(doc * 100, 0),
        "nurse_load_pct": num(nur * 100, 0),
        "doctor_load_peak_pct": num(f["doc_ratio"].quantile(0.95) * 100, 0),
        "nurse_load_peak_pct": num(f["nur_ratio"].quantile(0.95) * 100, 0),
    }
    if has_beds:
        out.update({
            "beds": num(f["beds"].mean(), 0),
            "occupancy_pct": num(f["occupancy_pct"].mean(), 1),
            "demand_pct": num(f["demand_pct"].mean(), 1),
            "peak_demand_pct": num(f["demand_pct"].quantile(0.95), 1),
            "hours_over_warning_pct": num((f["demand_pct"] >= th["occupancy_warning_pct"]).mean() * 100, 1),
            "overflow_patients_avg": num(f["overflow"].mean(), 1),
            "overflow_patients_peak": num(f["overflow"].quantile(0.95), 1),
        })
    out["status"] = _status(out.get("demand_pct"), doc, nur, th)
    return out


def _needs(sc: pd.DataFrame, has_beds: bool, d: pd.DataFrame, th: dict) -> dict:
    """What the scenario's busy hours (95th percentile) would need to stay below the warning level / at the norm."""
    res = {}
    if has_beds:
        census_peak = float(sc["census"].quantile(0.95))
        res["beds_for_warning"] = int(math.ceil(census_peak / (th["occupancy_warning_pct"] / 100)))
    load_peak = float(sc["load"].quantile(0.95))
    res["doctors_for_norm"] = int(math.ceil(load_peak / float(d["doc_norm"].iloc[0])))
    res["nurses_for_norm"] = int(math.ceil(load_peak / float(d["nurse_norm"].iloc[0])))
    return res


def _delta(a, b):
    return None if a is None or b is None else round(b - a, 1)


def validate_scenario(scenario: dict, known: dict[str, bool]) -> dict[str, dict]:
    """Return {dept: adjustments}; raise ScenarioError for anything impossible."""
    adj: dict[str, dict] = {}
    for item in scenario.get("departments", []):
        name = item["department"]
        if name not in known:
            raise ScenarioError(f"Unknown department '{name}'.")
        if name in adj:
            raise ScenarioError(f"Department '{name}' is listed more than once.")
        if item.get("beds_delta", 0) and not known[name]:
            raise ScenarioError(f"{name} has no beds, so beds cannot be changed there.")
        adj[name] = {k: item.get(k, 0) for k in ("beds_delta", "doctors_delta", "nurses_delta", "arrivals_change_pct")}
    return adj


def run_scenario(db: Session, scenario: dict, baseline_days: int = DEFAULT_DAYS) -> dict:
    """scenario: {arrivals_change_pct, los_change_pct, departments: [{department, beds_delta, doctors_delta, nurses_delta, arrivals_change_pct}]}"""
    th = get_thresholds(db)
    types = department_types(db)
    full = load_frame(db, None, None)
    if full.empty:
        raise ScenarioError("No data available. Upload hospital data first.")
    end = full["timestamp"].max().normalize()
    fit_frame = full[full["timestamp"] >= end - timedelta(days=FIT_DAYS - 1)]
    win = full[full["timestamp"] >= end - timedelta(days=baseline_days - 1)]

    known = {name: bool((g["total_beds"] > 0).any()) for name, g in win.groupby("department")}
    adj = validate_scenario(scenario, known)
    glob_arr = float(scenario.get("arrivals_change_pct", 0))
    glob_los = float(scenario.get("los_change_pct", 0))

    rows, bases, scens = [], [], []
    for name, g in win.groupby("department", sort=False):
        d = _prepare(g.reset_index(drop=True), types)
        fit_d = _prepare(fit_frame[fit_frame["department"] == name].reset_index(drop=True), types)
        b_staff, b_bed, src = _fit_wait(fit_d)
        a = adj.get(name, {})
        base, sc = _simulate_dept(d, a, glob_arr, glob_los, th, b_staff, b_bed)
        has_beds = bool(d["has_beds"].iloc[0])
        if has_beds and (sc["beds"] <= 0).any():
            raise ScenarioError(f"{name} would have no beds. Reduce the bed removal.")
        if (sc["doctors"][base["doctors"] > 0] < 1).any() or (sc["nurses"][base["nurses"] > 0] < 1).any():
            raise ScenarioError(f"{name} would be left with no doctors or nurses in some hours. Reduce the staff removal.")
        b_s, s_s = _summ(base, has_beds, th), _summ(sc, has_beds, th)
        rows.append({
            "department": name, "has_beds": has_beds,
            "changes": {k: a.get(k, 0) for k in ("beds_delta", "doctors_delta", "nurses_delta", "arrivals_change_pct")},
            "baseline": b_s, "scenario": s_s,
            "needs": _needs(sc, has_beds, d, th),
            "wait_model": {"staff_elasticity": num(b_staff, 2), "bed_elasticity": num(b_bed, 2), "source": src},
        })
        base["department"], sc["department"] = name, name
        bases.append(base)
        scens.append(sc)

    hospital = {"baseline": _hospital(pd.concat(bases), th), "scenario": _hospital(pd.concat(scens), th)}
    hospital["delta"] = {k: _delta(hospital["baseline"].get(k), hospital["scenario"].get(k)) for k in hospital["baseline"] if k != "status"}

    result = {
        "as_of": end.strftime("%Y-%m-%d"),
        "baseline_days": baseline_days,
        "scenario": {"arrivals_change_pct": glob_arr, "los_change_pct": glob_los, "departments": [r["changes"] | {"department": r["department"]} for r in rows if any(r["changes"].values())]},
        "hospital": hospital,
        "departments": rows,
        "assumptions": ASSUMPTIONS,
    }
    result["summary"] = _narrative(rows, hospital)
    return result


def _hospital(f: pd.DataFrame, th: dict) -> dict:
    beds = f[f["beds"] > 0]
    g = beds.groupby("timestamp")[["census", "beds", "placed", "overflow"]].sum()
    demand = g["census"] / g["beds"] * 100
    w = f["arrivals"].to_numpy(dtype=float)
    wait = float(np.average(f["wait"], weights=w)) if w.sum() > 0 else float(f["wait"].mean())
    return {
        "occupancy_pct": num((g["placed"] / g["beds"] * 100).mean(), 1),
        "demand_pct": num(demand.mean(), 1),
        "hours_over_warning_pct": num((demand >= th["occupancy_warning_pct"]).mean() * 100, 1),
        "overflow_patients_avg": num(g["overflow"].mean(), 1),
        "wait_min": num(wait, 1),
        "total_beds": num(g["beds"].mean(), 0),
        "arrivals_per_hour": num(f.groupby("timestamp")["arrivals"].sum().mean(), 1),
    }


def _narrative(rows: list[dict], hosp: dict) -> list[dict]:
    """Plain-language findings: each is {kind: better|worse|note, text}."""
    order = {"ok": 0, "warning": 1, "critical": 2}
    out = []
    for r in rows:
        b, s = r["baseline"], r["scenario"]
        if b["status"] != s["status"]:
            kind = "better" if order[s["status"]] < order[b["status"]] else "worse"
            out.append({"kind": kind, "text": f"{r['department']} moves from {b['status']} to {s['status']}."})
        if r["has_beds"] and (s.get("overflow_patients_peak") or 0) >= 1 and s["overflow_patients_peak"] > (b.get("overflow_patients_peak") or 0) + 0.5:
            out.append({"kind": "worse", "text": f"{r['department']} would run out of beds in busy hours: about {s['overflow_patients_peak']:.0f} patients without a bed (average {s['overflow_patients_avg']:.1f})."})
        if s["wait_min"] is not None and b["wait_min"] and abs(s["wait_min"] - b["wait_min"]) / b["wait_min"] >= 0.15:
            kind = "better" if s["wait_min"] < b["wait_min"] else "worse"
            out.append({"kind": kind, "text": f"{r['department']} waiting time {b['wait_min']:.0f} → {s['wait_min']:.0f} min."})
    hb, hs = hosp["baseline"], hosp["scenario"]
    if not out:
        out.append({"kind": "note", "text": "No department changes status and no waiting time moves by 15% or more."})
    out.append({"kind": "note", "text": f"Hospital occupancy {hb['demand_pct']:.0f}% → {hs['demand_pct']:.0f}%; average wait {hb['wait_min']:.0f} → {hs['wait_min']:.0f} min."})
    return out


def baseline_overview(db: Session, baseline_days: int = DEFAULT_DAYS) -> dict:
    """Current capacity and demand per department - the starting values for the scenario controls."""
    full = load_frame(db, None, None)
    if full.empty:
        return {"as_of": None, "departments": []}
    end = full["timestamp"].max().normalize()
    win = full[full["timestamp"] >= end - timedelta(days=baseline_days - 1)]
    depts = []
    for name, g in win.groupby("department", sort=False):
        depts.append({
            "department": name, "has_beds": bool((g["total_beds"] > 0).any()),
            "beds": num(g["total_beds"].mean(), 0), "doctors": num(g["doctors_available"].mean(), 1),
            "nurses": num(g["nurses_available"].mean(), 1), "arrivals_per_hour": num(g["arrivals"].mean(), 2),
        })
    return {"as_of": end.strftime("%Y-%m-%d"), "baseline_days": baseline_days, "departments": depts}


def save_run(db: Session, user_id: int, params: dict, result: dict) -> SimulationResult:
    row = SimulationResult(
        user_id=user_id, params_json=json.dumps(params),
        baseline_json=json.dumps({"hospital": result["hospital"]["baseline"], "as_of": result["as_of"]}),
        result_json=json.dumps(result),
        recommended_action=" ".join(s["text"] for s in result["summary"] if s["kind"] != "note")[:1000] or None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def history(db: Session, user_id: int, limit: int = 20) -> list[dict]:
    rows = db.scalars(select(SimulationResult).where(SimulationResult.user_id == user_id).order_by(SimulationResult.id.desc()).limit(limit)).all()
    out = []
    for r in rows:
        res = json.loads(r.result_json)
        out.append({"id": r.id, "created_at": r.created_at.isoformat() if r.created_at else None, "scenario": res["scenario"],
                    "baseline_days": res["baseline_days"], "hospital": res["hospital"], "summary": res["summary"]})
    return out
