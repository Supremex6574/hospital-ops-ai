from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Recommendation
from app.security.dependencies import get_current_admin
from app.services.decision.recommendations import generate, list_recommendations

router = APIRouter(prefix="/recommendations", tags=["recommendations"], dependencies=[Depends(get_current_admin)])


class StatusUpdate(BaseModel):
    status: Literal["new", "accepted", "dismissed"]


@router.get("")
def read(status: Literal["active", "new", "accepted", "dismissed", "resolved", "all"] = "active", db: Session = Depends(get_db)):
    """Current recommendations. Generated on first use and again whenever the data or thresholds change."""
    return list_recommendations(db, status)


@router.post("/refresh")
def refresh(db: Session = Depends(get_db)):
    generate(db, force=True)
    return list_recommendations(db, "active")


@router.patch("/{rec_id}")
def update(rec_id: int, body: StatusUpdate, db: Session = Depends(get_db)):
    rec = db.get(Recommendation, rec_id)
    if not rec:
        raise HTTPException(404, "Recommendation not found.")
    rec.status = body.status
    db.commit()
    return {"id": rec.id, "status": rec.status}
