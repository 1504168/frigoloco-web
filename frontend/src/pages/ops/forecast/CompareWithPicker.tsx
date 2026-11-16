import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { WeekDayKey } from '@/pages/ops/lib/pipelineKey'
import {
  COMPARE_WEEKS_BACK,
  defaultCustomRange,
  isoWeekBefore,
  weekLabel,
  type CompareChoice,
  type CompareSelection,
} from './forecastWeeks'

const COMPARE_CHOICES: { value: CompareChoice; label: string }[] = [
  { value: 'none', label: 'No comparison' },
  { value: 'same_weekday', label: 'Same weekday of week…' },
  { value: 'monday_to_friday', label: 'Mon-Fri of week…' },
  { value: 'custom', label: 'Custom range' },
]

interface CompareWithPickerProps {
  weekKey: WeekDayKey
  value: CompareSelection
  onChange: (selection: CompareSelection) => void
}

/** "Compare with" control: the extra period whose actuals sit next to the forecast window. */
export function CompareWithPicker({ weekKey, value, onChange }: CompareWithPickerProps) {
  const usesWeek = value.choice === 'same_weekday' || value.choice === 'monday_to_friday'
  return (
    <div className="flex items-center gap-1.5">
      <Select
        value={value.choice}
        onValueChange={(choice) => onChange(selectionForChoice(value, choice as CompareChoice, weekKey))}
      >
        <SelectTrigger className="h-9 w-48" aria-label="Compare with">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {COMPARE_CHOICES.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {usesWeek && (
        <Select
          value={String(value.weeksBack)}
          onValueChange={(weeksBack) => onChange({ ...value, weeksBack: Number(weeksBack) })}
        >
          <SelectTrigger className="h-9 w-32" aria-label="Compare week">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {COMPARE_WEEKS_BACK.map((weeksBack) => {
              const week = isoWeekBefore(weekKey, weeksBack)
              return (
                <SelectItem key={weeksBack} value={String(weeksBack)}>
                  {weekLabel(week)} {week.year}
                </SelectItem>
              )
            })}
          </SelectContent>
        </Select>
      )}
      {value.choice === 'custom' && (
        <>
          <Input
            type="date"
            aria-label="Compare from"
            className="h-9 w-36"
            value={value.firstDay}
            onChange={(event) => onChange({ ...value, firstDay: event.target.value })}
          />
          <Input
            type="date"
            aria-label="Compare to"
            className="h-9 w-36"
            value={value.lastDay}
            onChange={(event) => onChange({ ...value, lastDay: event.target.value })}
          />
        </>
      )}
    </div>
  )
}

/** Picking "Custom range" with no dates yet fills in the week before the delivery. */
function selectionForChoice(
  current: CompareSelection,
  choice: CompareChoice,
  weekKey: WeekDayKey,
): CompareSelection {
  const needsDates = choice === 'custom' && (current.firstDay === '' || current.lastDay === '')
  if (!needsDates) return { ...current, choice }
  return { ...current, choice, ...defaultCustomRange(weekKey) }
}
