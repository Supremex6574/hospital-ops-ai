# Smart Hospital Operations & Decision Support System

**AI-Powered Hospital Resource Utilization and Patient Flow Analytics with Intelligent Decision Support**

An academic prototype (final-year CSE project) that follows one pipeline:
**Analyze → Predict → Explain → Simulate → Optimize → Recommend → Monitor.**

> **Academic prototype. Not a clinical system.** It works on hospital *operations* only: patient flow, beds, staff,
> labs, equipment, waiting times. There is no diagnosis, treatment advice, prescription, billing or patient-identifiable
> data anywhere. All bundled data is synthetic. Every page carries this disclaimer.

## What it does

| Stage | Pages / modules |
|---|---|
| Data in | CSV/Excel upload with validation, privacy check and cleaning report; EHR event feed, HIS snapshots, IoT sensor readings (API); simulated live stream |
| Analyze | Dashboard (8 KPIs, 6 charts, peak-hour heatmap), Patient Flow (surge detection), Resource Utilization (beds, doctors, nurses, lab & equipment), Bottlenecks |
| Predict | Forecasting: 7-day admissions and bed occupancy, 5 models compared (MAE, RMSE, R², MAPE) with an 80% range |
| Explain | AI Insights: SHAP drivers of each forecast, grouped into weekday, history, recent, season, trend |
| Simulate | What-if: change arrivals, length of stay, beds, doctors, nurses and see occupancy, waiting time and workload |
| Optimize | Rebalance beds, doctors or nurses across departments so the busiest hours are equally tight |
| Recommend | Rule-based operational actions with evidence, estimated effect and accept / dismiss |
| Monitor | Alerts with editable thresholds, plus a simulated live stream that keeps the alerts current |

Details of every method: [`docs/METHODS.md`](docs/METHODS.md). Demo walk-through: [`docs/DEMO.md`](docs/DEMO.md).
Original design: [`hospital_ops_design.md`](hospital_ops_design.md).

## Run it
Full step-by-step guide with Windows commands and troubleshooting: [`docs/SETUP.md`](docs/SETUP.md). Short version:

```bash
# 1. Sample data (52,560 hourly rows, 6 departments, fixed seed)
python data/generate_synthetic.py

# 2. Backend  (http://127.0.0.1:8000, interactive API docs at /docs)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # then set SECRET_KEY
python -m uvicorn app.main:app --reload --port 8000

# 3. Frontend (http://localhost:5173, proxies /api to the backend)
cd frontend
npm install
npm run dev
```

Log in with `admin` / `Admin@123` (created on first start; change it in `.env` before any real use), open
**Data Upload** and click **Upload dataset** (or **Load sample dataset**). Every other page then has data.

## Tests
```bash
cd backend && python -m pytest -q        # about 190 tests, ~2 minutes
cd frontend && npm run build             # production build check
```

## Architecture

```
React (Vite, Tailwind, Recharts)  ──/api/v1──▶  FastAPI  ──▶  SQLAlchemy  ──▶  SQLite (PostgreSQL via DATABASE_URL)
                                                  │
                    services/ingestion   upload, EHR, HIS, IoT adapters → clean → derived metrics → hourly table
                    services/analytics   dashboard, flow, resources, bottlenecks, alerts
                    services/ml          forecasting (5 models, rolling backtest), SHAP explanations
                    services/decision    recommendations, what-if simulation, optimization
                    services/streaming   simulated live stream
```

Every source is turned into one canonical **hourly, department-level table** (`hospital_data` plus `derived_metrics`),
so every analysis works on any source. "Today" always means the newest hour in the data, not the wall clock.

## Security and privacy
- Login with JWT; every data route requires the admin role. Failed logins are throttled.
- Uploads are checked for type, size, row limits and personal data (identifier-like column names, e-mails, phone numbers).
- The EHR / HIS / IoT feeds have no field for a patient identifier and reject unknown fields. Validation errors never echo the submitted values.
- Nothing sensitive is written to logs or kept in the browser beyond the session token (session storage).
- Planning norms (patients per doctor and nurse) are assumptions in `backend/app/config.py`, not clinical standards.

## Known limits (be upfront about these in a viva)
- All data is synthetic; accuracy numbers describe the generator as much as any hospital.
- Forecast R² is near zero by construction: 7-day-ahead daily values with unforeseeable surges. Models are judged against a seasonal-naive baseline and by MAE / MAPE.
- SHAP explains what the *model* relies on, not what causes admissions.
- What-if and optimization are planning estimates under stated assumptions (shown on the page), not predictions.
- A feed hour must not already exist from another source; the API refuses overlaps (HTTP 409) rather than double counting.
- The live stream is in memory and meant for a single server process.
- Single role (admin). Role-based access for more users is a natural extension.

## Status
| Phase | Module | State |
|---|---|---|
| 0 | Repo + synthetic data generator | Done |
| 1 | Auth (JWT) + app shell + global filters | Done |
| 2 | Data upload, validation, cleaning, derived features | Done |
| 3 | Dashboard: 8 KPIs, 6 charts, peak-hour heatmap | Done |
| 4 | Patient flow + resource utilization | Done |
| 5 | Bottleneck detection, alerts, editable thresholds | Done |
| 6 | Admission and bed-occupancy forecasting with model comparison | Done |
| 7 | Explainable AI (SHAP) | Done |
| 8 | Recommendation engine | Done |
| 9 | What-if simulation | Done |
| 10 | Optimization | Done |
| 11 | Simulated live stream, EHR event + HIS snapshot feeds | Done |
| 12 | IoT sensor feed, documentation, demo script | Done |

## Database
SQLite by default (`backend/hospital_ops.db`, created automatically).
For PostgreSQL set `DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/hospital_ops`
and `pip install psycopg2-binary`. No code changes needed.

## Generated test files (`data/synthetic/`)
- `hospital_operations.csv` clean upload-ready dataset
- `surge_events.csv` ground-truth surge episodes (to validate anomaly detection)
- `messy_sample.csv` missing values, duplicates, bad types, impossible values (to test the cleaner)
- `pii_sample.csv` contains a forbidden PII column (to test upload rejection)

## API overview (all under `/api/v1`, bearer token except login and health)
| Area | Endpoints |
|---|---|
| Auth | `POST /auth/login`, `GET /auth/me` |
| Data | `POST /data/upload`, `/data/load-sample`, `GET /data/preview`, `/data/stats`, `/data/template`, `/data/uploads`, `DELETE /data/uploads/{id}` |
| Analytics | `GET /dashboard/kpis`, `/dashboard/summary`, `/flow/overview`, `/resources/compare`, `/resources/{beds\|doctors\|nurses\|lab}`, `/bottlenecks` |
| Alerts | `GET /alerts`, `/alerts/summary`, `POST /alerts/scan`, `/alerts/{id}/acknowledge`, `/alerts/acknowledge-all`, `GET/PUT /settings/thresholds` |
| Forecast and explain | `GET /forecast/overview`, `POST /forecast/retrain`, `GET /explain/forecast` |
| Decisions | `GET /recommendations`, `POST /recommendations/refresh`, `PATCH /recommendations/{id}`, `POST /simulation/run`, `GET /simulation/baseline`, `/simulation/history`, `POST /optimization/run` |
| Integration | `POST /integration/feed` (EHR events, HIS snapshots), `POST /integration/iot`, `GET /integration/sources`, `/integration/sample`, `/integration/iot-sample` |
| Stream | `GET /stream/status`, `POST /stream/start`, `/stream/stop`, `/stream/step`, `/stream/surge` |
