export const fmtInt = (n) => (n == null ? '—' : Number(n).toLocaleString('en-IN'))

export const fmtNum = (n, digits = 1) =>
  n == null ? '—' : Number(n).toLocaleString('en-IN', { maximumFractionDigits: digits, minimumFractionDigits: 0 })

export const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) : '—')

export const fmtDateTime = (iso) =>
  iso
    ? new Date(iso).toLocaleString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
    : '—'

/** Server timestamps are naive UTC (SQLite/Postgres without tz); mark them so the browser shows local time. */
export const asUtc = (iso) => (iso && !/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? `${iso}Z` : iso)
