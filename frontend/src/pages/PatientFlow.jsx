import { Link } from 'react-router-dom'
import { Activity, Clock, LogIn, LogOut, Timer, TrendingUp, Upload, Users, CalendarDays, AlertTriangle, ArrowRight } from 'lucide-react'
import { getFlow } from '../api/flow'
import { useApi } from '../hooks/useApi'
import { useFilters } from '../context/FilterContext'
import { PageShell } from '../components/common/PageShell'
import KpiCard from '../components/common/KpiCard'
import { EmptyState, ErrorBanner } from '../components/common/Feedback'
import ChartCard from '../components/charts/ChartCard'
import TimeSeriesChart from '../components/charts/TimeSeriesChart'
import CategoryBars from '../components/charts/CategoryBars'
import DepartmentBars from '../components/charts/DepartmentBars'
import PeakHeatmap, { DAYS, hh } from '../components/charts/PeakHeatmap'
import { VIZ, fmtTitle } from '../components/charts/theme'
import { fmtDate, fmtInt, fmtNum } from '../utils/format'

const minutes = (v) => (v == null ? '—' : `${fmtNum(v)} min`)
const pct = (v) => (v == null ? '—' : `${fmtNum(v)}%`)
const delta = (kp, goodWhenUp = null) => (kp?.delta_pct != null ? { pct: kp.delta_pct, goodWhenUp, label: 'vs previous period' } : undefined)

/** Registration-to-discharge journey, built only from columns that exist in the data. Missing stages say so. */
function Journey({ stages }) {
  return (
    <ol className="grid gap-3 sm:grid-cols-3 xl:grid-cols-6" aria-label="Patient journey">
      {stages.map((s, i) => (
        <li key={s.stage} className={`relative rounded-xl border p-3 ${s.available ? 'border-slate-200 bg-white shadow-sm' : 'border-dashed border-slate-300 bg-slate-50'}`}>
          <p className="flex items-center justify-between text-xs font-medium uppercase tracking-wide text-slate-500">
            {s.label}
            {i < stages.length - 1 && <ArrowRight className="hidden h-3.5 w-3.5 text-slate-300 xl:block" aria-hidden="true" />}
          </p>
          {s.available ? (
            <>
              <p className="mt-1.5 text-xl font-semibold tabular-nums text-slate-900">{fmtNum(s.value, 0)}</p>
              <p className="text-xs text-slate-500">{s.unit}</p>
              {s.secondary && <p className="mt-1 text-xs text-slate-600">{s.secondary}</p>}
            </>
          ) : (
            <p className="mt-2 text-xs text-slate-500">{s.secondary}</p>
          )}
        </li>
      ))}
    </ol>
  )
}

export default function PatientFlow() {
  const { params, range, departmentId, ready } = useFilters()
  const q = useApi(() => getFlow(params), [params], { enabled: ready })
  const f = q.data
  const loading = q.loading
  const first = loading && !f
  const noData = ready && f && !f.has_data && !loading
  const k = f?.kpis
  const hourly = f?.granularity === 'hour'
  const series = (f?.series ?? []).map((r) => ({ ...r, flagged: r.anomaly ? r.arrivals : null }))
  const showTypical = series.some((r) => r.expected != null)
  const hasFlags = series.some((r) => r.anomaly)

  const scope = [range.from && range.to ? `${fmtDate(range.from)} to ${fmtDate(range.to)}` : 'All available data', departmentId ? 'selected department' : 'all departments'].join(' · ')

  return (
    <PageShell title="Patient Flow Analytics" description={`How patients move from arrival to discharge. Showing ${scope}.`}>
      <ErrorBanner message={q.error} onRetry={q.reload} />
      {noData ? (
        <EmptyState icon={Upload} title="No data for this selection"
          description="Upload an operational dataset or widen the date range."
          action={<Link to="/data" className="inline-flex items-center gap-2 rounded-lg bg-brand-700 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-800"><Upload className="h-4 w-4" /> Go to Data Upload</Link>} />
      ) : (
        <>
          <section aria-label="Patient flow indicators" className={`grid gap-4 sm:grid-cols-2 xl:grid-cols-4 transition-opacity ${loading && f ? 'opacity-60' : ''}`}>
            <KpiCard label="Total Arrivals" icon={Users} loading={first} value={f ? fmtInt(k.arrivals.value) : null} delta={delta(k?.arrivals)} info="Patients arriving in the selected range" />
            <KpiCard label="Avg Daily Arrivals" icon={Activity} loading={first} value={f ? fmtInt(k.avg_daily_arrivals.value) : null} delta={delta(k?.avg_daily_arrivals)} />
            <KpiCard label="Admissions" icon={LogIn} loading={first} value={f ? fmtInt(k.admissions.value) : null} delta={delta(k?.admissions)} />
            <KpiCard label="Discharges" icon={LogOut} loading={first} value={f ? fmtInt(k.discharges.value) : null} delta={delta(k?.discharges)} />
            <KpiCard label="Avg Waiting Time" icon={Clock} loading={first} unit="min" value={f ? fmtNum(k.avg_wait_min.value) : null} delta={delta(k?.avg_wait_min, false)} hint="Weighted by arrivals" />
            <KpiCard label="Avg Length of Stay" icon={Timer} loading={first} unit="h" value={f && k.avg_los_hours.value != null ? fmtNum(k.avg_los_hours.value, 0) : null} delta={delta(k?.avg_los_hours)} hint="Weighted by discharges" />
            <KpiCard label="Peak Hour" icon={TrendingUp} loading={first} value={f ? hh(k.peak_hour) : null} hint="Hour of day with the most arrivals" />
            <KpiCard label="Busiest Weekday" icon={CalendarDays} loading={first} value={f ? k.busiest_weekday : null} hint="Highest average daily arrivals" />
          </section>

          <section aria-label="Patient journey" className={`transition-opacity ${loading && f ? 'opacity-60' : ''}`}>
            <h2 className="mb-2 text-sm font-semibold text-slate-900">Patient journey</h2>
            {f?.journey ? <Journey stages={f.journey} /> : null}
            <p className="mt-2 text-xs text-slate-500">Totals for the selected range. Stages come from the columns in the uploaded data; the dataset has no pharmacy information.</p>
          </section>

          <ChartCard title="Arrivals over time" subtitle={`Per ${hourly ? 'hour' : 'day'}${showTypical ? ', against the typical level for the same weekday' : ''}`}
            legend={[{ label: 'Arrivals', color: VIZ.s1 }, ...(showTypical ? [{ label: 'Typical for the weekday', color: VIZ.muted, dashed: true }] : []), ...(hasFlags ? [{ label: 'Unusual volume day', color: VIZ.critical, marker: true }] : [])]}
            loading={loading} hasData={!!f?.has_data} error={q.error} onRetry={q.reload}
            table={{ columns: [{ key: 't', label: hourly ? 'Hour' : 'Day', format: fmtTitle }, { key: 'arrivals', label: 'Arrivals', align: 'right' }, ...(showTypical ? [{ key: 'expected', label: 'Typical', align: 'right' }] : []), { key: 'anomaly', label: 'Unusual', format: (v) => (v ? 'Yes' : '') }], rows: series }}>
            <TimeSeriesChart data={series} yFormat={fmtInt} height={280}
              series={[{ key: 'arrivals', label: 'Arrivals', color: VIZ.s1, area: true },
                ...(showTypical ? [{ key: 'expected', label: 'Typical for the weekday', color: VIZ.muted, dashed: true }] : []),
                ...(hasFlags ? [{ key: 'flagged', label: 'Unusual volume day', color: VIZ.critical, marker: true }] : [])]} />
          </ChartCard>

          <ChartCard title="Unusual patient volume" subtitle="Days with far more arrivals than usual for that weekday"
            loading={loading} hasData={!!f?.has_data} error={q.error} onRetry={q.reload}
            empty="No data for the selected range.">
            {f?.anomalies?.length ? (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[640px] text-left text-xs">
                  <thead className="text-slate-500"><tr>
                    {['Date', 'Arrivals', 'Typical', 'Increase', 'Avg wait', 'Most affected department'].map((h, i) => <th key={h} className={`px-3 py-2 font-medium ${i > 0 && i < 5 ? 'text-right' : ''}`}>{h}</th>)}
                  </tr></thead>
                  <tbody className="divide-y divide-slate-100">
                    {f.anomalies.map((a) => (
                      <tr key={a.date}>
                        <td className="px-3 py-2 font-medium text-slate-800"><span className="inline-flex items-center gap-1.5"><AlertTriangle className="h-3.5 w-3.5 text-amber-600" aria-hidden="true" />{a.weekday} {fmtDate(a.date)}</span></td>
                        <td className="px-3 py-2 text-right tabular-nums">{fmtInt(a.arrivals)}</td>
                        <td className="px-3 py-2 text-right tabular-nums">{fmtInt(a.expected)}</td>
                        <td className="px-3 py-2 text-right font-semibold tabular-nums">+{fmtNum(a.increase_pct, 0)}%</td>
                        <td className="px-3 py-2 text-right tabular-nums">{minutes(a.wait_min)}{a.wait_normal_min != null && <span className="text-slate-500"> (usually {fmtNum(a.wait_normal_min, 0)})</span>}</td>
                        <td className="px-3 py-2">{a.top_department ? `${a.top_department} (+${fmtNum(a.top_department_increase_pct, 0)}%)` : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="rounded-lg bg-slate-50 px-4 py-6 text-center text-sm text-slate-600">No unusual-volume days in this range.</p>
            )}
            <p className="mt-3 text-xs text-slate-500">{f?.anomaly_note} {f?.anomaly_scope}</p>
          </ChartCard>

          <div className="grid gap-4 lg:grid-cols-2">
            <ChartCard title="Arrivals by department" subtitle="Total in range. All departments shown; the selected one is highlighted."
              loading={loading} hasData={!!f?.has_data} error={q.error} onRetry={q.reload}
              table={{ columns: [{ key: 'department', label: 'Department' }, { key: 'arrivals', label: 'Arrivals', align: 'right', format: fmtInt }, { key: 'share_pct', label: 'Share', align: 'right', format: pct }, { key: 'admission_rate_pct', label: 'Admitted', align: 'right', format: pct }, { key: 'avg_wait_min', label: 'Avg wait', align: 'right', format: minutes }, { key: 'avg_los_hours', label: 'Stay (h)', align: 'right', format: (v) => fmtNum(v, 0) }], rows: f?.departments ?? [] }}>
              <DepartmentBars rows={f?.departments ?? []} valueKey="arrivals" label="Arrivals" format={fmtInt} selectedId={departmentId} />
            </ChartCard>

            <ChartCard title="Average arrivals by weekday" subtitle="Average per day"
              loading={loading} hasData={!!f?.has_data} error={q.error} onRetry={q.reload}
              table={{ columns: [{ key: 'day', label: 'Weekday' }, { key: 'avg_arrivals', label: 'Avg arrivals', align: 'right', format: fmtInt }], rows: f?.weekday ?? [] }}>
              <CategoryBars rows={f?.weekday ?? []} xKey="day" yKey="avg_arrivals" label="Avg arrivals" format={fmtInt} />
            </ChartCard>
          </div>

          <ChartCard title="Waiting time and stay by department" subtitle="Average waiting time (minutes) in the selected range"
            loading={loading} hasData={!!f?.has_data} error={q.error} onRetry={q.reload}
            table={{ columns: [{ key: 'department', label: 'Department' }, { key: 'avg_wait_min', label: 'Avg wait', align: 'right', format: minutes }, { key: 'avg_los_hours', label: 'Stay (h)', align: 'right', format: (v) => fmtNum(v, 0) }], rows: f?.departments ?? [] }}>
            <DepartmentBars rows={f?.departments ?? []} valueKey="avg_wait_min" label="Avg wait" format={minutes} selectedId={departmentId} />
          </ChartCard>

          <ChartCard title="Peak hours" subtitle="Average arrivals per hour by weekday and hour of day"
            loading={loading} hasData={!!f?.has_data} error={q.error} onRetry={q.reload}
            table={{ columns: [{ key: 'dow', label: 'Day', format: (v) => DAYS[v] }, { key: 'hour', label: 'Hour', format: hh }, { key: 'avg_arrivals', label: 'Avg arrivals', align: 'right', format: (v) => fmtNum(v, 2) }], rows: f?.heatmap?.cells ?? [] }}>
            <PeakHeatmap cells={f?.heatmap?.cells ?? []} max={f?.heatmap?.max} />
          </ChartCard>
        </>
      )}
    </PageShell>
  )
}
