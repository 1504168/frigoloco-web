import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'

/** The five roles the backend recognises (GET /api/v1/auth/me → role). */
export const USER_ROLES = ['admin', 'ops_manager', 'warehouse', 'driver', 'finance'] as const

export type UserRole = (typeof USER_ROLES)[number]

/** Human-readable labels for each role, used in tables and selects. */
export const ROLE_LABELS: Record<UserRole, string> = {
  admin: 'Admin',
  ops_manager: 'Ops Manager',
  warehouse: 'Warehouse',
  driver: 'Driver',
  finance: 'Finance',
}

/** Shape returned by GET /api/v1/auth/me for the signed-in user. */
export interface CurrentUser {
  id: number
  email: string
  full_name: string
  role: UserRole
}

/** Query key for the current-user identity (shared with the sidebar gate). */
export const CURRENT_USER_KEY = ['auth', 'me'] as const

/**
 * Fetches the signed-in user's identity and role. Used to gate admin-only UI
 * (e.g. the Users nav item). Retries are disabled so an unauthenticated or
 * forbidden response settles immediately instead of hammering the endpoint.
 */
export function useCurrentUser() {
  return useQuery({
    queryKey: CURRENT_USER_KEY,
    queryFn: ({ signal }) => api.get<CurrentUser>('/api/v1/auth/me', { signal }),
    staleTime: 5 * 60_000,
    retry: false,
  })
}

/** Convenience gate: true only once the current user is loaded and is an admin. */
export function useIsAdmin(): boolean {
  const currentUser = useCurrentUser()
  return currentUser.data?.role === 'admin'
}
