import type { RouteObject } from 'react-router-dom'
import { LossReportPage } from '@/pages/reports/LossReportPage'
import { RestockReportPage } from '@/pages/reports/RestockReportPage'

/** Operations report routes (#56 restock, #57 loss), mounted under AppLayout by src/routes.tsx. */
export const reportsRoutes: RouteObject[] = [
  { path: '/reports/restock', element: <RestockReportPage /> },
  { path: '/reports/loss', element: <LossReportPage /> },
]
