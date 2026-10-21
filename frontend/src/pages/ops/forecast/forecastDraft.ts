/**
 * The editable copy of a forecast run's quantities: one input text per
 * fridge x category cell, so a half-typed value ("1.") survives re-renders.
 */
import type { ForecastCellEdit, ForecastRun } from '@/pages/ops/lib/types'

export type ForecastDraft = Record<string, string>

export type RoundMode = 'up' | 'down' | 'nearest'

export const ROUND_MODE_OPTIONS: { value: RoundMode; label: string }[] = [
  { value: 'up', label: 'Round up' },
  { value: 'down', label: 'Round down' },
  { value: 'nearest', label: 'Round nearest' },
]

const ROUNDERS: Record<RoundMode, (quantity: number) => number> = {
  up: Math.ceil,
  down: Math.floor,
  nearest: Math.round,
}

export function cellKey(fridgeId: number, categoryId: number): string {
  return `${fridgeId}:${categoryId}`
}

/** "3.00" -> "3", "2.50" -> "2.5": the run's quantities as input text. */
export function draftFromRun(run: ForecastRun): ForecastDraft {
  const draft: ForecastDraft = {}
  for (const result of run.results) {
    draft[cellKey(result.fridge_id, result.category_id)] = String(Number(result.forecast_qty))
  }
  return draft
}

/** A typed quantity, or null when the text is not a number >= 0. */
export function parseQuantity(text: string): number | null {
  if (text.trim() === '') return null
  const quantity = Number(text)
  return Number.isFinite(quantity) && quantity >= 0 ? quantity : null
}

export function isDraftChanged(run: ForecastRun, draft: ForecastDraft): boolean {
  return run.results.some((result) => {
    const typed = draft[cellKey(result.fridge_id, result.category_id)]
    return parseQuantity(typed) !== Number(result.forecast_qty)
  })
}

export function countInvalidCells(draft: ForecastDraft): number {
  return Object.values(draft).filter((text) => parseQuantity(text) === null).length
}

/** Rounds every valid cell to a whole number; invalid text is left for the user to fix. */
export function roundDraft(draft: ForecastDraft, mode: RoundMode): ForecastDraft {
  const round = ROUNDERS[mode]
  const rounded: ForecastDraft = {}
  for (const [key, text] of Object.entries(draft)) {
    const quantity = parseQuantity(text)
    rounded[key] = quantity === null ? text : String(round(quantity))
  }
  return rounded
}

/** Every cell of the run with the quantity shown on screen. Call only when no cell is invalid. */
export function cellsFromDraft(run: ForecastRun, draft: ForecastDraft): ForecastCellEdit[] {
  return run.results.map((result) => ({
    fridge_id: result.fridge_id,
    category_id: result.category_id,
    forecast_qty: Number(draft[cellKey(result.fridge_id, result.category_id)]),
  }))
}
