import { AlertTriangle, CheckCircle2, Info } from 'lucide-react'
import { fmtDate, fmtInt, fmtNum } from '../../utils/format'

const LABELS = {
  arrivals: 'Arrivals', admissions: 'Admissions', discharges: 'Discharges', avg_wait_min: 'Waiting time',
  avg_los_hours: 'Length of stay', total_beds: 'Total beds', occupied_beds: 'Occupied beds', available_beds: 'Available beds',
  doctors_available: 'Doctors', nurses_available: 'Nurses', appointments_scheduled: 'Appointments scheduled',
  appointments_completed: 'Appointments completed', lab_tests_ordered: 'Lab tests', lab_capacity: 'Lab capacity',
  equipment_available: 'Equipment available', equipment_total: 'Equipment total',
}
const label = (k) => LABELS[k] ?? k

const FIX_TEXT = {
  occupied_beds_above_total_clipped: (n) => `${fmtInt(n)} rows had more occupied beds than total beds; limited to the total.`,
  available_beds_recomputed: (n) => `${fmtInt(n)} rows had inconsistent available beds; recalculated as total minus occupied.`,
  equipment_available_above_total_clipped: (n) => `${fmtInt(n)} rows had more equipment available than exists; limited to the total.`,
  appointments_completed_above_scheduled_clipped: (n) => `${fmtInt(n)} rows had more completed than scheduled appointments; limited to scheduled.`,
}
const DROP_TEXT = { invalid_or_missing_date: 'unreadable or missing date', missing_department: 'missing department' }

function buildItems(r) {
  const items = []
  const cols = r.columns ?? {}
  const entries = Object.entries(cols).filter(([, v]) => v.present)

  const types = entries.filter(([, v]) => v.type_errors > 0)
  if (types.length) items.push({ tone: 'warn', text: `Non-numeric values replaced: ${types.map(([k, v]) => `${label(k)} (${fmtInt(v.type_errors)})`).join(', ')}.` })

  const neg = entries.filter(([, v]) => v.negative_values > 0)
  if (neg.length) items.push({ tone: 'warn', text: `Negative values treated as missing: ${neg.map(([k, v]) => `${label(k)} (${fmtInt(v.negative_values)})`).join(', ')}.` })

  const miss = Object.entries(r.missing_by_column ?? {})
  if (miss.length)
    items.push({ tone: 'info', text: `${fmtInt(r.missing_filled)} missing values filled using each department's typical value for that hour: ${miss.map(([k, n]) => `${label(k)} (${fmtInt(n)})`).join(', ')}.` })

  if (r.duplicates_removed) items.push({ tone: 'info', text: `${fmtInt(r.duplicates_removed)} exact duplicate rows removed.` })
  if (r.key_conflicts_resolved) items.push({ tone: 'warn', text: `${fmtInt(r.key_conflicts_resolved)} rows shared a date, time and department with different numbers; the later row was kept.` })

  Object.entries(r.dropped_reasons ?? {}).forEach(([k, n]) =>
    items.push({ tone: 'warn', text: `${fmtInt(n)} rows dropped: ${DROP_TEXT[k] ?? k}.` }))
  Object.entries(r.consistency_fixes ?? {}).forEach(([k, n]) => items.push({ tone: 'warn', text: FIX_TEXT[k]?.(n) ?? `${k}: ${n}` }))
  Object.entries(r.outliers_clipped ?? {}).forEach(([k, n]) =>
    items.push({ tone: 'warn', text: `${fmtInt(n)} extreme ${label(k).toLowerCase()} values limited to a plausible maximum.` }))

  const renamed = Object.entries(r.columns_renamed ?? {})
  if (renamed.length) items.push({ tone: 'info', text: `Columns recognised and renamed: ${renamed.map(([a, b]) => `${a} → ${b}`).join(', ')}.` })
  if (r.unknown_columns_dropped?.length) items.push({ tone: 'info', text: `Ignored unrecognised columns: ${r.unknown_columns_dropped.join(', ')}.` })
  if (r.optional_columns_missing?.length)
    items.push({ tone: 'info', text: `Not in the file (defaulted to 0, so related analytics will be limited): ${r.optional_columns_missing.map(label).join(', ')}.` })
  if (r.new_departments?.length) items.push({ tone: 'info', text: `New departments created: ${r.new_departments.join(', ')}.` })
  if (r.rows_replaced) items.push({ tone: 'info', text: `${fmtInt(r.rows_replaced)} existing rows for the same date, time and department were replaced by this upload.` })
  return items
}

const ICON = { ok: CheckCircle2, info: Info, warn: AlertTriangle }
const COLOR = { ok: 'text-sev-ok', info: 'text-sev-info', warn: 'text-sev-warn' }

function Stat({ label: l, value, tone }) {
  return (
    <div className="rounded-lg bg-slate-50 px-3 py-2.5">
      <p className="text-[11px] font-medium uppercase tracking-wide text-slate-500">{l}</p>
      <p className={`text-lg font-semibold tabular-nums ${tone ?? 'text-slate-900'}`}>{value}</p>
    </div>
  )
}

export default function ValidationReport({ filename, report }) {
  const items = buildItems(report)
  const clean = items.every((i) => i.tone === 'info')
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm" aria-label="Validation report">
      <div className="flex flex-wrap items-center gap-2">
        <CheckCircle2 className="h-5 w-5 text-sev-ok" aria-hidden="true" />
        <h2 className="text-base font-semibold text-slate-900">Processed {filename}</h2>
        <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">
          {clean ? 'Clean' : 'Cleaned with fixes'}
        </span>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Rows read" value={fmtInt(report.rows_total)} />
        <Stat label="Rows stored" value={fmtInt(report.rows_valid)} tone="text-sev-ok" />
        <Stat label="Rows dropped" value={fmtInt(report.rows_dropped)} tone={report.rows_dropped ? 'text-sev-warn' : undefined} />
        <Stat label="Duplicates" value={fmtInt(report.duplicates_removed)} />
        <Stat label="Values filled" value={fmtInt(report.missing_filled)} />
        <Stat label="Granularity" value={<span className="capitalize">{report.granularity}</span>} />
      </div>

      <p className="mt-3 text-sm text-slate-600">
        {fmtDate(report.date_range?.from)} to {fmtDate(report.date_range?.to)} · {report.departments?.length} departments:{' '}
        {report.departments?.join(', ')}
      </p>

      <h3 className="mt-5 text-sm font-semibold text-slate-800">What was checked and fixed</h3>
      <ul className="mt-2 space-y-2">
        {items.length === 0 && (
          <li className="flex items-start gap-2 text-sm text-slate-600">
            <CheckCircle2 className={`mt-0.5 h-4 w-4 shrink-0 ${COLOR.ok}`} /> No problems found. Every row was valid and consistent.
          </li>
        )}
        {items.map((it, i) => {
          const Icon = ICON[it.tone]
          return (
            <li key={i} className="flex items-start gap-2 text-sm text-slate-700">
              <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${COLOR[it.tone]}`} aria-hidden="true" /> {it.text}
            </li>
          )
        })}
      </ul>

      {report.summary?.length > 0 && (
        <div className="mt-5 overflow-x-auto">
          <table className="w-full min-w-[560px] text-left text-sm">
            <caption className="sr-only">Per-department summary of the processed data</caption>
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
              {report.summary.map((s) => (
                <tr key={s.department}>
                  <td className="py-2 pr-4 font-medium text-slate-800">{s.department}</td>
                  <td className="py-2 pr-4 text-right tabular-nums">{fmtInt(s.rows)}</td>
                  <td className="py-2 pr-4 text-right tabular-nums">{fmtNum(s.avg_arrivals_per_hour, 2)}</td>
                  <td className="py-2 pr-4 text-right tabular-nums">{s.avg_bed_occupancy_pct == null ? '—' : `${fmtNum(s.avg_bed_occupancy_pct)}%`}</td>
                  <td className="py-2 pr-4 text-right tabular-nums">{fmtNum(s.avg_wait_min)}</td>
                  <td className="py-2 text-right tabular-nums">{fmtNum(s.avg_workload_index)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
