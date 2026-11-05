"""Resource, patient-flow, IoT, ML, decision-support tables."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Resource(Base):
    __tablename__ = "resources"

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"))
    resource_type: Mapped[str] = mapped_column(String(20))  # bed/doctor/nurse/lab/equipment
    capacity: Mapped[int] = mapped_column(Integer, default=0)
    unit: Mapped[str] = mapped_column(String(20), default="units")


class Staff(Base):
    """Aggregate headcount only. No individual staff records, no PII."""

    __tablename__ = "staff"

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"))
    role: Mapped[str] = mapped_column(String(20))  # doctor / nurse
    shift: Mapped[str] = mapped_column(String(20), default="day")
    headcount: Mapped[int] = mapped_column(Integer, default=0)


class Bed(Base):
    __tablename__ = "beds"

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"))
    bed_type: Mapped[str] = mapped_column(String(20), default="general")
    status: Mapped[str] = mapped_column(String(20), default="free")  # occupied/free/maintenance
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PatientFlow(Base):
    __tablename__ = "patient_flow"
    __table_args__ = (Index("ix_patient_flow_dept_ts", "department_id", "timestamp"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"))
    stage: Mapped[str] = mapped_column(String(20))  # registration/waiting/consultation/lab/pharmacy/discharge
    patients_in_stage: Mapped[int] = mapped_column(Integer, default=0)
    avg_stage_time_min: Mapped[float] = mapped_column(Float, default=0.0)


class IoTReading(Base):
    __tablename__ = "iot_readings"
    __table_args__ = (Index("ix_iot_ts", "timestamp"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    device_type: Mapped[str] = mapped_column(String(20))  # bed_sensor/room_sensor/equipment/env
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"))
    device_id: Mapped[str] = mapped_column(String(40))
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(20), default="")
    status: Mapped[str] = mapped_column(String(20), default="ok")


class ModelResult(Base):
    __tablename__ = "model_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    target: Mapped[str] = mapped_column(String(30))  # admissions | bed_occupancy
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True)  # None = hospital-wide
    model_name: Mapped[str] = mapped_column(String(40))
    mae: Mapped[float | None] = mapped_column(Float, nullable=True)
    rmse: Mapped[float | None] = mapped_column(Float, nullable=True)
    r2: Mapped[float | None] = mapped_column(Float, nullable=True)
    mape: Mapped[float | None] = mapped_column(Float, nullable=True)
    trained_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False)
    params_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifact_path: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Forecast(Base):
    __tablename__ = "forecasts"
    __table_args__ = (Index("ix_forecasts_target_time", "target", "forecast_time"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    target: Mapped[str] = mapped_column(String(30))
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    forecast_time: Mapped[datetime] = mapped_column(DateTime)
    horizon_h: Mapped[int] = mapped_column(Integer, default=24)
    predicted_value: Mapped[float] = mapped_column(Float)
    lower_ci: Mapped[float | None] = mapped_column(Float, nullable=True)
    upper_ci: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_id: Mapped[int | None] = mapped_column(ForeignKey("model_results.id"), nullable=True)
    shap_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    category: Mapped[str] = mapped_column(String(30))
    priority: Mapped[str] = mapped_column(String(10))  # low/medium/high/critical
    text: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger_rule: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(15), default="new")  # new/accepted/dismissed/resolved
    title: Mapped[str | None] = mapped_column(String(160), nullable=True)
    impact: Mapped[str | None] = mapped_column(Text, nullable=True)
    horizon: Mapped[str | None] = mapped_column(String(60), nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(10), nullable=True)  # high = measured now, medium = forecast or pattern
    evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    as_of: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_created", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    type: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(10))  # info/warning/critical
    message: Mapped[str] = mapped_column(Text)
    metric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    as_of: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # data timestamp the alert refers to
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    acknowledged_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class SimulationResult(Base):
    __tablename__ = "simulation_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    params_json: Mapped[str] = mapped_column(Text)
    baseline_json: Mapped[str] = mapped_column(Text)
    result_json: Mapped[str] = mapped_column(Text)
    recommended_action: Mapped[str | None] = mapped_column(Text, nullable=True)
