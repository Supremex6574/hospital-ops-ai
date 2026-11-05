from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.security.dependencies import get_current_admin
from app.services.analytics.bottlenecks import compute_bottlenecks

router = APIRouter(prefix="/bottlenecks", tags=["bottlenecks"], dependencies=[Depends(get_current_admin)])


@router.get("")
def bottlenecks(date_from: date | None = Query(None, alias="from"), date_to: date | None = Query(None, alias="to"),
                department_id: int | None = Query(None, ge=1), db: Session = Depends(get_db)):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "The start date must not be after the end date.")
    return compute_bottlenecks(db, date_from, date_to, department_id)
