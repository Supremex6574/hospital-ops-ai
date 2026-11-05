"""Orchestrates one upload: validate -> read -> privacy check -> map -> clean -> features -> store."""
from __future__ import annotations

import json
import logging

import numpy as np
import pandas as pd
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.models import AppSetting, Department, DerivedMetric, HospitalData, Upload, User
from app.services.ingestion import adapters, cleaner, features, validator
from app.services.ingestion.errors import IngestError

log = logging.getLogger("hospital_ops.ingest")

CHUNK = 5000
NUMERIC = adapters.NUMERIC_COLUMNS
DERIVED_COLS = ["bed_occupancy_pct", "resource_util_pct", "patients_per_doctor", "patients_per_nurse",
                "workload_index", "equipment_util_pct", "lab_util_pct"]


def _guess_type(name: str) -> str:
    n = name.lower()
    if any(k in n for k in ("emergency", "casualty", "a&e")) or n in ("er", "ed"):
        return "ED"
    if "opd" in n or "outpatient" in n or "out patient" in n:
        return "OPD"
    if "icu" in n or "intensive" in n or "critical" in n:
        return "ICU"
    return "Ward"


def _load_weights(db: Session) -> dict[str, float]:
    keys = {"weight_bed_occupancy": "bed", "weight_doctor_load": "doctor", "weight_nurse_load": "nurse", "weight_wait": "wait"}
    rows = db.scalars(select(AppSetting).where(AppSetting.key.in_(keys))).all()
    out = {}
    for r in rows:
        try:
            out[keys[r.key]] = float(r.value)
        except ValueError:
            continue
    return out


def _resolve_departments(db: Session, clean_df: pd.DataFrame) -> tuple[dict[str, int], dict[str, str], list[str]]:
    existing = {d.name: d for d in db.scalars(select(Department)).all()}
    new_names: list[str] = []
    for name in sorted(clean_df["department"].unique()):
        if name not in existing:
            beds = int(clean_df.loc[clean_df["department"] == name, "total_beds"].max())
            dept = Department(name=name, type=_guess_type(name), total_beds=beds)
            db.add(dept)
            existing[name] = dept
            new_names.append(name)
    db.flush()  # assigns ids
    return {n: d.id for n, d in existing.items()}, {n: d.type for n, d in existing.items()}, new_names


def _replace_overlap(db: Session, df: pd.DataFrame, source: str) -> int:
    """Rows already stored for the same (timestamp, department, source) are replaced by the new upload."""
    ids_to_delete: list[int] = []
    for dept_id, grp in df.groupby("department_id"):
        rows = db.execute(
            select(HospitalData.id, HospitalData.timestamp).where(
                HospitalData.department_id == int(dept_id),
                HospitalData.source == source,
                HospitalData.timestamp >= grp["timestamp"].min().to_pydatetime(),
                HospitalData.timestamp <= grp["timestamp"].max().to_pydatetime(),
            )
        ).all()
        if not rows:
            continue
        incoming = set(grp["timestamp"])
        ids_to_delete.extend(r.id for r in rows if pd.Timestamp(r.timestamp) in incoming)
    for i in range(0, len(ids_to_delete), CHUNK):
        db.execute(delete(HospitalData).where(HospitalData.id.in_(ids_to_delete[i:i + CHUNK])))
    return len(ids_to_delete)


def _native(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return None if np.isnan(v) else float(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v


def _store(db: Session, upload: Upload, clean_df: pd.DataFrame, feats: pd.DataFrame, dept_ids: dict[str, int], source: str) -> int:
    df = clean_df.copy()
    df["department_id"] = df["department"].map(dept_ids)
    replaced = _replace_overlap(db, df, source)

    records = df.drop(columns=["department"]).to_dict("records")
    for r in records:
        r["timestamp"] = r["timestamp"].to_pydatetime()
        r["department_id"] = int(r["department_id"])
        r["source"] = source
        r["upload_id"] = upload.id
        for k in NUMERIC:
            r[k] = _native(r[k])
    for i in range(0, len(records), CHUNK):
        db.execute(insert(HospitalData), records[i:i + CHUNK])
    db.flush()

    # map the new row ids back to the feature rows by (timestamp, department)
    id_rows = db.execute(
        select(HospitalData.id, HospitalData.timestamp, HospitalData.department_id).where(HospitalData.upload_id == upload.id)
    ).all()
    id_df = pd.DataFrame(id_rows, columns=["hospital_data_id", "timestamp", "department_id"])
    id_df["timestamp"] = pd.to_datetime(id_df["timestamp"])
    keyed = pd.concat([df[["timestamp", "department_id"]], feats], axis=1).merge(id_df, on=["timestamp", "department_id"], how="inner")

    drecs = []
    for row in keyed[["hospital_data_id", *DERIVED_COLS, "is_peak_hour"]].to_dict("records"):
        rec = {k: _native(v) for k, v in row.items()}
        rec["hospital_data_id"] = int(rec["hospital_data_id"])
        rec["is_peak_hour"] = bool(rec["is_peak_hour"])
        drecs.append(rec)
    for i in range(0, len(drecs), CHUNK):
        db.execute(insert(DerivedMetric), drecs[i:i + CHUNK])
    return replaced


def _summary(clean_df: pd.DataFrame, feats: pd.DataFrame) -> list[dict]:
    d = pd.concat([clean_df[["department", "arrivals", "avg_wait_min"]], feats[["bed_occupancy_pct", "workload_index"]]], axis=1)
    g = d.groupby("department").agg(
        rows=("arrivals", "size"), avg_arrivals_per_hour=("arrivals", "mean"), avg_wait_min=("avg_wait_min", "mean"),
        avg_bed_occupancy_pct=("bed_occupancy_pct", "mean"), avg_workload_index=("workload_index", "mean"),
    ).round(2)
    return [{"department": k, **{c: _native(v) for c, v in row.items()}} for k, row in g.iterrows()]


def process_upload(db: Session, user: User, filename: str, content: bytes, source: str = "csv") -> Upload:
    """Runs the whole pipeline. On a user-fixable problem the failed upload is recorded and IngestError is re-raised."""
    safe_name = (filename or "upload")[:255]
    upload = Upload(user_id=user.id, filename=safe_name, status="pending")
    db.add(upload)
    db.commit()  # keeps the id (and the failure record) even if processing rolls back

    try:
        kind = validator.validate_upload(safe_name, content)
        raw = validator.read_table(content, kind)
        validator.check_privacy(raw)
        mapped, info = adapters.map_columns(raw, "excel" if kind == "excel" else "csv")
        optional_missing = validator.check_required(mapped)
        clean_df, report = cleaner.clean(mapped, optional_missing)

        dept_ids, dept_types, new_depts = _resolve_departments(db, clean_df)
        feats = features.compute_features(clean_df, dept_types, _load_weights(db))
        replaced = _store(db, upload, clean_df, feats, dept_ids, source)

        report.update({
            "columns_renamed": info["renamed"],
            "unknown_columns_dropped": info["unknown"],
            "duplicate_source_columns_ignored": info["duplicates"],
            "rows_inserted": int(len(clean_df)),
            "rows_replaced": replaced,
            "new_departments": new_depts,
            "summary": _summary(clean_df, feats),
        })
        upload.rows_total = report["rows_total"]
        upload.rows_valid = report["rows_valid"]
        upload.rows_dropped = report["rows_dropped"]
        upload.duplicates_removed = report["duplicates_removed"] + report["key_conflicts_resolved"]
        upload.missing_filled = report["missing_filled"]
        upload.status = "success"
        upload.report_json = json.dumps(report, default=_native)
        db.commit()
        return upload
    except IngestError as exc:
        db.rollback()
        upload = db.get(Upload, upload.id)
        upload.status = "failed"
        upload.report_json = json.dumps({"error": exc.message, "code": exc.code, "details": exc.details})
        db.commit()
        raise
    except Exception:
        db.rollback()
        upload = db.get(Upload, upload.id)
        upload.status = "failed"
        upload.report_json = json.dumps({"error": "Unexpected processing error", "code": "internal_error", "details": []})
        db.commit()
        log.exception("Upload %s failed", upload.id)  # stack trace only, never row data
        raise IngestError("Something went wrong while processing the file. Check the file format and try again.", "internal_error")


def ingest_rows(db: Session, upload: Upload, rows: pd.DataFrame, source: str) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    Store already-tabular rows that use canonical column names (no file involved): used by the live stream.
    Same cleaning, derived metrics and storage as an upload. Returns (clean rows, features, report); the caller commits.
    """
    optional_missing = validator.check_required(rows)
    clean_df, report = cleaner.clean(rows, optional_missing)
    dept_ids, dept_types, new_depts = _resolve_departments(db, clean_df)
    feats = features.compute_features(clean_df, dept_types, _load_weights(db))
    replaced = _store(db, upload, clean_df, feats, dept_ids, source)
    report.update({"rows_inserted": int(len(clean_df)), "rows_replaced": replaced, "new_departments": new_depts})
    return clean_df, feats, report
