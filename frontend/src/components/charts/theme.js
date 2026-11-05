// Chart tokens (light surface). Values come from the validated reference palette; the series pair
// blue + orange was checked with the palette validator (CVD ΔE 24.7, normal-vision ΔE 33.6, contrast ≥ 3:1).
export const VIZ = {
  surface: '#fcfcfb',
  text: '#0b0b0b',
  textSecondary: '#52514e',
  muted: '#898781',
  grid: '#e1e0d9',
  baseline: '#c3c2b7',
  deemphasis: '#c9c8c1',
  empty: '#f0efec',
  s1: '#2a78d6', // categorical slot 1: blue
  s2: '#eb6834', // categorical slot 2: orange
  deltaGood: '#006300',
  critical: '#d03b3b',
  // sequential blue ramp (light -> dark = low -> high); heatmaps use six evenly spaced steps
  ramp: ['#b7d3f6', '#86b6ef', '#5598e7', '#2a78d6', '#1c5cab', '#104281'],
}

const fmtUtcDay = (d) => d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', timeZone: 'UTC' })

/** t is "YYYY-MM-DD" (daily bucket) or "YYYY-MM-DDTHH:00" (hourly bucket); parsed as UTC so nothing shifts. */
function parseT(t) {
  const hourly = t.length > 10
  return { hourly, d: new Date(hourly ? `${t}:00Z` : `${t}T00:00:00Z`) }
}

export function fmtTick(t) {
  const { hourly, d } = parseT(t)
  return hourly ? `${fmtUtcDay(d)}, ${String(d.getUTCHours()).padStart(2, '0')}:00` : fmtUtcDay(d)
}

export function fmtTitle(t) {
  const { hourly, d } = parseT(t)
  const day = d.toLocaleDateString('en-GB', { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric', timeZone: 'UTC' })
  return hourly ? `${day}, ${String(d.getUTCHours()).padStart(2, '0')}:00` : day
}
