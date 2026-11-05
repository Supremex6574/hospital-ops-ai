# Demo script (about 10 minutes)

Prepare: start backend and frontend (see README), log in, **Data Upload → Load sample dataset**.

1. **Dashboard** (1 min): KPIs and trends are relative to the newest hour in the data. Point out the disclaimer in the sidebar.
2. **Patient Flow → Resource Utilization** (2 min): choose *All data* and *90 days*; show the unusual days and the department comparison. Switch a chart to its table view.
3. **Bottlenecks** (1 min): which department is under strain now and for how long.
4. **Forecasting** (1.5 min): winner versus baseline, error table, the 80 % range. Explain why R² is near zero.
5. **AI Insights** (1 min): the drivers behind the forecast. State that this explains the model, not the cause.
6. **Recommendations** (1 min): evidence and estimated effect; accept one, dismiss one.
7. **What-if** (1.5 min): quick start *Busy period*, run, read "What changes"; then add 40 beds in General Ward and rerun.
8. **Optimization** (1 min): Beds, then Doctors; use *Test this plan in What-if*.
9. **Alerts & Monitoring** (1.5 min): **Surge for 4 hours** on Emergency, then **Start** the stream (Fast). Watch the new hours, the bell and the alert list update. Stop.
10. **Integration** (optional, API docs at `/docs`): post `GET /integration/sample` output to `POST /integration/feed`; try a payload with a `patient_id` field and show it being rejected.

Questions to expect, with short answers:
- *Is the data real?* No, synthetic with a fixed seed; the generator also records the true surge days so detection is validated.
- *Why not deep learning?* Short daily series with weekly seasonality: simple models beat or match complex ones, and they are explainable.
- *What would change for a real hospital?* Replace the generator with real exports through the adapters, review planning norms, add roles and an audit log.
