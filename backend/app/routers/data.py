import json
from datetime import date, datetime, time, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import Department, DerivedMetric, HospitalData, Upload, User
from app.schemas.data import UploadOut, UploadResult
from app.security.dependencies import get_current_admin
from app.services.ingestion.adapters import CANONICAL_COLUMNS, NUMERIC_COLUMNS
from app.services.ingestion.errors import IngestError
from app.services.analytics.alerts import scan_alerts
from app.services.ingestion.pipeline import process_upload

router = APIRouter(prefix="/data", tags=["data"])

SAMPLE_PATH = Path(__file__).resolve().parents[3] / "data" / "synthetic" / "hospital_operations.csv"

# Allow-list of columns the stats endpoint may aggregate (never built from user input)
_STAT_COLS = {c: getattr(HospitalData, c) for c in NUMERIC_COLUMNS}


def _scope(stmt, date_from: date | None, date_to: date | None, department_id: int | None, upload_id: int | None = None):
    if date_from:
        stmt = stmt.where(HospitalData.timestamp >= datetime.combine(date_from, time.min))
    if date_to:
        stmt = stmt.where(HospitalData.timestamp < datetime.combine(date_to + timedelta(days=1), time.min))
    if department_id:
        stmt = stmt.where(HospitalData.department_id == department_id)
    if upload_id:
        stmt = stmt.where(HospitalData.upload_id == upload_id)
    return stmt


def _ingest_response(exc: IngestError, upload_id: int | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": "ingest_error", "detail": exc.message, "code": 422, "ingest_code": exc.code,
                 "details": exc.details, "upload_id": upload_id},
    )


def _run(db: Session, user: User, filename: str, content: bytes):
    try:
        upload = process_upload(db, user, filename, content)
    except IngestError as exc:
        last = db.scalar(select(Upload.id).where(Upload.user_id == user.id).order_by(Upload.id.desc()).limit(1))
        return _ingest_response(exc, last)
    try:  # refresh alerts for the newest data; a failure here must never fail the upload itself
        scan_alerts(db)
    except Exception:  # noqa: BLE001
        db.rollback()
    return UploadResult(upload=UploadOut.model_validate(upload), report=json.loads(upload.report_json or "{}"))


@router.post("/upload", response_model=UploadResult, status_code=201)
def upload_file(file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(get_current_admin)):
    limit = get_settings().max_upload_mb * 1024 * 1024
    content = file.file.read(limit + 1)  # never read more than limit + 1 bytes into memory
    return _run(db, user, file.filename or "", content)


@router.post("/load-sample", response_model=UploadResult, status_code=201)
def load_sample(db: Session = Depends(get_db), user: User = Depends(get_current_admin)):
    """Runs the bundled synthetic dataset through the same pipeline as a normal upload."""
    if not SAMPLE_PATH.exists():
        raise HTTPException(404, "The sample dataset is not available. Run data/generate_synthetic.py first.")
    return _run(db, user, SAMPLE_PATH.name, SAMPLE_PATH.read_bytes())


@router.get("/template", response_class=PlainTextResponse)
def template(_: User = Depends(get_current_admin)):
    header = ",".join(c for c in CANONICAL_COLUMNS if c != "timestamp")
    example = "2026-01-15,08:00,Emergency,14,5,4,38.5,6.0,40,27,13,8,22,0,0,12,22,9,12"
    return PlainTextResponse(
        f"{header}\n{example}\n",
        headers={"Content-Disposition": 'attachment; filename="hospital_data_template.csv"'},
    )


@router.get("/uploads", response_model=list[UploadOut])
def list_uploads(db: Session = Depends(get_db), _: User = Depends(get_current_admin)):
    return db.scalars(select(Upload).order_by(Upload.id.desc()).limit(100)).all()


@router.get("/uploads/{upload_id}/report")
def upload_report(upload_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_admin)):
    up = db.get(Upload, upload_id)
    if not up:
        raise HTTPException(404, "Upload not found.")
    return {"upload": UploadOut.model_validate(up), "report": json.loads(up.report_json or "{}")}


@router.delete("/uploads/{upload_id}", status_code=204)
def delete_upload(upload_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_admin)):
    up = db.get(Upload, upload_id)
    if not up:
        raise HTTPException(404, "Upload not found.")
    ids = db.scalars(select(HospitalData.id).where(HospitalData.upload_id == upload_id)).all()
    for i in range(0, len(ids), 5000):  # derived metrics first, so this also works without DB-level cascades
        chunk = ids[i:i + 5000]
        db.execute(delete(DerivedMetric).where(DerivedMetric.hospital_data_id.in_(chunk)))
        db.execute(delete(HospitalData).where(HospitalData.id.in_(chunk)))
    db.delete(up)
    db.commit()


@router.get("/stats")
def stats(
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    department_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    base = _scope(select(HospitalData), date_from, date_to, department_id).subquery()
    hd = base.c

    total, first, last, n_depts = db.execute(
        select(func.count(), func.min(hd.timestamp), func.max(hd.timestamp), func.count(func.distinct(hd.department_id)))
    ).one()

    columns = {}
    if total:
        aggs = []
        for c in NUMERIC_COLUMNS:
            aggs += [func.min(hd[c]), func.max(hd[c]), func.avg(hd[c])]
        row = db.execute(select(*aggs)).one()
        for i, c in enumerate(NUMERIC_COLUMNS):
            mn, mx, avg = row[3 * i: 3 * i + 3]
            columns[c] = {"min": mn, "max": mx, "mean": round(avg, 2) if avg is not None else None}

    per_dept = []
    if total:
        rows = db.execute(
            select(
                hd.department_id, func.count(), func.avg(hd.arrivals), func.avg(hd.avg_wait_min),
                func.avg(DerivedMetric.bed_occupancy_pct), func.avg(DerivedMetric.workload_index),
            )
            .select_from(base)
            .join(DerivedMetric, DerivedMetric.hospital_data_id == hd.id)
            .group_by(hd.department_id)
        ).all()
        names = {d.id: d.name for d in db.scalars(select(Department)).all()}
        per_dept = sorted(
            (
                {"department_id": r[0], "department": names.get(r[0], str(r[0])), "rows": r[1],
                 "avg_arrivals_per_hour": round(r[2] or 0, 2), "avg_wait_min": round(r[3] or 0, 1),
                 "avg_bed_occupancy_pct": round(r[4], 1) if r[4] is not None else None,
                 "avg_workload_index": round(r[5], 1) if r[5] is not None else None}
                for r in rows
            ),
            key=lambda x: x["department_id"],
        )

    return {
        "total_rows": total,
        "departments": n_depts,
        "date_from": first.isoformat() if first else None,
        "date_to": last.isoformat() if last else None,
        "uploads": db.scalar(select(func.count()).select_from(Upload).where(Upload.status == "success")) or 0,
        "columns": columns,
        "per_department": per_dept,
    }


@router.get("/preview")
def preview(
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    department_id: int | None = None,
    upload_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    q = _scope(select(HospitalData), date_from, date_to, department_id, upload_id)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.execute(
        q.with_only_columns(
            HospitalData.timestamp, Department.name, HospitalData.arrivals, HospitalData.admissions, HospitalData.discharges,
            HospitalData.avg_wait_min, HospitalData.occupied_beds, HospitalData.total_beds,
            HospitalData.doctors_available, HospitalData.nurses_available,
            DerivedMetric.bed_occupancy_pct, DerivedMetric.workload_index,
        )
        .join(Department, Department.id == HospitalData.department_id)
        .join(DerivedMetric, DerivedMetric.hospital_data_id == HospitalData.id)
        .order_by(HospitalData.timestamp.desc(), Department.id)
        .limit(limit).offset(offset)
    ).all()
    return {
        "total": total,
        "rows": [
            {"timestamp": r[0].isoformat(), "department": r[1], "arrivals": r[2], "admissions": r[3], "discharges": r[4],
             "avg_wait_min": r[5], "occupied_beds": r[6], "total_beds": r[7], "doctors_available": r[8],
             "nurses_available": r[9], "bed_occupancy_pct": r[10], "workload_index": r[11]}
            for r in rows
        ],
    }
