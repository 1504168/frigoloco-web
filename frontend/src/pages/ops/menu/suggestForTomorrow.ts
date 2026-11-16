/**
 * "Suggest for tomorrow": make sure tomorrow has a saved forecast (run and save one
 * with the default method when none is saved), so the menu can import from it.
 */
import { api, ApiError } from '@/lib/api'
import {
  currentWeekDayKey,
  deliveryDateFromKey,
  type WeekDayKey,
} from '@/pages/ops/lib/pipelineKey'
import type { ForecastRun } from '@/pages/ops/lib/types'

const NOT_FOUND_STATUS = 404

export type TomorrowForecast = 'already_saved' | 'computed_and_saved'

export function tomorrowKey(): WeekDayKey {
  const tomorrow = new Date()
  tomorrow.setDate(tomorrow.getDate() + 1)
  return currentWeekDayKey(tomorrow)
}

/** The saved forecast for ``key``, computing and saving one first when none exists. */
export async function ensureSavedForecast(key: WeekDayKey): Promise<TomorrowForecast> {
  try {
    await api.get<ForecastRun>('/api/v1/forecasts/saved', {
      params: { year: key.year, week: key.week, day_name: key.dayName },
    })
    return 'already_saved'
  } catch (error) {
    const isNotSavedYet = error instanceof ApiError && error.status === NOT_FOUND_STATUS
    if (!isNotSavedYet) throw error
  }
  const computedRun = await api.post<ForecastRun>('/api/v1/forecasts/run', {
    delivery_date: deliveryDateFromKey(key),
  })
  const computedCells = computedRun.results.map((result) => ({
    fridge_id: result.fridge_id,
    category_id: result.category_id,
    forecast_qty: Number(result.forecast_qty),
  }))
  await api.post<ForecastRun>('/api/v1/forecasts/save', {
    run_id: computedRun.run_id,
    cells: computedCells,
    overwrite: false,
  })
  return 'computed_and_saved'
}
