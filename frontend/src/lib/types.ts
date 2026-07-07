/**
 * Backend entity types mirrored from the FastAPI OpenAPI schema.
 * Only the entities used by foundation pages live here; each domain page-agent
 * should add its own types alongside its pages (or extend this file for shared ones).
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
