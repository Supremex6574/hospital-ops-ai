import { Link } from 'react-router-dom'
import { AlertOctagon, Clock, Flame, Upload, Zap } from 'lucide-react'
import { getBottlenecks } from '../api/alerts'
import { useApi } from '../hooks/useApi'
import { useFilters } from '../context/FilterContext'
import { PageShell } from '../components/common/PageShell'
import KpiCard from '../components/common/KpiCard'
import SeverityChip from '../components/common/SeverityChip'
import { EmptyState, ErrorBanner } from '../components/common/Feedback'
import ChartCard from '../components/charts/ChartCard'
import TimeSeriesChart from '../components/charts/TimeSeriesChart'
import CategoryBars from '../components/charts/CategoryBars'
import { VIZ, fmtTitle } from '../components/charts/theme'
import { hh } from '../components/charts/PeakHeatmap'
import { fmtDate, fmtDateTime, fmtInt, fmtNum } from '../utils/format'

const pct = (v) => (v == null ? '—' : `${fmtNum(v)}%`)

function StatusCards({ rows }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {rows.map((r) => (
        <article key={r.department_id} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm" aria-label={`${r.department} status`}>
          <header className="flex items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-slate-900">{r.department}</h3>
            <SeverityChip severity={r.severity} />
          </header>
          {r.active.length ? (
            <ul className="mt-2 space-y-1">
              {r.active.map((a) => <li key={a.condition} className="text-xs text-slate-700">{a.message}</li>)}
            </ul>
          ) : <p className="mt-2 text-xs text-slate-500">No condition is above its threshold.</p>}
          {r.limiting_resource && r.pressure_pct >= 50 && (
            <p className="mt-2 text-xs text-slate-500">Most stretched resource: <span className="font-medium text-slate-700">{r.limiting_resource}</span> ({r.pressure_pct}% of its warning level)</p>
          )}
        </article>
      ))}
    </div>
  )
}

/** Department x condition grid of flagged hours. Number in every cell; shade only reinforces it. */
function Matrix({ rows, conditions }) {
  const max = Math.max(1, ...rows.flatMap((r) => conditions.map((c) => r[c.key] ?? 0)))
  const step = (v) => (v === 0 ? null : Math.min(5, Math.floor((v / max) * 6)))
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] border-separate border-spacing-0.5 text-xs">
        <thead className="text-slate-500"><tr>
          <th className="px-2 py-1 text-left font-medium">Department</th>
          {conditions.map((c) => <th key={c.key} className="px-2 py-1 font-medium">{c.label}</th>)}
          <th className="px-2 py-1 font-medium">Any condition</th>
        </tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.department_id}>
              <th className="px-2 py-1 text-left font-medium text-slate-800">{r.department}</th>
              {conditions.map((c) => {
                const v = r[c.key] ?? 0, s = step(v)
                return <td key={c.key} className="rounded-[3px] px-2 py-1.5 text-center tabular-nums"
                  style={{ background: s == null ? VIZ.empty : VIZ.ramp[s], color: s != null && s >= 3 ? '#fff' : VIZ.text }}
                  title={`${r.department}, ${c.label}: ${v} hours`}>{fmtInt(v)}</td>
              })}
              <td className="px-2 py-1.5 text-center font-semibold tabular-nums">{fmtInt(r.flagged_hours)} <span className="font-normal text-slate-500">({pct(r.flagged_pct)})</span></td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-slate-500">Hours in the selected range when the condition was at warning or critical level. Darker = more hours.</p>
    </div>
  )
}

export default function Bottlenecks() {
  const { params, range, departmentId, ready } = useFilters()
  const q = useApi(() => getBottlenecks(params), [params], { enabled: ready })
  const b = q.data
  const loading = q.loading
  const first = loading && !b
  const noData = ready && b && !b.has_data && !loading
  const hourly = b?.granularity === 'hour'
  const sm = b?.summary
  const scope = [range.from && range.to ? `${fmtDate(range.from)} to ${fmtDate(range.to)}` : 'All available data', departmentId ? 'selected department' : 'all departments'].join(' · ')

  return (
    <PageShell title="Bottleneck Detection" description={`Where and when the hospital is under strain. Showing ${scope}.`}>
      <ErrorBanner message={q.error} onRetry={q.reload} />
      {noData ? (
        <EmptyState icon={Upload} title="No data for this selection" description="Upload an operational dataset or widen the date range."
          action={<Link to="/data" className="inline-flex items-center gap-2 rounded-lg bg-brand-700 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-800"><Upload className="h-4 w-4" /> Go to Data Upload</Link>} />
      ) : (
        <>
          <section aria-label="Bottleneck indicators" className={`grid gap-4 sm:grid-cols-3 transition-opacity ${loading && b ? 'opacity-60' : ''}`}>
            <KpiCard label="Strained hours" icon={Clock} loading={first} value={b ? fmtInt(sm.flagged_hours) : null}
              hint={b ? `of ${fmtInt(sm.total_hours)} department-hours (${fmtNum(sm.flagged_hours / sm.total_hours * 100, 0)}%)` : undefined}
              info="Department-hours where at least one condition is at warning or critical level" />
            <KpiCard label="Critical hours" icon={AlertOctagon} loading={first} value={b ? fmtInt(sm.critical_hours) : null} hint="At least one condition at critical level" />
            <KpiCard label="Most affected department" icon={Flame} loading={first} value={b ? (sm.worst_department ?? 'None') : null} hint="Most strained hours in range, all departments compared" />
          </section>

          <section aria-label="Current status">
            <h2 className="mb-2 text-sm font-semibold text-slate-900">Status at the latest hour {b?.as_of ? <span className="font-normal text-slate-500">({fmtDateTime(b.as_of)})</span> : null}</h2>
            {b ? <StatusCards rows={b.status} /> : <div className="h-24 animate-pulse rounded-xl bg-slate-100" />}
          </section>

          <ChartCard title="Which conditions, where" subtitle="Hours at warning or critical level, by department and condition. All departments shown."
            loading={loading} hasData={!!b?.has_data} error={q.error} onRetry={q.reload}
            table={{ columns: [{ key: 'department', label: 'Department' }, ...(b?.conditions ?? []).map((c) => ({ key: c.key, label: c.label, align: 'right' })), { key: 'flagged_hours', label: 'Any', align: 'right' }], rows: b?.matrix ?? [] }}>
            <Matrix rows={b?.matrix ?? []} conditions={b?.conditions ?? []} />
          </ChartCard>

          <ChartCard title="Strained hours over time" subtitle={`Department-hours per ${hourly ? 'hour' : 'day'} with a condition above threshold`}
            legend={[{ label: 'Warning or critical', color: VIZ.s1 }, { label: 'Critical only', color: VIZ.s2 }]}
            loading={loading} hasData={!!b?.trend?.length} error={q.error} onRetry={q.reload}
            table={{ columns: [{ key: 't', label: hourly ? 'Hour' : 'Day', format: fmtTitle }, { key: 'flagged', label: 'Strained', align: 'right' }, { key: 'critical', label: 'Critical', align: 'right' }], rows: b?.trend ?? [] }}>
            <TimeSeriesChart data={b?.trend ?? []} yFormat={fmtInt}
              series={[{ key: 'flagged', label: 'Warning or critical', color: VIZ.s1 }, { key: 'critical', label: 'Critical only', color: VIZ.s2 }]} />
          </ChartCard>

          <div className="grid gap-4 lg:grid-cols-2">
            <ChartCard title="When pressure builds" subtitle="Share of hours with a condition above threshold, by hour of day"
              loading={loading} hasData={!!b?.hours?.length} error={q.error} onRetry={q.reload}
              table={{ columns: [{ key: 'hour', label: 'Hour', format: hh }, { key: 'flagged_pct', label: 'Strained', align: 'right', format: pct }], rows: b?.hours ?? [] }}>
              <CategoryBars rows={b?.hours ?? []} xKey="hour" yKey="flagged_pct" label="Strained hours" format={(v) => `${fmtNum(v, 0)}%`} xFormat={(h) => hh(h)} tickEvery={3} />
            </ChartCard>

            <ChartCard title="Longest strained periods" subtitle="Runs of at least 3 hours, most critical hours first"
              loading={loading} hasData={!!b?.has_data} error={q.error} onRetry={q.reload}>
              {b?.episodes?.length ? (
                <ul className="divide-y divide-slate-100">
                  {b.episodes.map((e, i) => (
                    <li key={i} className="py-2 text-xs">
                      <p className="flex flex-wrap items-center justify-between gap-2">
                        <span className="font-semibold text-slate-800">{e.department}: {e.main_condition}</span>
                        <span className="tabular-nums text-slate-600">{e.hours} h{e.critical_hours ? `, ${e.critical_hours} critical` : ''}</span>
                      </p>
                      <p className="text-slate-500">{fmtDateTime(e.start)} to {fmtDateTime(e.end)}{e.peak_wait_min != null ? ` · peak wait ${e.peak_wait_min} min` : ''}{e.peak_occupancy_pct != null ? ` · peak occupancy ${e.peak_occupancy_pct}%` : ''}</p>
                      <p className="text-slate-500">Also: {e.conditions.join(', ')}</p>
                    </li>
                  ))}
                </ul>
              ) : <p className="rounded-lg bg-slate-50 px-4 py-6 text-center text-sm text-slate-600">No sustained strained periods in this range.</p>}
            </ChartCard>
          </div>

          <section className="rounded-xl border border-slate-200 bg-white p-4 text-xs text-slate-600" aria-label="How bottlenecks are detected">
            <h2 className="text-sm font-semibold text-slate-900">How bottlenecks are detected</h2>
            <p className="mt-1">Plain rules, no black box. Thresholds can be changed under Alerts &amp; Monitoring.</p>
            <ul className="mt-2 space-y-1">
              {b && b.conditions.map((c) => <li key={c.key}><span className="font-medium text-slate-800">{c.label}:</span> {b.rules[c.key]}</li>)}
            </ul>
          </section>
        </>
      )}
    </PageShell>
  )
}
