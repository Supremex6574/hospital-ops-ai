# Smart Hospital Operations & Decision Support System
Design package: architecture, structure, schema, APIs, ML, UI, phases

Pipeline: **Analyze → Predict → Explain → Simulate → Optimize → Recommend → Monitor**

---

## 1. Architecture

### Stack (final choices)
| Layer | Choice | Why |
|---|---|---|
| Frontend | React (Vite) + Tailwind + Recharts | Fast to build, professional look, good charts/heatmap support |
| Backend | FastAPI (Python) | Auto-generated API docs (great for demo/viva), async, Pydantic validation |
| Data/ML | Pandas, NumPy, scikit-learn, SHAP, Prophet (optional, falls back to sklearn) | As specified |
| DB | PostgreSQL (SQLite for dev via SQLAlchemy, no code change) | As specified |
| Auth | JWT (python-jose) + bcrypt, role: admin | Simple and secure |
| Real-time | Polling every 5-10 s (upgrade path: WebSocket/SSE) | Reliable, simple to demo |
| Simulated streams | Background generator thread/script posting to the same ingestion API | Same pipeline as real HIS/IoT |

### Layered view
```
[React Admin UI]  <--REST/JSON + JWT-->  [FastAPI]
                                            |
   routers (thin)  ->  services (logic)  ->  repositories (SQLAlchemy)  ->  PostgreSQL
                                            |
                         ┌──────────────────┼───────────────────┐
                    ingestion/          analytics/            ml/
                  (validate, clean,   (flow, utilization,   (features, train,
                   features, adapters) bottlenecks)          forecast, SHAP)
                                            |
                         decision/  (optimizer, recommender, simulator, alerts)
```

### Key design decisions
1. **Single canonical table** (`hospital_data`): every source (CSV, EHR-like, HIS, IoT) is converted by an *adapter* into the same hourly/department-level schema. This is how you demonstrate EHR/HIS/IoT integration at the data level without building an EMR.
2. **Rules + ML, not ML alone.** Bottlenecks, recommendations and the optimizer are transparent rule/analytical engines that consume ML forecasts. This makes explanations defensible in a viva.
3. **Explainability is stored, not recomputed:** SHAP values for each forecast are saved with the forecast row.
4. **Config-driven thresholds** (occupancy 85%/90%, wait time, staff ratios) in a `settings` table so the admin can tune them.
5. **No PII anywhere:** the schema has no name/phone/address columns; upload validation rejects files containing such column names.

---

## 2. Folder Structure
```
hospital-ops-ai/
├── README.md
├── docker-compose.yml              # postgres + backend + frontend (optional)
├── data/
│   ├── synthetic/                  # generated sample datasets
│   ├── uploads/                    # validated uploaded files
│   └── generate_synthetic.py       # realistic data generator (seasonality, spikes)
├── backend/
│   ├── requirements.txt
│   ├── .env.example
│   ├── app/
│   │   ├── main.py                 # FastAPI app, CORS, router registration
│   │   ├── config.py               # settings (DB URL, JWT secret, thresholds)
│   │   ├── database.py             # engine, session
│   │   ├── models/                 # SQLAlchemy ORM models (one file per table group)
│   │   ├── schemas/                # Pydantic request/response models
│   │   ├── routers/
│   │   │   ├── auth.py
│   │   │   ├── data.py             # upload, validate, stats
│   │   │   ├── dashboard.py
│   │   │   ├── patient_flow.py
│   │   │   ├── resources.py
│   │   │   ├── bottlenecks.py
│   │   │   ├── forecasting.py
│   │   │   ├── explain.py
│   │   │   ├── recommendations.py
│   │   │   ├── simulation.py
│   │   │   ├── optimization.py
│   │   │   ├── alerts.py
│   │   │   └── ingest.py           # EHR/HIS/IoT/stream endpoints
│   │   ├── services/
│   │   │   ├── ingestion/
│   │   │   │   ├── validator.py    # file type, size, columns, PII check
│   │   │   │   ├── cleaner.py      # missing, duplicates, dtypes, outliers
│   │   │   │   ├── features.py     # derived KPIs
│   │   │   │   └── adapters.py     # csv_adapter, ehr_adapter, his_adapter, iot_adapter
│   │   │   ├── analytics/
│   │   │   │   ├── patient_flow.py
│   │   │   │   ├── utilization.py
│   │   │   │   └── bottlenecks.py  # thresholds + z-score / rolling anomaly
│   │   │   ├── ml/
│   │   │   │   ├── feature_engineering.py  # lags, rolling, calendar
│   │   │   │   ├── train.py        # model comparison + selection
│   │   │   │   ├── forecast.py     # recursive multi-step forecast
│   │   │   │   └── explain.py      # SHAP + natural-language text
│   │   │   ├── decision/
│   │   │   │   ├── recommender.py  # rule engine
│   │   │   │   ├── optimizer.py    # staff/bed reallocation
│   │   │   │   ├── simulator.py    # what-if
│   │   │   │   └── alerts.py
│   │   │   └── streaming/
│   │   │       └── simulator_stream.py  # simulated real-time + IoT generator
│   │   ├── security/               # jwt, hashing, dependencies (get_current_admin)
│   │   └── utils/
│   ├── ml_artifacts/               # saved models (.joblib), metrics.json
│   └── tests/                      # pytest per service
└── frontend/
    ├── package.json
    └── src/
        ├── main.jsx, App.jsx, routes.jsx
        ├── api/                    # axios client + per-module api files
        ├── context/                # AuthContext, FilterContext (date range, department)
        ├── components/
        │   ├── layout/             # Sidebar, Topbar, PageShell
        │   ├── common/             # KpiCard, Loader, EmptyState, ErrorBanner, FilterBar
        │   ├── charts/             # LineChart, BarChart, Heatmap, ForecastChart, ShapChart
        │   └── cards/              # AlertCard, RecommendationCard
        ├── pages/
        │   ├── Login.jsx
        │   ├── Dashboard.jsx
        │   ├── DataUpload.jsx
        │   ├── PatientFlow.jsx
        │   ├── ResourceUtilization.jsx
        │   ├── Bottlenecks.jsx
        │   ├── Forecasting.jsx
        │   ├── AIInsights.jsx
        │   ├── Recommendations.jsx
        │   ├── WhatIf.jsx
        │   ├── Optimization.jsx
        │   └── Alerts.jsx
        └── hooks/                  # usePolling, useFilters
```

---

## 3. Database Schema (PostgreSQL, normalized)

```
users(id PK, username UNIQUE, password_hash, role, created_at, last_login)

departments(id PK, name UNIQUE, type  -- ED/OPD/ICU/Ward/Lab/Pharmacy
            , total_beds, is_active)

hospital_data(id PK, timestamp, department_id FK, 
              arrivals, admissions, discharges, 
              avg_wait_min, avg_los_hours,
              total_beds, occupied_beds, available_beds,
              doctors_available, nurses_available,
              appointments_scheduled, appointments_completed,
              lab_tests_ordered, lab_capacity, equipment_available, equipment_total,
              source           -- csv | ehr | his | iot | stream
              , upload_id FK NULL)
  UNIQUE(timestamp, department_id, source)   -- duplicate protection
  INDEX(timestamp), INDEX(department_id, timestamp)

derived_metrics(id PK, hospital_data_id FK UNIQUE,
                bed_occupancy_pct, resource_util_pct, 
                patients_per_doctor, patients_per_nurse,
                workload_index, equipment_util_pct, lab_util_pct,
                is_peak_hour)

uploads(id PK, user_id FK, filename, uploaded_at, rows_total, rows_valid,
        rows_dropped, duplicates_removed, missing_filled, status, report_json)

resources(id PK, department_id FK, resource_type  -- bed/doctor/nurse/lab/equipment
          , capacity, unit)
staff(id PK, department_id FK, role -- doctor/nurse, shift, headcount)  -- aggregate, no individuals
beds(id PK, department_id FK, bed_type, status -- occupied/free/maintenance, updated_at)

patient_flow(id PK, timestamp, department_id FK, stage 
             -- registration/waiting/consultation/lab/pharmacy/discharge
             , patients_in_stage, avg_stage_time_min)

iot_readings(id PK, timestamp, device_type -- bed_sensor/room_sensor/equipment/env
             , department_id FK, device_id, value, unit, status)

model_results(id PK, target -- admissions|bed_occupancy, model_name, 
              mae, rmse, r2, mape, trained_at, is_selected BOOL, params_json, artifact_path)

forecasts(id PK, target, department_id FK NULL, forecast_time, horizon_h,
          predicted_value, lower_ci, upper_ci, model_id FK, shap_json, created_at)

recommendations(id PK, created_at, department_id FK NULL, category, 
                priority -- low/med/high/critical, text, rationale, trigger_rule, status)

alerts(id PK, created_at, department_id FK NULL, type, severity, message,
       metric_value, threshold, acknowledged BOOL, acknowledged_by FK NULL)

simulation_results(id PK, user_id FK, created_at, params_json, baseline_json, 
                   result_json, recommended_action)

settings(key PK, value, description)   -- thresholds
```

---

## 4. Data Flow

```
Upload (CSV/XLSX)                       Stream / IoT / HIS / EHR-like
        │                                          │
        ▼                                          ▼
 1. validator   (ext, size ≤10MB, required cols, PII-column rejection)
        │
 2. adapter     (map source columns → canonical schema)
        │
 3. cleaner     (dtypes, parse dates, drop exact dupes, fill missing:
        │        ffill within dept for counts, median for ratios; clip outliers;
        │        enforce occupied ≤ total beds, available = total − occupied)
        │
 4. features    (occupancy %, utilization %, patients/doctor, patients/nurse,
        │        workload index, peak-hour flag, day-of-week, trend)
        │
 5. store       → hospital_data + derived_metrics + uploads(report)
        │
        ├──► analytics (flow, utilization, bottlenecks) ──► alerts
        ├──► ml (retrain on demand / predict) ──► forecasts + SHAP
        └──► decision (recommender, optimizer, simulator) ──► recommendations
                                   │
                          REST API ──► React dashboard (polling)
```

**Workload index** (one transparent formula used everywhere):
`workload = 0.4·bed_occupancy + 0.3·min(patients/doctor ÷ norm, 1.5)/1.5 + 0.2·nurse_load + 0.1·wait_norm`
(weights live in settings so you can justify and tune them).

---

## 5. API Design (all under `/api/v1`, JWT required except login)

| Module | Endpoints |
|---|---|
| Auth | `POST /auth/login`, `GET /auth/me` |
| Data | `POST /data/upload`, `GET /data/uploads`, `GET /data/uploads/{id}/report`, `GET /data/stats`, `GET /data/preview`, `DELETE /data/uploads/{id}` |
| Dashboard | `GET /dashboard/kpis`, `GET /dashboard/summary?from&to&dept` |
| Patient flow | `GET /flow/timeseries`, `GET /flow/by-department`, `GET /flow/stages`, `GET /flow/peak-heatmap`, `GET /flow/anomalies` |
| Resources | `GET /resources/beds`, `/doctors`, `/nurses`, `/lab`, `GET /resources/compare` |
| Bottlenecks | `GET /bottlenecks/current`, `GET /bottlenecks/history` |
| Forecast | `POST /forecast/train?target=`, `GET /forecast/models`, `GET /forecast/{target}?horizon=&dept=` |
| XAI | `GET /explain/{forecast_id}`, `GET /explain/global/{target}` |
| Recs | `GET /recommendations`, `POST /recommendations/generate`, `PATCH /recommendations/{id}` |
| What-if | `POST /simulation/run`, `GET /simulation/history` |
| Optimize | `POST /optimization/run`, `GET /optimization/latest` |
| Alerts | `GET /alerts`, `PATCH /alerts/{id}/ack` |
| Ingest | `POST /ingest/ehr`, `POST /ingest/his`, `POST /ingest/iot`, `POST /stream/start`, `POST /stream/stop`, `GET /stream/status` |

Common query params: `from`, `to` (ISO dates), `department_id`. Errors use a uniform `{error, detail, code}` body.

Example what-if request:
```json
POST /simulation/run
{ "department_id": null, "arrivals_change_pct": 20, "beds_change": 0,
  "doctors_change": 0, "nurses_change": 0, "discharge_rate_change_pct": 0 }
```

---

## 6. ML Pipeline

**Targets:** (A) daily/hourly admissions, (B) bed occupancy % (hospital-wide and per department).

1. **Data prep:** aggregate to the chosen grain (daily for the main models; hourly for peak-hour views). Time-ordered split: first 70% train, next 15% validation, last 15% test. Never shuffle.
2. **Features (no leakage, lagged only):**
   - Lags: t-1, t-2, t-7 (daily) ; rolling mean/std (3, 7 days) ; trend (7-day slope)
   - Calendar: day-of-week, month, weekend, holiday flag
   - Operational: previous occupancy, discharge rate, avg LOS, staff counts, wait time
3. **Models (kept small):**
   - Linear Regression (baseline)
   - Random Forest
   - Gradient Boosting (sklearn `GradientBoostingRegressor`)
   - Prophet (time-series; trend + weekly seasonality), skipped automatically if not installed
4. **Evaluation:** MAE, RMSE, R², MAPE on the test set + `TimeSeriesSplit` CV on train. Winner chosen by lowest RMSE (ties by MAPE). All results saved to `model_results`, shown as a comparison table + bar chart.
5. **Forecasting:** recursive multi-step (next 7 days / 24-72 h). Prediction interval from residual quantiles on validation. Occupancy clipped to [0, 100].
6. **Shortage detection:** forecast occupancy > threshold → creates alert/recommendation.
7. **Explainability:** `shap.TreeExplainer` on the selected tree model (global summary + per-prediction waterfall). Linear/Prophet fall back to coefficients/components. A **template-based NLG** step turns the top-4 SHAP contributions into text, e.g.:
   > "Predicted occupancy of 91% is mainly driven by: higher admissions over the last 3 days (+4.2 pts), high current occupancy (+3.1), lower discharge rate (+2.0), rising 7-day trend (+1.1)."
8. **Persistence:** `joblib` artifacts + `metrics.json`; retrain via API; synthetic data guarantees reproducible results (fixed seed).

---

## 7. UI / Page Structure

Layout: left **sidebar** (12 items, icons), **top bar** (global date-range picker, department selector, live-status badge, alert bell, user menu). Healthcare palette: teal/blue primary, white cards, red/amber/green for severity. Every page has loading skeletons, empty states, and error banners.

| # | Page | Content |
|---|---|---|
| 1 | Login | Branded form, validation, error messages |
| 2 | Dashboard | 8 KPI cards (patients, admissions, discharges, occupancy %, wait time, top workload dept, available beds, utilization); patient-flow line, admit/discharge trend, dept workload bar, occupancy gauge/chart, utilization chart, wait-time chart, forecast chart, peak-hour heatmap, alert list, top recommendations |
| 3 | Data Upload | Drag-drop, validation report (missing/dupes/type fixes), dataset stats, preview table, upload history, "load sample dataset" button |
| 4 | Patient Flow | Stage funnel (Registration → … → Discharge), arrivals over time, dept flow comparison, LOS, wait, peak heatmap, anomaly markers |
| 5 | Resource Utilization | Tabs: Beds / Doctors / Nurses / Lab-Equipment; dept comparison table with color-coded utilization |
| 6 | Bottlenecks | Live list of detected bottlenecks by severity and department with the metric vs threshold |
| 7 | Forecasting | Target + horizon selector, forecast chart with CI band, model comparison table (MAE/RMSE/R²/MAPE), selected-model badge, "Retrain" button, **"Why this prediction?"** button |
| 8 | AI Insights | SHAP global bar, per-prediction contribution chart, plain-English explanation |
| 9 | Recommendations | Priority-sorted cards (category, text, rationale, trigger), status (new/accepted/dismissed) |
| 10 | What-if | Sliders (arrivals %, beds, doctors, nurses, discharge rate, dept capacity); side-by-side Current vs Scenario (workload, occupancy, congestion, shortage) + recommended action |
| 11 | Optimization | Surplus→deficit staff/bed transfer suggestions, before/after workload balance chart |
| 12 | Alerts/Monitoring | Live feed (auto-refresh), severity filter, acknowledge, stream start/stop control, IoT device status panel |

---

## 8. Core Logic Notes (so the "intelligent" parts are clear)

**Bottleneck rules (all thresholds configurable):**
- Occupancy ≥ 85% warning, ≥ 90% critical
- Wait time > mean + 1.5σ of the same dept/hour-of-week baseline
- Patients per doctor/nurse above department norm
- Arrivals growth: 3-hour rolling mean > 1.3× baseline, or z-score > 2.5
- Lab: tests ordered / capacity > 90%

**Recommender:** rule table `(condition → text, priority, category)` fed by current analytics + forecasts. All text is operational only, with a guard list so no clinical wording is ever emitted.

**What-if simulator (analytical):**
- New arrivals = base × (1+Δ)
- Expected census (Little's Law) = arrivals × LOS
- New occupancy = census ÷ (beds + Δbeds), adjusted by the discharge-rate change
- Doctor/nurse load = new arrivals ÷ staff; wait time via scaling by utilization (simple M/M/c-style approximation or linear load factor)
- Output: shortage flags + recommended action from the same rule engine

**Optimizer:** for each department compute surplus/deficit of staff against norm-based demand; solve with a simple greedy transfer (largest deficit ← largest surplus, respecting minimum staffing), with an optional `scipy.optimize.linprog` variant. Output: transfers, expected workload variance reduction.

**Simulated real-time + IoT:** a background task generates a new record per department every N seconds (using the learned hourly/weekly pattern + noise + occasional surge events), and emits IoT readings (bed sensors, equipment status, room occupancy). Both enter through `/ingest/*` → same cleaner → same DB, so the dashboard updates identically to real data.

**Security:** bcrypt password hashing, JWT expiry, role dependency on every router, upload extension/size/MIME checks, column whitelist + PII-column rejection, Pydantic validation, parameterized queries (SQLAlchemy), no sensitive data in logs, rate-limit on login, CORS restricted. Footer disclaimer: *academic operational analytics prototype, not a clinical system*.

---

## 9. Development Phases (module by module, test before moving on)

| Phase | Module | Deliverable | Done when |
|---|---|---|---|
| 0 | Setup + synthetic data | Repo, venv, DB, `generate_synthetic.py` (≈1 year, 6 departments, hourly) | Sample CSV generated, loads in pandas |
| 1 | Auth + app shell | Login, JWT, sidebar layout, filter bar | Protected routes work |
| 2 | **Data upload & preprocessing** (MUST) | Validate/clean/feature pipeline, report, stats page | Bad files give clear errors; clean data stored |
| 3 | **Dashboard KPIs** (MUST) | KPI endpoints + cards + core charts | Matches pandas-computed values |
| 4 | **Patient flow + Resource utilization** (MUST) | Both pages + APIs | Dept comparison correct |
| 5 | **Bottleneck detection + Alerts** (MUST/SHOULD) | Rules, anomaly flags, alerts feed | Seeded surge triggers alert |
| 6 | **Forecasting + model evaluation** (MUST) | Training, comparison table, forecast chart | Best model chosen; metrics displayed |
| 7 | **SHAP / XAI** (MUST) | Global + local explanation + NLG | "Why this prediction?" works |
| 8 | **Recommendation engine** (MUST) | Rules + cards | Recs trace to triggers |
| 9 | What-if simulation (SHOULD) | Page + simulator | 20% arrivals scenario matches hand calc |
| 10 | Optimization (SHOULD) | Reallocation suggestions | Surplus→deficit transfers sensible |
| 11 | Near-real-time + EHR/HIS adapters (SHOULD) | Stream generator, polling, adapters | Dashboard updates live |
| 12 | IoT layer (ADVANCED) | Sensor simulator + device panel | Readings flow into analytics |
| 13 | Polish + docs + demo | UI polish, README, demo script, report diagrams | Full 18-step demo runs end-to-end |

**Suggested 2-person split:**
- *Member A (data/ML):* Phases 0, 2, 5, 6, 7, 9, 10, simulation engine, data generator
- *Member B (full-stack):* Phases 1, 3, 4, 8, 11, 12, all React pages, auth, DB models
- Shared: API contract (agree on the endpoint list above first), testing, report and demo

**Fallbacks (project still works if time runs out):** Prophet → drop (3 sklearn models suffice); IoT → generator only; optimizer → greedy only; real-time → manual "refresh" button; Postgres → SQLite.

---

## 10. Decisions I need from you before Phase 0

1. **Data:** use my synthetic generator (recommended; fully reproducible) or do you have a public dataset (e.g. Kaggle hospital admissions) to adapt?
2. **Database:** start on SQLite and switch to PostgreSQL later, or PostgreSQL from day one?
3. **Frontend:** React (recommended) or plain HTML/JS to reduce complexity?
4. **Departments:** default set is Emergency, OPD, ICU, General Ward, Pediatrics, Surgery (+ Lab as a resource). OK, or do you want changes?
5. **Environment:** Windows/macOS/Linux, and is Docker available?

Once you confirm (or just say "go with the recommended"), I will build **Phase 0 + Phase 1**: the repository skeleton, synthetic data generator, DB models, and login with the app shell. I will run and test them before moving on.
