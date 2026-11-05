from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.security.dependencies import get_current_admin
from app.services.ml.forecasting import get_forecast

router = APIRouter(prefix="/forecast", tags=["forecasting"], dependencies=[Depends(get_current_admin)])

Target = Literal["admissions", "bed_occupancy"]


@router.get("/overview")
def overview(target: Target = "admissions", department_id: int | None = Query(None, ge=1), db: Session = Depends(get_db)):
    """Model comparison, backtest and the next 7 days for one target. Trains on first use, then serves the stored result."""
    return get_forecast(db, target, department_id)


@router.post("/retrain")
def retrain(target: Target = "admissions", department_id: int | None = Query(None, ge=1), db: Session = Depends(get_db)):
    return get_forecast(db, target, department_id, force=True)
