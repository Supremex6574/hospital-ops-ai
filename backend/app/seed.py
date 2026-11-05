"""Idempotent first-run seeding: tables, admin user, departments, default thresholds."""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import DEFAULT_DEPARTMENTS, DEFAULT_THRESHOLDS, get_settings
from app.database import Base, engine
from app.models import AppSetting, Department, User
from app.security.passwords import hash_password

log = logging.getLogger("hospital_ops.seed")


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def seed(db: Session) -> None:
    s = get_settings()

    if db.scalar(select(User.id).limit(1)) is None:
        db.add(User(username=s.seed_admin_username, password_hash=hash_password(s.seed_admin_password), role="admin"))
        log.warning("Created default admin user '%s'. Change this password for any real use.", s.seed_admin_username)

    existing_depts = set(db.scalars(select(Department.name)).all())
    for name, dtype, beds in DEFAULT_DEPARTMENTS:
        if name not in existing_depts:
            db.add(Department(name=name, type=dtype, total_beds=beds))

    existing_keys = set(db.scalars(select(AppSetting.key)).all())
    for key, (value, desc) in DEFAULT_THRESHOLDS.items():
        if key not in existing_keys:
            db.add(AppSetting(key=key, value=value, description=desc))

    db.commit()
