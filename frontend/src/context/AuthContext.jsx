import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import api, { setUnauthorizedHandler, tokenStore } from '../api/client'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  // "booting" = we have a stored token and are verifying it with the server
  const [booting, setBooting] = useState(() => Boolean(tokenStore.get()))

  const logout = useCallback(() => {
    tokenStore.clear()
    setUser(null)
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(logout)
  }, [logout])

  useEffect(() => {
    if (!tokenStore.get()) return
    let cancelled = false
    api.get('/auth/me')
      .then((r) => { if (!cancelled) setUser(r.data) })
      .catch(() => { if (!cancelled) logout() })
      .finally(() => { if (!cancelled) setBooting(false) })
    return () => { cancelled = true }
  }, [logout])

  const login = useCallback(async (username, password) => {
    const { data } = await api.post('/auth/login', { username, password })
    tokenStore.set(data.access_token)
    setUser(data.user)
    return data.user
  }, [])

  const value = useMemo(() => ({ user, booting, login, logout }), [user, booting, login, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export const useAuth = () => {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
