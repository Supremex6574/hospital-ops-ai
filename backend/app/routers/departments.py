from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Department
from app.schemas.auth import DepartmentOut
from app.security.dependencies import get_current_admin

router = APIRouter(prefix="/departments", tags=["departments"], dependencies=[Depends(get_current_admin)])


@router.get("", response_model=list[DepartmentOut])
def list_departments(db: Session = Depends(get_db)):
    return db.scalars(select(Department).where(Department.is_active.is_(True)).order_by(Department.id)).all()
