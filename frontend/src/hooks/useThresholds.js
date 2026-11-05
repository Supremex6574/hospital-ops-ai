import { useEffect, useState } from 'react'
import { getThresholds } from '../api/alerts'

const FALLBACK = { warning: 85, critical: 90 }
let cache = null
const listeners = new Set()

/** Occupancy bands from the backend settings (shared by every page). Falls back to the defaults while loading. */
export function useOccupancyBands() {
  const [bands, setBands] = useState(cache ?? FALLBACK)
  useEffect(() => {
    listeners.add(setBands)
    if (!cache) {
      getThresholds().then((r) => {
        const m = Object.fromEntries(r.data.map((t) => [t.key, t.value]))
        cache = { warning: m.occupancy_warning_pct, critical: m.occupancy_critical_pct }
        listeners.forEach((l) => l(cache))
      }).catch(() => {})
    }
    return () => listeners.delete(setBands)
  }, [])
  return bands
}

/** Call after the settings were saved so every open page picks the new bands up. */
export function refreshOccupancyBands(rows) {
  const m = Object.fromEntries(rows.map((t) => [t.key, t.value]))
  cache = { warning: m.occupancy_warning_pct, critical: m.occupancy_critical_pct }
  listeners.forEach((l) => l(cache))
}
