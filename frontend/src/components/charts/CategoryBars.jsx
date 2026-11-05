import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import ChartTooltip from './ChartTooltip'
import { VIZ } from './theme'

/** Vertical bars over a short ordered category axis (weekdays, hours). One hue, thin bars, rounded tops, tooltip on hover. */
export default function CategoryBars({ rows, xKey, yKey, label, format = (v) => v, height = 240, tickEvery = 1, xFormat = (v) => v, signed = false }) {
  return (
    <div style={{ height }} role="img" aria-label={`Bar chart of ${label}`}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 16, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke={VIZ.grid} />
          <XAxis dataKey={xKey} tickFormatter={xFormat} interval={tickEvery - 1} tick={{ fill: VIZ.muted, fontSize: 11 }} tickLine={false} axisLine={{ stroke: VIZ.baseline }} />
          <YAxis tickFormatter={format} tick={{ fill: VIZ.muted, fontSize: 11 }} tickLine={false} axisLine={false} width={44} domain={signed ? [(m) => Math.floor(m * 1.3), (m) => Math.ceil(m * 1.3)] : undefined} />
          <Tooltip cursor={{ fill: 'rgba(11,11,11,0.04)' }} content={<ChartTooltip title={(r) => xFormat(r[xKey])} format={format} />} />
          {signed && <ReferenceLine y={0} stroke={VIZ.baseline} />}
          <Bar dataKey={yKey} name={label} fill={VIZ.s1} barSize={20} radius={signed ? 4 : [4, 4, 0, 0]} isAnimationActive={false}>
            {signed && rows.map((r) => <Cell key={r[xKey]} fill={r[yKey] >= 0 ? VIZ.s2 : VIZ.s1} />)}
            {rows.length <= 8 && <LabelList dataKey={yKey} position="top" formatter={format} fill={VIZ.textSecondary} fontSize={11} />}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
