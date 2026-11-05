from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.security.dependencies import get_current_admin
from app.services.analytics.dashboard import compute_kpis, compute_summary

router = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(get_current_admin)])


def _check_range(date_from: date | None, date_to: date | None) -> None:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "The start date must not be after the end date.")


@router.get("/kpis")
def kpis(
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    department_id: int | None = Query(None, ge=1),
    db: Session = Depends(get_db),
):
    _check_range(date_from, date_to)
    return compute_kpis(db, date_from, date_to, department_id)


@router.get("/summary")
def summary(
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    department_id: int | None = Query(None, ge=1),
    db: Session = Depends(get_db),
):
    _check_range(date_from, date_to)
    return compute_summary(db, date_from, date_to, department_id)
