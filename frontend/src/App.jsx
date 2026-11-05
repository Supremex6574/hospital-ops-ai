import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import { useAuth } from './context/AuthContext'
import { FilterProvider } from './context/FilterContext'
import AppLayout from './components/layout/AppLayout'
import { PageLoader } from './components/common/Feedback'
import Login from './pages/Login'
import { NAV } from './routes'

/** Blocks the whole app shell until the user is authenticated. */
function RequireAuth() {
  const { user, booting } = useAuth()
  const location = useLocation()
  if (booting) return <PageLoader label="Checking your session…" />
  if (!user) return <Navigate to="/login" replace state={{ from: location }} />
  return (
    <FilterProvider>
      <Outlet />
    </FilterProvider>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppLayout />}>
          {NAV.map(({ path, element }) => (
            <Route key={path} path={path} element={element} />
          ))}
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
