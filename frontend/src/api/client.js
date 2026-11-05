import axios from 'axios'

const TOKEN_KEY = 'hops.token'

// sessionStorage: cleared when the tab closes (safer default than localStorage for an admin tool)
export const tokenStore = {
  get: () => sessionStorage.getItem(TOKEN_KEY),
  set: (t) => sessionStorage.setItem(TOKEN_KEY, t),
  clear: () => sessionStorage.removeItem(TOKEN_KEY),
}

const api = axios.create({ baseURL: '/api/v1', timeout: 20000 })

api.interceptors.request.use((config) => {
  const token = tokenStore.get()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Any 401 on a protected call means the session is gone: clear it and let the app redirect to /login.
let onUnauthorized = null
export const setUnauthorizedHandler = (fn) => { onUnauthorized = fn }

api.interceptors.response.use(
  (res) => res,
  (error) => {
    const isLogin = error.config?.url?.includes('/auth/login')
    if (error.response?.status === 401 && !isLogin && onUnauthorized) onUnauthorized()
    return Promise.reject(error)
  },
)

/** Turn any axios error into a short, user-safe message (never logs or shows request bodies). */
export function errorMessage(error, fallback = 'Something went wrong. Please try again.') {
  if (!error.response) {
    return error.code === 'ECONNABORTED'
      ? 'The server took too long to respond.'
      : 'Cannot reach the server. Check that the backend is running.'
  }
  const d = error.response.data?.detail
  if (typeof d === 'string') return d
  if (Array.isArray(d) && d.length) return d.map((x) => x.message).join('; ')
  return fallback
}

export default api
