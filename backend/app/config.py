from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings. Override any value with an environment variable or backend/.env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Smart Hospital Operations & Decision Support System"
    api_prefix: str = "/api/v1"

    # SQLite for development; switch to PostgreSQL by setting e.g.
    # DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/hospital_ops
    database_url: str = "sqlite:///./hospital_ops.db"

    # JWT. CHANGE secret_key in any real deployment (set SECRET_KEY in the environment).
    secret_key: str = "dev-only-change-me-please-use-a-long-random-string"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 120

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # Seed admin account created on first start if no users exist.
    seed_admin_username: str = "admin"
    seed_admin_password: str = "Admin@123"

    # Login throttling (per username+IP)
    login_max_attempts: int = 5
    login_lock_seconds: int = 60

    max_upload_mb: int = 10
    max_upload_rows: int = 300_000


# Default operational thresholds, stored in the `settings` table on first run (admin-tunable later).
DEFAULT_THRESHOLDS: dict[str, tuple[str, str]] = {
    "occupancy_warning_pct": ("85", "Bed occupancy % that triggers a warning"),
    "occupancy_critical_pct": ("90", "Bed occupancy % that triggers a critical alert"),
    "wait_zscore_threshold": ("1.5", "Waiting time z-score vs same dept/hour-of-week baseline"),
    "arrival_growth_ratio": ("1.3", "3h rolling arrivals / baseline ratio flagged as rapid growth"),
    "arrival_zscore_threshold": ("2.5", "Arrival volume z-score flagged as unusual"),
    "lab_overload_pct": ("90", "Lab tests ordered / capacity % flagged as overload"),
    "weight_bed_occupancy": ("0.4", "Workload index weight: bed occupancy"),
    "weight_doctor_load": ("0.3", "Workload index weight: doctor load"),
    "weight_nurse_load": ("0.2", "Workload index weight: nurse load"),
    "weight_wait": ("0.1", "Workload index weight: waiting time"),
}

DEFAULT_DEPARTMENTS: list[tuple[str, str, int]] = [
    # name, type, total_beds
    ("Emergency", "ED", 40),
    ("OPD", "OPD", 0),
    ("ICU", "ICU", 20),
    ("General Ward", "Ward", 150),
    ("Pediatrics", "Ward", 40),
    ("Surgery", "Ward", 50),
]


# Staffing-load norms: (patients per doctor, patients per nurse). "Load" is the bed census for
# departments with beds and hourly arrivals for outpatient departments. These are documented,
# tunable assumptions (calibrated to the synthetic data), not clinical standards.
DEPT_NORMS: dict[str, tuple[float, float]] = {
    "Emergency": (7.0, 2.2),
    "OPD": (3.0, 3.0),
    "ICU": (7.0, 1.1),
    "General Ward": (28.0, 5.5),
    "Pediatrics": (12.0, 3.5),
    "Surgery": (12.0, 3.2),
}
TYPE_NORMS: dict[str, tuple[float, float]] = {
    "ED": (7.0, 2.2), "OPD": (3.0, 3.0), "ICU": (7.0, 1.1), "Ward": (15.0, 4.0),
}


@lru_cache
def get_settings() -> Settings:
    return Settings()
