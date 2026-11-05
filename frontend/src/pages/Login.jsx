import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { BarChart3, Eye, EyeOff, Lock, ShieldCheck, User } from 'lucide-react'
import { errorMessage } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { ErrorBanner, Spinner } from '../components/common/Feedback'

const STEPS = ['Analyze', 'Predict', 'Explain', 'Simulate', 'Optimize', 'Recommend', 'Monitor']

export default function Login() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const redirectTo = location.state?.from?.pathname || '/'

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPw, setShowPw] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [touched, setTouched] = useState(false)

  if (user) return <Navigate to={redirectTo} replace />

  const invalid = !username.trim() || !password

  const submit = async (e) => {
    e.preventDefault()
    setTouched(true)
    if (invalid) return
    setBusy(true)
    setError('')
    try {
      await login(username.trim(), password)
      navigate(redirectTo, { replace: true })
    } catch (err) {
      setError(errorMessage(err, 'Sign-in failed. Please try again.'))
      setPassword('')
    } finally {
      setBusy(false)
    }
  }

  const inputBase =
    'w-full rounded-lg border bg-white py-2.5 pl-10 pr-3 text-sm text-slate-900 placeholder:text-slate-400 focus:border-brand-600 focus:outline-none focus:ring-2 focus:ring-brand-600/20'

  return (
    <div className="grid min-h-full lg:grid-cols-2">
      {/* Brand panel */}
      <section className="relative hidden flex-col justify-between overflow-hidden bg-gradient-to-br from-brand-900 via-brand-800 to-brand-950 p-12 text-white lg:flex">
        <div className="absolute -right-24 -top-24 h-96 w-96 rounded-full bg-brand-500/10" aria-hidden="true" />
        <div className="absolute -bottom-32 -left-20 h-96 w-96 rounded-full bg-brand-500/10" aria-hidden="true" />
        <div className="relative flex items-center gap-3">
          <span className="rounded-xl bg-white/10 p-2.5"><BarChart3 className="h-6 w-6" /></span>
          <span className="text-lg font-semibold">Hospital Ops AI</span>
        </div>
        <div className="relative max-w-md">
          <h1 className="text-4xl font-semibold leading-tight tracking-tight">Smart Hospital Operations &amp; Decision Support</h1>
          <p className="mt-4 text-brand-100/80">
            Understand what is happening now, anticipate what comes next, and know what action to take, from patient flow to bed capacity.
          </p>
          <ol className="mt-8 flex flex-wrap gap-2" aria-label="Analytics pipeline">
            {STEPS.map((s, i) => (
              <li key={s} className="flex items-center gap-2 text-sm">
                <span className="rounded-full bg-white/10 px-3 py-1 text-brand-50">{s}</span>
                {i < STEPS.length - 1 && <span className="text-brand-200/50" aria-hidden="true">→</span>}
              </li>
            ))}
          </ol>
        </div>
        <p className="relative text-xs text-brand-200/70">Operational analytics only. No diagnosis, treatment or patient-identifiable data.</p>
      </section>

      {/* Form panel */}
      <section className="flex items-center justify-center bg-slate-50 px-6 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <span className="rounded-xl bg-brand-700 p-2.5 text-white"><BarChart3 className="h-5 w-5" /></span>
            <span className="text-lg font-semibold text-slate-900">Hospital Ops AI</span>
          </div>

          <h2 className="text-2xl font-semibold tracking-tight text-slate-900">Administrator sign in</h2>
          <p className="mt-1 text-sm text-slate-500">Access the operations dashboard.</p>

          <form onSubmit={submit} noValidate className="mt-8 space-y-4">
            <ErrorBanner message={error} />

            <div>
              <label htmlFor="username" className="mb-1.5 block text-sm font-medium text-slate-700">Username</label>
              <div className="relative">
                <User className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" aria-hidden="true" />
                <input id="username" autoComplete="username" autoFocus value={username} maxLength={64}
                  onChange={(e) => setUsername(e.target.value)}
                  aria-invalid={touched && !username.trim()}
                  className={`${inputBase} ${touched && !username.trim() ? 'border-red-400' : 'border-slate-300'}`}
                  placeholder="admin" />
              </div>
              {touched && !username.trim() && <p className="mt-1 text-xs text-red-600">Enter your username.</p>}
            </div>

            <div>
              <label htmlFor="password" className="mb-1.5 block text-sm font-medium text-slate-700">Password</label>
              <div className="relative">
                <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" aria-hidden="true" />
                <input id="password" type={showPw ? 'text' : 'password'} autoComplete="current-password" value={password} maxLength={128}
                  onChange={(e) => setPassword(e.target.value)}
                  aria-invalid={touched && !password}
                  className={`${inputBase} pr-10 ${touched && !password ? 'border-red-400' : 'border-slate-300'}`}
                  placeholder="••••••••" />
                <button type="button" onClick={() => setShowPw((s) => !s)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1.5 text-slate-400 hover:text-slate-600"
                  aria-label={showPw ? 'Hide password' : 'Show password'}>
                  {showPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
              {touched && !password && <p className="mt-1 text-xs text-red-600">Enter your password.</p>}
            </div>

            <button type="submit" disabled={busy}
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-brand-700 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-brand-800 disabled:cursor-not-allowed disabled:opacity-70">
              {busy ? <><Spinner /> Signing in…</> : 'Sign in'}
            </button>
          </form>

          <p className="mt-8 flex items-start gap-2 text-xs text-slate-500">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-brand-700" aria-hidden="true" />
            Academic prototype using synthetic, anonymized data. Not a certified clinical system.
          </p>
        </div>
      </section>
    </div>
  )
}
