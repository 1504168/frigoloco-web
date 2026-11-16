import { useQuery } from '@tanstack/react-query'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { api } from '@/lib/api'
import { weekKeyLabel, type DayName, type WeekDayKey } from '@/pages/ops/lib/pipelineKey'
import type { SavedForecast } from '@/pages/ops/lib/types'
import { SAVED_LIST_KEY } from './forecastQueries'

interface SavedForecastsSelectProps {
  /** Opens the picked saved forecast's week/day. */
  onPick: (key: WeekDayKey) => void
}

/** Every saved forecast, latest delivery first; picking one opens it. */
export function SavedForecastsSelect({ onPick }: SavedForecastsSelectProps) {
  const savedQuery = useQuery({
    queryKey: SAVED_LIST_KEY,
    queryFn: ({ signal }) => api.get<SavedForecast[]>('/api/v1/forecasts/saved-list', { signal }),
  })
  const savedRuns = savedQuery.data ?? []
  const keyByRunId = new Map<string, WeekDayKey>()
  for (const saved of savedRuns) keyByRunId.set(String(saved.run_id), savedKey(saved))

  function pick(runId: string) {
    const key = keyByRunId.get(runId)
    if (key !== undefined) onPick(key)
  }

  // An action menu, not a setting: the value stays empty so the same entry can be picked again.
  return (
    <Select value="" onValueChange={pick} disabled={savedRuns.length === 0}>
      <SelectTrigger className="h-9 w-44" aria-label="Saved forecasts">
        <SelectValue placeholder={`Saved (${savedRuns.length})`} />
      </SelectTrigger>
      <SelectContent>
        {savedRuns.map((saved) => (
          <SelectItem key={saved.run_id} value={String(saved.run_id)}>
            {weekKeyLabel(savedKey(saved))}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

function savedKey(saved: SavedForecast): WeekDayKey {
  // The backend always sends the canonical name, 'Monday' .. 'Sunday'.
  return { year: saved.iso_year, week: saved.week_no, dayName: saved.day_name as DayName }
}
