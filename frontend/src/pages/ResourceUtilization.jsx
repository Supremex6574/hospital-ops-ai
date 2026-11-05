import { useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertOctagon, AlertTriangle, BedDouble, CheckCircle2, Clock, FlaskConical, Gauge, HeartPulse, Stethoscope, Upload, Users } from 'lucide-react'
import { getForecast } from '../api/forecast'
import ForecastChart from '../components/charts/ForecastChart'
import { getCompare, getResource } from '../api/resources'
import { useApi } from '../hooks/useApi'
import { useFilters } from '../context/FilterContext'
import { PageShell } from '../components/common/PageShell'
import KpiCard from '../components/common/KpiCard'
import { EmptyState, ErrorBanner } from '../components/common/Feedback'
import ChartCard from '../components/charts/ChartCard'
import TimeSeriesChart from '../components/charts/TimeSeriesChart'
import DepartmentBars from '../components/charts/DepartmentBars'
import CategoryBars from '../components/charts/CategoryBars'
import { VIZ, fmtTitle } from '../components/charts/theme'
import { fmtDate, fmtInt, fmtNum } from '../utils/format'
import { hh } from '../components/charts/PeakHeatmap'

const TABS = [
  { id: 'overview', label: 'Overview', icon: Gauge },
  { id: 'beds', label: 'Beds', icon: BedDouble },
  { id: 'doctors', label: 'Doctors', icon: Stethoscope },
  { id: 'nurses', label: 'Nurses', icon: HeartPulse },
  { id: 'lab', label: 'Lab & equipment', icon: FlaskConical },
]
const pct = (v) => (v == null ? '—' : `${fmtNum(v)}%`)
const STATUS = {
  normal: { label: 'Normal', cls: 'bg-emerald-50 text-emerald-800', Icon: CheckCircle2 },
  warning: { label: 'High', cls: 'bg-amber-50 text-amber-800', Icon: AlertTriangle },
  critical: { label: 'Critical', cls: 'bg-red-50 text-red-700', Icon: AlertOctagon },
  unknown: { label: 'No data', cls: 'bg-slate-100 text-slate-600', Icon: Clock },
}
function StatusChip({ status }) {
  const s = STATUS[status] ?? STATUS.unknown
  return <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${s.cls}`}><s.Icon className="h-3.5 w-3.5" aria-hidden="true" />{s.label}</span>
}

/** Value with a thin proportional bar under it; `max` is the value that fills the bar. */
function BarCell({ value, max = 100, suffix = '%' }) {
  if (value == null) return <span className="text-slate-400">n/a</span>
  return (
    <div className="min-w-[72px]">
      <span className="tabular-nums">{fmtNum(value, 0)}{suffix}</span>
      <div className="mt-1 h-1 rounded bg-slate-100"><div className="h-1 rounded" style={{ width: `${Math.min(100, (value / max) * 100)}%`, background: VIZ.s1 }} /></div>
    </div>
  )
}

function Overview({ q }) {
  const d = q.data
  if (q.loading && !d) return <ChartCard title="Resource comparison" loading hasData={false} />
  if (!d?.has_data) return null
  const th = d.thresholds
  return (
    <div className="space-y-4">
      <ChartCard title="Resource comparison" subtitle="Average over the selected range for every department, highest workload first"
        loading={q.loading} hasData error={q.error} onRetry={q.reload}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-xs">
            <thead className="text-slate-500"><tr>
              <th className="px-3 py-2 font-medium">Department</th>
              <th className="px-3 py-2 font-medium">Bed occupancy</th>
              <th className="px-3 py-2 font-medium" title={d.notes.load_pct}>Doctor load</th>
              <th className="px-3 py-2 font-medium" title={d.notes.load_pct}>Nurse load</th>
              <th className="px-3 py-2 font-medium">Lab</th>
              <th className="px-3 py-2 font-medium">Equipment</th>
              <th className="px-3 py-2 font-medium" title={d.notes.workload}>Workload index</th>
              <th className="px-3 py-2 font-medium">Status</th>
            </tr></thead>
            <tbody className="divide-y divide-slate-100">
              {d.departments.map((r) => (
                <tr key={r.department_id}>
                  <td className="px-3 py-2 font-medium text-slate-800">{r.department}</td>
                  <td className="px-3 py-2"><BarCell value={r.bed_occupancy_pct} /></td>
                  <td className="px-3 py-2"><BarCell value={r.doctor_load_pct} max={150} /></td>
                  <td className="px-3 py-2"><BarCell value={r.nurse_load_pct} max={150} /></td>
                  <td className="px-3 py-2"><BarCell value={r.lab_util_pct} /></td>
                  <td className="px-3 py-2"><BarCell value={r.equipment_util_pct} /></td>
                  <td className="px-3 py-2"><BarCell value={r.workload_index} suffix="" /></td>
                  <td className="px-3 py-2"><StatusChip status={r.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs text-slate-500">
          {d.notes.load_pct} {d.notes.workload} Beds show n/a for outpatient departments. Occupancy bands: high from {th.occupancy_warning_pct}%, critical from {th.occupancy_critical_pct}%.
          Planning norms are assumptions for this prototype, not clinical standards.
        </p>
      </ChartCard>
      <ChartCard title="Workload by department" subtitle="Average workload index, 0 to 100"
        loading={q.loading} hasData error={q.error} onRetry={q.reload}
        table={{ columns: [{ key: 'department', label: 'Department' }, { key: 'workload_index', label: 'Workload', align: 'right' }, { key: 'resource_util_pct', label: 'Utilization', align: 'right', format: pct }], rows: d.departments }}>
        <DepartmentBars rows={d.departments} valueKey="workload_index" label="Workload index" format={(v) => fmtNum(v, 0)} max={100} />
      </ChartCard>
    </div>
  )
}

function OccupancyForecast({ departmentId }) {
  const q = useApi(() => getForecast({ target: 'bed_occupancy', ...(departmentId ? { department_id: departmentId } : {}) }), [departmentId])
  return (
    <ForecastChart f={q.data} loading={q.loading} error={q.error} onRetry={q.reload} format={pct} domain={[(m) => Math.max(0, Math.floor(m * 0.9)), 100]} height={240} historyDays={30}
      title="Predicted occupancy" subtitle="Expected daily average for the next 7 days; details on the Forecasting page" />
  )
}

const KIND = {
  beds: { title: 'Bed occupancy', unit: '%', fmt: pct, domain: [0, 100], bar: 'Occupancy', refs: (t) => [{ y: t.warning }, { y: t.critical, label: `High ${t.warning}% · Critical ${t.critical}%` }] },
  doctors: { title: 'Doctor load', unit: '% of norm', fmt: pct, bar: 'Load vs norm', refs: (t) => [{ y: t.warning, label: 'Norm 100%' }] },
  nurses: { title: 'Nurse load', unit: '% of norm', fmt: pct, bar: 'Load vs norm', refs: (t) => [{ y: t.warning, label: 'Norm 100%' }] },
  lab: { title: 'Lab utilization', unit: '%', fmt: pct, bar: 'Lab utilization', refs: (t) => [{ y: t.warning, label: `Overload ${t.warning}%` }] },
}

function Detail({ kind, q, departmentId }) {
  const d = q.data
  const cfg = KIND[kind]
  const first = q.loading && !d
  if (d && d.applicable === false) return <EmptyState icon={BedDouble} title="Not applicable here" description={d.message} />
  const k = d?.kpis
  const hourly = d?.granularity === 'hour'
  const withEq = kind === 'lab' && d?.series?.some((r) => r.equipment != null)
  const extra = kind === 'beds' && k?.current
    ? `${fmtInt(k.current.occupied)} of ${fmtInt(k.current.total)} beds in use, ${fmtInt(k.current.available)} free (latest hour)`
    : kind === 'lab' ? (k?.avg_equipment_util_pct != null ? `Equipment utilization ${fmtNum(k.avg_equipment_util_pct)}%` : undefined)
    : k?.avg_on_duty != null ? `${fmtNum(k.avg_on_duty)} on duty on average` : undefined
  const delta = k?.average?.delta_pct != null ? { pct: k.average.delta_pct, goodWhenUp: null, label: 'vs previous period' } : undefined

  return (
    <div className="space-y-4">
      <section aria-label={`${cfg.title} indicators`} className={`grid gap-4 sm:grid-cols-2 xl:grid-cols-4 transition-opacity ${q.loading && d ? 'opacity-60' : ''}`}>
        <KpiCard label={`Average ${cfg.title.toLowerCase()}`} icon={Gauge} loading={first} value={d ? fmtNum(k.average.value) : null} unit={cfg.unit} delta={delta} hint={extra} />
        <KpiCard label="Peak" icon={Users} loading={first} value={d ? fmtNum(k.peak) : null} unit={cfg.unit} hint="Highest hour in range" />
        <KpiCard label="Hours above high" icon={AlertTriangle} loading={first} value={d ? fmtInt(k.hours_over_warning) : null}
          hint={d ? `of ${fmtInt(k.total_hours)} hours; high from ${fmtNum(d.thresholds.warning, 0)}` : undefined} />
        <KpiCard label="Hours critical" icon={AlertOctagon} loading={first} value={d ? fmtInt(k.hours_over_critical) : null}
          hint={d ? `critical from ${fmtNum(d.thresholds.critical, 0)}` : undefined} />
      </section>

      <ChartCard title={`${cfg.title} over time`} subtitle={`${departmentId ? 'Selected department' : kind === 'beds' ? 'Hospital-wide, departments with beds' : 'Average across departments'}, per ${hourly ? 'hour' : 'day'}`}
        legend={withEq ? [{ label: 'Lab', color: VIZ.s1 }, { label: 'Equipment', color: VIZ.s2 }] : undefined}
        loading={q.loading} hasData={!!d?.series?.length} error={q.error} onRetry={q.reload}
        table={{ columns: [{ key: 't', label: hourly ? 'Hour' : 'Day', format: fmtTitle }, { key: 'value', label: cfg.title, align: 'right', format: cfg.fmt }, ...(withEq ? [{ key: 'equipment', label: 'Equipment', align: 'right', format: pct }] : [])], rows: d?.series ?? [] }}>
        <TimeSeriesChart data={d?.series ?? []} yFormat={(v) => fmtNum(v, 0)} tooltipFormat={cfg.fmt} yDomain={cfg.domain} height={260}
          series={[{ key: 'value', label: kind === 'lab' ? 'Lab' : cfg.title, color: VIZ.s1 }, ...(withEq ? [{ key: 'equipment', label: 'Equipment', color: VIZ.s2 }] : [])]}
          references={d ? cfg.refs(d.thresholds) : []} />
      </ChartCard>

      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard title={`${cfg.title} by department`} subtitle="Average in range. All departments shown; the selected one is highlighted."
          loading={q.loading} hasData={!!d?.departments?.length} error={q.error} onRetry={q.reload}
          table={{ columns: [{ key: 'department', label: 'Department' }, { key: 'average', label: 'Average', align: 'right', format: cfg.fmt }, { key: 'peak', label: 'Peak', align: 'right', format: cfg.fmt }, { key: 'share_over_warning_pct', label: 'Time above high', align: 'right', format: pct }, { key: 'status', label: 'Status', format: (v) => STATUS[v]?.label }], rows: d?.departments ?? [] }}>
          <DepartmentBars rows={d?.departments ?? []} valueKey="average" label={cfg.bar} format={(v) => fmtNum(v, 0) + (cfg.unit === '%' ? '%' : '%')} selectedId={departmentId} />
        </ChartCard>
        <ChartCard title="Pressure by hour of day" subtitle={`Average ${cfg.title.toLowerCase()} for each hour`}
          loading={q.loading} hasData={!!d?.hours?.length} error={q.error} onRetry={q.reload}
          table={{ columns: [{ key: 'hour', label: 'Hour', format: hh }, { key: 'value', label: cfg.title, align: 'right', format: cfg.fmt }], rows: d?.hours ?? [] }}>
          <CategoryBars rows={d?.hours ?? []} xKey="hour" yKey="value" label={cfg.title} format={(v) => fmtNum(v, 0)} xFormat={(h) => hh(h)} tickEvery={3} />
        </ChartCard>
      </div>

      {kind === 'beds' && <OccupancyForecast departmentId={departmentId} />}
    </div>
  )
}

export default function ResourceUtilization() {
  const { params, range, departmentId, ready } = useFilters()
  const [tab, setTab] = useState('overview')
  const compareQ = useApi(() => getCompare({ from: params.from, to: params.to }), [params.from, params.to, tab === 'overview'], { enabled: ready && tab === 'overview' })
  const detailQ = useApi(() => getResource(tab, params), [tab, params], { enabled: ready && tab !== 'overview' })

  const active = tab === 'overview' ? compareQ : detailQ
  const noData = ready && active.data && active.data.has_data === false && !active.loading
  const scope = [range.from && range.to ? `${fmtDate(range.from)} to ${fmtDate(range.to)}` : 'All available data', tab !== 'overview' && departmentId ? 'selected department' : 'all departments'].join(' · ')

  return (
    <PageShell title="Resource Utilization" description={`How heavily beds, staff, lab and equipment are used. Showing ${scope}.`}>
      <div role="tablist" aria-label="Resource" className="flex flex-wrap gap-1 rounded-xl border border-slate-200 bg-white p-1 shadow-sm">
        {TABS.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}
            className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium ${tab === t.id ? 'bg-brand-700 text-white' : 'text-slate-600 hover:bg-slate-50'}`}>
            <t.icon className="h-4 w-4" aria-hidden="true" />{t.label}
          </button>
        ))}
      </div>
      {tab === 'overview' && <p className="-mt-2 text-xs text-slate-500">The overview compares every department; the department filter applies to the other tabs.</p>}
      <ErrorBanner message={active.error} onRetry={active.reload} />
      {noData ? (
        <EmptyState icon={Upload} title="No data for this selection" description="Upload an operational dataset or widen the date range."
          action={<Link to="/data" className="inline-flex items-center gap-2 rounded-lg bg-brand-700 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-800"><Upload className="h-4 w-4" /> Go to Data Upload</Link>} />
      ) : tab === 'overview' ? <Overview q={compareQ} /> : <Detail key={tab} kind={tab} q={detailQ} departmentId={departmentId} />}
    </PageShell>
  )
}
