import { Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import ChartTooltip from './ChartTooltip'
import { VIZ } from './theme'

/**
 * Grouped columns, one group per department: current (blue) next to scenario (orange).
 * Pair this with ChartCard legend=[{label:'Current',color:VIZ.s1},{label:'Scenario',color:VIZ.s2}].
 * `refLine` draws an optional labelled threshold.
 */
export default function CompareBars({ rows, baseKey = 'base', scenKey = 'scen', label, format = (v) => v, height = 260, refLine }) {
  return (
    <div style={{ height }} role="img" aria-label={`Grouped bar chart of ${label}: current against scenario, by department`}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 12, right: 8, bottom: 0, left: 0 }} barGap={2} barCategoryGap="22%">
          <CartesianGrid vertical={false} stroke={VIZ.grid} />
          <XAxis dataKey="department" interval={0} tick={{ fill: VIZ.textSecondary, fontSize: 11 }} tickLine={false} axisLine={{ stroke: VIZ.baseline }} />
          <YAxis tickFormatter={format} tick={{ fill: VIZ.muted, fontSize: 11 }} tickLine={false} axisLine={false} width={44} />
          <Tooltip cursor={{ fill: 'rgba(11,11,11,0.04)' }} content={<ChartTooltip title={(r) => r.department} format={format} />} />
          {refLine && <ReferenceLine y={refLine.value} stroke={VIZ.muted} strokeDasharray="4 4" label={{ value: refLine.label, position: 'insideTopRight', fill: VIZ.muted, fontSize: 11 }} />}
          <Bar dataKey={baseKey} name="Current" fill={VIZ.s1} barSize={14} radius={[4, 4, 0, 0]} isAnimationActive={false} />
          <Bar dataKey={scenKey} name="Scenario" fill={VIZ.s2} barSize={14} radius={[4, 4, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
