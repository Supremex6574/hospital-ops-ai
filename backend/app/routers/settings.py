from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import DEFAULT_THRESHOLDS
from app.database import get_db
from app.models import AppSetting
from app.security.dependencies import get_current_admin
from app.services.analytics.common import get_thresholds

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(get_current_admin)])

# allowed range per key (inclusive); keeps thresholds meaningful
RANGES = {
    "occupancy_warning_pct": (50, 100), "occupancy_critical_pct": (50, 100), "wait_zscore_threshold": (0.5, 6),
    "arrival_growth_ratio": (1.05, 3), "arrival_zscore_threshold": (1, 8), "lab_overload_pct": (50, 150),
    "weight_bed_occupancy": (0, 1), "weight_doctor_load": (0, 1), "weight_nurse_load": (0, 1), "weight_wait": (0, 1),
}


class ThresholdUpdate(BaseModel):
    values: dict[str, float] = Field(min_length=1, max_length=len(RANGES))


def _view(db: Session) -> list[dict]:
    cur = get_thresholds(db)
    return [{"key": k, "value": cur[k], "default": float(v[0]), "description": v[1], "min": RANGES[k][0], "max": RANGES[k][1]}
            for k, v in DEFAULT_THRESHOLDS.items()]


@router.get("/thresholds")
def read(db: Session = Depends(get_db)):
    return _view(db)


@router.put("/thresholds")
def update(body: ThresholdUpdate, db: Session = Depends(get_db)):
    bad = [k for k in body.values if k not in RANGES]
    if bad:
        raise HTTPException(422, "Unknown setting.")
    for k, v in body.values.items():
        lo, hi = RANGES[k]
        if not lo <= v <= hi:
            raise HTTPException(422, f"{k} must be between {lo:g} and {hi:g}.")
    merged = {**get_thresholds(db), **body.values}
    if merged["occupancy_warning_pct"] >= merged["occupancy_critical_pct"]:
        raise HTTPException(422, "The warning occupancy must be below the critical occupancy.")
    if abs(sum(merged[k] for k in RANGES if k.startswith("weight_")) - 1.0) > 0.01:
        raise HTTPException(422, "The four workload weights must add up to 1.")
    for k, v in body.values.items():
        row = db.get(AppSetting, k)
        if row:
            row.value = f"{v:g}"
        else:
            db.add(AppSetting(key=k, value=f"{v:g}", description=DEFAULT_THRESHOLDS[k][1]))
    db.commit()
    return _view(db)
