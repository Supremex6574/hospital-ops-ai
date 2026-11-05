import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ArrowRight, Info, Play, Plus, SlidersHorizontal, Upload } from 'lucide-react'
import { runOptimization } from '../api/optimization'
import { errorMessage } from '../api/client'
import { PageShell } from '../components/common/PageShell'
import KpiCard from '../components/common/KpiCard'
import ChartCard from '../components/charts/ChartCard'
import CompareBars from '../components/charts/CompareBars'
import { VIZ } from '../components/charts/theme'
import { EmptyState, ErrorBanner, Spinner } from '../components/common/Feedback'
import { fmtNum } from '../utils/format'

const RESOURCES = [['beds', 'Beds'], ['doctors', 'Doctors'], ['nurses', 'Nurses']]
const LEGEND = [{ label: 'Current allocation', color: VIZ.s1 }, { label: 'Proposed allocation', color: VIZ.s2 }]
const signed = (n) => (n > 0 ? `+${n}` : `${n}`)

function Plan({ res }) {
  const nav = useNavigate()
  const sim = res.simulation.hospital
  const unit = res.resource
  const rows = res.rows.map((r) => ({ ...r, base: r.pressure_before, scen: r.pressure_after }))
  const changed = res.rows.some((r) => r.change)
  return (
    <div className="space-y-6">
      <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm" aria-label="Recommendation">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900"><Info className="h-4 w-4" aria-hidden="true" />Result</h2>
        <p className="mt-1 text-base text-slate-900">{res.headline}</p>
        {res.moves.length > 0 && (
          <ul className="mt-3 space-y-1.5">
            {res.moves.map((m, i) => (
              <li key={i} className="flex flex-wrap items-center gap-2 text-sm text-slate-800">
                {m.from ? <><span className="font-medium">{m.from}</span><ArrowRight className="h-4 w-4 text-slate-400" aria-hidden="true" /></> : <><Plus className="h-4 w-4 text-slate-500" aria-hidden="true" /><span className="text-slate-500">New</span><ArrowRight className="h-4 w-4 text-slate-400" aria-hidden="true" /></>}
                <span className="font-medium">{m.to}</span>
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">{m.count} {m.count === 1 ? unit.replace(/s$/, '') : unit}</span>
              </li>
            ))}
          </ul>
        )}
        {changed && (
          <button onClick={() => nav('/what-if', { state: { scenario: res.scenario } })} className="mt-3 inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
            <SlidersHorizontal className="h-4 w-4" /> Test this plan in What-if
          </button>
        )}
      </section>

      <section aria-label="Effect of the plan" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard label="Most stretched department" value={fmtNum(res.pressure_worst_after, 0)} unit="%" hint={`Busy-hour pressure. Now ${fmtNum(res.pressure_worst_before, 0)}%.`} />
        <KpiCard label="Bed demand" value={fmtNum(sim.scenario.demand_pct, 1)} unit="%" hint={`Hospital average. Now ${fmtNum(sim.baseline.demand_pct, 1)}%.`} />
        <KpiCard label="Average wait" value={fmtNum(sim.scenario.wait_min, 0)} unit="min" hint={`Now ${fmtNum(sim.baseline.wait_min, 0)} min.`} />
        <KpiCard label="Patients without a bed" value={fmtNum(sim.scenario.overflow_patients_avg, 1)} hint={`Average. Now ${fmtNum(sim.baseline.overflow_patients_avg, 1)}.`} />
      </section>

      <ChartCard title="Busy-hour pressure by department" subtitle="Load in the busiest 5% of hours as a % of capacity at the planning norm. The plan evens these out." legend={LEGEND} hasData
        table={{ columns: [{ key: 'department', label: 'Department' }, { key: 'current', label: `Now (${unit})`, align: 'right' }, { key: 'proposed', label: `Proposed (${unit})`, align: 'right' }, { key: 'base', label: 'Pressure now', align: 'right', format: (v) => `${fmtNum(v, 0)}%` }, { key: 'scen', label: 'Pressure after', align: 'right', format: (v) => `${fmtNum(v, 0)}%` }], rows }}>
        <CompareBars rows={rows} label="busy-hour pressure" format={(v) => `${fmtNum(v, 0)}%`} refLine={{ value: 100, label: 'At norm' }} />
      </ChartCard>

      <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm" aria-label="Allocation table">
        <h2 className="text-sm font-semibold text-slate-900">Proposed allocation</h2>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full min-w-[480px] text-left text-sm">
            <thead className="text-xs text-slate-500"><tr><th className="py-2 pr-3 font-medium">Department</th><th className="px-3 text-right font-medium">Now</th><th className="px-3 text-right font-medium">Proposed</th><th className="px-3 text-right font-medium">Change</th></tr></thead>
            <tbody className="divide-y divide-slate-100">
              {res.rows.map((r) => (
                <tr key={r.department}><td className="py-2 pr-3 font-medium text-slate-900">{r.department}</td><td className="px-3 text-right tabular-nums">{r.current}</td><td className="px-3 text-right tabular-nums">{r.proposed}</td><td className="px-3 text-right font-semibold tabular-nums">{r.change ? signed(r.change) : '—'}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <ul className="list-disc space-y-1 pl-5 text-xs text-slate-500">{res.notes.map((n) => <li key={n}>{n}</li>)}</ul>
    </div>
  )
}

export default function Optimization() {
  const [resource, setResource] = useState('beds')
  const [extra, setExtra] = useState(0)
  const [limit, setLimit] = useState(30)
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [noData, setNoData] = useState(false)

  const run = async () => {
    setBusy(true); setErr(''); setNoData(false)
    try { setRes((await runOptimization({ resource, extra, max_change_pct: limit })).data) } catch (e) {
      const m = errorMessage(e, 'The optimization could not be run.')
      if (/upload/i.test(m)) setNoData(true); else setErr(m)
    } finally { setBusy(false) }
  }

  return (
    <PageShell title="Optimization" description="Find a better split of beds and on-duty staff across departments, so the busiest hours are equally tight everywhere.">
      <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm" aria-label="Optimization settings">
        <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
          <div role="tablist" aria-label="Resource" className="flex gap-1 rounded-xl border border-slate-200 bg-white p-1">
            {RESOURCES.map(([id, label]) => (
              <button key={id} role="tab" aria-selected={resource === id} onClick={() => { setResource(id); setRes(null) }}
                className={`rounded-lg px-3 py-1.5 text-sm font-medium ${resource === id ? 'bg-brand-700 text-white' : 'text-slate-600 hover:bg-slate-50'}`}>{label}</button>
            ))}
          </div>
          <label className="flex flex-col gap-1 text-xs text-slate-500">Extra {resource} you could add
            <input type="number" min={0} max={100} value={extra || ''} placeholder="0" onChange={(e) => setExtra(Math.min(100, Math.max(0, Math.round(Number(e.target.value) || 0))))} className="w-24 rounded-lg border border-slate-300 px-2 py-1.5 text-sm tabular-nums text-slate-900" />
          </label>
          <label className="flex flex-col gap-1 text-xs text-slate-500">Largest change per department
            <select value={limit} onChange={(e) => setLimit(Number(e.target.value))} className="rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-900">
              {[10, 20, 30, 40, 60].map((v) => <option key={v} value={v}>{v}%</option>)}
            </select>
          </label>
          <button onClick={run} disabled={busy} className="inline-flex items-center gap-2 rounded-lg bg-brand-700 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-800 disabled:opacity-50">
            {busy ? <Spinner /> : <Play className="h-4 w-4" />} Find best allocation
          </button>
        </div>
        <p className="mt-3 text-xs text-slate-500">{resource === 'beds' ? 'Beds can move between ward-type departments (General Ward, Pediatrics, Surgery). Emergency and ICU stay as they are.' : `Reallocates ${resource} on duty across every department, from a pool equal to what is on duty now plus any extra.`}</p>
      </section>

      <ErrorBanner message={err} onRetry={run} />
      {noData && (
        <EmptyState icon={Upload} title="No hospital data loaded yet" description="The optimizer starts from your recent operational data. Upload a dataset first."
          action={<Link to="/data" className="inline-flex items-center gap-2 rounded-lg bg-brand-700 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-800"><Upload className="h-4 w-4" /> Go to Data Upload</Link>} />
      )}
      {res ? <div className={`transition-opacity ${busy ? 'opacity-60' : ''}`}><Plan res={res} /></div> : !noData && !busy && (
        <EmptyState icon={Play} title="Choose a resource and run" description="The optimizer proposes the allocation that makes the busiest hours equally tight across departments." />
      )}
      <p className="text-xs text-slate-500">Planning estimates built from past data and stated assumptions. Not a clinical tool.</p>
    </PageShell>
  )
}
