# Methods

Everything is deliberately simple and explainable. Numbers such as thresholds and planning norms are settings or
assumptions, never hidden constants.

## Data pipeline
Upload → type/size/row checks → privacy check (identifier-like columns, e-mails, phone numbers) → column-name mapping
(synonyms) → cleaning (types, negatives, duplicates, missing values, impossible values, each counted in a report) →
derived metrics (occupancy %, patients per doctor and nurse, lab and equipment utilisation, workload index, peak hour) →
hourly department table. Rows from the same source and hour are replaced, never duplicated.

## Analytics
- **Hospital occupancy** counts only departments with beds (OPD has none). **Waiting time** is weighted by arrivals.
- **Surge days** (Patient Flow): compare each day with the median of the same weekday over ±4 weeks; flag when the robust z-score of the log ratio is ≥ 2.5 and the ratio ≥ 1.15. On the synthetic ground truth: 20 of 22 flagged days are real surges (precision), 20 of 25 real surge days found (recall).
- **Bottleneck rules** (thresholds editable on the Alerts page): occupancy ≥ 85 / 90 %, waiting time z ≥ 1.5 *and* ≥ 1.25× the same weekday-hour median, arrivals over 3 h ≥ 1.3× typical, doctors/nurses load ≥ 130 / 150 % of the planning norm, lab ≥ 90 / 100 % of capacity. Severity: normal, warning, critical.

## Forecasting
Daily admissions and mean bed occupancy, 7 days ahead. Features known a week ahead: weekday, season (sin/cos), trend,
lags 7/14/21/28, their median, rolling 7/28-day means. Five models: seasonal naive, 7-day moving average, ridge,
random forest, gradient boosting. Rolling-origin backtest (up to 4 folds of 28 days), winner chosen by RMSE, refit on all
data. The 80 % range comes from backtest error percentiles. R² is reported but is near zero by design (see the page).

## Explainability
SHAP (TreeExplainer; LinearExplainer for ridge), values grouped into weekday, history, recent level, season and trend.
Additivity (base + contributions = prediction) is checked in the tests. It explains the model, not causality.

## Recommendations
Transparent rules over the bottleneck, forecast and pattern results: beds now / forecast, arrival surge, waiting time,
doctor and nurse load (with a staff-transfer calculation from departments with spare capacity), lab overload, daily
pattern, admissions forecast, hospital-wide surge. Priority comes from severity and how sustained the condition is
(≥ 3 of the last 6 hours); confidence is high (measured) or medium (forecast/pattern). Items are upserted by
`rule:department` and can be accepted, dismissed or auto-resolved.

## What-if simulation
Baseline = last 28 days. Bed census scales with arrivals × length of stay (Little's law); occupancy is capped at 100 %
and the excess is reported as patients without a bed. Staff load = patients per doctor / nurse against the planning norm.
Waiting time = baseline × (staff-load ratio)^b1 × (bed-pressure ratio)^b2, with b1 and b2 fitted per department by
log-log regression on its own history (clipped to 0..2.5; a floor of 0.3 on the staff effect where staffing and census
cannot be separated; defaults when history is short).

## Optimization
Goal: minimise the highest busy-hour pressure (95th-percentile load ÷ capacity at the planning norm). Greedy marginal
allocation is optimal for this integer min-max problem. Beds move only between ward-type departments; staff pools are
what is on duty now plus any extra, within a ± change limit, never leaving a quiet hour empty. Each plan is then run
through the what-if engine so its effect is measured the same way.

## Live stream, EHR, HIS, IoT
- **Stream:** each tick builds the next hour per department from the same weekday-hour in recent weeks with variation, carries the bed census smoothly, stores it through the normal pipeline and re-scans alerts. A surge can be injected for demonstrations.
- **EHR events:** arrival / admission / discharge events (with wait and length of stay) → hourly counts and means.
- **HIS snapshots:** beds, staff on duty, lab, equipment per department-hour.
- **IoT:** the last reading per device per hour. Bed sensors give occupied and total (sensored) beds, equipment sensors give total and idle, footfall sensors sum to arrivals. Partial sensor coverage understates capacity.
