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
  supplier_name: string | null
  purchase_price: string
  sales_price: string
  vat_rate: string
  shelf_life_days: number | null
  is_active: boolean
  /** Manual override (D5): null = follow Husky; else user-forced. */
  local_status: 'inactive' | 'cancelled' | null
  /** Husky-derived effective activity shown on the status badge. */
  effective_status: 'active' | 'inactive' | 'cancelled'
  /** Warehouse minimum: below it a low_stock alert opens. Null = no minimum. */
  min_stock_qty: number | null
  /** Position on the printed dispatch sheet inside the category. Null = after numbered ones. */
  print_order: number | null
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
  /** False = historic category: none of its products is active any more. */
  has_active_products: boolean
}

/** GET /api/v1/suppliers item (schema: SupplierRead). */
export interface Supplier {
  id: number
  name: string
  email: string | null
  warehouse_address: string | null
  /** Person to call when goods do not arrive. */
  contact_name: string | null
  contact_phone: string | null
  /** Payment conditions: days after the invoice (30, 60). Null = not recorded. */
  payment_terms_days: number | null
  /** True = the days count from the end of the invoice month. */
  payment_terms_end_of_month: boolean
  is_active: boolean
  created_at: string
  updated_at: string
}

export type SupplierAgreementBasis = 'year_end_rebate' | 'price_discount'

/** GET /api/v1/suppliers/{id}/agreements item. Reference data: no effect on prices. */
export interface SupplierAgreement {
  id: number
  supplier_id: number
  year: number
  /** A percentage as a decimal string: "2.50" = 2.5 %. */
  discount_pct: string
  basis: SupplierAgreementBasis
  review_date: string | null
  notes: string | null
}

/** GET/PUT /api/v1/suppliers/{id}/delivery-schedule item. Weekdays are ISO (Mon=1 … Sun=7). */
export interface SupplierDeliverySchedule {
  delivery_weekday: number
  /** Same weekday as the delivery = order the same day before cutoff_time. */
  cutoff_weekday: number
  /** "HH:MM:SS" Brussels time. */
  cutoff_time: string
}

/** GET /api/v1/suppliers/{id}/next-delivery (null when the supplier has no schedule). */
export interface SupplierNextDelivery {
  delivery_date: string
  order_deadline: string
}

/** GET /api/v1/suppliers/category-links item: a supplier with products in a category. */
export interface SupplierCategoryLink {
  supplier_id: number
  category_id: number
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
  /** ISO weekday numbers (Mon=1 … Sun=7) this fridge has delivery configured for. */
  delivery_weekdays: number[]
  /** 4G/5G modem number. */
  modem_number: string | null
  sim_card_number: string | null
  /** False = closed Saturday and Sunday; the forecast then skips weekend days. */
  active_on_weekends: boolean
  /** Raw Husky status (LIVE, SHIPPED, END_OF_LIFE, ...); null until the next catalogue sync. */
  husky_status: string | null
  /** Free-text site preferences (what they like or refuse). */
  preferences: string | null
  /** Delivery window "HH:MM:SS"; from later than to = a window across midnight. */
  delivery_time_from: string | null
  delivery_time_to: string | null
  night_delivery_ok: boolean
  created_at: string
  updated_at: string
}

export type ClientRuleType = 'exclude_tag' | 'note'

/** GET /api/v1/clients/{id}/rules item. fridge_id null = every fridge of the client. */
export interface ClientRule {
  id: number
  client_id: number
  fridge_id: number | null
  rule_type: ClientRuleType
  tag: string | null
  note: string | null
  valid_from: string | null
  valid_to: string | null
  created_at: string
}

/** GET /api/v1/clients/rules/violations item: a product the fridge's client excludes. */
export interface ClientRuleViolation {
  fridge_id: number
  product_id: number
  rule_id: number
  tag: string
  note: string | null
}

export type EquipmentCategory = 'coffee' | 'water_filter' | 'vending' | 'fridge' | 'other'

export type EquipmentOwnership = 'bought' | 'rent'

/** GET /api/v1/equipment item. Money fields are euro decimal strings. Reference data only. */
export interface Equipment {
  id: number
  machine_type: string
  equipment_category: EquipmentCategory
  machine_code: string
  supplier_id: number | null
  client_id: number | null
  fridge_id: number | null
  ownership: EquipmentOwnership
  purchase_price: string | null
  /** What we pay the supplier each month for a rented machine. */
  monthly_rent_cost: string | null
  /** What we charge the client each month. */
  monthly_fee: string | null
  purchase_date: string | null
  financing_years: number | null
  /** A fraction as a decimal string: "0.0400" = 4 %. */
  financing_rate: string | null
  financed_by: string | null
  is_active: boolean
  notes: string | null
  created_at: string
  updated_at: string
}

export type PoStatus = 'pending' | 'received' | 'closed_short' | 'cancelled'

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

/** One product a blocked dispatch asked for more of than the warehouse held. */
export interface StockBlockedLine {
  product_id: number
  product_name: string
  requested: number
  available: number
}

/** The dispatch an alert is about, keyed like the Dispatch page URL. */
export interface AlertDispatchRef {
  dispatch_id: number
  delivery_date: string
  iso_year: number
  iso_week: number
  day_name: string
}

/** Readable form of a `negative_blocked` alert (schema: StockBlockedDetails). */
export interface StockBlockedDetails {
  /** Null when the dispatch was deleted after the alert was raised. */
  dispatch: AlertDispatchRef | null
  lines: StockBlockedLine[]
  occurrences: number
  last_raised_at: string
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
  stock_blocked: StockBlockedDetails | null
}
