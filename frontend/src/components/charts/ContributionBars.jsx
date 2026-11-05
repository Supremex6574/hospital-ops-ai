import { Bar, BarChart, Cell, LabelList, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import ChartTooltip from './ChartTooltip'
import { VIZ } from './theme'

export const RAISE = VIZ.s2   // orange: pushes the forecast up
export const LOWER = VIZ.s1   // blue: pushes it down

/** Diverging bars from zero: one row per driver, signed value at the tip (direction is never colour alone). */
export default function ContributionBars({ rows, format, height }) {
  const h = height ?? Math.max(160, rows.length * 44 + 28)
  const signed = (v) => { const t = format(Math.abs(v)); return Number(t) === 0 ? '0' : `${v > 0 ? '+' : '−'}${t}` }
  return (
    <div style={{ height: h }} role="img" aria-label="Bars showing how much each driver raises or lowers the forecast">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 56, bottom: 0, left: 8 }} barCategoryGap={10}>
          <XAxis type="number" hide domain={['dataMin - 1', 'dataMax + 1']} />
          <YAxis type="category" dataKey="label" width={150} tick={{ fill: VIZ.textSecondary, fontSize: 12 }} tickLine={false} axisLine={false} />
          <ReferenceLine x={0} stroke={VIZ.baseline} />
          <Tooltip cursor={{ fill: 'rgba(11,11,11,0.04)' }} content={<ChartTooltip title={(r) => r.label} format={(v) => signed(v)} />} />
          <Bar dataKey="value" name="Effect" barSize={18} radius={4} isAnimationActive={false}>
            {rows.map((r) => <Cell key={r.label} fill={r.value >= 0 ? RAISE : LOWER} />)}
            <LabelList dataKey="value" position="right" formatter={signed} fill={VIZ.textSecondary} fontSize={11} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export function DirectionLegend() {
  return (
    <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600" aria-label="Legend">
      <li className="flex items-center gap-1.5"><span className="inline-block h-2.5 w-4 rounded-sm" style={{ background: RAISE }} aria-hidden="true" />Raises the forecast (+)</li>
      <li className="flex items-center gap-1.5"><span className="inline-block h-2.5 w-4 rounded-sm" style={{ background: LOWER }} aria-hidden="true" />Lowers the forecast (−)</li>
    </ul>
  )
}
