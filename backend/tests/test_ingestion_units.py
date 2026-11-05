"""Unit tests for validator, adapter, cleaner and feature engineering (no database)."""
import io

import numpy as np
import pandas as pd
import pytest

from app.config import get_settings
from app.services.ingestion import adapters, cleaner, features, validator
from app.services.ingestion.errors import IngestError


def raw(**cols) -> pd.DataFrame:
    """Build a string DataFrame like the reader produces (empty cell = NaN)."""
    return pd.DataFrame({k: pd.Series(v, dtype="object") for k, v in cols.items()})


def base_rows(n=3, dept="Emergency", **over):
    d = {
        "date": ["2026-01-01"] * n,
        "time": [f"{h:02d}:00" for h in range(n)],
        "department": [dept] * n,
        "arrivals": ["10"] * n, "admissions": ["4"] * n, "discharges": ["3"] * n,
        "avg_wait_min": ["30"] * n, "avg_los_hours": ["6"] * n,
        "total_beds": ["40"] * n, "occupied_beds": ["20"] * n, "available_beds": ["20"] * n,
        "doctors_available": ["8"] * n, "nurses_available": ["20"] * n,
        "appointments_scheduled": ["0"] * n, "appointments_completed": ["0"] * n,
        "lab_tests_ordered": ["10"] * n, "lab_capacity": ["20"] * n,
        "equipment_available": ["8"] * n, "equipment_total": ["12"] * n,
    }
    d.update({k: (v if isinstance(v, list) else [v] * n) for k, v in over.items()})  # scalars broadcast
    return raw(**d)


# ------------------------------------------------------------------ validator
@pytest.mark.parametrize("name,content,code", [
    ("data.txt", b"a,b\n1,2", "bad_extension"),
    ("data.csv", b"", "empty_file"),
    ("data.xlsx", b"not a zip file", "bad_signature"),
    ("data.csv", b"a,b\n\x00\x01\x02", "bad_signature"),
    ("", b"a,b", "no_filename"),
])
def test_validate_upload_rejects_bad_files(name, content, code):
    with pytest.raises(IngestError) as e:
        validator.validate_upload(name, content)
    assert e.value.code == code


def test_validate_upload_rejects_oversized():
    big = b"a" * (get_settings().max_upload_mb * 1024 * 1024 + 1)
    with pytest.raises(IngestError) as e:
        validator.validate_upload("big.csv", big)
    assert e.value.code == "too_large"


def test_read_table_keeps_strings_and_only_blank_is_missing():
    df = validator.read_table(b"a,b\n1,N/A\n,abc\n", "csv")
    assert df["b"].tolist() == ["N/A", "abc"]  # not turned into NaN, so the cleaner can report them
    assert pd.isna(df["a"].iloc[1])


def test_read_table_handles_latin1_and_bom():
    assert validator.read_table("dépt,x\nA,1\n".encode("latin-1"), "csv").shape == (1, 2)
    assert validator.read_table(b"\xef\xbb\xbfdept,x\nA,1\n", "csv").columns[0] == "dept"


def test_read_table_excel_roundtrip():
    buf = io.BytesIO()
    pd.DataFrame({"department": ["ICU"], "arrivals": [3]}).to_excel(buf, index=False)
    df = validator.read_table(buf.getvalue(), "excel")
    assert df["arrivals"].iloc[0] == "3"


@pytest.mark.parametrize("col", ["patient_name", "Phone Number", "email", "Home Address", "SSN", "Date of Birth", "patient_id", "Aadhaar"])
def test_privacy_rejects_pii_column_names(col):
    df = pd.DataFrame({"department": ["A"], col: ["x"]})
    with pytest.raises(IngestError) as e:
        validator.check_privacy(df)
    assert e.value.code == "pii_detected"
    assert col in e.value.details[0]


def test_privacy_allows_operational_names():
    for col in ["department_name", "ward_name", "department", "doctors_available"]:
        validator.check_privacy(pd.DataFrame({col: ["x"]}))


def test_privacy_scans_content_of_unknown_columns():
    df = pd.DataFrame({"department": ["A", "B"], "remarks": ["call john@example.com", "ok"]})
    with pytest.raises(IngestError):
        validator.check_privacy(df)
    df2 = pd.DataFrame({"department": ["A"], "remarks": ["call 9876543210"]})
    with pytest.raises(IngestError):
        validator.check_privacy(df2)
    validator.check_privacy(pd.DataFrame({"department": ["A"], "remarks": ["busy morning"]}))


def test_required_columns():
    ok = pd.DataFrame(columns=["date", "department", "arrivals"])
    assert "total_beds" in validator.check_required(ok)  # optional ones are reported
    for cols in (["department", "arrivals"], ["date", "arrivals"], ["date", "department"]):
        with pytest.raises(IngestError) as e:
            validator.check_required(pd.DataFrame(columns=cols))
        assert e.value.code == "missing_columns"


# ------------------------------------------------------------------ adapter
def test_synonyms_are_mapped_and_unknown_columns_dropped():
    df = pd.DataFrame(columns=["Dept", "Date", "Patients", "Wait Time", "Beds", "Doctors", "colour"])
    mapped, info = adapters.map_columns(df)
    assert set(mapped.columns) == {"department", "date", "arrivals", "avg_wait_min", "total_beds", "doctors_available"}
    assert info["unknown"] == ["colour"]
    assert info["renamed"]["Dept"] == "department"


def test_duplicate_source_columns_first_wins():
    df = pd.DataFrame([[1, 2]], columns=["arrivals", "patients"])
    mapped, info = adapters.map_columns(df)
    assert mapped["arrivals"].iloc[0] == 1 and info["duplicates"] == ["patients"]


def test_future_sources_not_implemented_yet():
    with pytest.raises(NotImplementedError):
        adapters.map_columns(pd.DataFrame(), source="iot")


# ------------------------------------------------------------------ cleaner
def test_clean_happy_path_types_and_report():
    df, rep = cleaner.clean(base_rows())
    assert len(df) == 3 and rep["rows_valid"] == 3 and rep["rows_dropped"] == 0
    assert rep["granularity"] == "hourly"
    assert df["arrivals"].dtype.kind == "i" and df["avg_wait_min"].dtype.kind == "f"
    assert df["timestamp"].iloc[1] == pd.Timestamp("2026-01-01 01:00")


def test_type_errors_negatives_and_missing_are_counted_and_filled():
    d = base_rows(4, arrivals=["10", "N/A", "-5", None], doctors_available=["8", "8", "8", "8"])
    df, rep = cleaner.clean(d)
    c = rep["columns"]["arrivals"]
    assert c["type_errors"] == 1 and c["negative_values"] == 1 and c["missing"] == 1
    assert rep["missing_by_column"]["arrivals"] == 3
    assert df["arrivals"].notna().all() and (df["arrivals"] == 10).all()  # filled with the department median


def test_exact_duplicates_and_key_conflicts():
    d = base_rows(3)
    dup = pd.concat([d, d.iloc[[0]]], ignore_index=True)           # exact duplicate
    conflict = d.iloc[[1]].copy(); conflict["arrivals"] = "99"       # same slot, different value
    df, rep = cleaner.clean(pd.concat([dup, conflict], ignore_index=True))
    assert rep["duplicates_removed"] == 1 and rep["key_conflicts_resolved"] == 1
    assert len(df) == 3 and df.loc[df["timestamp"] == pd.Timestamp("2026-01-01 01:00"), "arrivals"].iloc[0] == 99  # latest wins


def test_invalid_rows_are_dropped_with_reasons():
    d = base_rows(4, date=["2026-01-01", "not a date", "2026-01-01", "2026-01-01"], department=["Emergency", "Emergency", None, "Emergency"])
    df, rep = cleaner.clean(d)
    assert len(df) == 2 and rep["rows_dropped"] == 2
    assert rep["dropped_reasons"] == {"invalid_or_missing_date": 1, "missing_department": 1}


def test_all_rows_invalid_raises():
    with pytest.raises(IngestError) as e:
        cleaner.clean(base_rows(2, date=["x", "y"]))
    assert e.value.code == "no_valid_rows"


def test_consistency_rules():
    d = base_rows(2, occupied_beds=["999", "20"], available_beds=["5", "7"],
                  equipment_available=["50", "8"], appointments_scheduled=["3", "3"], appointments_completed=["9", "2"])
    df, rep = cleaner.clean(d)
    assert (df["occupied_beds"] <= df["total_beds"]).all()
    assert (df["available_beds"] == df["total_beds"] - df["occupied_beds"]).all()
    assert (df["equipment_available"] <= df["equipment_total"]).all()
    assert (df["appointments_completed"] <= df["appointments_scheduled"]).all()
    assert rep["consistency_fixes"]["occupied_beds_above_total_clipped"] == 1


def test_department_aliases_are_normalised():
    d = base_rows(4, department=["ER", " emergency  department ", "Paeds", "Out Patient"])
    df, _ = cleaner.clean(d)
    assert sorted(df["department"].unique()) == ["Emergency", "OPD", "Pediatrics"]


@pytest.mark.parametrize("times,hours", [(["8", "14", "23"], [8, 14, 23]), (["08:30", "14:00:00", "23:59"], [8, 14, 23]), (["2 PM", "3 AM", "11 PM"], [14, 3, 23])])
def test_time_formats(times, hours):
    df, _ = cleaner.clean(base_rows(3, time=times))
    assert sorted(df["timestamp"].dt.hour.tolist()) == sorted(hours)


def test_timestamp_column_and_timezones_become_naive():
    d = base_rows(2).drop(columns=["date", "time"])
    d["timestamp"] = ["2026-03-01T10:00:00+05:30", "2026-03-01T11:00:00+05:30"]
    df, _ = cleaner.clean(d)
    assert df["timestamp"].dt.tz is None and len(df) == 2


def test_missing_optional_columns_default_to_zero_and_arrivals_follow_admissions():
    d = raw(date=["2026-01-01"] * 2, time=["00:00", "01:00"], department=["ICU", "ICU"], admissions=["3", "5"])
    df, rep = cleaner.clean(d, optional_missing=["total_beds"])
    assert (df["arrivals"] == df["admissions"]).all() and (df["total_beds"] == 0).all()
    assert rep["optional_columns_missing"] == ["total_beds"]


def test_available_beds_derived_when_total_missing():
    d = base_rows(2).drop(columns=["total_beds"])
    df, _ = cleaner.clean(d)
    assert (df["total_beds"] == 40).all()


def test_extreme_counts_clipped_but_waiting_time_tail_is_kept():
    n = 60
    arr = [str(10 + (i % 5)) for i in range(n)]
    arr[7] = "5000"
    wait = [str(30 + (i % 7)) for i in range(n)]
    wait[9] = "300"  # a legitimately bad congestion hour must survive
    df, rep = cleaner.clean(base_rows(n, arrivals=arr, avg_wait_min=wait, time=[f"{i % 24:02d}:00" for i in range(n)],
                                      date=[f"2026-01-{1 + i // 24:02d}" for i in range(n)]))
    assert rep["outliers_clipped"] == {"arrivals": 1}
    assert df["avg_wait_min"].max() == 300


# ------------------------------------------------------------------ features
def test_feature_values_for_a_known_row():
    clean, _ = cleaner.clean(base_rows(2))
    f = features.compute_features(clean)
    assert f["bed_occupancy_pct"].iloc[0] == 50.0
    assert f["equipment_util_pct"].iloc[0] == pytest.approx(33.333, abs=0.01)
    assert f["lab_util_pct"].iloc[0] == 50.0
    assert f["patients_per_doctor"].iloc[0] == 2.5 and f["patients_per_nurse"].iloc[0] == 1.0
    assert 0 <= f["workload_index"].iloc[0] <= 100


def test_workload_rises_with_load():
    lo, _ = cleaner.clean(base_rows(3, occupied_beds=["10"] * 3, avg_wait_min=["10"] * 3, doctors_available=["8"] * 3))
    hi, _ = cleaner.clean(base_rows(3, occupied_beds=["39"] * 3, avg_wait_min=["10"] * 3, doctors_available=["2"] * 3))
    assert features.compute_features(hi)["workload_index"].mean() > features.compute_features(lo)["workload_index"].mean() + 20


def test_no_beds_or_staff_gives_missing_not_infinite_ratios():
    d = base_rows(2, department="OPD", total_beds=["0", "0"], occupied_beds=["0", "0"], available_beds=["0", "0"], doctors_available=["0", "5"])
    f = features.compute_features(cleaner.clean(d)[0])
    assert f["bed_occupancy_pct"].isna().all()
    assert np.isinf(f.select_dtypes("number").to_numpy()).sum() == 0
    assert pd.isna(f["patients_per_doctor"].iloc[0]) and f["patients_per_doctor"].iloc[1] == 2.0


def test_idle_department_has_zero_workload():
    d = base_rows(2, department="OPD", total_beds=["0"] * 2, occupied_beds=["0"] * 2, available_beds=["0"] * 2,
                  arrivals=["0", "20"], doctors_available=["0", "5"], nurses_available=["0", "5"], avg_wait_min=["0", "20"])
    f = features.compute_features(cleaner.clean(d)[0])
    assert f["workload_index"].iloc[0] == 0.0 and f["workload_index"].iloc[1] > 0


def test_peak_hours_are_top_quarter_of_hours():
    hours = list(range(24))
    arr = [str(5 + (20 if h in (9, 10, 11, 18, 19, 20) else 0)) for h in hours]
    d = base_rows(24, arrivals=arr, time=[f"{h:02d}:00" for h in hours])
    f = features.compute_features(cleaner.clean(d)[0])
    clean, _ = cleaner.clean(d)
    peak_hours = sorted(clean.loc[f["is_peak_hour"], "timestamp"].dt.hour.tolist())
    assert peak_hours == [9, 10, 11, 18, 19, 20]


def test_daily_data_has_no_peak_flags():
    d = base_rows(5, time=["00:00"] * 5, date=[f"2026-01-0{i + 1}" for i in range(5)])
    clean, rep = cleaner.clean(d)
    assert rep["granularity"] == "daily"
    assert not features.compute_features(clean)["is_peak_hour"].any()


def test_busy_hours_in_sparse_departments_are_not_clipped():
    """Regression: a department that mostly sees 0-1 admissions per hour must keep its legitimate 3-5 peaks."""
    n = 240
    adm = ["0"] * n
    for i in range(0, n, 12):
        adm[i], adm[i + 1] = "3", "5"
    d = base_rows(n, admissions=adm, arrivals=["6"] * n, time=[f"{i % 24:02d}:00" for i in range(n)],
                  date=[f"2026-01-{1 + i // 24:02d}" for i in range(n)])
    df, rep = cleaner.clean(d)
    assert "admissions" not in rep["outliers_clipped"]
    assert df["admissions"].max() == 5
