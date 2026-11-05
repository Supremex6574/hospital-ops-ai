import { Link } from 'react-router-dom'
import {
  Activity, BedDouble, Bell, Clock, Flame, Gauge, LineChart as LineChartIcon, Lightbulb, LogIn, LogOut, Upload, Users,
} from 'lucide-react'
import { getKpis, getSummary } from '../api/dashboard'
import { getAlertSummary } from '../api/alerts'
import { getForecast } from '../api/forecast'
import { getRecommendations } from '../api/recommendations'
import PriorityChip from '../components/common/PriorityChip'
import { useApi } from '../hooks/useApi'
import { useOccupancyBands } from '../hooks/useThresholds'
import { useFilters } from '../context/FilterContext'
import { PageShell } from '../components/common/PageShell'
import KpiCard from '../components/common/KpiCard'
import { EmptyState, ErrorBanner } from '../components/common/Feedback'
import ChartCard from '../components/charts/ChartCard'
import TimeSeriesChart from '../components/charts/TimeSeriesChart'
import DepartmentBars from '../components/charts/DepartmentBars'
import PeakHeatmap, { DAYS, hh } from '../components/charts/PeakHeatmap'
import { VIZ, fmtTitle } from '../components/charts/theme'
import { fmtDate, fmtInt, fmtNum } from '../utils/format'

const pct = (v) => (v == null ? '—' : `${fmtNum(v)}%`)
const minutes = (v) => (v == null ? '—' : `${fmtNum(v)} min`)

function occupancyStatus(v, OCCUPANCY) {
  if (v == null) return undefined
  if (v >= OCCUPANCY.critical) return { label: 'Critical occupancy', tone: 'crit' }
  if (v >= OCCUPANCY.warning) return { label: 'High occupancy', tone: 'warn' }
  return undefined
}

/** Compact next-7-days admissions forecast with a link to the full Forecasting page. */
function ForecastSummary() {
  const q = useApi(() => getForecast({ target: 'admissions' }), [])
  const f = q.data
  const next = f?.enough ? f.forecast : []
  const total = next.reduce((s, x) => s + x.predicted, 0)
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm" aria-label="Forecast">
      <div className="flex items-center gap-2">
        <span className="rounded-lg bg-brand-50 p-1.5 text-brand-700"><LineChartIcon className="h-4 w-4" aria-hidden="true" /></span>
        <h2 className="text-sm font-semibold text-slate-900">Admissions forecast</h2>
        <Link to="/forecasting" className="ml-auto text-xs font-medium text-brand-700 hover:underline">Details</Link>
      </div>
      {q.loading && !f ? <div className="mt-3 h-24 animate-pulse rounded-lg bg-slate-100" />
        : next.length ? (
          <>
            <p className="mt-3 text-2xl font-semibold text-slate-900">{fmtInt(Math.round(total))} <span className="text-sm font-normal text-slate-500">expected over the next 7 days</span></p>
            <p className="mt-1 text-xs text-slate-500">About {fmtInt(Math.round(total / 7))} per day. Typical error {fmtNum(f.models.find((m) => m.selected)?.mape, 1)}%.</p>
          </>
        ) : <p className="mt-3 text-sm text-slate-500">{f?.message ?? 'Load hospital data to see the forecast.'}</p>}
    </section>
  )
}

/** The three most urgent recommendations, with a link to the full list. */
function TopRecommendations() {
  const q = useApi(() => getRecommendations({ status: 'active' }), [])
  const items = (q.data?.items ?? []).slice(0, 3)
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm" aria-label="Recommendations">
      <div className="flex items-center gap-2">
        <span className="rounded-lg bg-brand-50 p-1.5 text-brand-700"><Lightbulb className="h-4 w-4" aria-hidden="true" /></span>
        <h2 className="text-sm font-semibold text-slate-900">Top recommendations</h2>
        <Link to="/recommendations" className="ml-auto text-xs font-medium text-brand-700 hover:underline">All</Link>
      </div>
      {q.loading && !q.data ? <div className="mt-3 h-24 animate-pulse rounded-lg bg-slate-100" />
        : items.length ? (
          <ul className="mt-3 space-y-2">
            {items.map((r) => <li key={r.id} className="text-xs"><PriorityChip priority={r.priority} /><p className="mt-1 font-medium text-slate-800">{r.title}</p></li>)}
          </ul>
        ) : <p className="mt-3 text-sm text-slate-500">{q.data?.has_data === false ? 'Load hospital data to see recommendations.' : 'Nothing needs action right now.'}</p>}
    </section>
  )
}

/** Open alert counts from the monitoring module. */
function AlertsSummary() {
  const q = useApi(() => getAlertSummary(), [])
  const s = q.data
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm" aria-label="Active alerts">
      <div className="flex items-center gap-2">
        <span className="rounded-lg bg-brand-50 p-1.5 text-brand-700"><Bell className="h-4 w-4" aria-hidden="true" /></span>
        <h2 className="text-sm font-semibold text-slate-900">Active alerts</h2>
        <Link to="/alerts" className="ml-auto text-xs font-medium text-brand-700 hover:underline">Details</Link>
      </div>
      {q.loading && !s ? <div className="mt-3 h-24 animate-pulse rounded-lg bg-slate-100" />
        : s ? (
          <>
            <p className="mt-3 text-2xl font-semibold text-slate-900">{s.open} <span className="text-sm font-normal text-slate-500">open</span></p>
            <p className="mt-1 text-xs text-slate-500">{s.critical} critical, {s.warning} warning</p>
          </>
        ) : <p className="mt-3 text-sm text-slate-500">Could not load alerts.</p>}
    </section>
  )
}

export default function Dashboard() {
  const { params, range, departmentId, ready } = useFilters()
  const OCCUPANCY = useOccupancyBands()
  const kpiQ = useApi(() => getKpis(params), [params], { enabled: ready })
  const sumQ = useApi(() => getSummary(params), [params], { enabled: ready })

  const k = kpiQ.data
  const s = sumQ.data
  const loadingKpis = kpiQ.loading && !k
  const noData = ready && k && !k.has_data && !kpiQ.loading
  const reload = () => { kpiQ.reload(); sumQ.reload() }

  const scope = [
    range.from && range.to ? `${fmtDate(range.from)} to ${fmtDate(range.to)}` : 'All available data',
    departmentId ? 'selected department' : 'all departments',
  ].join(' · ')

  const prevLabel = 'vs previous period'
  const dayLabel = k?.as_of_date ? `on ${fmtDate(k.as_of_date)} (latest day in range)` : undefined
  const dayDelta = (kp) => (kp?.delta_pct != null ? { pct: kp.delta_pct, goodWhenUp: null, label: 'vs previous day' } : undefined)

  const depts = s?.departments ?? []
  const peakDept = k?.highest_workload

  return (
    <PageShell title="Operations Dashboard" description={`What is happening in the hospital. Showing ${scope}.`}>
      <ErrorBanner message={kpiQ.error || sumQ.error} onRetry={reload} />

      {noData ? (
        <EmptyState
          icon={Upload}
          title={departmentId || range.from ? 'No data for this selection' : 'No hospital data loaded yet'}
          description={
            departmentId || range.from
              ? 'Try a wider date range or all departments.'
              : 'Upload an operational dataset (CSV or Excel) to populate KPIs, charts, forecasts and recommendations. A synthetic sample dataset can be loaded in one click.'
          }
          action={
            <Link to="/data" className="inline-flex items-center gap-2 rounded-lg bg-brand-700 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-800">
              <Upload className="h-4 w-4" /> Go to Data Upload
            </Link>
          }
        />
      ) : (
        <>
          <section aria-label="Key performance indicators" className={`grid gap-4 sm:grid-cols-2 xl:grid-cols-4 transition-opacity ${kpiQ.loading && k ? 'opacity-60' : ''}`}>
            <KpiCard label="Total Patients" icon={Users} loading={loadingKpis} value={k?.has_data ? fmtInt(k.total_patients.value) : null}
              hint="Arrivals in the selected range" info="Sum of patient arrivals across the selected range and departments"
              delta={k?.total_patients?.delta_pct != null ? { pct: k.total_patients.delta_pct, goodWhenUp: null, label: prevLabel } : undefined} />
            <KpiCard label="Today's Admissions" icon={LogIn} loading={loadingKpis} value={k?.has_data ? fmtInt(k.admissions_today.value) : null}
              hint={dayLabel} info="Admissions on the newest day of data in the selected range" delta={dayDelta(k?.admissions_today)} />
            <KpiCard label="Today's Discharges" icon={LogOut} loading={loadingKpis} value={k?.has_data ? fmtInt(k.discharges_today.value) : null}
              hint={dayLabel} info="Discharges on the newest day of data in the selected range" delta={dayDelta(k?.discharges_today)} />
            <KpiCard label="Bed Occupancy" icon={BedDouble} loading={loadingKpis} unit="%"
              value={k?.has_data && k.bed_occupancy_pct.value != null ? fmtNum(k.bed_occupancy_pct.value) : null}
              hint={k?.bed_occupancy_pct?.range_avg != null ? `Range average ${fmtNum(k.bed_occupancy_pct.range_avg)}%` : k?.has_data ? 'No beds in this department' : undefined}
              info="Occupied beds as a share of total beds at the latest hour, over departments that have beds"
              status={occupancyStatus(k?.bed_occupancy_pct?.value, OCCUPANCY)} />
            <KpiCard label="Avg Waiting Time" icon={Clock} loading={loadingKpis} unit="min" value={k?.has_data ? fmtNum(k.avg_wait_min.value) : null}
              hint="Weighted by arrivals" info="Average waiting time, weighted by the number of arrivals in each hour"
              delta={k?.avg_wait_min?.delta_pct != null ? { pct: k.avg_wait_min.delta_pct, goodWhenUp: false, label: prevLabel } : undefined} />
            <KpiCard label="Highest Dept Workload" icon={Flame} loading={loadingKpis} value={peakDept?.department ?? null}
              hint={peakDept ? `Workload index ${fmtNum(peakDept.workload_index)} / 100` : undefined}
              info="Department with the highest average workload index (beds, doctor and nurse load, waiting time)" />
            <KpiCard label="Available Beds" icon={Activity} loading={loadingKpis}
              value={k?.has_data && k.available_beds.value != null ? fmtInt(k.available_beds.value) : null}
              hint={k?.available_beds?.total_beds ? `of ${fmtInt(k.available_beds.total_beds)} total beds, latest hour` : undefined}
              info="Free beds across departments with beds at the latest hour of data" />
            <KpiCard label="Resource Utilization" icon={Gauge} loading={loadingKpis} unit="%" value={k?.has_data ? fmtNum(k.resource_util_pct.value) : null}
              hint="Beds, staff, lab and equipment" info="Mean of bed occupancy, doctor and nurse load, equipment and lab utilization"
              delta={k?.resource_util_pct?.delta_pct != null ? { pct: k.resource_util_pct.delta_pct, goodWhenUp: null, label: prevLabel } : undefined} />
          </section>

          <div className="grid gap-4 lg:grid-cols-2">
            <ChartCard title="Patient flow" subtitle={`Arrivals per ${s?.granularity === 'hourly' ? 'hour' : 'day'}`}
              loading={sumQ.loading} hasData={!!s?.has_data} error={sumQ.error} onRetry={sumQ.reload}
              table={{ columns: [{ key: 't', label: s?.granularity === 'hourly' ? 'Hour' : 'Day', format: fmtTitle }, { key: 'arrivals', label: 'Arrivals', align: 'right' }], rows: s?.flow ?? [] }}>
              <TimeSeriesChart data={s?.flow ?? []} series={[{ key: 'arrivals', label: 'Arrivals', color: VIZ.s1, area: true }]} yFormat={fmtInt} />
            </ChartCard>

            <ChartCard title="Admissions and discharges" subtitle={`Per ${s?.granularity === 'hourly' ? 'hour' : 'day'}`}
              legend={[{ label: 'Admissions', color: VIZ.s1 }, { label: 'Discharges', color: VIZ.s2 }]}
              loading={sumQ.loading} hasData={!!s?.has_data} error={sumQ.error} onRetry={sumQ.reload}
              table={{ columns: [{ key: 't', label: s?.granularity === 'hourly' ? 'Hour' : 'Day', format: fmtTitle }, { key: 'admissions', label: 'Admissions', align: 'right' }, { key: 'discharges', label: 'Discharges', align: 'right' }], rows: s?.flow ?? [] }}>
              <TimeSeriesChart data={s?.flow ?? []} yFormat={fmtInt}
                series={[{ key: 'admissions', label: 'Admissions', color: VIZ.s1 }, { key: 'discharges', label: 'Discharges', color: VIZ.s2 }]} />
            </ChartCard>

            <ChartCard title="Department workload" subtitle="Average workload index, 0 to 100. All departments shown; the selected one is highlighted."
              loading={sumQ.loading} hasData={!!s?.has_data} error={sumQ.error} onRetry={sumQ.reload}
              table={{ columns: [{ key: 'department', label: 'Department' }, { key: 'workload_index', label: 'Workload index', align: 'right', format: (v) => fmtNum(v) }, { key: 'patients_per_doctor', label: 'Patients / doctor', align: 'right', format: (v) => fmtNum(v, 2) }, { key: 'patients_per_nurse', label: 'Patients / nurse', align: 'right', format: (v) => fmtNum(v, 2) }], rows: depts }}>
              <DepartmentBars rows={depts} valueKey="workload_index" label="Workload index" format={(v) => fmtNum(v)} selectedId={departmentId} max={100} />
            </ChartCard>

            <ChartCard title="Bed occupancy" subtitle="Hospital-wide, departments with beds"
              empty="The selected department has no beds, so there is no occupancy to show."
              loading={sumQ.loading} hasData={!!s?.has_data && s.occupancy.length > 0} error={sumQ.error} onRetry={sumQ.reload}
              table={{ columns: [{ key: 't', label: s?.granularity === 'hourly' ? 'Hour' : 'Day', format: fmtTitle }, { key: 'occupancy_pct', label: 'Occupancy', align: 'right', format: pct }], rows: s?.occupancy ?? [] }}>
              <TimeSeriesChart data={s?.occupancy ?? []} yFormat={(v) => `${v}%`} tooltipFormat={pct} yDomain={[0, 100]}
                series={[{ key: 'occupancy_pct', label: 'Occupancy', color: VIZ.s1 }]}
                references={[{ y: OCCUPANCY.warning }, { y: OCCUPANCY.critical, label: `High ${OCCUPANCY.warning}% · Critical ${OCCUPANCY.critical}%` }]} />
            </ChartCard>

            <ChartCard title="Resource utilization" subtitle="Average of bed, staff, lab and equipment utilization by department"
              loading={sumQ.loading} hasData={!!s?.has_data} error={sumQ.error} onRetry={sumQ.reload}
              table={{ columns: [{ key: 'department', label: 'Department' }, { key: 'resource_util_pct', label: 'Utilization', align: 'right', format: pct }, { key: 'bed_occupancy_pct', label: 'Bed occupancy', align: 'right', format: pct }, { key: 'lab_util_pct', label: 'Lab', align: 'right', format: pct }], rows: depts }}>
              <DepartmentBars rows={depts} valueKey="resource_util_pct" label="Utilization" format={pct} selectedId={departmentId} max={100} />
            </ChartCard>

            <ChartCard title="Waiting time" subtitle={`Average minutes, weighted by arrivals, per ${s?.granularity === 'hourly' ? 'hour' : 'day'}`}
              loading={sumQ.loading} hasData={!!s?.has_data} error={sumQ.error} onRetry={sumQ.reload}
              table={{ columns: [{ key: 't', label: s?.granularity === 'hourly' ? 'Hour' : 'Day', format: fmtTitle }, { key: 'avg_wait_min', label: 'Avg wait', align: 'right', format: minutes }], rows: s?.wait ?? [] }}>
              <TimeSeriesChart data={s?.wait ?? []} yFormat={(v) => `${v}`} tooltipFormat={minutes} series={[{ key: 'avg_wait_min', label: 'Avg wait', color: VIZ.s1 }]} />
            </ChartCard>
          </div>

          <ChartCard title="Peak hours" subtitle="Average arrivals per hour by weekday and hour of day"
            loading={sumQ.loading} hasData={!!s?.has_data} error={sumQ.error} onRetry={sumQ.reload}
            table={{ columns: [{ key: 'dow', label: 'Day', format: (v) => DAYS[v] }, { key: 'hour', label: 'Hour', format: hh }, { key: 'avg_arrivals', label: 'Avg arrivals', align: 'right', format: (v) => fmtNum(v, 2) }], rows: s?.heatmap?.cells ?? [] }}>
            <PeakHeatmap cells={s?.heatmap?.cells ?? []} max={s?.heatmap?.max} />
          </ChartCard>

          <div className="grid gap-4 lg:grid-cols-3">
            <ForecastSummary />
            <AlertsSummary />
            <TopRecommendations />
          </div>
        </>
      )}
    </PageShell>
  )
}
