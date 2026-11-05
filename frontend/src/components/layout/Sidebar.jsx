import { NavLink } from 'react-router-dom'
import { X } from 'lucide-react'
import { BRAND_ICON as BrandIcon, NAV } from '../../routes'

const GROUPS = ['Overview', 'Analytics', 'Intelligence', 'Decision Support']

export default function Sidebar({ open, onClose }) {
  return (
    <>
      {/* mobile backdrop */}
      {open && <div className="fixed inset-0 z-30 bg-slate-900/50 lg:hidden" onClick={onClose} aria-hidden="true" />}

      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-64 flex-col bg-gradient-to-b from-brand-900 to-brand-950 text-brand-50 transition-transform duration-200 lg:static lg:translate-x-0 ${open ? 'translate-x-0' : '-translate-x-full'}`}
        aria-label="Primary navigation"
      >
        <div className="flex h-16 shrink-0 items-center gap-3 px-5">
          <span className="rounded-lg bg-brand-500/20 p-2 text-brand-200"><BrandIcon className="h-5 w-5" /></span>
          <div className="leading-tight">
            <p className="text-sm font-semibold text-white">Hospital Ops AI</p>
            <p className="text-[11px] text-brand-200/80">Decision Support System</p>
          </div>
          <button onClick={onClose} className="ml-auto rounded p-1 text-brand-200 hover:bg-white/10 lg:hidden" aria-label="Close menu">
            <X className="h-5 w-5" />
          </button>
        </div>

        <nav className="flex-1 space-y-5 overflow-y-auto px-3 pb-6 pt-2">
          {GROUPS.map((group) => (
            <div key={group}>
              <p className="px-2 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-brand-200/60">{group}</p>
              <ul className="space-y-0.5">
                {NAV.filter((n) => n.group === group).map(({ path, label, icon: Icon }) => (
                  <li key={path}>
                    <NavLink
                      to={path}
                      end={path === '/'}
                      onClick={onClose}
                      className={({ isActive }) =>
                        `flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
                          isActive ? 'bg-white/15 font-medium text-white shadow-inner' : 'text-brand-100/80 hover:bg-white/10 hover:text-white'
                        }`
                      }
                    >
                      <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                      {label}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>

        <div className="border-t border-white/10 px-5 py-3 text-[11px] leading-snug text-brand-200/70">
          Academic prototype for hospital operations analytics. Not a clinical system.
        </div>
      </aside>
    </>
  )
}
