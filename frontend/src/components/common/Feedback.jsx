import { AlertCircle, Inbox, Loader2, RefreshCw } from 'lucide-react'

/** Inline spinner for buttons and small areas. */
export function Spinner({ className = 'h-4 w-4' }) {
  return <Loader2 className={`${className} animate-spin`} aria-hidden="true" />
}

/** Full-area loading state. */
export function PageLoader({ label = 'Loading…' }) {
  return (
    <div className="flex h-64 items-center justify-center gap-3 text-slate-500" role="status" aria-live="polite">
      <Spinner className="h-5 w-5 text-brand-600" />
      <span className="text-sm">{label}</span>
    </div>
  )
}

/** Shimmer placeholder block. */
export function Skeleton({ className = 'h-24' }) {
  return <div className={`skeleton ${className}`} aria-hidden="true" />
}

/** Red error banner with optional retry. Messages come from errorMessage(), never raw payloads. */
export function ErrorBanner({ message, onRetry }) {
  if (!message) return null
  return (
    <div role="alert" className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <p className="flex-1">{message}</p>
      {onRetry && (
        <button onClick={onRetry} className="inline-flex items-center gap-1 font-medium text-red-700 hover:underline">
          <RefreshCw className="h-3.5 w-3.5" /> Retry
        </button>
      )}
    </div>
  )
}

/** Friendly empty state with an optional call to action. */
export function EmptyState({ icon: Icon = Inbox, title, description, action }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 bg-white px-6 py-14 text-center">
      <div className="mb-4 rounded-full bg-brand-50 p-3 text-brand-700">
        <Icon className="h-6 w-6" aria-hidden="true" />
      </div>
      <h3 className="text-base font-semibold text-slate-900">{title}</h3>
      {description && <p className="mt-1 max-w-md text-sm text-slate-500">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}
