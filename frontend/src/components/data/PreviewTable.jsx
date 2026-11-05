import { useCallback, useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight, Table2 } from 'lucide-react'
import { errorMessage } from '../../api/client'
import { getPreview } from '../../api/data'
import { useFilters } from '../../context/FilterContext'
import { EmptyState, ErrorBanner, Skeleton } from '../common/Feedback'
import { fmtInt, fmtNum } from '../../utils/format'

const PAGE = 25

/** Paginated view of stored (cleaned) rows. Follows the global date range and department filters. */
export default function PreviewTable({ refreshKey }) {
  const { params, range, departmentId, ready } = useFilters()
  const [offset, setOffset] = useState(0)
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  // reset to the first page whenever the filters change
  useEffect(() => { setOffset(0) }, [range.from, range.to, departmentId, refreshKey])

  const load = useCallback(() => {
    if (!ready) return
    setLoading(true)
    setError('')
    getPreview({ ...params, limit: PAGE, offset })
      .then((r) => setData(r.data))
      .catch((e) => setError(errorMessage(e, 'Could not load the data preview.')))
      .finally(() => setLoading(false))
  }, [params, offset, ready])

  useEffect(load, [load, refreshKey])

  const total = data?.total ?? 0
  const from = total ? offset + 1 : 0
  const to = Math.min(offset + PAGE, total)

  return (
    <section aria-label="Data preview" className="rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-4">
        <div>
          <h2 className="text-base font-semibold text-slate-900">Data preview</h2>
          <p className="text-xs text-slate-500">Cleaned records, newest first. Follows the date range and department filters above.</p>
        </div>
        <div className="flex items-center gap-2 text-sm text-slate-600">
          <span className="tabular-nums">{fmtInt(from)}–{fmtInt(to)} of {fmtInt(total)}</span>
          <button onClick={() => setOffset((o) => Math.max(0, o - PAGE))} disabled={offset === 0 || loading}
            className="rounded-md border border-slate-300 p-1.5 hover:bg-slate-50 disabled:opacity-40" aria-label="Previous page">
            <ChevronLeft className="h-4 w-4" />
          </button>
          <button onClick={() => setOffset((o) => o + PAGE)} disabled={to >= total || loading}
            className="rounded-md border border-slate-300 p-1.5 hover:bg-slate-50 disabled:opacity-40" aria-label="Next page">
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="px-5 pb-5">
        <ErrorBanner message={error} onRetry={load} />
        {loading && !data && <div className="space-y-2">{[...Array(6)].map((_, i) => <Skeleton key={i} className="h-8" />)}</div>}
        {!loading && !error && data && total === 0 && (
          <EmptyState icon={Table2} title="No rows match" description="Upload a dataset, or widen the date range and department filter." />
        )}
        {data && total > 0 && (
          <div className={`overflow-x-auto ${loading ? 'opacity-60' : ''}`}>
            <table className="w-full min-w-[820px] text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  {['Time', 'Department', 'Arrivals', 'Admit', 'Discharge', 'Wait (min)', 'Beds used', 'Doctors', 'Nurses', 'Occupancy', 'Workload'].map((h, i) => (
                    <th key={h} className={`py-2 pr-3 font-medium ${i > 1 ? 'text-right' : ''}`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.rows.map((r, i) => (
                  <tr key={`${r.timestamp}-${r.department}-${i}`}>
                    <td className="whitespace-nowrap py-1.5 pr-3 text-slate-600">{r.timestamp.replace('T', ' ').slice(0, 16)}</td>
                    <td className="py-1.5 pr-3 font-medium text-slate-800">{r.department}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{fmtInt(r.arrivals)}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{fmtInt(r.admissions)}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{fmtInt(r.discharges)}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{fmtNum(r.avg_wait_min)}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{r.total_beds ? `${r.occupied_beds}/${r.total_beds}` : '—'}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{fmtInt(r.doctors_available)}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{fmtInt(r.nurses_available)}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{r.bed_occupancy_pct == null ? '—' : `${fmtNum(r.bed_occupancy_pct)}%`}</td>
                    <td className="py-1.5 text-right tabular-nums">{fmtNum(r.workload_index)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  )
}
