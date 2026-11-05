import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import ChartTooltip from './ChartTooltip'
import { VIZ, fmtTick, fmtTitle } from './theme'

const AXIS_TEXT = { fill: VIZ.muted, fontSize: 11 }

/**
 * Line chart over time. 2px lines, hairline horizontal grid, crosshair + one tooltip listing every series.
 * `series`: [{ key, label, color, area?, dashed?, marker?, band? }]  (marker = isolated points only; band = shaded range, dataKey holds [low, high])  ·  `references`: [{ y, label?, position? }] horizontal threshold lines (omit label to draw a bare line).
 */
export default function TimeSeriesChart({ data, series, yFormat = (v) => v, yDomain, references = [], height = 240, tooltipFormat }) {
  return (
    <div style={{ height }} role="img" aria-label={`Line chart: ${series.map((s) => s.label).join(', ')} over time`}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke={VIZ.grid} />
          <XAxis dataKey="t" tickFormatter={fmtTick} tick={AXIS_TEXT} tickLine={false} axisLine={{ stroke: VIZ.baseline }} minTickGap={48} />
          <YAxis tickFormatter={yFormat} tick={AXIS_TEXT} tickLine={false} axisLine={false} width={44} domain={yDomain ?? [0, 'auto']} />
          {references.map((r) => (
            <ReferenceLine key={r.y} y={r.y} stroke={VIZ.baseline} ifOverflow="extendDomain"
              label={r.label ? { value: r.label, position: r.position ?? 'insideTopRight', fill: VIZ.textSecondary, fontSize: 11 } : undefined} />
          ))}
          <Tooltip
            cursor={{ stroke: VIZ.baseline, strokeWidth: 1 }}
            content={<ChartTooltip title={(row) => fmtTitle(row.t)} format={tooltipFormat ?? yFormat} />}
          />
          {series.map((s) =>
            s.band ? (
              <Area key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke="none" fill={s.color} fillOpacity={0.16}
                dot={false} activeDot={false} isAnimationActive={false} connectNulls={false} />
            ) : s.marker ? (
              <Line key={s.key} dataKey={s.key} name={s.label} stroke="none" isAnimationActive={false} connectNulls={false}
                dot={{ r: 5, fill: s.color, stroke: VIZ.surface, strokeWidth: 2 }} activeDot={{ r: 6, fill: s.color, stroke: VIZ.surface, strokeWidth: 2 }} />
            ) : s.area ? (
              <Area key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={s.color} strokeWidth={2} fill={s.color} fillOpacity={0.1}
                dot={false} activeDot={{ r: 4, fill: s.color, stroke: VIZ.surface, strokeWidth: 2 }} connectNulls isAnimationActive={false} />
            ) : (
              <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={s.color} strokeWidth={2} strokeDasharray={s.dashed ? '5 4' : undefined} strokeLinecap="round" strokeLinejoin="round"
                dot={false} activeDot={{ r: 4, fill: s.color, stroke: VIZ.surface, strokeWidth: 2 }} connectNulls isAnimationActive={false} />
            ),
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
