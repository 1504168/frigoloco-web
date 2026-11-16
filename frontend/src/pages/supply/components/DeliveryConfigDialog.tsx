import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ErrorState } from '@/components/shared/ErrorState'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { toast } from '@/components/ui/toast'
import { api, ApiError } from '@/lib/api'
import type { DeliveryConfigItem, Fridge } from '../types'
import { Dialog } from './Dialog'
import { WEEKDAYS, countSellingDays } from './fridgeOptions'

interface WeekdayRow {
  enabled: boolean
  min_daily_qty: string
}

function emptyWeek(): WeekdayRow[] {
  return WEEKDAYS.map(() => ({ enabled: false, min_daily_qty: '0' }))
}

/**
 * Derive days-to-fill for every row from the delivery rotation: for each ticked
 * weekday, the gap (counting the delivery day, not the next) until the next
 * ticked weekday. Thu+Sun -> Thu=3, Sun=4; a single day -> 7. Unticked rows
 * return null. Mirrors the backend rule in delivery_config_service.py.
 */
function deriveDaysToFill(rows: WeekdayRow[]): (number | null)[] {
  const enabledWeekdays = rows
    .map((row, index) => (row.enabled ? index + 1 : null))
    .filter((weekday): weekday is number => weekday !== null)
    .sort((a, b) => a - b)

  const result: (number | null)[] = rows.map(() => null)
  if (enabledWeekdays.length === 0) return result

  enabledWeekdays.forEach((weekday, position) => {
    const nextWeekday = enabledWeekdays[(position + 1) % enabledWeekdays.length]
    const gap = (((nextWeekday - weekday) % 7) + 7) % 7
    result[weekday - 1] = gap === 0 ? 7 : gap
  })
  return result
}

function pluralDays(count: number): string {
  return count === 1 ? 'day' : 'days'
}

export function DeliveryConfigDialog({ fridge, onClose }: { fridge: Fridge; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [rows, setRows] = React.useState<WeekdayRow[]>(emptyWeek)

  const configQuery = useQuery({
    queryKey: ['supply', 'delivery-config', fridge.id],
    queryFn: ({ signal }) =>
      api.get<DeliveryConfigItem[]>(`/api/v1/fridges/${fridge.id}/delivery-config`, { signal }),
  })

  // Seed the local editor once the current config loads.
  React.useEffect(() => {
    if (!configQuery.data) return
    const next = emptyWeek()
    for (const item of configQuery.data) {
      next[item.weekday - 1] = {
        enabled: true,
        min_daily_qty: String(item.min_daily_qty),
      }
    }
    setRows(next)
  }, [configQuery.data])

  const saveMutation = useMutation({
    mutationFn: () => {
      // days_to_fill is derived server-side from the rotation; send only the
      // ticked weekday and its min daily qty.
      const items = rows
        .map((row, index) => ({ row, index }))
        .filter(({ row }) => row.enabled)
        .map(({ row, index }) => ({
          weekday: index + 1,
          min_daily_qty: Number(row.min_daily_qty) || 0,
        }))
      return api.put<DeliveryConfigItem[]>(`/api/v1/fridges/${fridge.id}/delivery-config`, {
        items,
      })
    },
    onSuccess: () => {
      toast.success('Delivery schedule saved')
      queryClient.invalidateQueries({ queryKey: ['supply', 'delivery-config', fridge.id] })
      onClose()
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Failed to save schedule')
    },
  })

  function updateRow(index: number, patch: Partial<WeekdayRow>) {
    setRows((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)))
  }

  const enabledCount = rows.filter((row) => row.enabled).length
  const derivedDaysToFill = deriveDaysToFill(rows)
  const weekendHint = fridge.active_on_weekends
    ? ''
    : ' Closed on weekends: Saturday and Sunday are not counted as selling days.'

  return (
    <Dialog
      open
      onClose={onClose}
      title={`Delivery schedule: ${fridge.friendly_name}`}
      description={`Tick each weekday this fridge is restocked. Min daily qty and days-to-fill drive the forecast.${weekendHint}`}
      widthClassName="max-w-md"
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={saveMutation.isPending}>
            Cancel
          </Button>
          <Button onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending || configQuery.isLoading}>
            {saveMutation.isPending ? 'Saving…' : `Save (${enabledCount} day${enabledCount === 1 ? '' : 's'})`}
          </Button>
        </>
      }
    >
      {configQuery.isLoading ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Loading schedule…</p>
      ) : configQuery.isError ? (
        <ErrorState error={configQuery.error} onRetry={() => configQuery.refetch()} />
      ) : (
        <div className="space-y-2">
          <div className="grid grid-cols-[7rem_5rem_1fr] items-center gap-3 px-3 text-xs font-medium text-muted-foreground">
            <span>Weekday</span>
            <span>Min QTY</span>
            <span>Days To Fill</span>
          </div>
          {rows.map((row, index) => (
            <div
              key={WEEKDAYS[index]}
              className="grid grid-cols-[7rem_5rem_1fr] items-center gap-3 rounded-md border border-border px-3 py-2"
            >
              <label className="flex items-center gap-2 text-sm font-medium">
                <input
                  type="checkbox"
                  checked={row.enabled}
                  onChange={(event) => updateRow(index, { enabled: event.target.checked })}
                  className="h-4 w-4 rounded border-input accent-[var(--primary)]"
                />
                {WEEKDAYS[index]}
              </label>
              <Input
                inputMode="numeric"
                value={row.min_daily_qty}
                disabled={!row.enabled}
                onChange={(event) => updateRow(index, { min_daily_qty: event.target.value })}
              />
              <DaysToFillCell
                weekday={index + 1}
                calendarDays={derivedDaysToFill[index]}
                activeOnWeekends={fridge.active_on_weekends}
              />
            </div>
          ))}
        </div>
      )}
    </Dialog>
  )
}

interface DaysToFillCellProps {
  weekday: number
  /** Null when the weekday is not a delivery day. */
  calendarDays: number | null
  activeOnWeekends: boolean
}

/** Selling days the delivery must cover; the calendar span is added when weekends are skipped. */
function DaysToFillCell({ weekday, calendarDays, activeOnWeekends }: DaysToFillCellProps) {
  if (calendarDays === null) {
    return <div className="flex h-9 items-center text-sm text-muted-foreground">-</div>
  }
  const sellingDays = countSellingDays(weekday, calendarDays, activeOnWeekends)
  const skipsWeekendDays = sellingDays !== calendarDays
  return (
    <div className="flex h-9 items-center text-sm tabular-nums">
      <span>
        {sellingDays}
        <span className="ml-1 text-xs text-muted-foreground">
          {skipsWeekendDays ? 'selling ' : ''}
          {pluralDays(sellingDays)}
          {skipsWeekendDays ? ` (${calendarDays} calendar)` : ''}
        </span>
      </span>
    </div>
  )
}
