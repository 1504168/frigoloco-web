import type { RouteObject } from 'react-router-dom'
import { ForecastPage } from '@/pages/ops/forecast/ForecastPage'
import { MenuPage } from '@/pages/ops/menu/MenuPage'
import { DispatchPage } from '@/pages/ops/dispatch/DispatchPage'

/**
 * Operations / Planning domain routes (Forecast → Menu → Dispatch).
 *
 * OWNED BY: the ops page-agent. Each stage is a single page driven by the
 * (year, week, day) pipeline key held in the URL search params (see
 * `useWeekDayKey`), so the three pages stay in sync as the operator navigates
 * between them. Paths are mounted as children of AppLayout by src/routes.tsx;
 * the nav (config/nav.ts) links to /forecast, /menu and /dispatch.
 */
export const opsRoutes: RouteObject[] = [
  { path: '/forecast', element: <ForecastPage /> },
  { path: '/menu', element: <MenuPage /> },
  { path: '/dispatch', element: <DispatchPage /> },
]
