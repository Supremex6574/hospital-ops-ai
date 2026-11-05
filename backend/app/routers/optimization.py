from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.security.dependencies import get_current_admin
from app.services.decision.optimization import optimize
from app.services.decision.simulation import ScenarioError

router = APIRouter(prefix="/optimization", tags=["optimization"], dependencies=[Depends(get_current_admin)])


class Request(BaseModel):
    resource: Literal["beds", "doctors", "nurses"]
    extra: int = Field(0, ge=0, le=100)
    max_change_pct: int = Field(30, ge=5, le=60)
    baseline_days: int = Field(28, ge=7, le=90)


@router.post("/run")
def run(body: Request, db: Session = Depends(get_db)):
    try:
        return optimize(db, resource=body.resource, extra=body.extra, max_change_pct=body.max_change_pct, baseline_days=body.baseline_days)
    except ScenarioError as e:
        raise HTTPException(422, str(e))
