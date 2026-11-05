import { useEffect, useMemo, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { ArrowDownRight, ArrowUpRight, BedDouble, Clock, History, Info, Play, RotateCcw, Trash2, Upload, Users } from 'lucide-react'
import { deleteSimulationRun, getSimulationBaseline, getSimulationHistory, getSimulationRun, runSimulation } from '../api/simulation'
import { errorMessage } from '../api/client'
import { useApi } from '../hooks/useApi'
import { useOccupancyBands } from '../hooks/useThresholds'
import { PageShell } from '../components/common/PageShell'
import KpiCard from '../components/common/KpiCard'
import SeverityChip from '../components/common/SeverityChip'
import ChartCard from '../components/charts/ChartCard'
import CompareBars from '../components/charts/CompareBars'
import { VIZ } from '../components/charts/theme'
import { EmptyState, ErrorBanner, Spinner } from '../components/common/Feedback'
import { fmtDateTime, fmtNum } from '../utils/format'

const LEGEND = [{ label: 'Current', color: VIZ.s1 }, { label: 'Scenario', color: VIZ.s2 }]
const STATUS = { ok: 'normal', warning: 'warning', critical: 'critical' }
const EMPTY = { arrivals_change_pct: 0, los_change_pct: 0, departments: {} }

const PRESETS = [
  { id: 'arrivals', label: 'Arrivals +20%', apply: () => ({ ...EMPTY, arrivals_change_pct: 20 }) },
  { id: 'discharge', label: 'Stay 10% shorter', apply: () => ({ ...EMPTY, los_change_pct: -10 }) },
  { id: 'beds', label: '+10 ward beds', apply: () => ({ ...EMPTY, departments: { 'General Ward': { beds_delta: 10 } } }) },
  { id: 'ed', label: 'Emergency: +1 doctor, +2 nurses', apply: () => ({ ...EMPTY, departments: { Emergency: { doctors_delta: 1, nurses_delta: 2 } } }) },
  { id: 'surge', label: 'Busy period: arrivals +30%, stay +10%', apply: () => ({ ...EMPTY, arrivals_change_pct: 30, los_change_pct: 10 }) },
]

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v))
const toNum = (v) => (v === '' || v === '-' ? 0 : Number(v))

function NumberField({ label, value, onChange, min, max, suffix, disabled }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-slate-500">
      {label}
      <span className="flex items-center gap-1">
        <input type="number" inputMode="numeric" value={value || ''} placeholder="0" min={min} max={max} disabled={disabled}
          onChange={(e) => onChange(clamp(Math.round(toNum(e.target.value)), min, max))}
          className="w-20 rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm tabular-nums text-slate-900 disabled:bg-slate-50 disabled:text-slate-400" />
        {suffix && <span className="text-slate-400">{suffix}</span>}
      </span>
    </label>
  )
}

function Slider({ label, value, onChange, min, max, hint }) {
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <label className="text-sm font-medium text-slate-800" htmlFor={label}>{label}</label>
        <span className="text-sm font-semibold tabular-nums text-slate-900">{value > 0 ? '+' : ''}{value}%</span>
      </div>
      <input id={label} type="range" min={min} max={max} step={5} value={value} onChange={(e) => onChange(Number(e.target.value))} className="mt-2 w-full accent-brand-700" />
      <div className="flex justify-between text-[11px] text-slate-400"><span>{min}%</span><span>0</span><span>+{max}%</span></div>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  )
}

function Controls({ base, form, setForm, onRun, running, onReset }) {
  const setDept = (name, key, v) => setForm((f) => ({ ...f, departments: { ...f.departments, [name]: { ...f.departments[name], [key]: v } } }))
  const changed = form.arrivals_change_pct !== 0 || form.los_change_pct !== 0 || Object.values(form.departments).some((d) => Object.values(d).some(Boolean))
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm" aria-label="Scenario controls">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold text-slate-900">Scenario</h2>
        <span className="text-xs text-slate-500">Quick starts:</span>
        {PRESETS.map((p) => (
          <button key={p.id} onClick={() => setForm(p.apply())} className="rounded-full border border-slate-300 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50">{p.label}</button>
        ))}
      </div>

      <div className="mt-4 grid gap-6 md:grid-cols-2">
        <Slider label="Patient arrivals" value={form.arrivals_change_pct} min={-30} max={60} onChange={(v) => setForm((f) => ({ ...f, arrivals_change_pct: v }))} hint="Applies to every department." />
        <Slider label="Length of stay" value={form.los_change_pct} min={-30} max={40} onChange={(v) => setForm((f) => ({ ...f, los_change_pct: v }))} hint="Longer stays keep beds occupied longer; shorter stays free them sooner." />
      </div>

      <h3 className="mt-5 text-sm font-semibold text-slate-900">Capacity changes by department</h3>
      <p className="text-xs text-slate-500">Enter how many to add (positive) or remove (negative). Staff are the doctors and nurses on duty in every hour.</p>
      <div className="mt-2 divide-y divide-slate-100 rounded-lg border border-slate-100">
        {base.departments.map((d) => {
          const v = form.departments[d.department] ?? {}
          return (
            <div key={d.department} className="flex flex-wrap items-end gap-x-6 gap-y-2 px-3 py-3">
              <div className="w-36">
                <p className="text-sm font-medium text-slate-900">{d.department}</p>
                <p className="text-xs text-slate-500">{d.has_beds ? `${fmtNum(d.beds, 0)} beds · ` : 'No beds · '}{fmtNum(d.doctors, 1)} doctors · {fmtNum(d.nurses, 1)} nurses on duty</p>
              </div>
              <NumberField label="Beds" value={v.beds_delta} min={-200} max={200} disabled={!d.has_beds} onChange={(x) => setDept(d.department, 'beds_delta', x)} />
              <NumberField label="Doctors" value={v.doctors_delta} min={-30} max={30} onChange={(x) => setDept(d.department, 'doctors_delta', x)} />
              <NumberField label="Nurses" value={v.nurses_delta} min={-60} max={60} onChange={(x) => setDept(d.department, 'nurses_delta', x)} />
            </div>
          )
        })}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button onClick={onRun} disabled={running} className="inline-flex items-center gap-2 rounded-lg bg-brand-700 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-800 disabled:opacity-50">
          {running ? <Spinner /> : <Play className="h-4 w-4" />} Run simulation
        </button>
        <button onClick={onReset} disabled={running || !changed} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50">
          <RotateCcw className="h-4 w-4" /> Reset
        </button>
        {!changed && <span className="text-xs text-slate-500">No changes entered: the result will match the current situation.</span>}
      </div>
    </section>
  )
}

const KIND = {
  better: { Icon: ArrowDownRight, cls: 'text-emerald-800', word: 'Better' },
  worse: { Icon: ArrowUpRight, cls: 'text-red-700', word: 'Worse' },
  note: { Icon: Info, cls: 'text-slate-600', word: 'Note' },
}

function Findings({ items }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm" aria-label="What changes">
      <h2 className="text-sm font-semibold text-slate-900">What changes</h2>
      <ul className="mt-2 space-y-1.5">
        {items.map((s, i) => {
          const k = KIND[s.kind] ?? KIND.note
          return (
            <li key={i} className={`flex items-start gap-2 text-sm ${k.cls}`}>
              <k.Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <span><span className="font-semibold">{k.word}: </span><span className="text-slate-800">{s.text}</span></span>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

function Results({ res, busy }) {
  const bands = useOccupancyBands()
  const h = res.hospital
  const d = h.delta
  const delta = (key, label = 'vs current') => ({ pct: h.baseline[key] ? (d[key] / h.baseline[key]) * 100 : null, goodWhenUp: false, label })
  const bedDepts = res.departments.filter((x) => x.has_beds)
  const occRows = bedDepts.map((x) => ({ department: x.department, base: x.baseline.demand_pct, scen: x.scenario.demand_pct }))
  const waitRows = res.departments.map((x) => ({ department: x.department, base: x.baseline.wait_min, scen: x.scenario.wait_min }))
  const staffRows = res.departments.map((x) => ({ department: x.department, base: x.baseline.doctor_load_pct, scen: x.scenario.doctor_load_pct }))
  const pct = (v) => (v == null ? '—' : `${fmtNum(v, 0)}%`)
  const min = (v) => (v == null ? '—' : `${fmtNum(v, 0)} min`)

  return (
    <div className={`space-y-6 transition-opacity ${busy ? 'opacity-60' : ''}`}>
      <section aria-label="Hospital effect" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard icon={BedDouble} label="Bed demand" value={fmtNum(h.scenario.demand_pct, 1)} unit="%" delta={delta('demand_pct')} hint={`Current ${fmtNum(h.baseline.demand_pct, 1)}%. Above 100% means more patients than beds.`} />
        <KpiCard icon={Clock} label="Average wait" value={fmtNum(h.scenario.wait_min, 0)} unit="min" delta={delta('wait_min')} hint={`Current ${fmtNum(h.baseline.wait_min, 0)} min`} />
        <KpiCard icon={Users} label="Patients without a bed" value={fmtNum(h.scenario.overflow_patients_avg, 1)} hint={`Average at any hour. Current ${fmtNum(h.baseline.overflow_patients_avg, 1)}.`} tone={h.scenario.overflow_patients_avg >= 1 ? 'crit' : 'neutral'} />
        <KpiCard label={`Hours above ${bands.warning}% occupancy`} value={fmtNum(h.scenario.hours_over_warning_pct, 0)} unit="%" hint={`Current ${fmtNum(h.baseline.hours_over_warning_pct, 0)}% of hours`} />
      </section>

      <Findings items={res.summary} />

      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard title="Bed demand by department" subtitle={`Share of beds needed, average over the last ${res.baseline_days} days. Above 100% = not enough beds.`} legend={LEGEND} hasData={occRows.length > 0}
          table={{ columns: [{ key: 'department', label: 'Department' }, { key: 'base', label: 'Current', align: 'right', format: (v) => pct(v) }, { key: 'scen', label: 'Scenario', align: 'right', format: (v) => pct(v) }], rows: occRows }}>
          <CompareBars rows={occRows} label="bed demand" format={(v) => `${fmtNum(v, 0)}%`} refLine={{ value: bands.warning, label: `Warning ${bands.warning}%` }} />
        </ChartCard>
        <ChartCard title="Average waiting time" subtitle="Minutes, weighted by arrivals." legend={LEGEND} hasData
          table={{ columns: [{ key: 'department', label: 'Department' }, { key: 'base', label: 'Current', align: 'right', format: (v) => min(v) }, { key: 'scen', label: 'Scenario', align: 'right', format: (v) => min(v) }], rows: waitRows }}>
          <CompareBars rows={waitRows} label="waiting time" format={(v) => `${fmtNum(v, 0)}`} />
        </ChartCard>
        <ChartCard title="Doctor workload" subtitle="Patients per doctor against the planning norm. 100% = at the norm; above 130% is flagged as a bottleneck." legend={LEGEND} hasData className="lg:col-span-2"
          table={{ columns: [{ key: 'department', label: 'Department' }, { key: 'base', label: 'Current', align: 'right', format: (v) => pct(v) }, { key: 'scen', label: 'Scenario', align: 'right', format: (v) => pct(v) }], rows: staffRows }}>
          <CompareBars rows={staffRows} label="doctor workload" format={(v) => `${fmtNum(v, 0)}%`} refLine={{ value: 130, label: 'Bottleneck 130%' }} height={240} />
        </ChartCard>
      </div>

      <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm" aria-label="Department detail">
        <h2 className="text-sm font-semibold text-slate-900">Department detail</h2>
        <p className="text-xs text-slate-500">“To stay under warning” is what the busiest 5% of hours in this scenario would need, using the planning norms.</p>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-xs">
            <thead className="text-slate-500">
              <tr><th className="py-2 pr-3 font-medium">Department</th><th className="px-3 font-medium">Status now</th><th className="px-3 font-medium">Status in scenario</th><th className="px-3 text-right font-medium">Bed demand</th><th className="px-3 text-right font-medium">Patients without a bed</th><th className="px-3 text-right font-medium">Wait (min)</th><th className="px-3 font-medium">To stay under warning</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {res.departments.map((x) => (
                <tr key={x.department}>
                  <td className="py-2 pr-3 font-medium text-slate-900">{x.department}</td>
                  <td className="px-3"><SeverityChip severity={STATUS[x.baseline.status]} /></td>
                  <td className="px-3"><SeverityChip severity={STATUS[x.scenario.status]} /></td>
                  <td className="px-3 text-right tabular-nums">{x.has_beds ? `${pct(x.baseline.demand_pct)} → ${pct(x.scenario.demand_pct)}` : '—'}</td>
                  <td className="px-3 text-right tabular-nums">{x.has_beds ? `${fmtNum(x.baseline.overflow_patients_avg, 1)} → ${fmtNum(x.scenario.overflow_patients_avg, 1)}` : '—'}</td>
                  <td className="px-3 text-right tabular-nums">{fmtNum(x.baseline.wait_min, 0)} → {fmtNum(x.scenario.wait_min, 0)}</td>
                  <td className="px-3 text-slate-700">{x.has_beds ? `${x.needs.beds_for_warning} beds, ` : ''}{x.needs.doctors_for_norm} doctors, {x.needs.nurses_for_norm} nurses</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <details className="rounded-xl border border-slate-200 bg-white p-4 text-xs text-slate-600 shadow-sm">
        <summary className="cursor-pointer text-sm font-semibold text-slate-900">How this estimate is made</summary>
        <ul className="mt-2 list-disc space-y-1 pl-5">{res.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
        <p className="mt-2">Waiting-time sensitivity per department (higher means waiting reacts more strongly):</p>
        <ul className="mt-1 list-disc pl-5">
          {res.departments.map((x) => (
            <li key={x.department}>{x.department}: staff load {fmtNum(x.wait_model.staff_elasticity, 2)}{x.has_beds ? `, bed pressure ${fmtNum(x.wait_model.bed_elasticity, 2)}` : ''} ({x.wait_model.source.replace('+', ' + ')})</li>
          ))}
        </ul>
      </details>
    </div>
  )
}

function HistoryPanel({ items, onOpen, onDelete, busy }) {
  const describe = (s) => {
    const parts = []
    if (s.arrivals_change_pct) parts.push(`arrivals ${s.arrivals_change_pct > 0 ? '+' : ''}${s.arrivals_change_pct}%`)
    if (s.los_change_pct) parts.push(`stay ${s.los_change_pct > 0 ? '+' : ''}${s.los_change_pct}%`)
    s.departments.forEach((d) => {
      const bits = []
      if (d.beds_delta) bits.push(`${d.beds_delta > 0 ? '+' : ''}${d.beds_delta} beds`)
      if (d.doctors_delta) bits.push(`${d.doctors_delta > 0 ? '+' : ''}${d.doctors_delta} doctors`)
      if (d.nurses_delta) bits.push(`${d.nurses_delta > 0 ? '+' : ''}${d.nurses_delta} nurses`)
      if (bits.length) parts.push(`${d.department} ${bits.join(', ')}`)
    })
    return parts.length ? parts.join(' · ') : 'No changes (current situation)'
  }
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm" aria-label="Saved simulations">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900"><History className="h-4 w-4" aria-hidden="true" />Previous simulations</h2>
      {items.length === 0 ? <p className="mt-2 text-sm text-slate-500">Each run is saved here so you can compare options later.</p> : (
        <ul className="mt-2 divide-y divide-slate-100">
          {items.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center gap-3 py-2 text-sm">
              <div className="min-w-0 flex-1">
                <p className="truncate text-slate-900">{describe(r.scenario)}</p>
                <p className="text-xs text-slate-500">{fmtDateTime(r.created_at)} · bed demand {fmtNum(r.hospital.baseline.demand_pct, 0)}% → {fmtNum(r.hospital.scenario.demand_pct, 0)}% · wait {fmtNum(r.hospital.baseline.wait_min, 0)} → {fmtNum(r.hospital.scenario.wait_min, 0)} min</p>
              </div>
              <button disabled={busy} onClick={() => onOpen(r.id)} className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50">Open</button>
              <button disabled={busy} onClick={() => onDelete(r.id)} aria-label="Delete this simulation" className="rounded-lg border border-slate-300 p-1.5 text-slate-600 hover:bg-slate-50 disabled:opacity-50"><Trash2 className="h-4 w-4" /></button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export default function WhatIf() {
  const base = useApi(getSimulationBaseline, [])
  const hist = useApi(getSimulationHistory, [])
  const [form, setForm] = useState(EMPTY)
  const [res, setRes] = useState(null)
  const [running, setRunning] = useState(false)
  const [err, setErr] = useState('')
  const incoming = useLocation().state?.scenario

  const body = useMemo(() => ({
    arrivals_change_pct: form.arrivals_change_pct,
    los_change_pct: form.los_change_pct,
    departments: Object.entries(form.departments)
      .filter(([, v]) => Object.values(v).some(Boolean))
      .map(([department, v]) => ({ department, beds_delta: v.beds_delta ?? 0, doctors_delta: v.doctors_delta ?? 0, nurses_delta: v.nurses_delta ?? 0 })),
  }), [form])

  const run = async () => {
    setRunning(true); setErr('')
    try { setRes((await runSimulation(body)).data); hist.reload() } catch (e) { setErr(errorMessage(e, 'The simulation could not be run.')) } finally { setRunning(false) }
  }
  const open = async (id) => {
    setRunning(true); setErr('')
    try {
      const r = (await getSimulationRun(id)).data
      setRes(r)
      const depts = {}
      r.scenario.departments.forEach((d) => { depts[d.department] = { beds_delta: d.beds_delta, doctors_delta: d.doctors_delta, nurses_delta: d.nurses_delta } })
      setForm({ arrivals_change_pct: r.scenario.arrivals_change_pct, los_change_pct: r.scenario.los_change_pct, departments: depts })
    } catch (e) { setErr(errorMessage(e, 'That simulation could not be opened.')) } finally { setRunning(false) }
  }
  const remove = async (id) => {
    try { await deleteSimulationRun(id); hist.reload() } catch (e) { setErr(errorMessage(e, 'That simulation could not be deleted.')) }
  }
  useEffect(() => {
    window.scrollTo?.(0, 0)
    if (incoming) {
      const depts = {}
      ;(incoming.departments ?? []).forEach((d) => { depts[d.department] = { beds_delta: d.beds_delta ?? 0, doctors_delta: d.doctors_delta ?? 0, nurses_delta: d.nurses_delta ?? 0 } })
      setForm({ arrivals_change_pct: incoming.arrivals_change_pct ?? 0, los_change_pct: incoming.los_change_pct ?? 0, departments: depts })
    }
  }, [])

  const noData = base.data && base.data.departments.length === 0

  return (
    <PageShell title="What-if Simulation" description="Change arrivals, length of stay, beds or staff and see the effect on bed demand, waiting time and workload before deciding.">
      <ErrorBanner message={err || base.error} onRetry={base.reload} />
      {noData ? (
        <EmptyState icon={Upload} title="No hospital data loaded yet" description="The simulation starts from your recent operational data. Upload a dataset first."
          action={<Link to="/data" className="inline-flex items-center gap-2 rounded-lg bg-brand-700 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-800"><Upload className="h-4 w-4" /> Go to Data Upload</Link>} />
      ) : base.data ? (
        <>
          <p className="text-xs text-slate-500">Starting point: the last {base.data.baseline_days} days of data, up to {base.data.as_of}.</p>
          <Controls base={base.data} form={form} setForm={setForm} onRun={run} running={running} onReset={() => setForm(EMPTY)} />
          {res ? <Results res={res} busy={running} /> : (
            <EmptyState icon={Play} title="Set up a scenario and run it" description="Pick a quick start or enter your own changes, then choose Run simulation." />
          )}
          <HistoryPanel items={hist.data ?? []} onOpen={open} onDelete={remove} busy={running} />
        </>
      ) : !base.error && <p className="flex items-center gap-2 text-sm text-slate-600" role="status"><Spinner /> Loading current capacity…</p>}
      <p className="text-xs text-slate-500">Planning estimates built from past data and stated assumptions. They are not predictions and not a clinical tool.</p>
    </PageShell>
  )
}
