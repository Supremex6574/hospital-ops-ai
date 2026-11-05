"""API tests for the data module: upload, storage, replace-on-reupload, reports, stats, preview, delete."""
import importlib.util
import io
import sys
import time
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import delete, func, select

from app.database import SessionLocal
from app.models import Department, DerivedMetric, HospitalData, Upload

API = "/api/v1"
ROOT = Path(__file__).resolve().parents[2]
SYN = ROOT / "data" / "synthetic"


def _generator():
    spec = importlib.util.spec_from_file_location("gen", ROOT / "data" / "generate_synthetic.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gen"] = mod  # dataclasses need the module registered
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def small_csv() -> bytes:
    df, _ = _generator().generate("2026-01-01", 3, seed=1)  # 3 days x 24h x 6 depts = 432 rows
    return df.to_csv(index=False).encode()


@pytest.fixture(autouse=True)
def empty_data_tables():
    with SessionLocal() as db:
        db.execute(delete(DerivedMetric))
        db.execute(delete(HospitalData))
        db.execute(delete(Upload))
        db.commit()
    yield


def up(client, headers, content, name="data.csv", ctype="text/csv"):
    return client.post(f"{API}/data/upload", headers=headers, files={"file": (name, content, ctype)})


def count(model):
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(model))


def test_all_data_endpoints_require_auth(client):
    assert client.post(f"{API}/data/upload", files={"file": ("a.csv", b"x", "text/csv")}).status_code == 401
    for path in ("/data/stats", "/data/preview", "/data/uploads", "/data/template", "/data/uploads/1/report"):
        assert client.get(f"{API}{path}").status_code == 401, path
    assert client.post(f"{API}/data/load-sample").status_code == 401
    assert client.delete(f"{API}/data/uploads/1").status_code == 401


def test_upload_clean_csv_stores_rows_and_derived_metrics(client, auth_headers, small_csv):
    r = up(client, auth_headers, small_csv)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["upload"]["status"] == "success" and body["upload"]["rows_valid"] == 432
    rep = body["report"]
    assert rep["rows_inserted"] == 432 and rep["rows_replaced"] == 0 and rep["granularity"] == "hourly"
    assert len(rep["departments"]) == 6 and len(rep["summary"]) == 6
    assert count(HospitalData) == 432 and count(DerivedMetric) == 432


def test_reuploading_same_file_replaces_instead_of_duplicating(client, auth_headers, small_csv):
    up(client, auth_headers, small_csv)
    r = up(client, auth_headers, small_csv)
    assert r.json()["report"]["rows_replaced"] == 432
    assert count(HospitalData) == 432 and count(DerivedMetric) == 432  # no growth, no orphans
    assert client.get(f"{API}/data/stats", headers=auth_headers).json()["total_rows"] == 432


def test_messy_file_is_repaired_and_reported(client, auth_headers):
    r = up(client, auth_headers, (SYN / "messy_sample.csv").read_bytes(), "messy.csv")
    assert r.status_code == 201, r.text
    rep = r.json()["report"]
    assert rep["duplicates_removed"] == 40 and rep["rows_valid"] == 3000
    assert rep["missing_filled"] > 0
    assert rep["columns"]["arrivals"]["type_errors"] > 0 and rep["columns"]["doctors_available"]["negative_values"] == 4
    assert rep["consistency_fixes"]["occupied_beds_above_total_clipped"] == 3
    with SessionLocal() as db:  # nothing impossible reaches the database
        assert db.scalar(select(func.count()).select_from(HospitalData).where(HospitalData.occupied_beds > HospitalData.total_beds)) == 0
        assert db.scalar(select(func.count()).select_from(HospitalData).where(HospitalData.doctors_available < 0)) == 0


def test_pii_file_rejected_and_nothing_stored(client, auth_headers):
    r = up(client, auth_headers, (SYN / "pii_sample.csv").read_bytes(), "pii.csv")
    assert r.status_code == 422
    b = r.json()
    assert b["ingest_code"] == "pii_detected" and "patient_name" in b["details"][0]
    assert count(HospitalData) == 0
    with SessionLocal() as db:  # the failed attempt is recorded for the history view
        up_row = db.get(Upload, b["upload_id"])
        assert up_row.status == "failed"


@pytest.mark.parametrize("name,content,code", [
    ("notes.txt", b"hello", "bad_extension"),
    ("empty.csv", b"", "empty_file"),
    ("fake.xlsx", b"just text", "bad_signature"),
    ("cols.csv", b"foo,bar\n1,2\n", "missing_columns"),
])
def test_bad_files_get_clear_422(client, auth_headers, name, content, code):
    r = up(client, auth_headers, content, name)
    assert r.status_code == 422 and r.json()["ingest_code"] == code and r.json()["detail"]


def test_upload_larger_than_limit_rejected(client, auth_headers):
    r = up(client, auth_headers, b"a,b\n" + b"1,2\n" * (3 * 1024 * 1024))  # ~12 MB
    assert r.status_code == 422 and r.json()["ingest_code"] == "too_large"


def test_excel_upload_with_unusual_headings(client, auth_headers):
    df = pd.DataFrame({
        "Date": ["2026-02-01", "2026-02-01"], "Hour": ["09:00", "10:00"], "Dept": ["Cardiology", "Cardiology"],
        "Patients": [12, 15], "Beds": [30, 30], "Occupied": [20, 22], "Doctors": [5, 5], "Nurses": [12, 12],
        "Remarks": ["ok", "busy"],
    })
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    r = up(client, auth_headers, buf.getvalue(), "export.xlsx",
           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert r.status_code == 201, r.text
    rep = r.json()["report"]
    assert rep["new_departments"] == ["Cardiology"] and rep["unknown_columns_dropped"] == ["Remarks"]
    assert rep["columns_renamed"]["Dept"] == "department"
    with SessionLocal() as db:
        d = db.scalar(select(Department).where(Department.name == "Cardiology"))
        assert d is not None and d.type == "Ward" and d.total_beds == 30


def test_stats_preview_and_filters(client, auth_headers, small_csv):
    up(client, auth_headers, small_csv)
    s = client.get(f"{API}/data/stats", headers=auth_headers).json()
    assert s["total_rows"] == 432 and s["departments"] == 6 and s["uploads"] == 1
    assert s["date_from"].startswith("2026-01-01") and s["date_to"].startswith("2026-01-03T23")
    assert len(s["per_department"]) == 6 and s["columns"]["arrivals"]["max"] >= s["columns"]["arrivals"]["mean"]

    one_day = client.get(f"{API}/data/stats", headers=auth_headers, params={"from": "2026-01-02", "to": "2026-01-02"}).json()
    assert one_day["total_rows"] == 144
    er = client.get(f"{API}/data/stats", headers=auth_headers, params={"department_id": 1}).json()
    assert er["total_rows"] == 72 and er["departments"] == 1

    p = client.get(f"{API}/data/preview", headers=auth_headers, params={"limit": 10}).json()
    assert p["total"] == 432 and len(p["rows"]) == 10
    assert {"timestamp", "department", "bed_occupancy_pct", "workload_index"} <= set(p["rows"][0])
    ts = [r["timestamp"] for r in p["rows"]]
    assert ts == sorted(ts, reverse=True)
    page2 = client.get(f"{API}/data/preview", headers=auth_headers, params={"limit": 10, "offset": 10}).json()
    assert page2["rows"][0] != p["rows"][0]


def test_stats_on_empty_database(client, auth_headers):
    s = client.get(f"{API}/data/stats", headers=auth_headers).json()
    assert s["total_rows"] == 0 and s["per_department"] == [] and s["date_from"] is None


def test_preview_limit_validation(client, auth_headers):
    assert client.get(f"{API}/data/preview", headers=auth_headers, params={"limit": 5000}).status_code == 422


def test_upload_history_report_and_delete(client, auth_headers, small_csv):
    uid = up(client, auth_headers, small_csv).json()["upload"]["id"]
    up(client, auth_headers, b"", "bad.csv")  # failed attempt
    hist = client.get(f"{API}/data/uploads", headers=auth_headers).json()
    assert [h["status"] for h in hist] == ["failed", "success"]  # newest first

    rep = client.get(f"{API}/data/uploads/{uid}/report", headers=auth_headers).json()
    assert rep["upload"]["id"] == uid and rep["report"]["rows_inserted"] == 432
    assert client.get(f"{API}/data/uploads/99999/report", headers=auth_headers).status_code == 404

    assert client.delete(f"{API}/data/uploads/{uid}", headers=auth_headers).status_code == 204
    assert count(HospitalData) == 0 and count(DerivedMetric) == 0
    assert client.delete(f"{API}/data/uploads/{uid}", headers=auth_headers).status_code == 404


def test_template_download(client, auth_headers):
    r = client.get(f"{API}/data/template", headers=auth_headers)
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    lines = r.text.strip().splitlines()
    assert lines[0].split(",")[:3] == ["date", "time", "department"] and len(lines) == 2
    # the template itself must be a valid upload
    assert up(client, auth_headers, r.content, "template.csv").status_code == 201


def test_load_sample_runs_full_year_through_pipeline(client, auth_headers):
    t = time.time()
    r = client.post(f"{API}/data/load-sample", headers=auth_headers)
    assert r.status_code == 201, r.text
    assert r.json()["report"]["rows_inserted"] == 52560 and r.json()["report"]["missing_filled"] == 0
    assert count(HospitalData) == 52560 and count(DerivedMetric) == 52560
    assert time.time() - t < 60
