import { FileText, History, Trash2 } from 'lucide-react'
import { EmptyState, Skeleton, Spinner } from '../common/Feedback'
import { asUtc, fmtDateTime, fmtInt } from '../../utils/format'

const BADGE = {
  success: 'bg-emerald-50 text-emerald-700',
  failed: 'bg-red-50 text-red-700',
  pending: 'bg-amber-50 text-amber-700',
}

export default function UploadHistory({ uploads, loading, busyId, onView, onDelete }) {
  return (
    <section aria-label="Upload history" className="rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="px-5 py-4">
        <h2 className="text-base font-semibold text-slate-900">Upload history</h2>
        <p className="text-xs text-slate-500">Deleting a successful upload removes the rows it added.</p>
      </div>
      <div className="px-5 pb-5">
        {loading && !uploads && <div className="space-y-2">{[...Array(3)].map((_, i) => <Skeleton key={i} className="h-9" />)}</div>}
        {uploads?.length === 0 && (
          <EmptyState icon={History} title="No uploads yet" description="Uploaded files and their processing results will appear here." />
        )}
        {uploads?.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[680px] text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="py-2 pr-3 font-medium">File</th>
                  <th className="py-2 pr-3 font-medium">When</th>
                  <th className="py-2 pr-3 font-medium">Status</th>
                  <th className="py-2 pr-3 text-right font-medium">Stored</th>
                  <th className="py-2 pr-3 text-right font-medium">Dropped</th>
                  <th className="py-2 pr-3 text-right font-medium">Duplicates</th>
                  <th className="py-2 pr-3 text-right font-medium">Filled</th>
                  <th className="py-2 text-right font-medium"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {uploads.map((u) => (
                  <tr key={u.id}>
                    <td className="max-w-[220px] truncate py-2 pr-3 font-medium text-slate-800" title={u.filename}>{u.filename}</td>
                    <td className="whitespace-nowrap py-2 pr-3 text-slate-600">{fmtDateTime(asUtc(u.uploaded_at))}</td>
                    <td className="py-2 pr-3">
                      <span className={`rounded-full px-2 py-0.5 text-xs font-medium capitalize ${BADGE[u.status] ?? BADGE.pending}`}>{u.status}</span>
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums">{fmtInt(u.rows_valid)}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">{fmtInt(u.rows_dropped)}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">{fmtInt(u.duplicates_removed)}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">{fmtInt(u.missing_filled)}</td>
                    <td className="whitespace-nowrap py-2 text-right">
                      <button onClick={() => onView(u)} className="mr-1 inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-brand-700 hover:bg-brand-50">
                        <FileText className="h-3.5 w-3.5" /> Report
                      </button>
                      <button onClick={() => onDelete(u)} disabled={busyId === u.id}
                        className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
                        aria-label={`Delete upload ${u.filename}`}>
                        {busyId === u.id ? <Spinner className="h-3.5 w-3.5" /> : <Trash2 className="h-3.5 w-3.5" />} Delete
                      </button>
                    </td>
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
