import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import api from '../api/client'

const FilterContext = createContext(null)

const MS_DAY = 86400000
const iso = (d) => d.toISOString().slice(0, 10)
const shift = (isoDate, days) => iso(new Date(new Date(`${isoDate}T00:00:00Z`).getTime() + days * MS_DAY))

export const PRESETS = [
  { key: '7d', label: '7 days', days: 7 },
  { key: '30d', label: '30 days', days: 30 },
  { key: '90d', label: '90 days', days: 90 },
  { key: 'all', label: 'All data', days: null },
]

/**
 * Global filters shared by every analytics page: date range + department.
 *
 * Presets are anchored to the NEWEST date in the stored data (not the wall clock), so "30 days" always
 * means the last 30 days of data. Otherwise any historical dataset would show an empty dashboard.
 * Call `refreshDataRange()` after anything that changes the stored data (upload, delete).
 */
export function FilterProvider({ children }) {
  const [preset, setPreset] = useState('30d')
  const [custom, setCustom] = useState({ from: null, to: null })
  const [departmentId, setDepartmentId] = useState(null) // null = all departments
  const [dataRange, setDataRange] = useState({ from: null, to: null, loaded: false })

  const refreshDataRange = useCallback(
    () =>
      api
        .get('/data/stats')
        .then((r) => setDataRange({ from: r.data.date_from?.slice(0, 10) ?? null, to: r.data.date_to?.slice(0, 10) ?? null, loaded: true }))
        .catch(() => setDataRange((d) => ({ ...d, loaded: true }))),
    [],
  )
  useEffect(() => { refreshDataRange() }, [refreshDataRange])

  const anchor = dataRange.to ?? iso(new Date())

  const range = useMemo(() => {
    if (preset === 'custom') return custom
    const p = PRESETS.find((x) => x.key === preset)
    if (!p?.days) return { from: null, to: null }
    return { from: shift(anchor, -(p.days - 1)), to: anchor }
  }, [preset, custom, anchor])

  const applyPreset = useCallback((key) => setPreset(key), [])
  const setCustomRange = useCallback((from, to) => {
    setCustom({ from: from || null, to: to || null })
    setPreset('custom')
  }, [])

  const value = useMemo(() => ({
    preset, range, departmentId, dataRange,
    ready: dataRange.loaded, // false until we know where the data ends
    applyPreset, setCustomRange, setDepartmentId, refreshDataRange,
    // ready-made query params for API calls
    params: {
      ...(range.from ? { from: range.from } : {}),
      ...(range.to ? { to: range.to } : {}),
      ...(departmentId ? { department_id: departmentId } : {}),
    },
  }), [preset, range, departmentId, dataRange, applyPreset, setCustomRange, refreshDataRange])

  return <FilterContext.Provider value={value}>{children}</FilterContext.Provider>
}

export const useFilters = () => {
  const ctx = useContext(FilterContext)
  if (!ctx) throw new Error('useFilters must be used inside <FilterProvider>')
  return ctx
}
