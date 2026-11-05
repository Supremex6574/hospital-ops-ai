import { useState } from 'react'
import { BarChart3, Table2 } from 'lucide-react'
import { ErrorBanner, Skeleton } from '../common/Feedback'

/**
 * Card frame for every chart: title, optional legend (always shown for 2+ series), a chart/table view
 * toggle, and the refetch behaviour from the dataviz rules: previous render stays, dimmed, while loading.
 *
 * `table` = { columns: [{ key, label, align?, format? }], rows: [...] }
 */
export default function ChartCard({ title, subtitle, legend, table, loading, hasData, error, onRetry, empty, className = '', children }) {
  const [view, setView] = useState('chart')
  const showTable = view === 'table' && table

  return (
    <section className={`rounded-xl border border-slate-200 bg-white p-4 shadow-sm ${className}`} aria-label={title}>
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
          {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
        </div>
        {table && hasData && (
          <button
            onClick={() => setView(showTable ? 'chart' : 'table')}
            className="inline-flex shrink-0 items-center gap-1 rounded-md border border-slate-200 px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50"
            aria-pressed={showTable}
          >
            {showTable ? <BarChart3 className="h-3.5 w-3.5" /> : <Table2 className="h-3.5 w-3.5" />}
            {showTable ? 'Chart' : 'Table'}
          </button>
        )}
      </header>

      {legend?.length > 1 && !showTable && (
        <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1" aria-label="Legend">
          {legend.map((l) => (
            <li key={l.label} className="flex items-center gap-1.5 text-xs text-slate-600">
              {l.band
                ? <span className="inline-block h-2.5 w-4 rounded-sm" style={{ background: l.color, opacity: 0.25 }} aria-hidden="true" />
                : l.marker
                ? <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: l.color }} aria-hidden="true" />
                : <span className="inline-block w-4 border-t-2" style={{ borderColor: l.color, borderStyle: l.dashed ? 'dashed' : 'solid' }} aria-hidden="true" />}
              {l.label}
            </li>
          ))}
        </ul>
      )}

      <div className="mt-3">
        {error && !hasData ? (
          <ErrorBanner message={error} onRetry={onRetry} />
        ) : loading && !hasData ? (
          <Skeleton className="h-56 w-full" />
        ) : !hasData ? (
          <div className="flex h-56 items-center justify-center rounded-lg bg-slate-50 px-6 text-center text-sm text-slate-500">
            {empty ?? 'No data for the selected range and department.'}
          </div>
        ) : (
          <div className={`transition-opacity ${loading ? 'opacity-60' : ''}`}>
            {showTable ? <DataTable table={table} /> : children}
          </div>
        )}
      </div>
    </section>
  )
}

function DataTable({ table }) {
  return (
    <div className="max-h-72 overflow-auto rounded-lg border border-slate-100">
      <table className="w-full text-left text-xs">
        <thead className="sticky top-0 bg-slate-50 text-slate-500">
          <tr>
            {table.columns.map((c) => (
              <th key={c.key} className={`px-3 py-2 font-medium ${c.align === 'right' ? 'text-right' : ''}`}>{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {table.rows.map((r, i) => (
            <tr key={i}>
              {table.columns.map((c) => (
                <td key={c.key} className={`px-3 py-1.5 tabular-nums text-slate-700 ${c.align === 'right' ? 'text-right' : ''}`}>
                  {c.format ? c.format(r[c.key], r) : (r[c.key] ?? '—')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
