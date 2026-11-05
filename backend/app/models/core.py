"""Core tables: users, departments, uploads, canonical hospital data and derived metrics."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(20), default="admin")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    type: Mapped[str] = mapped_column(String(20))  # ED / OPD / ICU / Ward / Lab / Pharmacy
    total_beds: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Upload(Base):
    __tablename__ = "uploads"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(String(255))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    rows_total: Mapped[int] = mapped_column(Integer, default=0)
    rows_valid: Mapped[int] = mapped_column(Integer, default=0)
    rows_dropped: Mapped[int] = mapped_column(Integer, default=0)
    duplicates_removed: Mapped[int] = mapped_column(Integer, default=0)
    missing_filled: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/success/failed
    report_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class HospitalData(Base):
    """Canonical hourly, department-level operational record. Every source maps into this."""

    __tablename__ = "hospital_data"
    __table_args__ = (
        UniqueConstraint("timestamp", "department_id", "source", name="uq_hospital_data_point"),
        Index("ix_hospital_data_ts", "timestamp"),
        Index("ix_hospital_data_dept_ts", "department_id", "timestamp"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"))

    arrivals: Mapped[int] = mapped_column(Integer, default=0)
    admissions: Mapped[int] = mapped_column(Integer, default=0)
    discharges: Mapped[int] = mapped_column(Integer, default=0)
    avg_wait_min: Mapped[float] = mapped_column(Float, default=0.0)
    avg_los_hours: Mapped[float] = mapped_column(Float, default=0.0)

    total_beds: Mapped[int] = mapped_column(Integer, default=0)
    occupied_beds: Mapped[int] = mapped_column(Integer, default=0)
    available_beds: Mapped[int] = mapped_column(Integer, default=0)

    doctors_available: Mapped[int] = mapped_column(Integer, default=0)
    nurses_available: Mapped[int] = mapped_column(Integer, default=0)

    appointments_scheduled: Mapped[int] = mapped_column(Integer, default=0)
    appointments_completed: Mapped[int] = mapped_column(Integer, default=0)

    lab_tests_ordered: Mapped[int] = mapped_column(Integer, default=0)
    lab_capacity: Mapped[int] = mapped_column(Integer, default=0)
    equipment_available: Mapped[int] = mapped_column(Integer, default=0)
    equipment_total: Mapped[int] = mapped_column(Integer, default=0)

    source: Mapped[str] = mapped_column(String(10), default="csv")  # csv | ehr | his | iot | stream
    upload_id: Mapped[int | None] = mapped_column(ForeignKey("uploads.id", ondelete="CASCADE"), nullable=True)

    derived: Mapped["DerivedMetric"] = relationship(back_populates="record", uselist=False, cascade="all, delete-orphan")


class DerivedMetric(Base):
    __tablename__ = "derived_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    hospital_data_id: Mapped[int] = mapped_column(ForeignKey("hospital_data.id", ondelete="CASCADE"), unique=True)
    bed_occupancy_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    resource_util_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    patients_per_doctor: Mapped[float | None] = mapped_column(Float, nullable=True)
    patients_per_nurse: Mapped[float | None] = mapped_column(Float, nullable=True)
    workload_index: Mapped[float | None] = mapped_column(Float, nullable=True)
    equipment_util_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    lab_util_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_peak_hour: Mapped[bool] = mapped_column(Boolean, default=False)

    record: Mapped[HospitalData] = relationship(back_populates="derived")


class AppSetting(Base):
    """Admin-tunable thresholds and weights."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
