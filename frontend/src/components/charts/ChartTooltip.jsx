import { VIZ } from './theme'

/**
 * One tooltip for every series at the hovered position. Values lead (strong), names follow (secondary);
 * rows are keyed with a short stroke of the series colour. All text is rendered by React (escaped).
 */
export default function ChartTooltip({ active, payload, title, format = (v) => v }) {
  if (!active || !payload?.length) return null
  const rows = payload.filter((p) => p.value != null && p.stroke !== 'none')
  if (!rows.length) return null
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 shadow-lg" style={{ minWidth: 150 }}>
      <p className="mb-1 text-xs font-medium text-slate-500">{title(payload[0].payload, payload[0])}</p>
      <ul className="space-y-0.5">
        {rows.map((p) => (
          <li key={p.dataKey} className="flex items-center gap-2 text-xs">
            <span className="inline-block h-0.5 w-3 rounded" style={{ background: p.color || p.stroke || p.fill || VIZ.s1 }} aria-hidden="true" />
            <span className="font-semibold tabular-nums" style={{ color: VIZ.text }}>{format(p.value, p)}</span>
            {p.name && <span style={{ color: VIZ.textSecondary }}>{p.name}</span>}
          </li>
        ))}
      </ul>
    </div>
  )
}
