import { AlertOctagon, AlertTriangle, CheckCircle2 } from 'lucide-react'

const S = {
  critical: { label: 'Critical', cls: 'bg-red-50 text-red-700', Icon: AlertOctagon },
  warning: { label: 'Warning', cls: 'bg-amber-50 text-amber-800', Icon: AlertTriangle },
  normal: { label: 'Normal', cls: 'bg-emerald-50 text-emerald-800', Icon: CheckCircle2 },
}

/** Severity is always icon + word, never colour alone. */
export default function SeverityChip({ severity }) {
  const s = S[severity] ?? S.normal
  return <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${s.cls}`}><s.Icon className="h-3.5 w-3.5" aria-hidden="true" />{s.label}</span>
}
