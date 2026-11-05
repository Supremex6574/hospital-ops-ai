import { Construction } from 'lucide-react'
import { EmptyState } from './Feedback'

/** Standard page header + content area. */
export function PageShell({ title, description, actions, children }) {
  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{title}</h1>
          {description && <p className="mt-1 text-sm text-slate-500">{description}</p>}
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </header>
      {children}
    </div>
  )
}

/** Placeholder for modules scheduled in a later development phase. */
export function ComingSoon({ title, description, phase }) {
  return (
    <PageShell title={title} description={description}>
      <EmptyState
        icon={Construction}
        title="This module is being built"
        description={`Scheduled for development phase ${phase}. The navigation, filters and API contract are already in place.`}
      />
    </PageShell>
  )
}
