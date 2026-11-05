from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.security.dependencies import get_current_admin
from app.services.analytics.resources import compute_compare, compute_detail

router = APIRouter(prefix="/resources", tags=["resources"], dependencies=[Depends(get_current_admin)])


def _check(date_from: date | None, date_to: date | None) -> None:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "The start date must not be after the end date.")


@router.get("/compare")
def compare(date_from: date | None = Query(None, alias="from"), date_to: date | None = Query(None, alias="to"),
            db: Session = Depends(get_db)):
    _check(date_from, date_to)
    return compute_compare(db, date_from, date_to)


@router.get("/{kind}")
def detail(kind: Literal["beds", "doctors", "nurses", "lab"],
           date_from: date | None = Query(None, alias="from"), date_to: date | None = Query(None, alias="to"),
           department_id: int | None = Query(None, ge=1), db: Session = Depends(get_db)):
    _check(date_from, date_to)
    return compute_detail(db, kind, date_from, date_to, department_id)
