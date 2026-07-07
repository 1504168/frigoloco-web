import { Navigate, type RouteObject } from 'react-router-dom'
import { AppLayout } from '@/components/layout/AppLayout'
import { PlaceholderPage } from '@/pages/_shared/PlaceholderPage'
import { ProductsPage } from '@/pages/masters/ProductsPage'
import { SyncPage } from '@/pages/masters/SyncPage'
import { AlertsPage } from '@/pages/alerts/AlertsPage'
import { opsRoutes } from '@/pages/ops/routes'
import { supplyRoutes } from '@/pages/supply/routes'
import { financeRoutes } from '@/pages/finance/routes'
import { ratingRoutes } from '@/pages/rating/routes'

/**
 * REAL foundation pages (fetch live backend data). Owned by the foundation.
 */
const foundationRoutes: RouteObject[] = [
  { path: '/masters/products', element: <ProductsPage /> },
  { path: '/masters/sync', element: <SyncPage /> },
  { path: '/alerts', element: <AlertsPage /> },
]

/**
 * TEMPORARY placeholders for nav routes not yet claimed by a domain page-agent.
 * As a domain agent implements one of these, they register it in their
 * pages/<domain>/routes.tsx and REMOVE the matching entry here to avoid a
 * duplicate-path conflict.
 */
const placeholderRoutes: RouteObject[] = []

/**
 * The route tree. Every page renders inside AppLayout (sidebar + topbar).
 * Domain route arrays are composed in via the registry pattern; sibling
 * page-agents only ever touch their own pages/<domain>/routes.tsx.
 */
export const routes: RouteObject[] = [
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: <Navigate to="/masters/products" replace /> },
      ...foundationRoutes,
      ...opsRoutes,
      ...supplyRoutes,
      ...financeRoutes,
      ...ratingRoutes,
      ...placeholderRoutes,
      { path: '*', element: <PlaceholderPage title="Page not found" description="The page you are looking for does not exist." /> },
    ],
  },
]
