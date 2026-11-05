import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import HospitalData, User
from app.schemas.data import UploadOut, UploadResult
from app.security.dependencies import get_current_admin
from app.services.analytics.alerts import scan_alerts
from app.services.ingestion.errors import IngestError
from app.services.ingestion.feeds import Feed, SensorBatch, aggregate, aggregate_sensors, source_conflicts
from app.services.ingestion.pipeline import process_upload

router = APIRouter(prefix="/integration", tags=["integration"], dependencies=[Depends(get_current_admin)])

SOURCES = [
    ("csv", "CSV / Excel upload", "Operational exports uploaded from the Data Upload page."),
    ("ehr", "EHR event feed", "Anonymised arrival / admission / discharge events, aggregated to hourly rows."),
    ("his", "HIS resource snapshots", "Beds, staff on duty, lab and equipment state per department and hour."),
    ("stream", "Simulated live stream", "One simulated hour of data at a time (Alerts & Monitoring page)."),
    ("iot", "IoT sensors", "Bed, equipment and footfall sensors, aggregated to hourly rows."),
]


@router.get("/sources")
def sources(db: Session = Depends(get_db)):
    rows = {r[0]: (r[1], r[2]) for r in db.execute(select(HospitalData.source, func.count(), func.max(HospitalData.timestamp)).group_by(HospitalData.source)).all()}
    return [
        {"id": sid, "name": name, "description": desc, "rows": rows.get(sid, (0, None))[0],
         "latest": rows[sid][1].isoformat() if sid in rows and rows[sid][1] else None, "available": True}
        for sid, name, desc in SOURCES
    ]


@router.get("/sample")
def sample():
    """An example payload (invented values, no personal data) showing the accepted shape."""
    return {
        "events": [
            {"event_type": "arrival", "timestamp": "2026-10-01T09:05:00", "department": "Emergency", "wait_min": 22.5},
            {"event_type": "admission", "timestamp": "2026-10-01T09:40:00", "department": "Emergency"},
            {"event_type": "discharge", "timestamp": "2026-10-01T09:50:00", "department": "General Ward", "los_hours": 71.0},
        ],
        "snapshots": [
            {"timestamp": "2026-10-01T09:00:00", "department": "Emergency", "total_beds": 40, "occupied_beds": 31,
             "doctors_available": 6, "nurses_available": 18, "lab_tests_ordered": 14, "lab_capacity": 22,
             "equipment_available": 9, "equipment_total": 12},
        ],
    }


@router.post("/feed", response_model=UploadResult, status_code=201)
def feed(body: Feed, db: Session = Depends(get_db), user: User = Depends(get_current_admin)):
    """Accept an anonymised EHR event feed and/or HIS snapshots and store them as hourly department rows."""
    if not body.events and not body.snapshots:
        raise HTTPException(422, "Send at least one event or snapshot.")
    frame, source = aggregate(body)
    return _store(db, user, frame, source)


OVERLAP = "{n} of these hours already exist from another source and would be counted twice. Send only hours that are not already loaded."


def _store(db, user, frame, source):
    n = source_conflicts(db, frame, source)
    if n:
        raise HTTPException(409, OVERLAP.format(n=n))
    try:
        upload = process_upload(db, user, f"{source}_feed.csv", frame.to_csv(index=False).encode(), source=source)
    except IngestError as exc:
        return JSONResponse(status_code=422, content={"error": "ingest_error", "detail": exc.message, "code": 422,
                                                      "ingest_code": exc.code, "details": exc.details})
    try:
        scan_alerts(db)
    except Exception:  # noqa: BLE001
        db.rollback()
    return UploadResult(upload=UploadOut.model_validate(upload), report=json.loads(upload.report_json or "{}"))


@router.post("/iot", response_model=UploadResult, status_code=201)
def iot(body: SensorBatch, db: Session = Depends(get_db), user: User = Depends(get_current_admin)):
    """Accept sensor readings (bed, equipment, footfall) and store them as hourly department rows."""
    return _store(db, user, aggregate_sensors(body), "iot")


@router.get("/iot-sample")
def iot_sample():
    return {"readings": [
        {"sensor_type": "bed", "device_id": "ICU-BED-01", "department": "ICU", "timestamp": "2026-10-01T09:10:00", "value": 1},
        {"sensor_type": "bed", "device_id": "ICU-BED-02", "department": "ICU", "timestamp": "2026-10-01T09:12:00", "value": 0},
        {"sensor_type": "equipment", "device_id": "ICU-VENT-01", "department": "ICU", "timestamp": "2026-10-01T09:15:00", "value": 1},
        {"sensor_type": "footfall", "device_id": "ED-DOOR-01", "department": "Emergency", "timestamp": "2026-10-01T09:30:00", "value": 4},
    ]}
