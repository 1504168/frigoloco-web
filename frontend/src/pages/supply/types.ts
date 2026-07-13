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
  workers_count: number | null
  worker_type: string | null
  preferences: string | null
  notes: string | null
  created_at: string
  updated_at: string
}

/** POST /api/v1/clients body (schema: ClientCreate). */
export interface ClientCreate {
  name: string
  location?: string | null
  workers_count?: number | null
  worker_type?: string | null
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

/** GET /api/v1/clients/{id}/interventions item (schema: ClientInterventionRead). */
export interface ClientIntervention {
  id: number
  fridge_id: number
  intervention_type: string
  description: string | null
  occurred_at: string
  created_by: number | null
  created_at: string
}

/** POST /api/v1/clients/{id}/interventions body (schema: ClientInterventionCreate). */
export interface ClientInterventionCreate {
  fridge_id: number
  intervention_type: string
  description?: string | null
  occurred_at: string
  created_by?: number | null
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
}

export type FridgeUpdate = Partial<FridgeCreate>

/** GET/PUT /api/v1/fridges/{id}/delivery-config item (schema: DeliveryConfigItem). */
export interface DeliveryConfigItem {
  weekday: number
  min_daily_qty: number
  days_to_fill: number
}

// ──────────────────────────── Purchase Orders ────────────────────────────

/** POST /api/v1/purchase-orders line (schema: PoLineCreate). */
export interface PoLineCreate {
  product_id: number
  qty: number
  unit_price: number | string
  vat_rate: number | string
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

/** POST /api/v1/purchase-orders/{id}/receive line (schema: PoReceiveLine). */
export interface PoReceiveLine {
  po_line_id: number
  qty_received: number
}

/** POST /api/v1/purchase-orders/{id}/receive body (schema: PoReceiveRequest). */
export interface PoReceiveRequest {
  received: PoReceiveLine[]
  acknowledge_over_receipt?: boolean
}

/** One entry in an over_receipt (409) error's `details` array (verified live). */
export interface OverReceiptDetail {
  po_line_id: number
  qty_ordered: number
  qty_received: number
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

/** GET /api/v1/stock/movements response (schema: MovementsPage) - keyset paginated. */
export interface MovementsPage {
  items: StockMovement[]
  limit: number
  after_id: number | null
  next_after_id: number | null
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
