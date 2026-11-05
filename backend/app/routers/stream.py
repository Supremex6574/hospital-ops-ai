from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security.dependencies import get_current_admin
from app.services.streaming import simulator as sim

router = APIRouter(prefix="/stream", tags=["stream"], dependencies=[Depends(get_current_admin)])


class Start(BaseModel):
    interval_seconds: float = Field(3, ge=1, le=30)


class Step(BaseModel):
    hours: int = Field(1, ge=1, le=sim.MAX_HOURS_PER_STEP)


class Surge(BaseModel):
    department: str = Field(min_length=1, max_length=60)
    hours: int = Field(4, ge=1, le=12)


def _guard(fn):
    try:
        return fn()
    except sim.StreamError as e:
        raise HTTPException(422, str(e))


@router.get("/status")
def status(db: Session = Depends(get_db)):
    return sim.status(db)


@router.post("/start")
def start(body: Start, db: Session = Depends(get_db), user: User = Depends(get_current_admin)):
    _guard(lambda: sim.start(user.id, body.interval_seconds))
    return sim.status(db)


@router.post("/stop")
def stop(db: Session = Depends(get_db)):
    sim.stop()
    return sim.status(db)


@router.post("/step")
def step(body: Step, db: Session = Depends(get_db), user: User = Depends(get_current_admin)):
    if sim._state["running"]:
        raise HTTPException(409, "Stop the live stream before stepping manually.")
    _guard(lambda: [sim.tick(db, user.id) for _ in range(body.hours)])
    return sim.status(db)


@router.post("/surge")
def surge(body: Surge, db: Session = Depends(get_db)):
    _guard(lambda: sim.inject_surge(db, body.department, body.hours))
    return sim.status(db)
