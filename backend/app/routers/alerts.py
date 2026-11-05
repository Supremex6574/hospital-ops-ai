from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Alert, Department, User
from app.security.dependencies import get_current_admin
from app.services.analytics.alerts import scan_alerts

router = APIRouter(prefix="/alerts", tags=["alerts"], dependencies=[Depends(get_current_admin)])


def _out(a: Alert, dept: str | None) -> dict:
    return {"id": a.id, "created_at": a.created_at, "as_of": a.as_of, "department_id": a.department_id, "department": dept,
            "type": a.type, "severity": a.severity, "message": a.message, "metric_value": a.metric_value,
            "threshold": a.threshold, "acknowledged": a.acknowledged}


@router.get("")
def list_alerts(status: Literal["open", "acknowledged", "all"] = "open",
                severity: Literal["warning", "critical"] | None = None,
                limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    stmt = select(Alert, Department.name).outerjoin(Department, Department.id == Alert.department_id)
    if status != "all":
        stmt = stmt.where(Alert.acknowledged.is_(status == "acknowledged"))
    if severity:
        stmt = stmt.where(Alert.severity == severity)
    stmt = stmt.order_by(Alert.severity.asc(), Alert.id.desc()).limit(limit)  # 'critical' sorts before 'warning'
    return [_out(a, d) for a, d in db.execute(stmt).all()]


@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    rows = dict(db.execute(select(Alert.severity, func.count()).where(Alert.acknowledged.is_(False)).group_by(Alert.severity)).all())
    return {"open": sum(rows.values()), "critical": rows.get("critical", 0), "warning": rows.get("warning", 0)}


@router.post("/scan")
def scan(db: Session = Depends(get_db)):
    return scan_alerts(db)


@router.post("/acknowledge-all")
def acknowledge_all(db: Session = Depends(get_db), user: User = Depends(get_current_admin)):
    n = db.execute(update(Alert).where(Alert.acknowledged.is_(False)).values(acknowledged=True, acknowledged_by=user.id)).rowcount
    db.commit()
    return {"acknowledged": n}


@router.post("/{alert_id}/acknowledge")
def acknowledge(alert_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_admin)):
    a = db.get(Alert, alert_id)
    if not a:
        raise HTTPException(404, "Alert not found.")
    a.acknowledged, a.acknowledged_by = True, user.id
    db.commit()
    return _out(a, db.scalar(select(Department.name).where(Department.id == a.department_id)))
