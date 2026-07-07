import {
  Bell,
  Boxes,
  CheckSquare,
  ClipboardList,
  LayoutGrid,
  Package,
  RefreshCw,
  Refrigerator,
  Settings,
  Snowflake,
  Star,
  TrendingUp,
  Truck,
  Users,
  Wallet,
  type LucideIcon,
} from 'lucide-react'

/** A single sidebar link. */
export interface NavItem {
  label: string
  path: string
  icon: LucideIcon
  /** react-query key whose data drives a count badge (e.g. unacknowledged alerts). */
  badgeKey?: 'alerts'
}

/** A titled group of nav links (mirrors the mockup's `.nav-section` blocks). */
export interface NavSection {
  title: string
  items: NavItem[]
}

/**
 * Canonical information architecture. Order and grouping follow the foundation
 * brief and mockups/frigoloco-forecasting-app-mockup.html. Sibling page-agents
 * register the routes for these paths via their domain routes.tsx.
 */
export const NAV_SECTIONS: NavSection[] = [
  {
    title: 'Planning',
    items: [
      { label: 'Forecast', path: '/forecast', icon: TrendingUp },
      { label: 'Menu', path: '/menu', icon: LayoutGrid },
      { label: 'Product Rating', path: '/rating', icon: Star },
    ],
  },
  {
    title: 'Operations',
    items: [
      { label: 'Dispatch', path: '/dispatch', icon: Truck },
      { label: 'Purchase Orders', path: '/purchase-orders', icon: ClipboardList },
      { label: 'Stock', path: '/stock', icon: Boxes },
      { label: 'Verification', path: '/verification', icon: CheckSquare },
    ],
  },
  {
    title: 'Finance',
    items: [{ label: 'Finance', path: '/finance', icon: Wallet }],
  },
  {
    title: 'Masters',
    items: [
      { label: 'Products', path: '/masters/products', icon: Package },
      { label: 'Suppliers', path: '/masters/suppliers', icon: Refrigerator },
      { label: 'Clients', path: '/masters/clients', icon: Users },
      { label: 'Fridges', path: '/masters/fridges', icon: Snowflake },
      { label: 'Sync', path: '/masters/sync', icon: RefreshCw },
    ],
  },
  {
    title: 'System',
    items: [
      { label: 'Alerts', path: '/alerts', icon: Bell, badgeKey: 'alerts' },
      { label: 'Settings', path: '/settings', icon: Settings },
    ],
  },
]
