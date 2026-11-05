import { useEffect, useRef, useState } from 'react'
import { Activity, Database, FastForward, Flame, Pause, Play } from 'lucide-react'
import { getStreamStatus, getSources, injectSurge, startStream, stepStream, stopStream } from '../../api/stream'
import { getSimulationBaseline } from '../../api/simulation'
import { errorMessage } from '../../api/client'
import { useApi } from '../../hooks/useApi'
import { ErrorBanner, Spinner } from '../common/Feedback'
import { fmtDateTime, fmtNum } from '../../utils/format'

const SPEEDS = [[1, 'Fast (1 s per hour)'], [3, 'Normal (3 s per hour)'], [10, 'Slow (10 s per hour)']]

export function LiveMonitor({ onNewData }) {
  const st = useApi(getStreamStatus, [])
  const depts = useApi(getSimulationBaseline, [])
  const [speed, setSpeed] = useState(3)
  const [surgeDept, setSurgeDept] = useState('Emergency')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const lastTicks = useRef(null)
  const d = st.data
  const running = !!d?.running

  // poll while running; tell the page when a new simulated hour has arrived
  useEffect(() => {
    if (!running) return undefined
    const t = setInterval(() => st.reload(), 2000)
    return () => clearInterval(t)
  }, [running]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!d) return
    if (lastTicks.current != null && d.ticks !== lastTicks.current) { onNewData?.(); window.dispatchEvent(new Event('alerts-changed')) }
    lastTicks.current = d.ticks
  }, [d?.ticks]) // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (fn) => {
    setBusy(true); setErr('')
    try { await fn(); st.reload() } catch (e) { setErr(errorMessage(e, 'That did not work.')) } finally { setBusy(false) }
  }
  const noData = d && !d.data_through
  const surgeActive = d && Object.keys(d.injections ?? {}).length > 0

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm" aria-label="Near-real-time monitoring">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900"><Activity className="h-4 w-4" aria-hidden="true" />Live monitoring (simulated stream)</h2>
        <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${running ? 'bg-emerald-50 text-emerald-800' : 'bg-slate-100 text-slate-600'}`}>
          <span className={`h-2 w-2 rounded-full ${running ? 'bg-emerald-500' : 'bg-slate-400'}`} aria-hidden="true" />{running ? 'Running' : 'Stopped'}
        </span>
        {d?.data_through && <span className="ml-auto text-xs text-slate-500">Data through <span className="font-medium text-slate-800">{fmtDateTime(d.data_through)}</span> · {d.ticks} simulated {d.ticks === 1 ? 'hour' : 'hours'} added</span>}
      </div>
      <p className="mt-1 text-xs text-slate-500">Each tick adds the next hour of data for every department, then re-checks the alerts. Hours are built from the same weekday and hour in recent weeks, with variation. Nothing here is real patient data.</p>

      <ErrorBanner message={err || st.error || d?.error} />
      {noData ? <p className="mt-3 text-sm text-slate-600">Load or upload hospital data first. The stream continues from the newest hour.</p> : (
        <div className="mt-3 flex flex-wrap items-end gap-3">
          {running ? (
            <button onClick={() => act(stopStream)} disabled={busy} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-800 hover:bg-slate-50 disabled:opacity-50"><Pause className="h-4 w-4" />Stop</button>
          ) : (
            <button onClick={() => act(() => startStream(speed))} disabled={busy} className="inline-flex items-center gap-2 rounded-lg bg-brand-700 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-800 disabled:opacity-50">{busy ? <Spinner /> : <Play className="h-4 w-4" />}Start</button>
          )}
          <label className="flex flex-col gap-1 text-xs text-slate-500">Speed
            <select value={speed} disabled={running} onChange={(e) => setSpeed(Number(e.target.value))} className="rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm text-slate-900 disabled:bg-slate-50">
              {SPEEDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
          <button onClick={() => act(() => stepStream(1))} disabled={busy || running} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"><FastForward className="h-4 w-4" />+1 hour</button>
          <button onClick={() => act(() => stepStream(6))} disabled={busy || running} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"><FastForward className="h-4 w-4" />+6 hours</button>
          <div className="ml-auto flex items-end gap-2">
            <label className="flex flex-col gap-1 text-xs text-slate-500">Demonstrate a surge in
              <select value={surgeDept} onChange={(e) => setSurgeDept(e.target.value)} className="rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm text-slate-900">
                {(depts.data?.departments ?? [{ department: 'Emergency' }]).map((x) => <option key={x.department}>{x.department}</option>)}
              </select>
            </label>
            <button onClick={() => act(() => injectSurge(surgeDept, 4))} disabled={busy} className="inline-flex items-center gap-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm font-medium text-amber-900 hover:bg-amber-100 disabled:opacity-50"><Flame className="h-4 w-4" />Surge for 4 hours</button>
          </div>
        </div>
      )}
      {surgeActive && <p role="status" className="mt-2 text-xs text-amber-800">Surge queued: {Object.entries(d.injections).map(([k, v]) => `${k} (${v} h left)`).join(', ')}. It applies to the next simulated hours.</p>}

      {d?.recent?.length > 0 && (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[520px] text-left text-xs">
            <caption className="pb-1 text-left text-xs font-medium text-slate-500">Latest simulated hours</caption>
            <thead className="text-slate-500"><tr><th className="py-1 pr-3 font-medium">Hour</th><th className="px-3 text-right font-medium">Arrivals</th><th className="px-3 text-right font-medium">Bed occupancy</th><th className="px-3 text-right font-medium">Avg wait</th><th className="px-3 text-right font-medium">New alerts</th></tr></thead>
            <tbody className="divide-y divide-slate-100">
              {d.recent.slice(0, 8).map((r) => (
                <tr key={r.timestamp}><td className="py-1 pr-3 text-slate-800">{fmtDateTime(r.timestamp)}</td><td className="px-3 text-right tabular-nums">{r.arrivals}</td><td className="px-3 text-right tabular-nums">{r.occupancy_pct == null ? '—' : `${fmtNum(r.occupancy_pct, 1)}%`}</td><td className="px-3 text-right tabular-nums">{fmtNum(r.avg_wait_min, 0)} min</td><td className="px-3 text-right tabular-nums">{r.new_alerts || '—'}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

export function DataSources({ refreshKey = 0 }) {
  const q = useApi(getSources, [refreshKey])
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm" aria-label="Connected data sources">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900"><Database className="h-4 w-4" aria-hidden="true" />Data sources</h2>
      <p className="mt-1 text-xs text-slate-500">Every source ends up in the same hourly department table, so all analysis works on any of them. The EHR and HIS feeds accept anonymised data only (there is no field for a patient identifier).</p>
      <ErrorBanner message={q.error} onRetry={q.reload} />
      <ul className="mt-3 divide-y divide-slate-100">
        {(q.data ?? []).map((s) => (
          <li key={s.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2 text-sm">
            <div className="min-w-0 flex-1"><p className="font-medium text-slate-900">{s.name}</p><p className="text-xs text-slate-500">{s.description}</p></div>
            <span className="text-xs tabular-nums text-slate-600">{s.available ? `${s.rows.toLocaleString('en-IN')} rows${s.latest ? ` · latest ${fmtDateTime(s.latest)}` : ''}` : 'Not connected'}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
