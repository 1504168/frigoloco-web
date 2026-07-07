import type { RouteObject } from 'react-router-dom'
import { RatingPage } from '@/pages/rating/RatingPage'

/**
 * Product Rating domain routes. OWNED BY the rating page-agent: everything under
 * src/pages/rating/ and this array. Mounted as children of AppLayout by
 * src/routes.tsx.
 *
 * Claimed paths:
 *   /rating — full product scorecard (server-side sort + pagination + recompute)
 */
export const ratingRoutes: RouteObject[] = [
  { path: '/rating', element: <RatingPage /> },
]
