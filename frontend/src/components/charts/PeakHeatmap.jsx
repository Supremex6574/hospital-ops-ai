import { useRef, useState } from 'react'
import { VIZ } from './theme'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const HOURS = Array.from({ length: 24 }, (_, i) => i)
const hh = (h) => `${String(h).padStart(2, '0')}:00`

/**
 * Weekday x hour grid of average arrivals. One-hue sequential ramp (light = few, dark = many) in six
 * steps with a 2px gap between cells; hover any cell for its exact value. A table view is offered by the card.
 */
export default function PeakHeatmap({ cells, max }) {
  const [tip, setTip] = useState(null)
  const wrap = useRef(null)
  const lookup = new Map(cells.map((c) => [`${c.dow}-${c.hour}`, c.avg_arrivals]))
  const step = (v) => (v == null || !max ? null : Math.min(5, Math.floor((v / max) * 6)))

  const onMove = (e, dow, hour, v) => {
    const box = wrap.current.getBoundingClientRect()
    setTip({ x: e.clientX - box.left, y: e.clientY - box.top, dow, hour, v })
  }

  return (
    <div ref={wrap} className="relative" onPointerLeave={() => setTip(null)}>
      <div className="overflow-x-auto pb-1">
        <div role="img" aria-label="Heatmap of average hourly arrivals by weekday and hour" className="min-w-[640px]">
          <div className="grid items-center gap-0.5" style={{ gridTemplateColumns: '36px repeat(24, minmax(0, 1fr))' }}>
            <span />
            {HOURS.map((h) => (
              <span key={h} className="text-center text-[10px] text-slate-500">{h % 3 === 0 ? h : ''}</span>
            ))}
            {DAYS.map((d, dow) => (
              <div key={d} className="contents">
                <span className="pr-1 text-right text-[11px] text-slate-500">{d}</span>
                {HOURS.map((h) => {
                  const v = lookup.get(`${dow}-${h}`)
                  const s = step(v)
                  return (
                    <div
                      key={h}
                      className="h-[22px] rounded-[3px]"
                      style={{ background: s == null ? VIZ.empty : VIZ.ramp[s] }}
                      onPointerMove={(e) => onMove(e, dow, h, v)}
                    />
                  )
                })}
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-3 flex items-center gap-2 text-[11px] text-slate-500">
        <span>Fewer arrivals</span>
        <span className="flex gap-0.5" aria-hidden="true">
          {VIZ.ramp.map((c) => <span key={c} className="h-3 w-6 rounded-[3px]" style={{ background: c }} />)}
        </span>
        <span>More (up to {max ? max.toFixed(1) : '—'} per hour)</span>
      </div>

      {tip && (
        <div className="pointer-events-none absolute z-10 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-lg"
          style={{ left: Math.min(tip.x + 12, (wrap.current?.clientWidth ?? 600) - 150), top: tip.y + 12 }}>
          <p className="font-medium text-slate-500">{DAYS[tip.dow]}, {hh(tip.hour)}</p>
          <p><span className="font-semibold tabular-nums" style={{ color: VIZ.text }}>{tip.v == null ? '—' : tip.v.toFixed(1)}</span>{' '}
            <span style={{ color: VIZ.textSecondary }}>avg arrivals / hour</span></p>
        </div>
      )}
    </div>
  )
}

export { DAYS, hh }
