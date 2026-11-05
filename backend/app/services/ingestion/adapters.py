"""
Source adapters: turn any supported source into the canonical column set.

Phase 2 implements the tabular adapter (CSV / Excel / operational exports) with a synonym table, so
real exports with different headings still load. EHR-like, HIS and IoT adapters (which aggregate
event-level or sensor data to hourly department rows) are added in phases 11-12 and plug in here.
"""
from __future__ import annotations

import re

import pandas as pd

# canonical name -> accepted synonyms (all compared after normalisation: lower_snake_case)
CANONICAL_COLUMNS = [
    "timestamp", "date", "time", "department",
    "arrivals", "admissions", "discharges",
    "avg_wait_min", "avg_los_hours",
    "total_beds", "occupied_beds", "available_beds",
    "doctors_available", "nurses_available",
    "appointments_scheduled", "appointments_completed",
    "lab_tests_ordered", "lab_capacity",
    "equipment_available", "equipment_total",
]

NUMERIC_COLUMNS = [c for c in CANONICAL_COLUMNS if c not in ("timestamp", "date", "time", "department")]

SYNONYMS: dict[str, list[str]] = {
    "timestamp": ["datetime", "date_time", "ts", "recorded_at", "record_time"],
    "date": ["day", "record_date", "admission_date"],
    "time": ["hour", "time_of_day", "record_hour"],
    "department": ["dept", "department_name", "dept_name", "ward", "unit", "service"],
    "arrivals": ["arrival", "patient_arrivals", "patients", "patient_count", "visits", "footfall", "registrations"],
    "admissions": ["admission", "admitted", "patients_admitted", "admits"],
    "discharges": ["discharge", "discharged", "patients_discharged"],
    "avg_wait_min": ["wait_time", "waiting_time", "avg_wait_time", "avg_waiting_time", "wait_min", "waiting_time_min", "wait_minutes"],
    "avg_los_hours": ["los", "length_of_stay", "avg_los", "avg_length_of_stay", "los_hours"],
    "total_beds": ["beds", "bed_capacity", "total_bed", "capacity_beds", "bed_count"],
    "occupied_beds": ["beds_occupied", "occupied", "bed_occupied", "occupied_bed"],
    "available_beds": ["beds_available", "available", "free_beds", "vacant_beds", "bed_available"],
    "doctors_available": ["doctors", "doctor_count", "doctors_on_duty", "physicians_available"],
    "nurses_available": ["nurses", "nurse_count", "nurses_on_duty"],
    "appointments_scheduled": ["appointments", "scheduled_appointments", "appointments_booked", "appointment_count"],
    "appointments_completed": ["completed_appointments", "appointments_done", "appointments_attended"],
    "lab_tests_ordered": ["lab_tests", "lab_orders", "tests_ordered", "lab_workload", "lab_requests"],
    "lab_capacity": ["lab_capacity_per_hour", "lab_max_tests", "lab_capacity_tests"],
    "equipment_available": ["equipment_free", "available_equipment", "equipment_ready"],
    "equipment_total": ["total_equipment", "equipment_count", "equipment_capacity"],
}

_REVERSE = {syn: canon for canon, syns in SYNONYMS.items() for syn in syns}
_REVERSE.update({c: c for c in CANONICAL_COLUMNS})


def normalize_name(name: object) -> str:
    s = re.sub(r"[^0-9a-zA-Z]+", "_", str(name).strip().lower()).strip("_")
    return s


def map_columns(df: pd.DataFrame, source: str = "csv") -> tuple[pd.DataFrame, dict]:
    """
    Rename columns to canonical names. Returns (dataframe, info) where info lists
    `renamed` (original -> canonical), `unknown` (dropped, not recognised) and `duplicates`
    (several source columns mapping to one canonical name; first one wins).
    """
    if source not in ("csv", "excel"):
        raise NotImplementedError(f"Adapter for source '{source}' is added in a later phase")

    renamed: dict[str, str] = {}
    unknown: list[str] = []
    duplicates: list[str] = []
    keep: dict[str, str] = {}  # canonical -> original column

    for col in df.columns:
        norm = normalize_name(col)
        canon = _REVERSE.get(norm)
        if canon is None:
            unknown.append(str(col))
        elif canon in keep:
            duplicates.append(str(col))
        else:
            keep[canon] = col
            if str(col) != canon:
                renamed[str(col)] = canon

    out = df[[orig for orig in keep.values()]].copy()
    out.columns = list(keep.keys())
    return out, {"renamed": renamed, "unknown": unknown, "duplicates": duplicates}
