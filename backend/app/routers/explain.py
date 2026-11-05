from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.security.dependencies import get_current_admin
from app.services.ml.explain import explain_forecast

router = APIRouter(prefix="/explain", tags=["explainability"], dependencies=[Depends(get_current_admin)])


@router.get("/forecast")
def forecast_explanation(target: Literal["admissions", "bed_occupancy"] = "admissions",
                         department_id: int | None = Query(None, ge=1), db: Session = Depends(get_db)):
    """Why the selected forecasting model predicts what it does: global drivers and a per-day breakdown (SHAP)."""
    return explain_forecast(db, target, department_id)
