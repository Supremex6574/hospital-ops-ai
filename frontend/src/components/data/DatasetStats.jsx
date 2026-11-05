import { useState } from 'react'
import { CalendarRange, ChevronDown, Database, FileCheck2, Building2 } from 'lucide-react'
import KpiCard from '../common/KpiCard'
import { fmtDate, fmtInt, fmtNum } from '../../utils/format'

const COLS = {
  arrivals: 'Arrivals', admissions: 'Admissions', discharges: 'Discharges', avg_wait_min: 'Waiting time (min)',
  avg_los_hours: 'Length of stay (h)', total_beds: 'Total beds', occupied_beds: 'Occupied beds',
  doctors_available: 'Doctors', nurses_available: 'Nurses', lab_tests_ordered: 'Lab tests', lab_capacity: 'Lab capacity',
}

export default function DatasetStats({ stats, loading }) {
  const [showCols, setShowCols] = useState(false)
  const s = stats

  return (
    <section aria-label="Dataset statistics" className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard label="Stored rows" icon={Database} loading={loading} value={s ? fmtInt(s.total_rows) : null} hint="Hourly department records" />
        <KpiCard label="Date range" icon={CalendarRange} loading={loading}
          value={s?.date_from ? `${fmtDate(s.date_from)}` : null} hint={s?.date_to ? `to ${fmtDate(s.date_to)}` : 'No data yet'} />
        <KpiCard label="Departments" icon={Building2} loading={loading} value={s ? fmtInt(s.departments) : null} />
        <KpiCard label="Successful uploads" icon={FileCheck2} loading={loading} value={s ? fmtInt(s.uploads) : null} />
      </div>

      {s?.total_rows > 0 && (
        <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="overflow-x-auto p-5">
            <table className="w-full min-w-[560px] text-left text-sm">
              <caption className="mb-2 text-left text-sm font-semibold text-slate-800">By department</caption>
              <thead className="text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="py-2 pr-4 font-medium">Department</th>
                  <th className="py-2 pr-4 text-right font-medium">Rows</th>
                  <th className="py-2 pr-4 text-right font-medium">Arrivals / hr</th>
                  <th className="py-2 pr-4 text-right font-medium">Bed occupancy</th>
                  <th className="py-2 pr-4 text-right font-medium">Avg wait (min)</th>
                  <th className="py-2 text-right font-medium">Workload</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {s.per_department.map((d) => (
                  <tr key={d.department_id}>
                    <td className="py-2 pr-4 font-medium text-slate-800">{d.department}</td>
                    <td className="py-2 pr-4 text-right tabular-nums">{fmtInt(d.rows)}</td>
                    <td className="py-2 pr-4 text-right tabular-nums">{fmtNum(d.avg_arrivals_per_hour, 2)}</td>
                    <td className="py-2 pr-4 text-right tabular-nums">{d.avg_bed_occupancy_pct == null ? '—' : `${fmtNum(d.avg_bed_occupancy_pct)}%`}</td>
                    <td className="py-2 pr-4 text-right tabular-nums">{fmtNum(d.avg_wait_min)}</td>
                    <td className="py-2 text-right tabular-nums">{fmtNum(d.avg_workload_index)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <button onClick={() => setShowCols((v) => !v)} aria-expanded={showCols}
            className="flex w-full items-center justify-between border-t border-slate-100 px-5 py-3 text-sm font-medium text-slate-700 hover:bg-slate-50">
            Column statistics
            <ChevronDown className={`h-4 w-4 transition-transform ${showCols ? 'rotate-180' : ''}`} />
          </button>
          {showCols && (
            <div className="overflow-x-auto px-5 pb-5">
              <table className="w-full min-w-[420px] text-left text-sm">
                <thead className="text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="py-2 pr-4 font-medium">Column</th>
                    <th className="py-2 pr-4 text-right font-medium">Min</th>
                    <th className="py-2 pr-4 text-right font-medium">Mean</th>
                    <th className="py-2 text-right font-medium">Max</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {Object.entries(COLS).map(([k, name]) => s.columns[k] && (
                    <tr key={k}>
                      <td className="py-2 pr-4 text-slate-800">{name}</td>
                      <td className="py-2 pr-4 text-right tabular-nums">{fmtNum(s.columns[k].min)}</td>
                      <td className="py-2 pr-4 text-right tabular-nums">{fmtNum(s.columns[k].mean)}</td>
                      <td className="py-2 text-right tabular-nums">{fmtNum(s.columns[k].max)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
