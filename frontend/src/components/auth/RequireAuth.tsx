import { Navigate, Outlet } from 'react-router-dom'
import { hasToken } from '@/lib/auth'

/**
 * Route guard for the authenticated app shell. When no bearer token is stored,
 * the user is redirected to the public /login page; otherwise the nested routes
 * render. Token presence is sufficient here - an expired token is caught by the
 * api client, which clears it and redirects on the first 401.
 */
export function RequireAuth() {
  if (!hasToken()) {
    return <Navigate to="/login" replace />
  }
  return <Outlet />
}
