import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Check, CheckCircle2, Clock, Lightbulb, RefreshCw, Undo2, Upload, X } from 'lucide-react'
import { getRecommendations, refreshRecommendations, setRecommendationStatus } from '../api/recommendations'
import { errorMessage } from '../api/client'
import { useApi } from '../hooks/useApi'
import { useFilters } from '../context/FilterContext'
import { PageShell } from '../components/common/PageShell'
import KpiCard from '../components/common/KpiCard'
import PriorityChip from '../components/common/PriorityChip'
import { EmptyState, ErrorBanner, Spinner } from '../components/common/Feedback'
import { fmtDateTime } from '../utils/format'

const STATUS_TABS = [['active', 'Active'], ['dismissed', 'Dismissed'], ['resolved', 'Resolved']]
const notify = () => window.dispatchEvent(new Event('recommendations-changed'))

function Card({ r, busy, onSet }) {
  const accepted = r.status === 'accepted'
  return (
    <article className={`rounded-xl border bg-white p-4 shadow-sm ${accepted ? 'border-emerald-300' : 'border-slate-200'}`} aria-label={r.title}>
      <header className="flex flex-wrap items-center gap-2">
        <PriorityChip priority={r.priority} />
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">{r.category}</span>
        <span className="text-xs text-slate-500">{r.department ?? 'Whole hospital'}</span>
        <span className="ml-auto inline-flex items-center gap-1 text-xs text-slate-500"><Clock className="h-3.5 w-3.5" aria-hidden="true" />{r.horizon}</span>
      </header>
      <h2 className="mt-2 text-base font-semibold text-slate-900">{r.title}</h2>
      <p className="mt-1 text-sm text-slate-800">{r.action}</p>
      <dl className="mt-3 grid gap-3 text-xs sm:grid-cols-2">
        <div><dt className="font-medium text-slate-500">Why</dt><dd className="mt-0.5 text-slate-700">{r.reason}</dd></div>
        <div><dt className="font-medium text-slate-500">Expected effect (estimate)</dt><dd className="mt-0.5 text-slate-700">{r.impact}</dd></div>
      </dl>
      <ul className="mt-3 flex flex-wrap gap-1.5" aria-label="Evidence">
        {r.evidence.map((e) => <li key={e.label} className="rounded-md bg-slate-50 px-2 py-1 text-xs text-slate-600"><span className="text-slate-500">{e.label}:</span> <span className="font-medium text-slate-800">{e.value}</span></li>)}
      </ul>
      <footer className="mt-3 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
        <span className="text-xs text-slate-500">
          {r.confidence === 'high' ? 'Confidence: high, measured in the latest data' : 'Confidence: medium, based on a forecast or a repeating pattern'}
        </span>
        <div className="ml-auto flex gap-2">
          {r.status === 'accepted' && <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-800"><CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />Accepted</span>}
          {r.status === 'new' && (
            <>
              <button disabled={busy} onClick={() => onSet(r.id, 'accepted')} className="inline-flex items-center gap-1 rounded-lg bg-brand-700 px-3 py-1.5 text-xs font-semibold text-white hover:bg-brand-800 disabled:opacity-50"><Check className="h-3.5 w-3.5" />Accept</button>
              <button disabled={busy} onClick={() => onSet(r.id, 'dismissed')} className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"><X className="h-3.5 w-3.5" />Dismiss</button>
            </>
          )}
          {(r.status === 'accepted' || r.status === 'dismissed') && (
            <button disabled={busy} onClick={() => onSet(r.id, 'new')} className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"><Undo2 className="h-3.5 w-3.5" />Undo</button>
          )}
        </div>
      </footer>
    </article>
  )
}

export default function Recommendations() {
  const { departmentId, ready } = useFilters()
  const [status, setStatus] = useState('active')
  const [category, setCategory] = useState('all')
  const q = useApi(() => getRecommendations({ status }), [status], { enabled: ready })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const d = q.data
  const first = q.loading && !d

  const run = async (fn) => { setBusy(true); setErr(''); try { await fn(); q.reload(); notify() } catch (e) { setErr(errorMessage(e, 'That did not work.')) } finally { setBusy(false) } }
  const categories = useMemo(() => ['all', ...new Set((d?.items ?? []).map((i) => i.category))], [d])
  const items = (d?.items ?? []).filter((i) => (category === 'all' || i.category === category) && (!departmentId || i.department_id === departmentId || i.department_id == null))

  return (
    <PageShell title="Recommendations" description="Practical operational actions drawn from the bottlenecks, forecasts and drivers found in the data."
      actions={(
        <button onClick={() => run(refreshRecommendations)} disabled={busy} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50">
          {busy ? <Spinner /> : <RefreshCw className="h-4 w-4" />} Refresh
        </button>
      )}>
      <ErrorBanner message={err || q.error} onRetry={q.reload} />
      {first && <p className="flex items-center gap-2 text-sm text-slate-600" role="status"><Spinner /> Analysing the latest data. The first run trains the forecasts and can take up to half a minute.</p>}

      {d && !d.has_data && !q.loading ? (
        <EmptyState icon={Upload} title="No hospital data loaded yet" description="Upload an operational dataset and recommendations will be generated from it."
          action={<Link to="/data" className="inline-flex items-center gap-2 rounded-lg bg-brand-700 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-800"><Upload className="h-4 w-4" /> Go to Data Upload</Link>} />
      ) : (
        <>
          <section aria-label="Recommendation counts" className="grid gap-4 sm:grid-cols-4">
            <KpiCard label="High priority" loading={first} value={d ? String(d.counts?.high ?? 0) : null} tone={d?.counts?.high ? 'crit' : 'neutral'} hint="Act today" />
            <KpiCard label="Medium priority" loading={first} value={d ? String(d.counts?.medium ?? 0) : null} tone={d?.counts?.medium ? 'warn' : 'neutral'} hint="Plan this week" />
            <KpiCard label="Low priority" loading={first} value={d ? String(d.counts?.low ?? 0) : null} hint="Keep in mind" />
            <KpiCard label="Based on data up to" loading={first} value={d?.as_of ? fmtDateTime(d.as_of) : null} />
          </section>

          <div className="flex flex-wrap items-center gap-3">
            <div role="tablist" aria-label="Status" className="flex gap-1 rounded-xl border border-slate-200 bg-white p-1 shadow-sm">
              {STATUS_TABS.map(([id, label]) => (
                <button key={id} role="tab" aria-selected={status === id} onClick={() => { setStatus(id); setCategory('all') }}
                  className={`rounded-lg px-3 py-1.5 text-sm font-medium ${status === id ? 'bg-brand-700 text-white' : 'text-slate-600 hover:bg-slate-50'}`}>{label}</button>
              ))}
            </div>
            <label className="flex items-center gap-2 text-sm text-slate-600">Category
              <select value={category} onChange={(e) => setCategory(e.target.value)} className="rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm">
                {categories.map((c) => <option key={c} value={c}>{c === 'all' ? 'All categories' : c}</option>)}
              </select>
            </label>
            {departmentId && <span className="text-xs text-slate-500">Showing the selected department and hospital-wide items.</span>}
          </div>

          {items.length === 0 && !first ? (
            <EmptyState icon={Lightbulb} title={status === 'active' ? 'Nothing needs action right now' : `No ${status} recommendations`}
              description={status === 'active' ? 'No department is under sustained strain at the latest hour of data and the forecasts show no coming problem.' : 'Items you change status on will appear here.'} />
          ) : (
            <div className={`space-y-3 transition-opacity ${q.loading && d ? 'opacity-60' : ''}`}>
              {items.map((r) => <Card key={r.id} r={r} busy={busy} onSet={(id, s) => run(() => setRecommendationStatus(id, s))} />)}
            </div>
          )}
          {d?.disclaimer && <p className="text-xs text-slate-500">{d.disclaimer}</p>}
        </>
      )}
    </PageShell>
  )
}
