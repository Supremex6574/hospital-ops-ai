import { useState } from 'react'
import { Link } from 'react-router-dom'
import { BrainCircuit, Info, Sigma, Target, Upload } from 'lucide-react'
import { getForecastExplanation } from '../api/explain'
import { useApi } from '../hooks/useApi'
import { useFilters } from '../context/FilterContext'
import { PageShell } from '../components/common/PageShell'
import KpiCard from '../components/common/KpiCard'
import { EmptyState, ErrorBanner } from '../components/common/Feedback'
import ChartCard from '../components/charts/ChartCard'
import DepartmentBars from '../components/charts/DepartmentBars'
import CategoryBars from '../components/charts/CategoryBars'
import ContributionBars, { DirectionLegend } from '../components/charts/ContributionBars'
import { fmtDate, fmtNum } from '../utils/format'

const TARGETS = [{ id: 'admissions', label: 'Admissions' }, { id: 'bed_occupancy', label: 'Bed occupancy' }]
const short = (iso) => new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-GB', { weekday: 'short', day: '2-digit', month: 'short', timeZone: 'UTC' })

export default function AIInsights() {
  const { departmentId, ready } = useFilters()
  const [target, setTarget] = useState('admissions')
  const [dayIdx, setDayIdx] = useState(0)
  const q = useApi(() => getForecastExplanation({ target, ...(departmentId ? { department_id: departmentId } : {}) }), [target, departmentId], { enabled: ready })
  const e = q.data
  const pct = target === 'bed_occupancy'
  const dg = pct ? 1 : 0
  const fmt = (v) => fmtNum(v, dg)
  const eff = (v) => { const t = fmtNum(v, 1); return t === '-0' ? '0' : t }
  const first = q.loading && !e
  const ok = e?.explainable
  const day = ok ? e.days[Math.min(dayIdx, e.days.length - 1)] : null
  const scope = departmentId ? 'selected department' : 'whole hospital'

  return (
    <PageShell title="AI Insights" description={`Why the ${pct ? 'bed occupancy' : 'admissions'} forecast looks the way it does (${scope}), explained with SHAP.`}>
      <div role="tablist" aria-label="Forecast target" className="flex w-fit gap-1 rounded-xl border border-slate-200 bg-white p-1 shadow-sm">
        {TARGETS.map((t) => (
          <button key={t.id} role="tab" aria-selected={target === t.id} onClick={() => { setTarget(t.id); setDayIdx(0) }}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium ${target === t.id ? 'bg-brand-700 text-white' : 'text-slate-600 hover:bg-slate-50'}`}>{t.label}</button>
        ))}
      </div>
      <ErrorBanner message={q.error} onRetry={q.reload} />

      {e && !e.has_data && !q.loading ? (
        e.message ? <EmptyState icon={Target} title="Nothing to explain here" description={e.message} />
          : <EmptyState icon={Upload} title="No hospital data loaded yet" description="Upload an operational dataset so a forecasting model can be trained and explained."
              action={<Link to="/data" className="inline-flex items-center gap-2 rounded-lg bg-brand-700 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-800"><Upload className="h-4 w-4" /> Go to Data Upload</Link>} />
      ) : e && e.explainable === false && !q.loading ? (
        <EmptyState icon={BrainCircuit} title={e.model_label ? `${e.model_label} is selected` : 'Not enough history yet'} description={e.message} />
      ) : (
        <>
          <section aria-label="Explanation indicators" className={`grid gap-4 sm:grid-cols-2 xl:grid-cols-4 transition-opacity ${q.loading && e ? 'opacity-60' : ''}`}>
            <KpiCard label="Model explained" icon={BrainCircuit} loading={first} value={ok ? e.model_label : null} hint="The model selected on the Forecasting page" />
            <KpiCard label="Method" icon={Sigma} loading={first} value={ok ? 'SHAP' : null} hint={ok ? e.method : undefined} info="SHAP splits each forecast into a baseline plus one contribution per input; they add up exactly" />
            <KpiCard label="Baseline" icon={Target} loading={first} value={ok ? fmt(e.baseline) : null} unit={ok ? (pct ? '%' : 'patients') : undefined} hint="Average model output before any driver is applied" />
            <KpiCard label="Biggest driver" icon={Info} loading={first} value={ok ? e.groups[0].label : null} hint={ok ? `${fmtNum(e.groups[0].share_pct, 0)}% of the total influence` : undefined} />
          </section>

          {ok && (
            <section className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-700 shadow-sm" aria-label="Summary">
              <ul className="space-y-1">{e.summary.map((t) => <li key={t}>{t}</li>)}</ul>
            </section>
          )}

          <div className="grid gap-4 lg:grid-cols-2">
            <ChartCard title="What the model relies on" subtitle="Share of the total influence on the forecast, by group of inputs"
              loading={q.loading} hasData={ok} error={q.error} onRetry={q.reload}
              table={{ columns: [{ key: 'label', label: 'Driver' }, { key: 'share_pct', label: 'Share', align: 'right', format: (v) => `${fmtNum(v, 1)}%` }, { key: 'mean_abs', label: `Average push (${pct ? 'points' : 'patients'})`, align: 'right', format: (v) => fmtNum(v, 2) }], rows: e?.groups ?? [] }}>
              <DepartmentBars rows={(e?.groups ?? []).map((g, i) => ({ department_id: i, department: g.label, share: g.share_pct }))}
                valueKey="share" label="Share of influence" format={(v) => `${fmtNum(v, 0)}%`} height={220} />
            </ChartCard>

            <ChartCard title="Weekday effect" subtitle={`How much the day of the week moves the forecast on average (${pct ? 'points' : 'patients'})`}
              loading={q.loading} hasData={ok} error={q.error} onRetry={q.reload}
              table={{ columns: [{ key: 'day', label: 'Day' }, { key: 'effect', label: 'Effect', align: 'right', format: (v) => fmtNum(v, 2) }], rows: e?.weekday_effect ?? [] }}>
              <CategoryBars rows={e?.weekday_effect ?? []} xKey="day" yKey="effect" label="Weekday effect" format={eff} signed height={220} />
              <DirectionLegend />
            </ChartCard>
          </div>

          <ChartCard title="Inputs in detail" subtitle="The ten inputs with the largest average push, in the same units as the forecast"
            loading={q.loading} hasData={ok} error={q.error} onRetry={q.reload}
            table={{ columns: [{ key: 'label', label: 'Input' }, { key: 'group', label: 'Group' }, { key: 'mean_abs', label: 'Average push', align: 'right', format: (v) => fmtNum(v, 2) }], rows: e?.features ?? [] }}>
            <DepartmentBars rows={(e?.features ?? []).map((f, i) => ({ department_id: i, department: f.label, push: f.mean_abs }))}
              valueKey="push" label="Average push" format={(v) => fmtNum(v, 2)} height={400} labelWidth={250} />
          </ChartCard>

          <ChartCard title="Why this forecast" subtitle="Pick a day to see what raises or lowers its forecast compared with the baseline"
            loading={q.loading} hasData={ok} error={q.error} onRetry={q.reload}>
            <div role="tablist" aria-label="Forecast day" className="mb-3 flex flex-wrap gap-1">
              {(e?.days ?? []).map((d, i) => (
                <button key={d.date} role="tab" aria-selected={i === dayIdx} onClick={() => setDayIdx(i)}
                  className={`rounded-lg border px-2.5 py-1 text-xs font-medium ${i === dayIdx ? 'border-brand-700 bg-brand-700 text-white' : 'border-slate-200 text-slate-600 hover:bg-slate-50'}`}>{short(d.date)}</button>
              ))}
            </div>
            {day && (
              <>
                <p className="text-sm text-slate-800">
                  <span className="font-semibold">{day.weekday} {fmtDate(day.date)}:</span> expected {fmt(day.predicted)}{pct ? '%' : ' patients'}, starting from a baseline of {fmt(day.baseline)}.
                </p>
                <ContributionBars rows={day.drivers.map((d) => ({ label: d.label, value: d.effect }))} format={eff} />
                <DirectionLegend />
                <ul className="mt-3 space-y-2 text-xs text-slate-600">
                  {day.drivers.map((d) => (
                    <li key={d.group}>
                      <p className="font-medium text-slate-800">{d.sentence}.</p>
                      {d.details.length > 0 && (
                        <p className="text-slate-500">{d.details.map((x) => `${x.label}${x.value != null ? ` (${fmtNum(x.value, 1)})` : ''}: ${Math.abs(x.effect) < 0.05 ? '0.0' : `${x.effect > 0 ? '+' : '−'}${eff(Math.abs(x.effect))}`}`).join(' · ')}</p>
                      )}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </ChartCard>

          <p className="text-xs text-slate-500">
            SHAP shows which inputs the model leans on, not what causes demand in the hospital. The data in this prototype is synthetic, so the patterns reflect how it was generated.
          </p>
        </>
      )}
    </PageShell>
  )
}
