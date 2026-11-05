"""
Recommendation engine: turns what the other modules found into practical operational actions.

Transparent rules, not a black box. Each recommendation names the rule that raised it, the evidence (real numbers from
the data), a rough estimate of the effect, and how sure we are:
  high confidence    = measured in the newest data (a current bottleneck that has lasted a few hours)
  medium confidence  = based on a forecast or on a repeating daily pattern

Scope: hospital operations only (beds, staff allocation, lab capacity, patient flow). No clinical advice. Anything that
touches patient care is phrased as "where the care team agrees".

Inputs: bottleneck flags (analytics.bottlenecks), 7-day forecasts (ml.forecasting) and their SHAP drivers (ml.explain).
"""
from __future__ import annotations

import json
import math
from datetime import datetime

import numpy as np
import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Department, Recommendation
from app.services.analytics.bottlenecks import LABELS, STAFF_WARN, flagged_history
from app.services.ml.explain import explain_forecast
from app.services.ml.forecasting import get_forecast

SUSTAINED_HOURS = 3        # a condition must hold in at least this many of the last 6 hours to count as sustained
LOOKBACK_HOURS = 6
PATTERN_DAYS = 28
DONOR_LOAD_CAP = 0.95      # a department lending staff must stay at or below 95% of its planning norm
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _pr(sev: int, sustained: int) -> str:
    if sev == 2 and sustained >= SUSTAINED_HOURS:
        return "high"
    if sev >= 1 and sustained >= SUSTAINED_HOURS or sev == 2:
        return "medium"
    return "low"


def _runs(hours: list[int]) -> list[tuple[int, int]]:
    hours = sorted(hours)
    runs, start, prev = [], hours[0], hours[0]
    for h in hours[1:]:
        if h != prev + 1:
            runs.append((start, prev)); start = h
        prev = h
    runs.append((start, prev))
    return runs


def _hours_text(hours: list[int]) -> str:
    """[9,10,11,15] -> '09:00-12:00 and 15:00-16:00'."""
    return " and ".join(f"{a:02d}:00-{b + 1:02d}:00" for a, b in _runs(hours))


def _rec(rule, dept, category, priority, title, action, reason, impact, horizon, confidence, evidence):
    return {"rule": rule, "department": dept, "category": category, "priority": priority, "title": title, "action": action,
            "reason": reason, "impact": impact, "horizon": horizon, "confidence": confidence,
            "evidence": [{"label": k, "value": v} for k, v in evidence]}


def _peak_hours(g: pd.DataFrame, col: str) -> list[int]:
    """Hours of day where the condition appears most often over the recent weeks (empty if there is no real pattern)."""
    if g.empty:
        return []
    share = g.groupby("hour")[col].apply(lambda x: (x > 0).mean())
    if share.max() < 0.25:
        return []
    hours = [int(h) for h in share[share >= max(0.25, 0.7 * share.max())].index]
    return hours if len(_runs(hours)) <= 3 else []   # scattered hours are not a pattern worth acting on


# ------------------------------------------------------------------------------------------ transfers
def _staff_transfer(last: pd.DataFrame, dept: str, kind: str) -> dict | None:
    """Suggest moving staff from the department with the most spare capacity. Returns None when nobody can lend."""
    n, p, norm = ("doctors_available", "patients_per_doctor", "doc_norm") if kind == "doctors" else ("nurses_available", "patients_per_nurse", "nurse_norm")
    row = last[last["department"] == dept].iloc[0]
    load = row[p] * row[n]
    need = math.ceil(load / row[norm]) - int(row[n])
    if need < 1:
        return None
    best = None
    for _, d in last[last["department"] != dept].iterrows():
        if not d[n] or pd.isna(d[p]):
            continue
        dload = d[p] * d[n]
        spare = int(d[n]) - math.ceil(dload / (d[norm] * DONOR_LOAD_CAP))
        if spare >= 1 and (best is None or spare > best["spare"]):
            best = {"donor": d["department"], "spare": spare, "dload": dload, "davail": int(d[n]), "dnorm": d[norm]}
    move = min(need, best["spare"]) if best else 0
    return {"need": need, "load": load, "avail": int(row[n]), "norm": row[norm], "move": move, "donor": best}


# ------------------------------------------------------------------------------------------ engine
def build_recommendations(df: pd.DataFrame, th: dict, dept_ids: dict[str, int], dept_forecasts: dict, adm_forecast: dict | None,
                          adm_driver: str | None) -> list[dict]:
    """Pure function: flagged history in, list of recommendation dicts out."""
    t_last = df["timestamp"].max()
    last = df[df["timestamp"] == t_last]
    recent = df[df["timestamp"] > t_last - pd.Timedelta(hours=LOOKBACK_HOURS)]
    pattern = df[df["timestamp"] > t_last - pd.Timedelta(days=PATTERN_DAYS)]
    recs: list[dict] = []

    for _, r in last.iterrows():
        d = r["department"]
        rd = recent[recent["department"] == d]
        sustained = lambda c: int((rd[f"sev_{c}"] > 0).sum())  # noqa: E731
        sev = lambda c: int(r[f"sev_{c}"])  # noqa: E731

        # 1. beds are tight right now
        if sev("occupancy"):
            keep = math.ceil(r["total_beds"] * th["occupancy_warning_pct"] / 100) - 1   # most beds that can stay occupied below the warning level
            n = int(r["occupied_beds"]) - keep
            after = keep / r["total_beds"] * 100
            recs.append(_rec(
                "beds_now", d, "Bed capacity", _pr(sev("occupancy"), sustained("occupancy")), f"Free up beds in {d}",
                f"Ask the ward to review today's expected discharges and, where the care team agrees, bring them earlier in the day"
                f"{f' to free about {n} beds' if n > 0 else ''}. Prepare overflow beds in case admissions continue.",
                f"Bed occupancy is {r['bed_occupancy_pct']:.0f}% ({int(r['occupied_beds'])} of {int(r['total_beds'])} beds) and has been "
                f"above the {th['occupancy_warning_pct']:g}% warning level in {sustained('occupancy')} of the last {LOOKBACK_HOURS} hours.",
                f"Freeing {n} bed{'s' if n != 1 else ''} would bring occupancy to about {after:.0f}%." if n > 0 else "Occupancy would stay at the warning level.",
                "Now", "high", [("Occupancy", f"{r['bed_occupancy_pct']:.0f}%"), ("Free beds", str(int(r["available_beds"]))),
                               ("Hours above warning (last 6)", str(sustained("occupancy")))]))

        # 2. forecast says beds will get tight
        fc = dept_forecasts.get(d)
        if fc and fc.get("enough") and r["total_beds"] > 0:
            peak = max(fc["forecast"], key=lambda x: x["predicted"])
            if peak["predicted"] >= th["occupancy_warning_pct"]:
                over = (peak["predicted"] - th["occupancy_warning_pct"]) / 100 * r["total_beds"]
                day = pd.Timestamp(peak["date"]).strftime("%A %d %b")
                mape = next(m["mape"] for m in fc["models"] if m["selected"])
                recs.append(_rec(
                    "beds_forecast", d, "Bed capacity", "high" if peak["predicted"] >= th["occupancy_critical_pct"] else "medium",
                    f"Plan bed capacity in {d} for {day}",
                    f"Plan ahead: check which planned admissions and discharges fall around {day}, and agree an overflow plan with the ward manager before then.",
                    f"The forecast expects average occupancy of {peak['predicted']:.0f}% on {day} (likely range {peak['lower']:.0f}-{peak['upper']:.0f}%), "
                    f"above the {th['occupancy_warning_pct']:g}% warning level. Typical forecast error is about {mape:.0f}%.",
                    f"About {over:.0f} beds above the warning level at the expected peak.", f"By {day}", "medium",
                    [("Forecast peak", f"{peak['predicted']:.0f}%"), ("Range", f"{peak['lower']:.0f}-{peak['upper']:.0f}%"), ("Day", day)]))

        # 3. arrival surge
        if sev("arrivals"):
            usual = r["arrivals_typical_3h"]
            recs.append(_rec(
                "arrival_surge", d, "Patient flow", _pr(sev("arrivals"), sustained("arrivals")), f"Prepare for the arrival surge in {d}",
                f"Bring in on-call or float staff to {d} for the next few hours and open any fast-track or extra registration lane.",
                f"Arrivals over the last 3 hours are {r['arrivals_3h']:.0f}, {r['arrivals_ratio']:.1f}x the usual {usual:.0f} for this weekday and hour.",
                f"Extra {r['arrivals_3h'] - usual:.0f} patients over 3 hours compared with a normal day.", "Next 3 hours", "high",
                [("3-hour arrivals", f"{r['arrivals_3h']:.0f}"), ("Usual", f"{usual:.0f}"), ("Ratio", f"{r['arrivals_ratio']:.1f}x")]))

        # 4. waiting time
        if sev("wait"):
            hrs = _peak_hours(pattern[pattern["department"] == d], "sev_wait")
            when = f" Focus on {_hours_text(hrs)}, when long waits are most common." if hrs else ""
            recs.append(_rec(
                "waiting_time", d, "Patient flow", _pr(sev("wait"), sustained("wait")), f"Reduce waiting time in {d}",
                f"Add a triage or registration resource in {d} and move simple cases to a fast-track lane.{when}",
                f"Average waiting time is {r['avg_wait_min']:.0f} min, {r['avg_wait_min'] / r['wait_typical']:.1f}x the usual {r['wait_typical']:.0f} min for this weekday and hour.",
                f"Bringing waits back to normal would save about {r['avg_wait_min'] - r['wait_typical']:.0f} minutes per patient.", "Now", "high",
                [("Waiting time", f"{r['avg_wait_min']:.0f} min"), ("Usual", f"{r['wait_typical']:.0f} min"), ("Long-wait hours (last 6)", str(sustained("wait")))]))

        # 5. staff load
        for kind, who in (("doctors", "doctor"), ("nurses", "nurse")):
            if not sev(kind):
                continue
            t = _staff_transfer(last, d, kind)
            pct = r["doc_pct" if kind == "doctors" else "nurse_pct"]
            if t and t["move"] >= 1:
                dn = t["donor"]
                new_pct = t["load"] / (t["avail"] + t["move"]) / t["norm"] * 100
                d_after = dn["dload"] / (dn["davail"] - t["move"]) / dn["dnorm"] * 100
                action = (f"Move {t['move']} {who}{'s' if t['move'] > 1 else ''} from {dn['donor']} to {d} for this shift, subject to skills and rota rules. "
                          f"{dn['donor']} can lend them and stay within its planning norm.")
                impact = f"{d} load would fall from {pct:.0f}% to about {new_pct:.0f}% of the norm; {dn['donor']} would rise to about {d_after:.0f}%."
            else:
                action = f"Call in {'on-call doctors' if kind == 'doctors' else 'float or agency nurses'} for {d}; no other department has spare {who}s right now."
                impact = f"About {t['need'] if t else '?'} more {who}s would bring the load back to the planning norm."
            recs.append(_rec(
                f"{who}_load", d, "Staffing", _pr(sev(kind), sustained(kind)), f"Rebalance {who}s for {d}", action,
                f"Patients per {who} are {pct:.0f}% of the planning norm ({t['avail'] if t else '?'} {who}s on duty), above the {STAFF_WARN:g}% warning level.",
                impact, "This shift", "high", [(f"Load vs norm", f"{pct:.0f}%"), (f"{who.title()}s on duty", str(t["avail"]) if t else "-")]))

        # 6. lab capacity
        if sev("lab"):
            hrs = _peak_hours(pattern[pattern["department"] == d], "sev_lab")
            when = f" The overload usually falls on {_hours_text(hrs)}." if hrs else ""
            over = r["lab_util_pct"] - 100
            recs.append(_rec(
                "lab_overload", d, "Lab capacity", _pr(sev("lab"), sustained("lab")), f"Ease lab demand from {d}",
                f"Stagger non-urgent lab orders from {d} across the day and ask the lab to add a technician or extend hours at the busiest times.{when}",
                f"Lab tests ordered are {r['lab_util_pct']:.0f}% of capacity (warning from {th['lab_overload_pct']:g}%).",
                f"Spreading orders would remove about {max(over, 0):.0f}% excess demand in the peak hour." if over > 0 else "Staggering orders keeps the peak under capacity.",
                "Today", "high", [("Lab load", f"{r['lab_util_pct']:.0f}%"), ("Overload hours (last 6)", str(sustained("lab")))]))

        # 7. a daily pattern worth staffing for
        g = pattern[pattern["department"] == d]
        if len(g) >= 7 * 24 and (g["max_sev"] > 0).mean() >= 0.15:
            hrs = _peak_hours(g, "max_sev")
            if hrs and len(hrs) <= 8:
                share = (g[g["hour"].isin(hrs)]["max_sev"] > 0).mean() * 100
                recs.append(_rec(
                    "daily_pattern", d, "Staffing", "low", f"Cover the recurring busy hours in {d}",
                    f"Review the shift pattern for {d} and move or add staff so that {_hours_text(hrs)} is covered.",
                    f"Over the last {PATTERN_DAYS} days {d} was under strain in {share:.0f}% of the hours between {_hours_text(hrs)}.",
                    "Matching staffing to the busy hours reduces repeated strain.", "Next rota", "medium",
                    [("Busy hours", _hours_text(hrs)), ("Strained share", f"{share:.0f}%")]))

    # 8. admissions expected to rise
    if adm_forecast and adm_forecast.get("enough"):
        hist = pd.Series([h["actual"] for h in adm_forecast["history"]][-14:])
        total_next = sum(f["predicted"] for f in adm_forecast["forecast"])
        base = hist.mean() * 7
        if base > 0 and (total_next - base) / base >= 0.08:
            top = max(adm_forecast["forecast"], key=lambda x: x["predicted"])
            day = pd.Timestamp(top["date"]).strftime("%A %d %b")
            why = f" The forecasting model links this mainly to \"{adm_driver.lower()}\"." if adm_driver else ""
            recs.append(_rec(
                "admissions_forecast", None, "Patient flow", "medium", "Prepare for higher admissions next week",
                f"Review elective admission scheduling and staffing for the week, with {day} the busiest day.",
                f"The forecast expects {total_next:.0f} admissions over the next 7 days, {(total_next - base) / base * 100:.0f}% more than the last two weeks' average ({base:.0f}).{why}",
                f"About {total_next - base:.0f} extra admissions across the week.", "Next 7 days", "medium",
                [("Expected 7-day total", f"{total_next:.0f}"), ("Recent weekly average", f"{base:.0f}"), ("Busiest day", day)]))

    # 9. several departments under critical strain at the same time
    critical = [d for d, g in last.groupby("department") if (g["max_sev"] == 2).any()]
    if len(critical) >= 3:
        recs.append(_rec(
            "hospital_surge", None, "Hospital-wide", "high", "Escalate to hospital-level coordination",
            "Hold a short coordination call with department heads and agree one hospital-level plan for beds, staff moves and diversion of non-urgent work.",
            f"{len(critical)} departments are at critical level at the same time: {', '.join(sorted(critical))}.",
            "A joint plan avoids departments competing for the same staff and beds.", "Now", "high",
            [("Departments at critical level", str(len(critical)))]))

    for r_ in recs:
        r_["department_id"] = dept_ids.get(r_["department"])
    recs.sort(key=lambda x: (PRIORITY_ORDER[x["priority"]], x["department"] or "", x["rule"]))
    return recs


# ------------------------------------------------------------------------------------------ service
_STATE: dict = {}


def _key(db: Session, df: pd.DataFrame, th: dict) -> tuple:
    return (len(df), df["timestamp"].max().isoformat(), tuple(sorted(th.items())))


def generate(db: Session, force: bool = False) -> dict:
    df, th = flagged_history(db)
    if df.empty:
        return {"has_data": False}
    key = _key(db, df, th)
    existing = db.scalar(select(Recommendation.id).limit(1))
    if not force and _STATE.get("key") == key and existing is not None:
        return {"has_data": True, "as_of": _STATE["as_of"], "refreshed": False}

    depts = {d.name: d.id for d in db.scalars(select(Department)).all()}
    last = df[df["timestamp"] == df["timestamp"].max()]
    # department forecasts only where beds could plausibly become a problem (keeps first load reasonable)
    recent14 = df[df["timestamp"] > df["timestamp"].max() - pd.Timedelta(days=14)]
    dept_fc = {}
    for name, g in recent14[recent14["total_beds"] > 0].groupby("department"):
        if g["bed_occupancy_pct"].max() >= th["occupancy_warning_pct"] - 10:
            fc = get_forecast(db, "bed_occupancy", depts[name])
            if fc.get("enough"):
                dept_fc[name] = fc
    adm = get_forecast(db, "admissions", None)
    driver = None
    try:
        ex = explain_forecast(db, "admissions", None)
        if ex.get("explainable") and ex.get("groups"):
            driver = ex["groups"][0]["label"]
    except Exception:  # noqa: BLE001 - explanation is a nice-to-have, never block recommendations
        driver = None

    recs = build_recommendations(df, th, depts, dept_fc, adm, driver)
    as_of = df["timestamp"].max().to_pydatetime()
    _persist(db, recs, as_of)
    _STATE.update(key=key, as_of=as_of.strftime("%Y-%m-%dT%H:00"))
    return {"has_data": True, "as_of": _STATE["as_of"], "refreshed": True}


def _fingerprint(rule: str, department_id: int | None) -> str:
    return f"{rule}:{department_id or 'hospital'}"


def _persist(db: Session, recs: list[dict], as_of: datetime) -> None:
    """Upsert by rule + department. Accepted/dismissed choices survive a refresh; items whose condition cleared are retired."""
    old = {r.trigger_rule: r for r in db.scalars(select(Recommendation)).all()}
    seen = set()
    now = datetime.utcnow()
    for r in recs:
        fp = _fingerprint(r["rule"], r["department_id"])
        seen.add(fp)
        fields = dict(department_id=r["department_id"], category=r["category"], priority=r["priority"], title=r["title"], text=r["action"],
                      rationale=r["reason"], impact=r["impact"], horizon=r["horizon"], confidence=r["confidence"],
                      evidence_json=json.dumps(r["evidence"]), as_of=as_of, updated_at=now)
        row = old.get(fp)
        if row:
            for k, v in fields.items():
                setattr(row, k, v)
            if row.status == "resolved":
                row.status = "new"
        else:
            db.add(Recommendation(trigger_rule=fp, status="new", **fields))
    for fp, row in old.items():
        if fp in seen:
            continue
        if row.status == "new":
            db.delete(row)
        elif row.status == "accepted":
            row.status, row.updated_at = "resolved", now   # the condition cleared after the action was accepted
        elif row.status == "dismissed":
            db.delete(row)
    db.commit()


def list_recommendations(db: Session, status: str = "active") -> dict:
    meta = generate(db)
    if not meta.get("has_data"):
        return {"has_data": False, "items": []}
    q = select(Recommendation, Department.name).outerjoin(Department, Department.id == Recommendation.department_id)
    if status == "active":
        q = q.where(Recommendation.status.in_(["new", "accepted"]))
    elif status in ("new", "accepted", "dismissed", "resolved"):
        q = q.where(Recommendation.status == status)
    rows = db.execute(q).all()
    items = [{
        "id": r.id, "rule": (r.trigger_rule or "").split(":")[0], "department_id": r.department_id, "department": name, "category": r.category,
        "priority": r.priority, "title": r.title, "action": r.text, "reason": r.rationale, "impact": r.impact, "horizon": r.horizon,
        "confidence": r.confidence, "evidence": json.loads(r.evidence_json or "[]"), "status": r.status, "as_of": r.as_of,
    } for r, name in rows]
    items.sort(key=lambda x: (PRIORITY_ORDER.get(x["priority"], 9), x["department"] or "", x["rule"]))
    counts = {p: sum(1 for i in items if i["priority"] == p and i["status"] in ("new", "accepted")) for p in PRIORITY_ORDER}
    return {"has_data": True, "as_of": meta["as_of"], "items": items, "counts": counts,
            "disclaimer": "Suggestions for hospital operations only, based on the data loaded. They are not clinical advice; managers decide what to act on."}
