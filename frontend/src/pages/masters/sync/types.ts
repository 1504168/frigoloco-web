/**
 * Husky master-data sync types, mirrored from the FastAPI schema
 * (verified live against http://localhost:8100).
 *
 * Field-ownership contract (D5): sync overwrites Husky-owned fields only; local
 * fields and the manual `local_status` override survive every sync. Effective
 * activity = `local_status` when set, else Husky-derived (`effective_status`).
 */

/** Manual override value on products/fridges. NULL = follow Husky. */
export type LocalStatus = 'inactive' | 'cancelled' | null

/** Husky-derived effective activity shown on the status badge. */
export type EffectiveStatus = 'active' | 'inactive' | 'cancelled'

/** Server-side list filter (`?status=`). */
export type StatusFilter = 'active' | 'inactive' | 'cancelled' | 'all'

/** Feeds accepted by POST /api/v1/sync/husky/{feed}. */
export type SyncFeed =
  | 'catalogue'
  | 'prices'
  | 'purchases'
  | 'restock'
  | 'reviews'
  | 'stock'
  | 'all'

/** POST /api/v1/sync/husky/{feed} response (schema: SyncTriggerResponse). */
export interface SyncTriggerResponse {
  sync_run_id: number
  feed: string
  endpoint: string
  status: string
  window_from: string | null
  window_to: string | null
}

/** One checkpoint row (schema: SyncRunRead). */
export interface SyncRun {
  id: number
  job: string
  endpoint: string
  window_from: string | null
  window_to: string | null
  status: string
  records_fetched: number
  records_upserted: number
  blob_path: string | null
  error: string | null
  started_at: string
  finished_at: string | null
}

/** A sync run is terminal once it has a finish timestamp. */
export function isRunFinished(run: SyncRun | undefined): boolean {
  return Boolean(run && run.finished_at)
}
