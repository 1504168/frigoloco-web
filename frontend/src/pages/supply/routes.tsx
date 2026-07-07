import type { RouteObject } from 'react-router-dom'
import { PurchaseOrdersPage } from './PurchaseOrdersPage'
import { StockPage } from './StockPage'
import { SuppliersPage } from './SuppliersPage'
import { ClientsPage } from './ClientsPage'
import { FridgesPage } from './FridgesPage'

/**
 * Supply domain routes (Purchase Orders, Stock, Suppliers, Clients, Fridges).
 *
 * OWNED BY: the supply page-agent. This agent owns everything under
 * src/pages/supply/ and this array. Paths are absolute and mounted as children
 * of AppLayout by src/routes.tsx; the matching placeholder entries there are
 * removed as each real page is registered here.
 */
export const supplyRoutes: RouteObject[] = [
  { path: '/purchase-orders', element: <PurchaseOrdersPage /> },
  { path: '/stock', element: <StockPage /> },
  { path: '/masters/suppliers', element: <SuppliersPage /> },
  { path: '/masters/clients', element: <ClientsPage /> },
  { path: '/masters/fridges', element: <FridgesPage /> },
]
