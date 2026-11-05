import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Award, CalendarClock, CheckCircle2, Gauge, RefreshCw, Target, TrendingUp, Upload } from 'lucide-react'
import { getForecast, retrainForecast } from '../api/forecast'
import { errorMessage } from '../api/client'
import { useApi } from '../hooks/useApi'
import { useFilters } from '../context/FilterContext'
import { PageShell } from '../components/common/PageShell'
import KpiCard from '../components/common/KpiCard'
import { EmptyState, ErrorBanner, Spinner } from '../components/common/Feedback'
import ChartCard from '../components/charts/ChartCard'
import DepartmentBars from '../components/charts/DepartmentBars'
import ForecastChart from '../components/charts/ForecastChart'
import { fmtDate, fmtNum } from '../utils/format'

const TARGETS = [{ id: 'admissions', label: 'Admissions' }, { id: 'bed_occupancy', label: 'Bed occupancy' }]
const WEEKDAY = (iso) => new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-GB', { weekday: 'short', timeZone: 'UTC' })

export default function Forecasting() {
  const { departmentId, ready } = useFilters()
  const [target, setTarget] = useState('admissions')
  const params = { target, ...(departmentId ? { department_id: departmentId } : {}) }
  const q = useApi(() => getForecast(params), [target, departmentId], { enabled: ready })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const f = q.data
  const pct = target === 'bed_occupancy'
  const fmt = (v) => (v == null ? '—' : pct ? `${fmtNum(v, 1)}%` : fmtNum(v, 0))

  const retrain = async () => {
    setBusy(true); setErr('')
    try { await retrainForecast(params); q.reload() } catch (e) { setErr(errorMessage(e, 'Could not retrain the models.')) } finally { setBusy(false) }
  }

  const first = q.loading && !f
  const best = f?.enough ? f.models.find((m) => m.selected) : null
  const next = f?.enough ? f.forecast : []
  const nextTotal = next.reduce((s, x) => s + x.predicted, 0)
  const nextPeak = next.length ? next.reduce((a, b) => (b.predicted > a.predicted ? b : a)) : null
  const scope = departmentId ? 'selected department' : 'whole hospital'

  return (
    <PageShell title="Forecasting" description={`Expected ${pct ? 'bed occupancy' : 'daily admissions'} for the next 7 days, ${scope}. Uses all stored data; the date range filter does not apply here.`}
      actions={(
        <button onClick={retrain} disabled={busy || !f?.enough} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50">
          {busy ? <Spinner /> : <RefreshCw className="h-4 w-4" />} Retrain models
        </button>
      )}>
      <div role="tablist" aria-label="Forecast target" className="flex w-fit gap-1 rounded-xl border border-slate-200 bg-white p-1 shadow-sm">
        {TARGETS.map((t) => (
          <button key={t.id} role="tab" aria-selected={target === t.id} onClick={() => setTarget(t.id)}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium ${target === t.id ? 'bg-brand-700 text-white' : 'text-slate-600 hover:bg-slate-50'}`}>{t.label}</button>
        ))}
      </div>
      <ErrorBanner message={err || q.error} onRetry={q.reload} />

      {f && !f.has_data && !q.loading ? (
        f.message ? <EmptyState icon={Target} title="Nothing to forecast here" description={f.message} />
          : <EmptyState icon={Upload} title="No hospital data loaded yet" description="Upload an operational dataset to train the forecasting models."
              action={<Link to="/data" className="inline-flex items-center gap-2 rounded-lg bg-brand-700 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-800"><Upload className="h-4 w-4" /> Go to Data Upload</Link>} />
      ) : f && f.enough === false ? (
        <EmptyState icon={CalendarClock} title="Not enough history yet" description={f.message} />
      ) : (
        <>
          <section aria-label="Forecast indicators" className={`grid gap-4 sm:grid-cols-2 xl:grid-cols-4 transition-opacity ${q.loading && f ? 'opacity-60' : ''}`}>
            <KpiCard label="Selected model" icon={Award} loading={first} value={best ? best.label.split(' (')[0] : null} hint="Lowest error in the backtest" />
            <KpiCard label="Typical error (MAE)" icon={Gauge} loading={first} value={best ? fmt(best.mae) : null} unit={best && !pct ? 'patients' : undefined}
              hint={best?.mape != null ? `About ${fmtNum(best.mape, 1)}% off on average (MAPE)` : undefined} info="Mean absolute error over the rolling backtest" />
            <KpiCard label="Better than the simple rule" icon={TrendingUp} loading={first} value={best ? `${best.vs_naive_pct > 0 ? '+' : ''}${fmtNum(best.vs_naive_pct, 0)}%` : null}
              hint="Lower RMSE than 'same weekday last week'" />
            <KpiCard label={pct ? 'Peak in next 7 days' : 'Expected next 7 days'} icon={CalendarClock} loading={first}
              value={next.length ? (pct ? fmt(nextPeak.predicted) : fmtNum(nextTotal, 0)) : null}
              hint={next.length ? (pct ? `Highest on ${WEEKDAY(nextPeak.date)} ${fmtDate(nextPeak.date)}` : 'Total admissions, all 7 days') : undefined} />
          </section>

          <ForecastChart f={f} loading={q.loading} error={q.error} onRetry={q.reload} format={fmt} domain={pct ? [(m) => Math.max(0, Math.floor(m * 0.9)), 100] : undefined}
            title={pct ? 'Bed occupancy forecast' : 'Admissions forecast'}
            subtitle={f?.enough ? `Daily ${pct ? 'average occupancy' : 'admissions'}. Last data day ${fmtDate(f.last_data_date)}.` : undefined} />

          <div className="grid gap-4 lg:grid-cols-2">
            <ChartCard title="Next 7 days" subtitle="Expected value with a likely range" loading={q.loading} hasData={!!next.length} error={q.error} onRetry={q.reload}>
              <table className="w-full text-left text-xs">
                <thead className="text-slate-500"><tr><th className="px-3 py-2 font-medium">Day</th><th className="px-3 py-2 text-right font-medium">Expected</th><th className="px-3 py-2 text-right font-medium">Likely range</th></tr></thead>
                <tbody className="divide-y divide-slate-100">
                  {next.map((x) => (
                    <tr key={x.date}>
                      <td className="px-3 py-2 font-medium text-slate-800">{WEEKDAY(x.date)} {fmtDate(x.date)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{fmt(x.predicted)}</td>
                      <td className="px-3 py-2 text-right tabular-nums text-slate-600">{fmt(x.lower)} to {fmt(x.upper)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </ChartCard>

            <ChartCard title="Model error (RMSE)" subtitle="Lower is better. Every model was scored on the same days it had not seen."
              loading={q.loading} hasData={!!f?.enough} error={q.error} onRetry={q.reload}>
              <DepartmentBars rows={(f?.models ?? []).map((m, i) => ({ department_id: i, department: m.label.split(' (')[0], rmse: m.rmse }))}
                valueKey="rmse" label="RMSE" format={(v) => fmtNum(v, 1)} height={220} />
            </ChartCard>
          </div>

          <ChartCard title="Model comparison" subtitle={f?.enough ? `Rolling backtest over the latest ${f.test_days} days (${f.folds} fold${f.folds > 1 ? 's' : ''} of 28 days); trained on earlier days only` : undefined}
            loading={q.loading} hasData={!!f?.enough} error={q.error} onRetry={q.reload}>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[620px] text-left text-xs">
                <thead className="text-slate-500"><tr>
                  <th className="px-3 py-2 font-medium">Model</th>
                  {['MAE', 'RMSE', 'R²', 'MAPE', 'RMSE vs simple rule'].map((h) => <th key={h} className="px-3 py-2 text-right font-medium">{h}</th>)}
                  <th className="px-3 py-2 font-medium">Result</th>
                </tr></thead>
                <tbody className="divide-y divide-slate-100">
                  {(f?.models ?? []).map((m) => (
                    <tr key={m.model} className={m.selected ? 'bg-brand-50/50' : ''}>
                      <td className="px-3 py-2 font-medium text-slate-800">{m.label}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{fmtNum(m.mae, 2)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{fmtNum(m.rmse, 2)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{m.r2 == null ? '—' : fmtNum(m.r2, 2)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{m.mape == null ? '—' : `${fmtNum(m.mape, 1)}%`}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{m.vs_naive_pct == null ? '—' : `${m.vs_naive_pct > 0 ? '+' : ''}${fmtNum(m.vs_naive_pct, 1)}%`}</td>
                      <td className="px-3 py-2">{m.selected ? <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 font-medium text-emerald-800"><CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />Selected</span> : <span className="text-slate-400">—</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <ul className="mt-3 space-y-1 text-xs text-slate-500">
              {(f?.notes ?? []).map((n) => <li key={n}>{n}</li>)}
              <li>R² compares a model with simply predicting the average. Sudden surges cannot be seen coming from data that is a week old, so R² stays near zero or below for every model here. MAE and MAPE show the practical size of the error, and the comparison with the simple rule shows whether the model adds anything.</li>
              <li>Prototype forecasts are trained on the stored (synthetic) data and are for planning discussion only.</li>
            </ul>
          </ChartCard>
        </>
      )}
    </PageShell>
  )
}
