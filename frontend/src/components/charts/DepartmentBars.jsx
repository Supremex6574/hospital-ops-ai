import { Bar, BarChart, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import ChartTooltip from './ChartTooltip'
import { VIZ } from './theme'

/**
 * Horizontal bars, one per department, sorted high to low, value at the tip.
 * One hue; if a department is selected in the global filter it keeps the accent and the rest recede (emphasis).
 */
export default function DepartmentBars({ rows, valueKey, label, format = (v) => v, selectedId, max, height, labelWidth = 108 }) {
  const data = rows.filter((r) => r[valueKey] != null).sort((a, b) => b[valueKey] - a[valueKey])
  const h = height ?? Math.max(160, data.length * 40 + 24)
  return (
    <div style={{ height: h }} role="img" aria-label={`Bar chart of ${label} by department`}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 52, bottom: 0, left: 0 }} barCategoryGap={10}>
          <XAxis type="number" hide domain={[0, max ?? 'auto']} />
          <YAxis type="category" dataKey="department" width={labelWidth} tick={{ fill: VIZ.textSecondary, fontSize: 12 }} tickLine={false} axisLine={{ stroke: VIZ.baseline }} />
          <Tooltip cursor={{ fill: 'rgba(11,11,11,0.04)' }} content={<ChartTooltip title={(row) => row.department} format={format} />} />
          <Bar dataKey={valueKey} name={label} barSize={18} radius={[0, 4, 4, 0]} isAnimationActive={false}>
            {data.map((r) => (
              <Cell key={r.department_id} fill={selectedId && r.department_id !== selectedId ? VIZ.deemphasis : VIZ.s1} />
            ))}
            <LabelList dataKey={valueKey} position="right" formatter={format} fill={VIZ.textSecondary} fontSize={11} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
