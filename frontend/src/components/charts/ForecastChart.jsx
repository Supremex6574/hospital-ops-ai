import ChartCard from './ChartCard'
import TimeSeriesChart from './TimeSeriesChart'
import { VIZ, fmtTitle } from './theme'

/** Rows for the chart: recent actuals, the model's backtest predictions, and the forecast with its range. */
export function forecastRows(f, historyDays = 45) {
  if (!f?.history) return []
  const hist = f.history.slice(-historyDays)
  const first = hist[0]?.date
  const test = new Map(f.test.filter((r) => r.date >= first).map((r) => [r.date, r.predicted]))
  const rows = hist.map((h) => ({ t: h.date, actual: h.actual, fitted: test.get(h.date) ?? null, forecast: null, band: null }))
  const last = rows[rows.length - 1]
  if (last) { last.forecast = last.actual; last.band = [last.actual, last.actual] }  // join the lines at the last actual day
  f.forecast.forEach((x) => rows.push({ t: x.date, actual: null, fitted: null, forecast: x.predicted, band: [x.lower, x.upper], lower: x.lower, upper: x.upper }))
  return rows
}

/** Card with actuals, backtest fit and 7-day forecast. `format` formats values; `domain` fixes the y range. */
export default function ForecastChart({ f, loading, error, onRetry, title, subtitle, format, domain, height = 280, historyDays = 45 }) {
  const rows = forecastRows(f, historyDays)
  const has = !!f?.enough
  return (
    <ChartCard title={title} subtitle={subtitle}
      legend={[{ label: 'Actual', color: VIZ.s1 }, { label: 'Model on past days', color: VIZ.muted, dashed: true }, { label: 'Forecast', color: VIZ.s2 }, { label: 'Likely range (80%)', color: VIZ.s2, band: true }]}
      loading={loading} hasData={has} error={error} onRetry={onRetry}
      empty={f?.message ?? 'No forecast available for this selection.'}
      table={{ columns: [{ key: 't', label: 'Day', format: fmtTitle }, { key: 'actual', label: 'Actual', align: 'right', format }, { key: 'fitted', label: 'Model on past days', align: 'right', format }, { key: 'forecast', label: 'Forecast', align: 'right', format }, { key: 'lower', label: 'Low', align: 'right', format }, { key: 'upper', label: 'High', align: 'right', format }], rows }}>
      <TimeSeriesChart data={rows} height={height} yFormat={(v) => format(v)} tooltipFormat={format} yDomain={domain ?? [(m) => Math.max(0, Math.floor(m * 0.85)), (m) => Math.ceil(m * 1.05)]}
        series={[
          { key: 'band', label: 'Likely range', color: VIZ.s2, band: true },
          { key: 'actual', label: 'Actual', color: VIZ.s1 },
          { key: 'fitted', label: 'Model on past days', color: VIZ.muted, dashed: true },
          { key: 'forecast', label: 'Forecast', color: VIZ.s2 },
        ]} />
    </ChartCard>
  )
}
