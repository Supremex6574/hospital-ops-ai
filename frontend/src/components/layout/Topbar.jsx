import { useEffect, useRef, useState } from 'react'
import { Bell, Building2, CalendarRange, ChevronDown, LogOut, Menu, Upload, User } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import api from '../../api/client'
import { getAlertSummary } from '../../api/alerts'
import { useAuth } from '../../context/AuthContext'
import { PRESETS, useFilters } from '../../context/FilterContext'

/** Polls the API health endpoint so the badge reflects whether the backend is reachable. */
function useApiStatus(intervalMs = 15000) {
  const [online, setOnline] = useState(null)
  useEffect(() => {
    let stop = false
    const ping = () => api.get('/health', { timeout: 5000 }).then(() => !stop && setOnline(true)).catch(() => !stop && setOnline(false))
    ping()
    const id = setInterval(ping, intervalMs)
    return () => { stop = true; clearInterval(id) }
  }, [intervalMs])
  return online
}

function LiveBadge() {
  const online = useApiStatus()
  const style =
    online === null ? 'bg-slate-100 text-slate-500' : online ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'
  const dot = online === null ? 'bg-slate-400' : online ? 'bg-emerald-500 live-dot' : 'bg-red-500'
  const text = online === null ? 'Connecting' : online ? 'API online' : 'API offline'
  return (
    <span className={`hidden items-center gap-2 rounded-full px-3 py-1 text-xs font-medium sm:inline-flex ${style}`} role="status">
      <span className={`h-2 w-2 rounded-full ${dot}`} /> {text}
    </span>
  )
}

function UserMenu() {
  const { user, logout } = useAuth()
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useEffect(() => {
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])
  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen((o) => !o)} className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-slate-100" aria-haspopup="menu" aria-expanded={open}>
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-700 text-sm font-semibold text-white">
          {user?.username?.[0]?.toUpperCase() ?? <User className="h-4 w-4" />}
        </span>
        <span className="hidden text-left leading-tight md:block">
          <span className="block text-sm font-medium text-slate-800">{user?.username}</span>
          <span className="block text-[11px] capitalize text-slate-500">{user?.role}</span>
        </span>
        <ChevronDown className="h-4 w-4 text-slate-400" />
      </button>
      {open && (
        <div role="menu" className="absolute right-0 z-50 mt-2 w-44 rounded-lg border border-slate-200 bg-white py-1 shadow-lg">
          <button role="menuitem" onClick={logout} className="flex w-full items-center gap-2 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50">
            <LogOut className="h-4 w-4" /> Sign out
          </button>
        </div>
      )}
    </div>
  )
}

function FilterBar() {
  const { preset, range, departmentId, applyPreset, setCustomRange, setDepartmentId } = useFilters()
  const [departments, setDepartments] = useState([])

  useEffect(() => {
    let cancelled = false
    api.get('/departments').then((r) => !cancelled && setDepartments(r.data)).catch(() => {})
    return () => { cancelled = true }
  }, [])

  const field = 'rounded-md border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700'

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-slate-200 bg-white px-4 py-2 sm:px-6">
      <div className="flex flex-wrap items-center gap-2">
        <CalendarRange className="h-4 w-4 text-slate-400" aria-hidden="true" />
        <div className="inline-flex overflow-hidden rounded-md border border-slate-300" role="group" aria-label="Date range presets">
          {PRESETS.map((p) => (
            <button
              key={p.key}
              onClick={() => applyPreset(p.key)}
              className={`whitespace-nowrap px-2.5 py-1 text-xs font-medium ${preset === p.key ? 'bg-brand-700 text-white' : 'bg-white text-slate-600 hover:bg-slate-50'}`}
            >
              {p.label}
            </button>
          ))}
        </div>
        <input type="date" aria-label="From date" className={field} value={range.from ?? ''} max={range.to ?? undefined}
          onChange={(e) => { const v = e.target.value; setCustomRange(v, v && range.to && v > range.to ? v : range.to) }} />
        <span className="text-xs text-slate-400">to</span>
        <input type="date" aria-label="To date" className={field} value={range.to ?? ''} min={range.from ?? undefined}
          onChange={(e) => { const v = e.target.value; setCustomRange(v && range.from && v < range.from ? v : range.from, v) }} />
      </div>

      <div className="flex items-center gap-2">
        <Building2 className="h-4 w-4 text-slate-400" aria-hidden="true" />
        <select aria-label="Department" className={`${field} min-w-36`} value={departmentId ?? ''}
          onChange={(e) => setDepartmentId(e.target.value ? Number(e.target.value) : null)}>
          <option value="">All departments</option>
          {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
      </div>
    </div>
  )
}

/** Bell with the number of open alerts; polls the summary and refreshes when alerts change elsewhere. */
function AlertBell() {
  const [sum, setSum] = useState(null)
  const navigate = useNavigate()
  useEffect(() => {
    let live = true
    const load = () => getAlertSummary().then((r) => live && setSum(r.data)).catch(() => {})
    load()
    const id = setInterval(load, 30000)
    window.addEventListener('alerts-changed', load)
    return () => { live = false; clearInterval(id); window.removeEventListener('alerts-changed', load) }
  }, [])
  const n = sum?.open ?? 0
  return (
    <button onClick={() => navigate('/alerts')} className="relative rounded-lg p-2 text-slate-600 hover:bg-slate-100"
      aria-label={n ? `Alerts: ${n} open${sum.critical ? `, ${sum.critical} critical` : ''}` : 'Alerts: none open'}>
      <Bell className="h-5 w-5" />
      {n > 0 && (
        <span className={`absolute -right-0.5 -top-0.5 min-w-[18px] rounded-full px-1 text-center text-[11px] font-semibold leading-[18px] text-white ${sum.critical ? 'bg-red-600' : 'bg-amber-600'}`}>
          {n > 99 ? '99+' : n}
        </span>
      )}
    </button>
  )
}

export default function Topbar({ onMenu }) {
  const navigate = useNavigate()
  return (
    <header className="sticky top-0 z-20">
      <div className="flex h-16 items-center gap-3 border-b border-slate-200 bg-white px-4 sm:px-6">
        <button onClick={onMenu} className="rounded-lg p-2 text-slate-600 hover:bg-slate-100 lg:hidden" aria-label="Open menu">
          <Menu className="h-5 w-5" />
        </button>
        <div className="flex-1" />
        <button onClick={() => navigate('/data')} className="hidden items-center gap-1.5 rounded-lg border border-brand-700 px-3 py-1.5 text-xs font-semibold text-brand-700 hover:bg-brand-50 sm:inline-flex">
          <Upload className="h-3.5 w-3.5" aria-hidden="true" /> Upload data
        </button>
        <LiveBadge />
        <AlertBell />
        <UserMenu />
      </div>
      <FilterBar />
    </header>
  )
}
