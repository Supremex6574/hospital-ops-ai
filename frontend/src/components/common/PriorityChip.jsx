import { AlertOctagon, AlertTriangle, Info } from 'lucide-react'

const P = {
  high: { label: 'High priority', cls: 'bg-red-50 text-red-700', Icon: AlertOctagon },
  medium: { label: 'Medium priority', cls: 'bg-amber-50 text-amber-800', Icon: AlertTriangle },
  low: { label: 'Low priority', cls: 'bg-slate-100 text-slate-700', Icon: Info },
}

/** Priority is always icon + words, never colour alone. */
export default function PriorityChip({ priority }) {
  const p = P[priority] ?? P.low
  return <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${p.cls}`}><p.Icon className="h-3.5 w-3.5" aria-hidden="true" />{p.label}</span>
}
