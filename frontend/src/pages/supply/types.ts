/**
 * Supply-domain types: the request bodies and page-local shapes that only this
 * domain uses. The server-mirrored entities it reads (Supplier, Fridge,
 * PurchaseOrder, …) are defined once in src/lib/types.ts and re-exported here so
 * the supply pages keep importing everything from './types'. Money/decimal fields
 * are decimal STRINGS as the backend serialises them.
 */

import type { Product } from '@/lib/types'

export type {
  Fridge,
  PoStatus,
  PurchaseOrder,
  PurchaseOrderLine,
  Supplier,
} from '@/lib/types'

// ─────────────────────────────── Suppliers ───────────────────────────────

/** POST /api/v1/suppliers body (schema: SupplierCreate). */
export interface SupplierCreate {
  name: string
  email?: string | null
  warehouse_address?: string | null
  contact_name?: string | null
  contact_phone?: string | null
  is_active?: boolean
}

/** PUT /api/v1/suppliers/{id} body (schema: SupplierUpdate). All fields optional. */
export type SupplierUpdate = Partial<SupplierCreate>

// ──────────────────────────────── Clients ────────────────────────────────

/** GET /api/v1/clients item (schema: ClientRead). */
export interface Client {
  id: number
  name: string
  location: string | null
  preferences: string | null
  notes: string | null
  created_at: string
  updated_at: string
}

/** POST /api/v1/clients body (schema: ClientCreate). */
export interface ClientCreate {
  name: string
  location?: string | null
  preferences?: string | null
  notes?: string | null
}

export type ClientUpdate = Partial<ClientCreate>

/** GET /api/v1/clients/{id}/fees item (schema: ClientFeeRead). */
export interface ClientFee {
  id: number
  client_id: number
  yearly_fee: string
  contract_start: string
  contract_end: string | null
}

/** POST /api/v1/clients/{id}/fees body (schema: ClientFeeCreate). */
export interface ClientFeeCreate {
  yearly_fee: number | string
  contract_start: string
  contract_end?: string | null
}

export type ClientContactRole = 'account_finance' | 'operations' | 'it'

/** GET/PUT /api/v1/clients/{id}/contacts item (schema: ClientContactItem). */
export interface ClientContact {
  role: ClientContactRole
  name: string | null
  job_title: string | null
  phone: string | null
  email: string | null
}

// ──────────────────────────────── Fridges ────────────────────────────────

/** POST /api/v1/fridges body (schema: FridgeCreate). */
export interface FridgeCreate {
  husky_id: string
  husky_name?: string | null
  friendly_name: string
  client_id?: number | null
  delivery_address?: string | null
  delivery_instructions?: string | null
  is_active?: boolean
  modem_number?: string | null
  sim_card_number?: string | null
  active_on_weekends?: boolean
}

export type FridgeUpdate = Partial<FridgeCreate>

/** GET /api/v1/fridges/{id}/interventions item (schema: FridgeInterventionRead). */
export interface FridgeIntervention {
  id: number
  fridge_id: number
  intervention_type: string
  description: string | null
  occurred_at: string
  created_by: number | null
  created_at: string
}

/** POST /api/v1/fridges/{id}/interventions body (schema: FridgeInterventionCreate). */
export interface FridgeInterventionCreate {
  intervention_type: string
  description?: string | null
  occurred_at: string
}

/** GET/PUT /api/v1/fridges/{id}/delivery-config item (schema: DeliveryConfigItem). */
export interface DeliveryConfigItem {
  weekday: number
  min_daily_qty: number
  days_to_fill: number
}

// ──────────────────────────── Purchase Orders ────────────────────────────

/** POST /api/v1/purchase-orders line (schema: PoLineCreate). Price and VAT come from the catalogue. */
export interface PoLineCreate {
  product_id: number
  qty: number
}

/** POST /api/v1/purchase-orders body (schema: PurchaseOrderCreate). */
export interface PurchaseOrderCreate {
  supplier_id: number
  order_date: string
  expected_delivery_date: string
  delivery_address?: string | null
  comment?: string | null
  lines: PoLineCreate[]
}

/** GET /api/v1/menus/draft-purchase-order-lines item (schema: MenuDraftLineOut). */
export interface MenuDraftLineOut {
  product_id: number
  code: string
  name: string
  qty: number
  /** Unit purchase price as a euro decimal string. */
  unit_price: string
  /** VAT as a fraction string (e.g. "0.06"). */
  vat_rate: string
}

/** POST /api/v1/purchase-orders/{id}/receive line (schema: PoReceiveLine). */
export interface PoReceiveLine {
  po_line_id: number
  qty_received: number
}

/** POST /api/v1/purchase-orders/{id}/receive body (schema: PoReceiveRequest). */
export interface PoReceiveRequest {
  received: PoReceiveLine[]
  acknowledge_over_receipt?: boolean
  /** Issues seen at delivery, e.g. "2 boxes broken"; null when there are none. */
  comment?: string | null
}

/** One entry in an over_receipt (409) error's `details` array (verified live). */
export interface OverReceiptDetail {
  po_line_id: number
  qty_ordered: number
  qty_received: number
}

export type PoDiscrepancyKind = 'short' | 'over'

export type PoDiscrepancyReason = 'missing' | 'damaged' | 'wrong_product' | 'other'

/** POST /api/v1/purchase-orders/{id}/close-short line (schema: PoCloseShortLine). */
export interface PoCloseShortLine {
  po_line_id: number
  reason: PoDiscrepancyReason | null
  comment: string | null
}

/** POST /api/v1/purchase-orders/{id}/close-short body (schema: PoCloseShortRequest). */
export interface PoCloseShortRequest {
  lines: PoCloseShortLine[]
}

/** GET /api/v1/purchase-orders/discrepancies item (schema: PoDiscrepancyRead). */
export interface PoDiscrepancy {
  id: number
  po_id: number
  order_no: string
  supplier_id: number
  supplier_name: string
  product_code: string
  product_name: string
  kind: PoDiscrepancyKind
  qty_ordered: number
  qty_received: number
  /** Positive shortfall (kind short) or excess (kind over). */
  qty_difference: number
  reason: PoDiscrepancyReason | null
  comment: string | null
  created_by_name: string | null
  created_at: string
}

export type PoHistoryAction = 'created' | 'edited' | 'received' | 'closed_short' | 'cancelled'

/** GET /api/v1/purchase-orders/{id}/history item (schema: PoHistoryEvent). */
export interface PoHistoryEvent {
  action: PoHistoryAction
  at: string
  user_name: string | null
  comment: string | null
  lines: { label: string; detail: string }[]
}

/** One product of the menu order plan (schema: MenuOrderPlanLine). */
export interface MenuOrderPlanLine {
  product_id: number
  product_code: string
  product_name: string
  need_qty: number
  in_stock_qty: number
  on_order_qty: number
  to_order_qty: number
  /** Unit purchase price as a euro decimal string. */
  unit_price: string
  vat_rate: string
}

/** GET /api/v1/purchase-orders/menu-order-plan (schema: MenuOrderPlan). */
export interface MenuOrderPlan {
  year: number
  week: number
  day_names: string[]
  days_without_menu: string[]
  expected_delivery_date: string
  suppliers: { supplier_id: number; supplier_name: string; lines: MenuOrderPlanLine[] }[]
  lines_without_supplier: MenuOrderPlanLine[]
}

// ───────────────────────────────── Stock ─────────────────────────────────

/** GET /api/v1/stock/balances item (schema: StockBalanceOut). */
export interface StockBalance {
  product_id: number
  product_code: string
  product_name: string
  physical_qty: number
  on_order_qty: number
  available_qty: number
  category_id: number
  category_name: string
  supplier_id: number | null
  supplier_name: string | null
  /** Warehouse minimum; null = no minimum set. */
  min_stock_qty: number | null
  /** True when the warehouse holds fewer units than min_stock_qty. */
  is_low_stock: boolean
  /** Units in all fridges from the latest Husky stock reading. */
  fridge_units: number
  is_active: boolean
}

/** PUT /api/v1/stock/products/{id}/minimum response (schema: MinimumStockOut). */
export interface MinimumStock {
  product_id: number
  min_stock_qty: number | null
  physical_qty: number
  is_low_stock: boolean
}

/** Another product with the same name (schema: SameNameProductOut). */
export interface SameNameProduct {
  product_id: number
  product_code: string
  is_active: boolean
  fridge_units: number
}

/** One fridge holding a product (schema: FridgeUnitsOut). */
export interface FridgeUnits {
  fridge_id: number
  fridge_name: string
  units: number
  next_expiry_at: string | null
  taken_at: string
  is_stale: boolean
}

/** GET /api/v1/stock/products/{id}/fridges response (schema: ProductLocationsOut). */
export interface ProductLocations {
  product_id: number
  product_code: string
  product_name: string
  physical_qty: number
  on_order_qty: number
  available_qty: number
  fridge_units_total: number
  latest_taken_at: string | null
  fridges: FridgeUnits[]
  is_active: boolean
  same_name_products: SameNameProduct[]
}

export type StockMovementType =
  | 'po_receipt'
  | 'dispatch'
  | 'adjustment'
  | 'cancellation_reversal'

/** GET /api/v1/stock/movements item (schema: MovementOut). */
export interface StockMovement {
  id: number
  product_id: number
  qty: number
  movement_type: StockMovementType
  po_line_id: number | null
  dispatch_line_id: number | null
  reason: string | null
  created_by: number | null
  created_at: string
}

/** GET /api/v1/stock/movements response (schema: MovementsPage) - newest first, keyset paginated. */
export interface MovementsPage {
  items: StockMovement[]
  limit: number
  before_id: number | null
  next_before_id: number | null
}

/** POST /api/v1/stock/adjustments body (schema: AdjustmentRequest). */
export interface AdjustmentRequest {
  product_id: number
  qty: number
  reason: string
}

// ──────────────────────────── Shared product ─────────────────────────────

/** Minimal product shape used by the PO line editor / stock lookups. */
export type ProductLite = Pick<Product, 'id' | 'code' | 'name' | 'purchase_price' | 'vat_rate'>
