/**
 * Canonical backend entity types mirrored from the FastAPI OpenAPI schema.
 * Every server-mirrored entity has exactly ONE definition here; the per-domain
 * `types.ts` files re-export from this module and layer their own request bodies
 * and page-local shapes on top. Money/decimal fields are decimal STRINGS as the
 * backend serialises them.
 */

/** GET /api/v1/products item (schema: ProductRead). Money fields are decimal strings. */
export interface Product {
  id: number
  code: string
  name: string
  category_id: number
  supplier_id: number | null
  purchase_price: string
  sales_price: string
  vat_rate: string
  shelf_life_days: number | null
  is_active: boolean
  /** Manual override (D5): null = follow Husky; else user-forced. */
  local_status: 'inactive' | 'cancelled' | null
  /** Husky-derived effective activity shown on the status badge. */
  effective_status: 'active' | 'inactive' | 'cancelled'
  husky_synced_at: string | null
  created_at: string
  updated_at: string
}

/** GET /api/v1/categories item (schema: CategoryRead). Returns a bare array, not a Page<T>. */
export interface Category {
  id: number
  name: string
  display_order: number
  dispatch_print_order: number
}

/** GET /api/v1/suppliers item (schema: SupplierRead). */
export interface Supplier {
  id: number
  name: string
  email: string | null
  warehouse_address: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

/** GET /api/v1/fridges item (schema: FridgeRead). */
export interface Fridge {
  id: number
  husky_id: string
  husky_name: string | null
  friendly_name: string
  client_id: number | null
  delivery_address: string | null
  delivery_instructions: string | null
  is_active: boolean
  /** Manual override (D5): null = follow Husky; else user-forced. */
  local_status: 'inactive' | 'cancelled' | null
  /** Husky-derived effective activity shown on the status badge. */
  effective_status: 'active' | 'inactive' | 'cancelled'
  created_at: string
  updated_at: string
}

export type PoStatus = 'pending' | 'received' | 'cancelled'

/** GET /api/v1/purchase-orders line (schema: PurchaseOrderLineRead). */
export interface PurchaseOrderLine {
  id: number
  product_id: number
  product_code: string
  product_name: string
  qty_ordered: number
  qty_received: number
  unit_price: string
  vat_rate: string
  line_ex_vat: string
  line_vat: string
  line_incl_vat: string
}

/** GET /api/v1/purchase-orders item (schema: PurchaseOrderRead). */
export interface PurchaseOrder {
  id: number
  order_no: string
  supplier_id: number
  status: PoStatus
  order_date: string
  expected_delivery_date: string
  delivery_address: string | null
  comment: string | null
  total_ex_vat: string
  total_vat: string
  total_incl_vat: string
  created_at: string
  lines: PurchaseOrderLine[]
}

/** GET /api/v1/settings item (schema: SettingRead). `value` is untyped JSON. */
export interface Setting {
  key: string
  value: unknown
  description: string | null
  updated_at: string
}

/** GET /api/v1/alerts item (schema: AlertRead). */
export interface Alert {
  id: number
  alert_type: string
  payload: Record<string, unknown>
  status: string
  created_at: string
  acknowledged_by: number | null
  acknowledged_at: string | null
}
