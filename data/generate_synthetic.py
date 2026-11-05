"""
Synthetic hospital operations data generator (Phase 0).

Produces one year of HOURLY, department-level operational data for 6 departments.
No patient-level or personal data is generated, only aggregate operational counts.

Outputs (in data/synthetic/):
  hospital_operations.csv   clean, upload-ready dataset (canonical columns)
  surge_events.csv          ground-truth surge episodes (to test anomaly detection later)
  messy_sample.csv          small corrupted sample (missing/dupes/bad types) to test the validator
  pii_sample.csv            sample with a forbidden PII column to test PII rejection

Usage:
  python data/generate_synthetic.py            # defaults: 365 days from 2025-10-01, seed 42
  python data/generate_synthetic.py --days 90 --seed 7
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

COLUMNS = [
    "date", "time", "department",
    "arrivals", "admissions", "discharges",
    "avg_wait_min", "avg_los_hours",
    "total_beds", "occupied_beds", "available_beds",
    "doctors_available", "nurses_available",
    "appointments_scheduled", "appointments_completed",
    "lab_tests_ordered", "lab_capacity",
    "equipment_available", "equipment_total",
]


@dataclass(frozen=True)
class Dept:
    name: str
    beds: int
    arrivals_per_hr: float      # mean arrivals per hour (open hours, average day)
    admit_rate: float           # share of arrivals that need a bed
    los_hours: float            # mean length of stay
    target_occ: float           # starting / typical occupancy fraction
    doctors_day: int
    doctors_night: int
    nurses_day: int
    nurses_night: int
    doc_capacity: float         # patients one doctor can handle per hour
    base_wait: float            # baseline waiting time (minutes)
    lab_per_arrival: float
    lab_per_occupied: float
    lab_capacity: int           # tests per hour allocated to the department
    equipment_total: int
    appt_rate: float            # share of arrivals that are scheduled appointments
    hour_profile: str           # key into HOUR_PROFILES
    dow_profile: str            # key into DOW_PROFILES
    seasonal_sensitivity: float # response to monsoon/flu season
    surge_multiplier: float     # how strongly a surge episode hits this dept
    discharge_daytime: bool     # discharges concentrated in daytime (wards) vs flat (ED)


DEPTS = [
    Dept("Emergency",    40, 11.0, 0.42,  6.0, 0.66,  8, 5, 22, 16, 3.5, 35, 0.80, 0.20, 22, 12, 0.00, "ed",      "ed",      0.8, 1.60, False),
    Dept("OPD",           0, 18.0, 0.00,  0.0, 0.00, 14, 0, 10,  0, 4.0, 28, 0.55, 0.00, 20,  8, 0.70, "opd",     "opd",     0.5, 1.15, False),
    Dept("ICU",          20,  0.22, 0.85, 84.0, 0.75,  4, 3, 24, 20, 0.5,  5, 1.00, 0.80, 18, 20, 0.00, "flat",    "flat",    0.4, 1.10, False),
    Dept("General Ward", 150, 1.5, 0.87, 96.0, 0.78, 12, 5, 40, 28, 1.2, 15, 1.00, 0.12, 24, 15, 0.20, "flat",    "flat",    1.0, 1.15, True),
    Dept("Pediatrics",   40,  1.6, 0.33, 54.0, 0.70,  5, 3, 14, 10, 2.5, 25, 0.60, 0.15,  8,  8, 0.40, "peds",    "flat",    1.2, 1.50, True),
    Dept("Surgery",      50,  0.7, 0.72, 72.0, 0.72,  7, 3, 18, 12, 1.0, 20, 1.50, 0.18, 12, 14, 0.90, "surgery", "surgery", 0.2, 1.05, True),
]


def _norm(a: np.ndarray) -> np.ndarray:
    a = np.asarray(a, dtype=float)
    return a / a.mean()


HOUR_PROFILES = {
    # 24 values (hour 0..23). Normalised so the mean over 24h is 1 (except OPD, handled as open-hours).
    "ed": _norm([0.45, 0.35, 0.30, 0.28, 0.30, 0.40, 0.60, 0.90, 1.20, 1.45, 1.55, 1.50,
                 1.40, 1.30, 1.25, 1.25, 1.30, 1.40, 1.50, 1.50, 1.35, 1.10, 0.80, 0.60]),
    "opd": np.array([0, 0, 0, 0, 0, 0, 0, 0.3, 1.2, 1.7, 1.8, 1.6, 1.0, 0.8, 1.2, 1.3, 1.0, 0.4, 0, 0, 0, 0, 0, 0]) / (
        np.array([0, 0, 0, 0, 0, 0, 0, 0.3, 1.2, 1.7, 1.8, 1.6, 1.0, 0.8, 1.2, 1.3, 1.0, 0.4, 0, 0, 0, 0, 0, 0]).sum() / 10.0),
    "flat": _norm(np.ones(24)),
    "peds": _norm([0.6, 0.5, 0.5, 0.5, 0.5, 0.6, 0.8, 1.0, 1.3, 1.4, 1.4, 1.3,
                   1.1, 1.0, 1.0, 1.1, 1.3, 1.4, 1.3, 1.2, 1.0, 0.8, 0.7, 0.6]),
    "surgery": _norm([0.2, 0.2, 0.2, 0.2, 0.3, 0.6, 1.3, 1.8, 1.8, 1.5, 1.3, 1.1,
                      1.0, 1.0, 1.0, 0.9, 0.8, 0.7, 0.5, 0.4, 0.3, 0.3, 0.2, 0.2]),
}

# Monday=0 ... Sunday=6
DOW_PROFILES = {
    "ed": np.array([1.12, 1.00, 0.98, 0.98, 1.02, 0.98, 0.92]),
    "opd": np.array([1.35, 1.15, 1.05, 1.0, 1.0, 0.85, 0.15]),
    "flat": np.ones(7),
    "surgery": np.array([1.25, 1.25, 1.2, 1.15, 1.0, 0.2, 0.05]),
}

DISCHARGE_HOUR_PROFILE = _norm([0.2, 0.1, 0.1, 0.1, 0.1, 0.2, 0.5, 1.0, 1.8, 2.4, 2.6, 2.4,
                                2.0, 1.8, 2.0, 2.4, 2.4, 1.6, 0.9, 0.5, 0.3, 0.3, 0.2, 0.2])


def make_surge_events(start: pd.Timestamp, days: int, rng: np.random.Generator) -> pd.DataFrame:
    """Random multi-day surge episodes (e.g. seasonal outbreaks, mass-casualty days)."""
    if days >= 30:
        n = max(2, int(round(7 * days / 365)))
        candidates = np.arange(10, max(11, days - 8))
    else:  # very short runs (tests): at most one surge, anywhere after day 0
        n = 1
        candidates = np.arange(1, max(2, days - 1))
    starts = np.sort(rng.choice(candidates, size=min(n, len(candidates)), replace=False))
    rows = []
    for s in starts:
        length = int(rng.integers(2, 6))
        mult = float(rng.uniform(1.30, 1.70))
        rows.append({
            "start": start + pd.Timedelta(days=int(s)),
            "end": start + pd.Timedelta(days=int(s) + length),
            "magnitude": round(mult, 2),
        })
    return pd.DataFrame(rows)


def generate(start: str, days: int, seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    t0 = pd.Timestamp(start)
    idx = pd.date_range(t0, periods=days * 24, freq="h")
    T = len(idx)
    hour = idx.hour.to_numpy()
    dow = idx.dayofweek.to_numpy()
    doy = idx.dayofyear.to_numpy()

    surges = make_surge_events(t0, days, rng)
    surge_level = np.zeros(T)  # 0..1 "how strongly a surge is active"
    for _, ev in surges.iterrows():
        m = (idx >= ev["start"]) & (idx < ev["end"])
        surge_level[m] = np.maximum(surge_level[m], ev["magnitude"] - 1.0)

    # seasonality: mild annual wave + a monsoon-fever bump around August (day ~220)
    annual = 1 + 0.06 * np.sin(2 * np.pi * (doy - 30) / 365.0)
    monsoon = np.exp(-0.5 * ((doy - 225) / 28.0) ** 2)  # 0..1 bump

    frames = []
    for d in DEPTS:
        hp = HOUR_PROFILES[d.hour_profile][hour]
        dp = DOW_PROFILES[d.dow_profile][dow]
        season = annual * (1 + 0.20 * d.seasonal_sensitivity * monsoon)
        surge_mult = 1 + surge_level * (d.surge_multiplier - 1) / 0.5  # magnitude 1.5 -> full multiplier
        lam = d.arrivals_per_hr * hp * dp * season * surge_mult
        arrivals = rng.poisson(np.clip(lam, 0, None))

        is_day = (hour >= 8) & (hour < 20)
        doctors = np.where(is_day, d.doctors_day, d.doctors_night)
        nurses = np.where(is_day, d.nurses_day, d.nurses_night)
        # random absences (up to ~12%), never negative; closed departments stay at 0
        doctors = np.where(doctors > 0, np.maximum(1, doctors - rng.binomial(doctors, 0.08)), 0)
        nurses = np.where(nurses > 0, np.maximum(1, nurses - rng.binomial(nurses, 0.08)), 0)

        occupied = np.zeros(T, dtype=int)
        admissions = np.zeros(T, dtype=int)
        discharges = np.zeros(T, dtype=int)

        if d.beds > 0:
            occ_prev = int(round(d.beds * d.target_occ))
            for t in range(T):
                p_dis = min(1.0, (DISCHARGE_HOUR_PROFILE[hour[t]] if d.discharge_daytime else 1.0) / d.los_hours)
                dis = rng.binomial(occ_prev, p_dis)
                free = d.beds - (occ_prev - dis)
                adm = min(rng.binomial(arrivals[t], d.admit_rate), free)
                occ = occ_prev - dis + adm
                occupied[t], admissions[t], discharges[t] = occ, adm, dis
                occ_prev = occ
        else:
            # outpatient care has no admission or discharge; completed consultations are tracked in
            # appointments_completed instead (counting them as discharges would double hospital discharges)
            discharges = np.zeros(T, dtype=int)

        beds_arr = np.full(T, d.beds)
        available = beds_arr - occupied
        occ_frac = np.where(d.beds > 0, occupied / max(d.beds, 1), 0.0)

        # waiting time grows non-linearly with load and with bed pressure
        cap = np.maximum(doctors * d.doc_capacity, 1e-9)
        load = np.clip(arrivals / cap, 0, 2.5)
        bed_pressure = np.clip((occ_frac - 0.88) / 0.12, 0, 1) * 0.6
        wait = d.base_wait * (0.65 + 1.9 * (load ** 2) + bed_pressure)
        wait = wait * rng.lognormal(0, 0.12, T)
        wait = np.where(arrivals == 0, 0.0, wait)

        los = np.where(d.beds > 0, d.los_hours * rng.lognormal(0, 0.10, T), 0.0)

        lab_ordered = rng.poisson(np.clip(arrivals * d.lab_per_arrival + occupied * d.lab_per_occupied, 0, None))

        sched = np.minimum(arrivals, rng.binomial(arrivals, d.appt_rate)) if d.appt_rate > 0 else np.zeros(T, dtype=int)
        completed = np.minimum(sched, np.round(sched * rng.uniform(0.82, 0.97, T)).astype(int))

        in_use = rng.binomial(d.equipment_total, np.clip(0.15 + 0.6 * np.maximum(occ_frac, np.clip(load / 2, 0, 1)), 0, 0.95))
        maint = rng.binomial(d.equipment_total, 0.04)
        equip_avail = np.clip(d.equipment_total - in_use - maint, 0, d.equipment_total)

        frames.append(pd.DataFrame({
            "date": idx.strftime("%Y-%m-%d"),
            "time": idx.strftime("%H:%M"),
            "department": d.name,
            "arrivals": arrivals,
            "admissions": admissions,
            "discharges": discharges,
            "avg_wait_min": np.round(wait, 1),
            "avg_los_hours": np.round(los, 1),
            "total_beds": beds_arr,
            "occupied_beds": occupied,
            "available_beds": available,
            "doctors_available": doctors,
            "nurses_available": nurses,
            "appointments_scheduled": sched,
            "appointments_completed": completed,
            "lab_tests_ordered": lab_ordered,
            "lab_capacity": d.lab_capacity,
            "equipment_available": equip_avail,
            "equipment_total": d.equipment_total,
        }))

    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values(["date", "time", "department"]).reset_index(drop=True)
    return df[COLUMNS], surges


def make_messy(df: pd.DataFrame, rng: np.random.Generator, n: int = 3000) -> pd.DataFrame:
    """Small deliberately corrupted sample used to test validation/cleaning in Phase 2."""
    m = df.head(n).copy()
    m = m.astype({c: "object" for c in ["arrivals", "avg_wait_min", "doctors_available", "occupied_beds"]})
    num_cols = ["arrivals", "admissions", "discharges", "avg_wait_min", "doctors_available", "nurses_available", "occupied_beds"]
    for c in num_cols:  # ~3% missing values per column
        m.loc[rng.random(len(m)) < 0.03, c] = np.nan
    bad_idx = rng.choice(len(m), size=25, replace=False)
    m.loc[bad_idx[:10], "arrivals"] = "N/A"          # wrong data type
    m.loc[bad_idx[10:18], "avg_wait_min"] = "abc"    # wrong data type
    m.loc[bad_idx[18:22], "doctors_available"] = -3  # impossible value
    m.loc[bad_idx[22:], "occupied_beds"] = 9999      # occupied > total beds
    dupes = m.sample(40, random_state=1)             # exact duplicate rows
    m = pd.concat([m, dupes], ignore_index=True).sample(frac=1, random_state=2).reset_index(drop=True)
    return m


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default="2025-10-01")
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=str(Path(__file__).parent / "synthetic"))
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    df, surges = generate(args.start, args.days, args.seed)
    df.to_csv(out / "hospital_operations.csv", index=False)
    surges.to_csv(out / "surge_events.csv", index=False)

    rng = np.random.default_rng(args.seed + 1)
    make_messy(df, rng).to_csv(out / "messy_sample.csv", index=False)

    pii = df.head(500).copy()
    pii.insert(0, "patient_name", "REDACTED-TEST")
    pii.to_csv(out / "pii_sample.csv", index=False)

    print(f"rows={len(df):,}  departments={df['department'].nunique()}  "
          f"range={df['date'].min()}..{df['date'].max()}  surges={len(surges)}")
    print(f"written to {out}")


if __name__ == "__main__":
    main()
