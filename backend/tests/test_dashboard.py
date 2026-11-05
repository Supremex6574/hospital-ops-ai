"""Dashboard KPIs and chart series, checked against values computed independently with pandas."""
import importlib.util
import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import delete

from app.database import SessionLocal
from app.models import DerivedMetric, HospitalData, Upload

API = "/api/v1"
ROOT = Path(__file__).resolve().parents[2]


def _generate(days: int) -> pd.DataFrame:
    spec = importlib.util.spec_from_file_location("gen_dash", ROOT / "data" / "generate_synthetic.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gen_dash"] = mod
    spec.loader.exec_module(mod)
    return mod.generate("2026-01-01", days, seed=3)[0]


@pytest.fixture(scope="module")
def src() -> pd.DataFrame:
    df = _generate(10)  # 2026-01-01 .. 2026-01-10, hourly, 6 departments
    df["timestamp"] = pd.to_datetime(df["date"] + " " + df["time"])
    return df


@pytest.fixture()
def loaded(client, auth_headers, src):
    with SessionLocal() as db:
        db.execute(delete(DerivedMetric)); db.execute(delete(HospitalData)); db.execute(delete(Upload)); db.commit()
    csv = src.drop(columns=["timestamp"]).to_csv(index=False).encode()
    r = client.post(f"{API}/data/upload", headers=auth_headers, files={"file": ("d.csv", csv, "text/csv")})
    assert r.status_code == 201, r.text
    # the cleaner must not have altered this clean file, otherwise comparisons below would be meaningless
    assert r.json()["report"]["rows_valid"] == len(src) and r.json()["report"]["missing_filled"] == 0
    assert not r.json()["report"]["outliers_clipped"]
    return src


def get(client, headers, path, **params):
    r = client.get(f"{API}/dashboard/{path}", headers=headers, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def window(df, a, b):
    return df[(df.timestamp >= a) & (df.timestamp < pd.Timestamp(b) + pd.Timedelta(days=1))]


def test_endpoints_require_auth(client):
    for p in ("kpis", "summary"):
        assert client.get(f"{API}/dashboard/{p}").status_code == 401


def test_empty_database_returns_no_data_flag(client, auth_headers):
    with SessionLocal() as db:
        db.execute(delete(DerivedMetric)); db.execute(delete(HospitalData)); db.execute(delete(Upload)); db.commit()
    assert get(client, auth_headers, "kpis")["has_data"] is False
    assert get(client, auth_headers, "summary")["has_data"] is False


def test_kpis_match_pandas(client, auth_headers, loaded):
    src = loaded
    k = get(client, auth_headers, "kpis", **{"from": "2026-01-06", "to": "2026-01-10"})
    cur = window(src, "2026-01-06", "2026-01-10")
    prev = window(src, "2026-01-01", "2026-01-05")
    as_of = cur.timestamp.max()

    assert k["has_data"] and k["as_of_date"] == "2026-01-10" and k["as_of"].startswith("2026-01-10T23")
    assert k["total_patients"]["value"] == cur.arrivals.sum()
    assert k["total_patients"]["previous"] == prev.arrivals.sum()
    assert k["total_patients"]["delta_pct"] == pytest.approx((cur.arrivals.sum() - prev.arrivals.sum()) / prev.arrivals.sum() * 100, abs=0.06)

    day, before = cur[cur.timestamp.dt.date == as_of.date()], cur[cur.timestamp.dt.date == (as_of - pd.Timedelta(days=1)).date()]
    assert k["admissions_today"]["value"] == day.admissions.sum()
    assert k["admissions_today"]["previous"] == before.admissions.sum()
    assert k["discharges_today"]["value"] == day.discharges.sum()

    now = cur[(cur.timestamp == as_of) & (cur.total_beds > 0)]
    assert k["bed_occupancy_pct"]["value"] == pytest.approx(now.occupied_beds.sum() / now.total_beds.sum() * 100, abs=0.06)
    assert k["available_beds"] == {"value": int(now.available_beds.sum()), "total_beds": int(now.total_beds.sum())}

    assert k["avg_wait_min"]["value"] == pytest.approx(np.average(cur.avg_wait_min, weights=cur.arrivals), abs=0.06)
    assert 0 < k["resource_util_pct"]["value"] <= 100
    hw = k["highest_workload"]
    assert hw["department"] in set(src.department) and 0 < hw["workload_index"] <= 100


def test_range_average_occupancy_uses_only_departments_with_beds(client, auth_headers, loaded):
    cur = window(loaded, "2026-01-06", "2026-01-10")
    beds = cur[cur.total_beds > 0].groupby("timestamp")[["occupied_beds", "total_beds"]].sum()
    expected = (beds.occupied_beds / beds.total_beds * 100).mean()
    k = get(client, auth_headers, "kpis", **{"from": "2026-01-06", "to": "2026-01-10"})
    assert k["bed_occupancy_pct"]["range_avg"] == pytest.approx(expected, abs=0.06)


def test_department_filter_scopes_kpis(client, auth_headers, loaded):
    er_id = 1
    k = get(client, auth_headers, "kpis", **{"from": "2026-01-06", "to": "2026-01-10", "department_id": er_id})
    er = window(loaded, "2026-01-06", "2026-01-10")
    er = er[er.department == "Emergency"]
    assert k["total_patients"]["value"] == er.arrivals.sum()
    assert k["highest_workload"]["department"] == "Emergency"
    assert k["available_beds"]["total_beds"] == 40


def test_outpatient_department_has_no_bed_figures(client, auth_headers, loaded):
    opd_id = 2
    k = get(client, auth_headers, "kpis", department_id=opd_id)
    assert k["bed_occupancy_pct"]["value"] is None and k["available_beds"]["value"] is None
    s = get(client, auth_headers, "summary", department_id=opd_id)
    assert s["occupancy"] == []


def test_all_data_range_has_no_previous_period(client, auth_headers, loaded):
    k = get(client, auth_headers, "kpis")
    assert k["total_patients"]["value"] == loaded.arrivals.sum()
    assert k["total_patients"]["previous"] is None and k["total_patients"]["delta_pct"] is None


def test_summary_daily_series_match_pandas(client, auth_headers, loaded):
    s = get(client, auth_headers, "summary", **{"from": "2026-01-03", "to": "2026-01-10"})
    assert s["granularity"] == "daily" and len(s["flow"]) == 8
    cur = window(loaded, "2026-01-03", "2026-01-10")
    daily = cur.groupby(cur.timestamp.dt.date)[["arrivals", "admissions", "discharges"]].sum()
    for row in s["flow"]:
        d = pd.Timestamp(row["t"]).date()
        assert (row["arrivals"], row["admissions"], row["discharges"]) == tuple(int(x) for x in daily.loc[d])

    beds = cur[cur.total_beds > 0].groupby("timestamp")[["occupied_beds", "total_beds"]].sum()
    occ = (beds.occupied_beds / beds.total_beds * 100)
    exp = occ.groupby(occ.index.date).mean()
    for row in s["occupancy"]:
        assert row["occupancy_pct"] == pytest.approx(exp.loc[pd.Timestamp(row["t"]).date()], abs=0.06)

    d1 = cur[cur.timestamp.dt.date == pd.Timestamp("2026-01-05").date()]
    w = next(r for r in s["wait"] if r["t"] == "2026-01-05")["avg_wait_min"]
    assert w == pytest.approx(np.average(d1.avg_wait_min, weights=d1.arrivals), abs=0.06)


def test_short_ranges_switch_to_hourly(client, auth_headers, loaded):
    s = get(client, auth_headers, "summary", **{"from": "2026-01-09", "to": "2026-01-10"})
    assert s["granularity"] == "hourly" and len(s["flow"]) == 48
    assert s["flow"][0]["t"] == "2026-01-09T00:00"


def test_department_comparison_ignores_the_department_filter(client, auth_headers, loaded):
    s = get(client, auth_headers, "summary", department_id=1)
    assert len(s["departments"]) == 6
    assert s["department_id"] == 1
    # but the time series is scoped to the chosen department
    er = loaded[loaded.department == "Emergency"]
    assert sum(r["arrivals"] for r in s["flow"]) == er.arrivals.sum()
    row = next(d for d in s["departments"] if d["department"] == "Emergency")
    assert row["arrivals"] == er.arrivals.sum()
    opd = next(d for d in s["departments"] if d["department"] == "OPD")
    assert opd["bed_occupancy_pct"] is None


def test_heatmap_matches_pandas(client, auth_headers, loaded):
    s = get(client, auth_headers, "summary")
    hm = s["heatmap"]
    assert len(hm["cells"]) == 7 * 24
    per_ts = loaded.groupby("timestamp").arrivals.sum().reset_index()
    per_ts["dow"], per_ts["hour"] = per_ts.timestamp.dt.dayofweek, per_ts.timestamp.dt.hour
    exp = per_ts.groupby(["dow", "hour"]).arrivals.mean()
    for c in hm["cells"]:
        if (c["dow"], c["hour"]) in exp.index:
            assert c["avg_arrivals"] == pytest.approx(exp[(c["dow"], c["hour"])], abs=0.006)
    assert hm["max"] == pytest.approx(exp.max(), abs=0.006)
    # a clear daytime peak: the busiest hour of the day is not in the middle of the night
    busiest_hour = max(hm["cells"], key=lambda c: c["avg_arrivals"] or 0)["hour"]
    assert 7 <= busiest_hour <= 20


def test_invalid_params_rejected(client, auth_headers, loaded):
    r = client.get(f"{API}/dashboard/kpis", headers=auth_headers, params={"from": "2026-02-01", "to": "2026-01-01"})
    assert r.status_code == 422
    assert client.get(f"{API}/dashboard/summary", headers=auth_headers, params={"from": "not-a-date"}).status_code == 422
    assert client.get(f"{API}/dashboard/kpis", headers=auth_headers, params={"department_id": 0}).status_code == 422


def test_range_with_no_rows_reports_no_data(client, auth_headers, loaded):
    assert get(client, auth_headers, "kpis", **{"from": "2030-01-01", "to": "2030-01-31"})["has_data"] is False
    assert get(client, auth_headers, "summary", **{"from": "2030-01-01", "to": "2030-01-31"})["has_data"] is False
