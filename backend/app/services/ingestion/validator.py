"""File-level validation: type, size, encoding, structure, and personal-data rejection."""
from __future__ import annotations

import io
import re
from pathlib import Path

import pandas as pd

from app.config import get_settings
from app.services.ingestion.adapters import CANONICAL_COLUMNS, normalize_name
from app.services.ingestion.errors import IngestError

ALLOWED_EXTENSIONS = {".csv", ".xlsx"}
MAX_COLUMNS = 80

# Column-name tokens that indicate personal data. Matched on the normalised, underscore-split name.
PII_TOKENS = {
    "name", "firstname", "lastname", "surname", "phone", "mobile", "telephone", "email", "address",
    "street", "ssn", "aadhaar", "aadhar", "passport", "dob", "birthdate", "birthday", "mrn", "contact",
    "guardian", "patientid", "pincode", "zipcode",
}
PII_PHRASES = ("patient_id", "patient_name", "date_of_birth", "birth_date", "zip_code", "post_code", "medical_record")
# Names that contain a PII token but are legitimate operational columns.
PII_ALLOWED = {"department_name", "dept_name", "ward_name", "unit_name", "service_name"}

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d{1,3}[\s-]?)?\d{10}(?!\d)")


def _pii_column_names(columns) -> list[str]:
    bad = []
    for col in columns:
        norm = normalize_name(col)
        if norm in PII_ALLOWED or norm in CANONICAL_COLUMNS:
            continue
        tokens = set(norm.split("_"))
        if tokens & PII_TOKENS or any(p in norm for p in PII_PHRASES):
            bad.append(str(col))
    return bad


def validate_upload(filename: str, content: bytes) -> str:
    """Checks extension, size and file signature. Returns the file kind ('csv' or 'excel')."""
    s = get_settings()
    if not filename:
        raise IngestError("The upload has no file name.", "no_filename")
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise IngestError(
            f"Unsupported file type '{ext or 'none'}'. Upload a .csv or .xlsx file.", "bad_extension"
        )
    if len(content) == 0:
        raise IngestError("The file is empty.", "empty_file")
    if len(content) > s.max_upload_mb * 1024 * 1024:
        raise IngestError(f"The file is larger than the {s.max_upload_mb} MB limit.", "too_large")

    if ext == ".xlsx":
        if not content.startswith(b"PK"):  # xlsx is a zip container
            raise IngestError("The file is not a valid Excel (.xlsx) workbook.", "bad_signature")
        return "excel"

    if b"\x00" in content[:4096]:
        raise IngestError("The file looks binary, not a text CSV.", "bad_signature")
    return "csv"


def read_table(content: bytes, kind: str) -> pd.DataFrame:
    """
    Parse into a DataFrame of *strings*. Types are deliberately not guessed here: the cleaner coerces
    them so it can count and report every bad value. Only truly empty cells are missing.
    """
    s = get_settings()
    try:
        if kind == "excel":
            df = pd.read_excel(io.BytesIO(content), dtype=str, engine="openpyxl")
        else:
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = content.decode("latin-1")
            df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False, na_values=[""], skipinitialspace=True)
    except IngestError:
        raise
    except Exception as exc:  # parser errors are user-fixable file problems
        raise IngestError(f"The file could not be read as a table ({type(exc).__name__}).", "unreadable") from exc

    if df.shape[1] == 0 or df.shape[0] == 0:
        raise IngestError("The file contains no data rows.", "no_rows")
    if df.shape[1] > MAX_COLUMNS:
        raise IngestError(f"Too many columns ({df.shape[1]}). The limit is {MAX_COLUMNS}.", "too_many_columns")
    if df.shape[0] > s.max_upload_rows:
        raise IngestError(
            f"Too many rows ({df.shape[0]:,}). The limit is {s.max_upload_rows:,}.", "too_many_rows"
        )
    return df


def check_privacy(df: pd.DataFrame) -> None:
    """Rejects files carrying personal data: by column name, then by content in unrecognised columns."""
    bad = _pii_column_names(df.columns)
    if bad:
        raise IngestError(
            "This file appears to contain personal data columns. Remove them and upload again.",
            "pii_detected",
            details=[f"Column '{c}' looks like personal information." for c in bad],
        )

    known = {normalize_name(c) for c in CANONICAL_COLUMNS}
    from app.services.ingestion.adapters import _REVERSE  # synonym table

    for col in df.columns:
        if normalize_name(col) in known or normalize_name(col) in _REVERSE:
            continue
        sample = df[col].dropna().astype(str).head(2000)
        if sample.empty:
            continue
        hits = sample.map(lambda v: bool(_EMAIL_RE.search(v) or _PHONE_RE.search(v))).mean()
        if hits >= 0.01:
            raise IngestError(
                "This file appears to contain personal data (emails or phone numbers).",
                "pii_detected",
                details=[f"Column '{col}' contains values that look like emails or phone numbers."],
            )


def check_required(mapped: pd.DataFrame) -> list[str]:
    """Verifies the minimum columns exist after mapping. Returns warnings for missing optional columns."""
    problems = []
    if "timestamp" not in mapped.columns and "date" not in mapped.columns:
        problems.append("A date column is required (use 'date', or 'timestamp' with date and time together).")
    if "department" not in mapped.columns:
        problems.append("A 'department' column is required.")
    if "arrivals" not in mapped.columns and "admissions" not in mapped.columns:
        problems.append("At least one patient volume column is required ('arrivals' or 'admissions').")
    if problems:
        raise IngestError(
            "The file is missing required columns.", "missing_columns", details=problems
        )

    optional_missing = [
        c for c in CANONICAL_COLUMNS
        if c not in mapped.columns and c not in ("timestamp", "date", "time")
    ]
    return optional_missing
