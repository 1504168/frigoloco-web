import { QueryClient } from '@tanstack/react-query'
import { ApiError } from '@/lib/api'

/**
 * Shared react-query client with sensible defaults for a data-heavy ops app:
 *  - 30s stale time so quick navigations don't refetch constantly.
 *  - No refetch on window focus (avoids surprise reloads mid-edit).
 *  - Retry transient failures once, but never retry 4xx client errors.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
          return false
        }
        return failureCount < 1
      },
    },
    mutations: {
      retry: false,
    },
  },
})
