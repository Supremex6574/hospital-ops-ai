"""
Optimization: how to rebalance beds and on-duty staff across departments.

Goal ("balance the pressure"): make the busiest hours (95th percentile) equally tight everywhere, i.e. minimise the
highest pressure ratio across departments. Greedy marginal allocation does this exactly for integer units:
start every department at its minimum, then give each remaining unit to the department that is currently most pressed.

- Staff:  pressure = busy-hour patient load / (staff on duty x planning norm). Pool = doctors (or nurses) currently on duty
          in all departments, plus any extra you can add. Nobody moves more than `max_change_pct` of their team.
- Beds:   pressure = busy-hour census / beds. Only ward-type departments (General Ward, Pediatrics, Surgery) exchange beds;
          ED and ICU are specialised and stay as they are. Extra beds, if any, also go to ward-type departments.

The proposed changes are then run through the what-if engine so the effect on occupancy, waiting time and staff load is
measured the same way as on the What-if page. Planning aid built on stated assumptions, not a clinical tool.
"""
from __future__ import annotations

import math
from datetime import timedelta

import numpy as np

from app.services.analytics.common import department_types, load_frame
from app.services.decision.simulation import DEFAULT_DAYS, ScenarioError, _prepare, run_scenario

MOVABLE_BED_TYPES = {"Ward"}


def _greedy(demand: dict[str, float], cur: dict[str, int], pool: int, lo: dict[str, int], hi: dict[str, int]) -> dict[str, int]:
    """Integer allocation of `pool` units minimising max(demand/x). Each x stays within [lo, hi]."""
    x = dict(lo)
    left = pool - sum(x.values())
    if left < 0:  # pool smaller than the minimums: scale back to the pool, most pressed keep theirs
        order = sorted(x, key=lambda k: demand[k] / max(x[k], 1))
        for k in order:
            while left < 0 and x[k] > 1:
                x[k] -= 1
                left += 1
    while left > 0:
        open_ = [k for k in x if x[k] < hi[k]]
        if not open_:
            break
        k = max(open_, key=lambda k: demand[k] / max(x[k], 1))
        x[k] += 1
        left -= 1
    return x


def _moves(delta: dict[str, int], unit: str) -> list[dict]:
    """Turn per-department deltas into readable transfers; leftover positive units are new capacity."""
    give = {k: -v for k, v in delta.items() if v < 0}
    take = {k: v for k, v in delta.items() if v > 0}
    out = []
    for t in sorted(take, key=lambda k: -take[k]):
        for g in sorted(give, key=lambda k: -give[k]):
            n = min(take[t], give[g])
            if n > 0:
                out.append({"from": g, "to": t, "count": n, "unit": unit})
                take[t] -= n
                give[g] -= n
        if take[t] > 0:
            out.append({"from": None, "to": t, "count": take[t], "unit": unit})
    return out


def optimize(db, *, resource: str, extra: int = 0, max_change_pct: int = 30, baseline_days: int = DEFAULT_DAYS) -> dict:
    if resource not in ("beds", "doctors", "nurses"):
        raise ScenarioError("Unknown resource.")
    types = department_types(db)
    full = load_frame(db, None, None)
    if full.empty:
        raise ScenarioError("No data available. Upload hospital data first.")
    end = full["timestamp"].max().normalize()
    win = full[full["timestamp"] >= end - timedelta(days=baseline_days - 1)]

    cur, demand, floor = {}, {}, {}
    for name, g in win.groupby("department", sort=False):
        d = _prepare(g.reset_index(drop=True), types)
        has_beds = bool(d["has_beds"].iloc[0])
        if resource == "beds":
            if not has_beds or types.get(name) not in MOVABLE_BED_TYPES:
                continue
            cur[name] = int(round(d["total_beds"].mean()))
            demand[name] = float(d["occupied_beds"].quantile(0.95))
        else:
            col, norm = ("doctors_available", d["doc_norm"].iloc[0]) if resource == "doctors" else ("nurses_available", d["nurse_norm"].iloc[0])
            cur[name] = max(1, int(round(d[col].mean())))
            pos = d[col][d[col] > 0]
            floor[name] = cur[name] - (int(pos.min()) - 1 if len(pos) else 0)  # never leave a quiet hour with nobody
            demand[name] = float(d["load"].quantile(0.95)) / float(norm)  # units needed at the planning norm
    if len(cur) < 2:
        raise ScenarioError("Need at least two departments to rebalance.")

    lo = {k: max(1, floor.get(k, 1), int(math.floor(v * (1 - max_change_pct / 100)))) for k, v in cur.items()}
    lo = {k: min(v, cur[k]) for k, v in lo.items()}
    hi = {k: int(math.ceil(v * (1 + max_change_pct / 100))) for k, v in cur.items()}
    pool = sum(cur.values()) + extra
    new = _greedy(demand, cur, pool, lo, hi)
    delta = {k: new[k] - cur[k] for k in cur}

    def pressure(alloc):
        return {k: demand[k] / max(alloc[k], 1) for k in alloc}

    before, after = pressure(cur), pressure(new)
    # keep the current allocation if the "improvement" is negligible (avoids pointless shuffling)
    improved = max(after.values()) < max(before.values()) - 0.01
    if not improved and extra == 0:
        delta = {k: 0 for k in cur}
        new, after = dict(cur), dict(before)

    key = {"beds": "beds_delta", "doctors": "doctors_delta", "nurses": "nurses_delta"}[resource]
    scenario = {"departments": [{"department": k, key: v} for k, v in delta.items() if v]}
    sim = run_scenario(db, scenario, baseline_days)
    rows = [{
        "department": k, "current": cur[k], "proposed": new[k], "change": delta[k],
        "pressure_before": round(before[k] * 100, 0), "pressure_after": round(after[k] * 100, 0),
    } for k in cur]
    unit = "beds" if resource == "beds" else resource
    moves = _moves(delta, unit)
    worst_b, worst_a = max(before.values()) * 100, max(after.values()) * 100
    if not any(delta.values()):
        headline = f"The current {resource} allocation is already balanced for the busiest hours. No change recommended."
    else:
        headline = f"Busiest-hour pressure on the most stretched department drops from {worst_b:.0f}% to {worst_a:.0f}%."
    return {
        "resource": resource, "extra": extra, "max_change_pct": max_change_pct, "as_of": sim["as_of"], "baseline_days": baseline_days,
        "headline": headline, "pressure_worst_before": round(worst_b, 0), "pressure_worst_after": round(worst_a, 0),
        "rows": rows, "moves": moves, "scenario": scenario, "simulation": sim,
        "notes": [
            "Pressure = busy-hour (95th percentile) load as a percentage of capacity at the planning norm; 100% means exactly at the norm.",
            "Only ward-type departments exchange beds; Emergency and ICU stay as they are." if resource == "beds" else "Staff are the doctors/nurses on duty in every hour; a real roster needs shift-level planning.",
            "Planning estimates from past data, not a clinical tool.",
        ],
    }
