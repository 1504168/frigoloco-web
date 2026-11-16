import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { DISPATCH_QUERY_KEY } from '@/pages/ops/dispatch/dispatchApi'

/** GET /dispatches/warm-distribution item (schema: WarmDishLineOut). */
export interface WarmDishLine {
  delivery_date: string
  fridge_id: number
  friendly_name: string
  product_id: number
  product_name: string
  category_name: string
  qty: number
}

export interface ComparedWeek {
  year: number
  week: number
  week_start: string
}

export interface CategoryWeekUnits {
  category_id: number
  category_name: string
  this_week_units: number
  previous_week_units: number
  last_year_units: number
}

/** GET /dispatches/week-comparison response (schema: WeekComparisonOut). */
export interface WeekComparison {
  this_week: ComparedWeek
  previous_week: ComparedWeek
  same_week_last_year: ComparedWeek
  categories: CategoryWeekUnits[]
}

export interface IsoWeek {
  year: number
  week: number
}

export function useWarmDishLines(isoWeek: IsoWeek, includePlanned: boolean) {
  return useQuery({
    queryKey: [...DISPATCH_QUERY_KEY, 'warm', isoWeek.year, isoWeek.week, includePlanned],
    queryFn: ({ signal }) =>
      api.get<WarmDishLine[]>('/api/v1/dispatches/warm-distribution', {
        params: { year: isoWeek.year, week: isoWeek.week, include_planned: includePlanned },
        signal,
      }),
  })
}

export function useWeekComparison(isoWeek: IsoWeek) {
  return useQuery({
    queryKey: [...DISPATCH_QUERY_KEY, 'week-comparison', isoWeek.year, isoWeek.week],
    queryFn: ({ signal }) =>
      api.get<WeekComparison>('/api/v1/dispatches/week-comparison', {
        params: { year: isoWeek.year, week: isoWeek.week },
        signal,
      }),
  })
}

/** "2026 W05". */
export function isoWeekLabel(isoWeek: IsoWeek): string {
  return `${isoWeek.year} W${String(isoWeek.week).padStart(2, '0')}`
}
