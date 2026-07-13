import type { RouteObject } from 'react-router-dom'
import { FinancePage } from '@/pages/finance/FinancePage'
import { VerificationsPage } from '@/pages/finance/VerificationsPage'
import { SettingsPage } from '@/pages/finance/SettingsPage'

/**
 * Finance domain routes. OWNED BY the finance page-agent: everything under
 * src/pages/finance/ and this array. Paths are absolute and mounted as children
 * of AppLayout by src/routes.tsx.
 *
 * Claimed paths (matching placeholders removed from src/routes.tsx):
 *   /finance      - weekly & monthly financials + fridge report
 *   /verification - dispatch reconciliation runs
 *   /settings     - business settings editor
 */
export const financeRoutes: RouteObject[] = [
  { path: '/finance', element: <FinancePage /> },
  { path: '/verification', element: <VerificationsPage /> },
  { path: '/settings', element: <SettingsPage /> },
]
