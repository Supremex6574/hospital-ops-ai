from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import SimulationResult, User
from app.security.dependencies import get_current_admin
from app.services.decision.simulation import ScenarioError, baseline_overview, history, run_scenario, save_run

router = APIRouter(prefix="/simulation", tags=["simulation"], dependencies=[Depends(get_current_admin)])


class DeptChange(BaseModel):
    department: str = Field(min_length=1, max_length=60)
    beds_delta: int = Field(0, ge=-200, le=200)
    doctors_delta: int = Field(0, ge=-30, le=30)
    nurses_delta: int = Field(0, ge=-60, le=60)
    arrivals_change_pct: float = Field(0, ge=-50, le=100)


class Scenario(BaseModel):
    arrivals_change_pct: float = Field(0, ge=-50, le=100)
    los_change_pct: float = Field(0, ge=-40, le=60)
    baseline_days: int = Field(28, ge=7, le=90)
    departments: list[DeptChange] = Field(default_factory=list, max_length=12)
    save: bool = True


@router.get("/baseline")
def baseline(days: int = Query(28, ge=7, le=90), db: Session = Depends(get_db)):
    return baseline_overview(db, days)


@router.post("/run")
def run(body: Scenario, db: Session = Depends(get_db), user: User = Depends(get_current_admin)):
    params = body.model_dump(exclude={"save", "baseline_days"})
    try:
        result = run_scenario(db, params, body.baseline_days)
    except ScenarioError as e:
        raise HTTPException(422, str(e))
    if body.save:
        result["id"] = save_run(db, user.id, body.model_dump(exclude={"save"}), result).id
    return result


@router.get("/history")
def runs(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(get_current_admin)):
    return history(db, user.id, limit)


@router.get("/history/{run_id}")
def one_run(run_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_admin)):
    import json
    row = db.get(SimulationResult, run_id)
    if not row or row.user_id != user.id:
        raise HTTPException(404, "Simulation not found.")
    return json.loads(row.result_json) | {"id": row.id}


@router.delete("/history/{run_id}", status_code=204)
def delete_run(run_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_admin)):
    row = db.get(SimulationResult, run_id)
    if not row or row.user_id != user.id:
        raise HTTPException(404, "Simulation not found.")
    db.delete(row)
    db.commit()
