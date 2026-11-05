import { useState } from 'react'
import { BellRing, CheckCheck, RefreshCw, Save, Settings2 } from 'lucide-react'
import { acknowledgeAlert, acknowledgeAll, getAlerts, getAlertSummary, getThresholds, saveThresholds, scanAlerts } from '../api/alerts'
import { useApi } from '../hooks/useApi'
import { refreshOccupancyBands } from '../hooks/useThresholds'
import { errorMessage } from '../api/client'
import { PageShell } from '../components/common/PageShell'
import KpiCard from '../components/common/KpiCard'
import SeverityChip from '../components/common/SeverityChip'
import { EmptyState, ErrorBanner, Spinner } from '../components/common/Feedback'
import { fmtDateTime, fmtNum } from '../utils/format'
import { DataSources, LiveMonitor } from '../components/monitoring/LiveMonitor'

const TYPE = { occupancy: 'Bed occupancy', wait: 'Waiting time', arrivals: 'Arrival surge', doctors: 'Doctor load', nurses: 'Nurse load', lab: 'Lab overload' }
const notify = () => window.dispatchEvent(new Event('alerts-changed'))

function Thresholds() {
  const q = useApi(() => getThresholds(), [])
  const [edit, setEdit] = useState({})
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState(null)
  const rows = q.data ?? []
  const val = (r) => edit[r.key] ?? r.value

  const save = async () => {
    setSaving(true); setMsg(null)
    try {
      const res = await saveThresholds(Object.fromEntries(Object.entries(edit).map(([k, v]) => [k, Number(v)])))
      refreshOccupancyBands(res.data); setEdit({}); q.reload(); setMsg({ ok: true, text: 'Saved. New thresholds apply to the next analysis and scan.' })
    } catch (e) { setMsg({ ok: false, text: errorMessage(e, 'Could not save the thresholds.') }) } finally { setSaving(false) }
  }

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm" aria-label="Thresholds">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900"><Settings2 className="h-4 w-4" aria-hidden="true" /> Alert thresholds</h2>
      <p className="mt-1 text-xs text-slate-500">Used by bottleneck detection, alerts and the workload index. The four workload weights must add up to 1.</p>
      <ErrorBanner message={q.error} onRetry={q.reload} />
      <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {rows.map((r) => (
          <label key={r.key} className="block text-xs">
            <span className="font-medium text-slate-700">{r.description}</span>
            <input type="number" step="any" min={r.min} max={r.max} value={val(r)} onChange={(e) => setEdit({ ...edit, [r.key]: e.target.value })}
              className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
            <span className="text-slate-400">Allowed {r.min} to {r.max}, default {r.default}</span>
          </label>
        ))}
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button onClick={save} disabled={saving || !Object.keys(edit).length}
          className="inline-flex items-center gap-2 rounded-lg bg-brand-700 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-800 disabled:opacity-50">
          {saving ? <Spinner /> : <Save className="h-4 w-4" />} Save thresholds
        </button>
        {msg && <p role="status" className={`text-xs ${msg.ok ? 'text-emerald-700' : 'text-red-700'}`}>{msg.text}</p>}
      </div>
    </section>
  )
}

export default function Alerts() {
  const [status, setStatus] = useState('open')
  const list = useApi(() => getAlerts({ status }), [status])
  const sum = useApi(() => getAlertSummary(), [])
  const [bump, setBump] = useState(0)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const reload = () => { list.reload(); sum.reload(); notify() }
  const run = async (fn) => { setBusy(true); setErr(''); try { await fn(); reload() } catch (e) { setErr(errorMessage(e, 'That did not work.')) } finally { setBusy(false) } }
  const alerts = list.data ?? []
  const s = sum.data

  return (
    <PageShell title="Alerts & Monitoring" description="Conditions that need attention at the newest hour of data, generated from the bottleneck rules."
      actions={(
        <>
          <button onClick={() => run(scanAlerts)} disabled={busy} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50">
            {busy ? <Spinner /> : <RefreshCw className="h-4 w-4" />} Scan now
          </button>
          <button onClick={() => run(acknowledgeAll)} disabled={busy || !s?.open} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50">
            <CheckCheck className="h-4 w-4" /> Acknowledge all
          </button>
        </>
      )}>
      <ErrorBanner message={err || list.error || sum.error} onRetry={reload} />
      <section aria-label="Alert counts" className="grid gap-4 sm:grid-cols-3">
        <KpiCard label="Open alerts" icon={BellRing} loading={sum.loading && !s} value={s ? fmtNum(s.open, 0) : null} />
        <KpiCard label="Critical" loading={sum.loading && !s} value={s ? fmtNum(s.critical, 0) : null} tone={s?.critical ? 'crit' : 'neutral'} />
        <KpiCard label="Warning" loading={sum.loading && !s} value={s ? fmtNum(s.warning, 0) : null} tone={s?.warning ? 'warn' : 'neutral'} />
      </section>

      <div role="tablist" aria-label="Alert status" className="flex gap-1 rounded-xl border border-slate-200 bg-white p-1 shadow-sm w-fit">
        {[['open', 'Open'], ['acknowledged', 'Acknowledged']].map(([id, label]) => (
          <button key={id} role="tab" aria-selected={status === id} onClick={() => setStatus(id)}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium ${status === id ? 'bg-brand-700 text-white' : 'text-slate-600 hover:bg-slate-50'}`}>{label}</button>
        ))}
      </div>

      {list.loading && !list.data ? <div className="h-32 animate-pulse rounded-xl bg-slate-100" />
        : alerts.length === 0 ? (
          <EmptyState icon={BellRing} title={status === 'open' ? 'No open alerts' : 'No acknowledged alerts'}
            description={status === 'open' ? 'Every monitored condition is within its threshold at the latest hour of data, or no data has been loaded yet.' : 'Alerts you acknowledge will be listed here.'} />
        ) : (
          <ul className={`space-y-2 transition-opacity ${list.loading ? 'opacity-60' : ''}`}>
            {alerts.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
                <SeverityChip severity={a.severity} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-slate-900">{a.department ?? 'Hospital'} · {TYPE[a.type] ?? a.type}</p>
                  <p className="text-xs text-slate-600">{a.message}</p>
                  <p className="text-xs text-slate-400">Data as of {fmtDateTime(a.as_of)}</p>
                </div>
                {!a.acknowledged && (
                  <button onClick={() => run(() => acknowledgeAlert(a.id))} disabled={busy}
                    className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50">Acknowledge</button>
                )}
              </li>
            ))}
          </ul>
        )}

      <LiveMonitor onNewData={() => { list.reload(); sum.reload(); setBump((n) => n + 1) }} />
      <DataSources refreshKey={bump} />

      <Thresholds />
    </PageShell>
  )
}
