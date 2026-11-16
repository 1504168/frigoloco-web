import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ErrorState } from '@/components/shared/ErrorState'
import { InfoHint, type Hint } from '@/components/shared/InfoHint'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { toast } from '@/components/ui/toast'
import { api, ApiError } from '@/lib/api'
import { formatDate, formatDateTime12Hour } from '@/lib/format'
import type { SupplierDeliverySchedule, SupplierNextDelivery } from '@/lib/types'
import { Checkbox } from './form'
import { WEEKDAYS } from './fridgeOptions'

const DAYS_PER_WEEK = 7
const DEFAULT_CUTOFF_TIME = '12:00'
/** "12:00:00" from the API -> "12:00" for the time input. */
const HOURS_AND_MINUTES_LENGTH = 5
const CUTOFF_HINT: Hint = {
  text: 'The latest day and time an order must reach the supplier to arrive on this delivery day.',
  example:
    "Monday delivery, order by Friday 12:00: an order sent Friday 2 PM misses Monday's " +
    "delivery.",
}

interface ScheduleRow {
  isDeliveryDay: boolean
  cutoffWeekday: number
  cutoffTime: string
}

/** Delivery weekdays of one supplier, each with the order cutoff (weekday + time) it needs. */
export function SupplierScheduleTab({ supplierId }: { supplierId: number }) {
  const queryClient = useQueryClient()
  const scheduleUrl = `/api/v1/suppliers/${supplierId}/delivery-schedule`
  const scheduleQueryKey = ['supply', 'supplier-schedule', supplierId]
  const nextDeliveryQueryKey = ['supply', 'supplier-next-delivery', supplierId]

  const scheduleQuery = useQuery({
    queryKey: scheduleQueryKey,
    queryFn: ({ signal }) => api.get<SupplierDeliverySchedule[]>(scheduleUrl, { signal }),
  })
  const nextDeliveryQuery = useQuery({
    queryKey: nextDeliveryQueryKey,
    queryFn: ({ signal }) =>
      api.get<SupplierNextDelivery | null>(`/api/v1/suppliers/${supplierId}/next-delivery`, {
        signal,
      }),
  })

  const [editedRows, setEditedRows] = React.useState<ScheduleRow[] | null>(null)
  const savedRows = scheduleQuery.data ? toScheduleRows(scheduleQuery.data) : null
  const rows = editedRows ?? savedRows

  const saveMutation = useMutation({
    mutationFn: (rowsToSave: ScheduleRow[]) =>
      api.put<SupplierDeliverySchedule[]>(scheduleUrl, { items: toScheduleItems(rowsToSave) }),
    onSuccess: () => {
      toast.success('Delivery schedule saved')
      setEditedRows(null)
      queryClient.invalidateQueries({ queryKey: scheduleQueryKey })
      queryClient.invalidateQueries({ queryKey: nextDeliveryQueryKey })
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Failed to save schedule')
    },
  })

  if (scheduleQuery.isError) {
    return <ErrorState error={scheduleQuery.error} onRetry={() => scheduleQuery.refetch()} />
  }
  if (!rows) {
    return <p className="py-4 text-center text-sm text-muted-foreground">Loading schedule…</p>
  }

  const hasMissingCutoffTime = rows.some((row) => row.isDeliveryDay && row.cutoffTime === '')
  const updateRow = (weekdayIndex: number, change: Partial<ScheduleRow>) => {
    const changedRows = rows.map((row, index) => (index === weekdayIndex ? { ...row, ...change } : row))
    setEditedRows(changedRows)
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground">
        Tick the days this supplier delivers and when the order must be placed for that
        delivery, e.g. Monday delivery: order by Friday 12:00.
      </p>
      <div className="overflow-hidden rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Delivery day</th>
              <th className="px-3 py-2 text-left font-medium">
                <span className="inline-flex items-center gap-1">
                  Order by (day) <InfoHint {...CUTOFF_HINT} />
                </span>
              </th>
              <th className="px-3 py-2 text-left font-medium">Order by (time)</th>
              <th className="px-3 py-2 text-left font-medium">Days before delivery</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, weekdayIndex) => (
              <ScheduleRowCells
                key={WEEKDAYS[weekdayIndex]}
                row={row}
                weekdayIndex={weekdayIndex}
                onChange={(change) => updateRow(weekdayIndex, change)}
              />
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between gap-3">
        <NextDeliveryHint nextDelivery={nextDeliveryQuery.data} />
        <Button
          size="sm"
          onClick={() => saveMutation.mutate(rows)}
          disabled={saveMutation.isPending || editedRows === null || hasMissingCutoffTime}
        >
          {saveMutation.isPending ? 'Saving…' : 'Save schedule'}
        </Button>
      </div>
    </div>
  )
}

interface ScheduleRowCellsProps {
  row: ScheduleRow
  weekdayIndex: number
  onChange: (change: Partial<ScheduleRow>) => void
}

function ScheduleRowCells({ row, weekdayIndex, onChange }: ScheduleRowCellsProps) {
  const weekdayName = WEEKDAYS[weekdayIndex]
  const deliveryWeekday = weekdayIndex + 1
  return (
    <tr className="border-t border-border">
      <td className="px-3 py-2">
        <Checkbox
          label={weekdayName}
          checked={row.isDeliveryDay}
          onChange={(event) => onChange({ isDeliveryDay: event.target.checked })}
        />
      </td>
      <td className="px-3 py-2">
        <Select
          value={String(row.cutoffWeekday)}
          onValueChange={(value) => onChange({ cutoffWeekday: Number(value) })}
          disabled={!row.isDeliveryDay}
        >
          <SelectTrigger aria-label={`Order day for ${weekdayName} delivery`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {WEEKDAYS.map((cutoffWeekdayName, cutoffIndex) => (
              <SelectItem key={cutoffWeekdayName} value={String(cutoffIndex + 1)}>
                {cutoffWeekdayName}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </td>
      <td className="px-3 py-2">
        <Input
          type="time"
          value={row.cutoffTime}
          disabled={!row.isDeliveryDay}
          aria-label={`Order time for ${weekdayName} delivery`}
          onChange={(event) => onChange({ cutoffTime: event.target.value })}
        />
      </td>
      <td className="px-3 py-2 tabular-nums text-muted-foreground">
        {row.isDeliveryDay ? daysBeforeDelivery(deliveryWeekday, row.cutoffWeekday) : ''}
      </td>
    </tr>
  )
}

function NextDeliveryHint({ nextDelivery }: { nextDelivery: SupplierNextDelivery | null | undefined }) {
  if (!nextDelivery) return <span />
  return (
    <p className="text-sm text-muted-foreground">
      Next delivery <span className="font-medium text-foreground">{formatDate(nextDelivery.delivery_date)}</span>
      {' '}if ordered by{' '}
      <span className="font-medium text-foreground">{formatDateTime12Hour(nextDelivery.order_deadline)}</span>
    </p>
  )
}

/** Mirrors days_before_delivery in the backend supplier_schedule_service.py (0 = same day). */
function daysBeforeDelivery(deliveryWeekday: number, cutoffWeekday: number): number {
  return (deliveryWeekday - cutoffWeekday + DAYS_PER_WEEK) % DAYS_PER_WEEK
}

function previousWeekday(weekday: number): number {
  return weekday === 1 ? DAYS_PER_WEEK : weekday - 1
}

function toScheduleRows(schedules: SupplierDeliverySchedule[]): ScheduleRow[] {
  return WEEKDAYS.map((_, weekdayIndex) => {
    const deliveryWeekday = weekdayIndex + 1
    const schedule = schedules.find((item) => item.delivery_weekday === deliveryWeekday)
    if (!schedule) {
      return {
        isDeliveryDay: false,
        cutoffWeekday: previousWeekday(deliveryWeekday),
        cutoffTime: DEFAULT_CUTOFF_TIME,
      }
    }
    return {
      isDeliveryDay: true,
      cutoffWeekday: schedule.cutoff_weekday,
      cutoffTime: schedule.cutoff_time.slice(0, HOURS_AND_MINUTES_LENGTH),
    }
  })
}

function toScheduleItems(rows: ScheduleRow[]): SupplierDeliverySchedule[] {
  const items: SupplierDeliverySchedule[] = []
  rows.forEach((row, weekdayIndex) => {
    if (!row.isDeliveryDay) return
    items.push({
      delivery_weekday: weekdayIndex + 1,
      cutoff_weekday: row.cutoffWeekday,
      cutoff_time: row.cutoffTime,
    })
  })
  return items
}
