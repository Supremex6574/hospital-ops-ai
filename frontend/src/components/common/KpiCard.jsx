import { AlertOctagon, AlertTriangle, ArrowDown, ArrowUp, Minus } from 'lucide-react'
import { Skeleton } from './Feedback'
import { VIZ } from '../charts/theme'

const TONES = {
  neutral: 'text-slate-900',
  ok: 'text-sev-ok',
  warn: 'text-sev-warn',
  crit: 'text-sev-crit',
}

const STATUS_STYLE = {
  warn: { cls: 'bg-amber-50 text-amber-800', Icon: AlertTriangle },
  crit: { cls: 'bg-red-50 text-red-700', Icon: AlertOctagon },
}

/**
 * Change vs the previous period. Direction is always shown as an arrow + signed number (never colour alone).
 * `goodWhenUp`: true = an increase is good, false = an increase is bad, null = neither (volume metrics).
 */
function Delta({ pct, goodWhenUp, label }) {
  if (pct == null) return null
  const flat = Math.abs(pct) < 0.5
  const Icon = flat ? Minus : pct > 0 ? ArrowUp : ArrowDown
  let color = VIZ.textSecondary
  if (!flat && goodWhenUp != null) color = (pct > 0) === goodWhenUp ? VIZ.deltaGood : VIZ.critical
  return (
    <p className="mt-1 flex items-center gap-1 text-xs" style={{ color }}>
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      <span className="font-medium tabular-nums">{flat ? 'No change' : `${pct > 0 ? '+' : ''}${pct.toFixed(1)}%`}</span>
      <span className="text-slate-500">{label}</span>
    </p>
  )
}

/**
 * KPI tile. `value` null/undefined renders an em dash (no data); `loading` renders a skeleton.
 * Optional: `delta` { pct, goodWhenUp, label } · `status` { label, tone: 'warn' | 'crit' } · `info` (hover definition).
 */
export default function KpiCard({ label, value, unit, hint, icon: Icon, tone = 'neutral', loading = false, delta, status, info }) {
  const st = status && STATUS_STYLE[status.tone]
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-medium uppercase tracking-wide text-slate-500" title={info}>{label}</p>
        {Icon && (
          <span className="rounded-lg bg-brand-50 p-1.5 text-brand-700">
            <Icon className="h-4 w-4" aria-hidden="true" />
          </span>
        )}
      </div>
      {loading ? (
        <Skeleton className="mt-3 h-8 w-24" />
      ) : (
        <>
          <p className={`mt-2 text-2xl font-semibold ${TONES[tone] ?? TONES.neutral}`}>
            {value ?? '—'}
            {value != null && unit && <span className="ml-1 text-sm font-normal text-slate-500">{unit}</span>}
          </p>
          {st && (
            <p className={`mt-1 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${st.cls}`}>
              <st.Icon className="h-3.5 w-3.5" aria-hidden="true" /> {status.label}
            </p>
          )}
          {delta && <Delta {...delta} />}
        </>
      )}
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  )
}
