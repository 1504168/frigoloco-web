import * as React from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, Plus, Trash2 } from 'lucide-react'
import { Modal } from '@/components/shared/Modal'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { toast } from '@/components/ui/toast'
import { api, ApiError } from '@/lib/api'
import { formatDate } from '@/lib/format'
import type { BankHoliday } from '@/pages/ops/lib/types'
import { BANK_HOLIDAYS_KEY, BANK_HOLIDAYS_URL, useBankHolidays } from './forecastQueries'

const SELLING_DAYS_HINT =
  'Bank holidays are not selling days: the forecast leaves them out of the sales window and of the days to fill. Re-run a forecast after changing this list.'

interface BankHolidaysPanelProps {
  open: boolean
  onClose: () => void
  initialYear: number
}

/** List, add and remove the bank holidays of one year. */
export function BankHolidaysPanel({ open, onClose, initialYear }: BankHolidaysPanelProps) {
  const queryClient = useQueryClient()
  const [year, setYear] = React.useState(initialYear)
  const [newDate, setNewDate] = React.useState('')
  const [newLabel, setNewLabel] = React.useState('')
  const holidaysQuery = useBankHolidays(year)

  const refreshHolidays = () => queryClient.invalidateQueries({ queryKey: BANK_HOLIDAYS_KEY })

  const createMutation = useMutation({
    mutationFn: (holiday: BankHoliday) => api.post<BankHoliday>(BANK_HOLIDAYS_URL, holiday),
    onSuccess: (created) => {
      setNewDate('')
      setNewLabel('')
      refreshHolidays()
      toast.success(`${created.label} added`)
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Bank holiday not added')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (holidayDate: string) => api.del<void>(`${BANK_HOLIDAYS_URL}/${holidayDate}`),
    onSuccess: refreshHolidays,
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Bank holiday not removed')
    },
  })

  const canAdd = newDate !== '' && newLabel.trim() !== '' && !createMutation.isPending
  const holidays = holidaysQuery.data ?? []

  return (
    <Modal open={open} onClose={onClose} title="Bank holidays" description={SELLING_DAYS_HINT}>
      <div className="flex items-center justify-between">
        <Button variant="ghost" size="icon" aria-label="Previous year" onClick={() => setYear(year - 1)}>
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <span className="text-sm font-semibold tabular-nums">{year}</span>
        <Button variant="ghost" size="icon" aria-label="Next year" onClick={() => setYear(year + 1)}>
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
      <ul className="divide-y divide-border rounded-lg border border-border text-sm">
        {holidays.length === 0 && (
          <li className="px-3 py-2 text-muted-foreground">
            {holidaysQuery.isPending ? 'Loading…' : `No bank holidays for ${year}.`}
          </li>
        )}
        {holidays.map((holiday) => (
          <li key={holiday.holiday_date} className="flex items-center justify-between gap-2 px-3 py-1.5">
            <span className="tabular-nums text-muted-foreground">
              {formatDate(holiday.holiday_date)}
            </span>
            <span className="flex-1 truncate">{holiday.label}</span>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              aria-label={`Remove ${holiday.label}`}
              disabled={deleteMutation.isPending}
              onClick={() => deleteMutation.mutate(holiday.holiday_date)}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </li>
        ))}
      </ul>
      <div className="flex items-center gap-2">
        <Input
          type="date"
          aria-label="Holiday date"
          className="h-9 w-40"
          value={newDate}
          onChange={(event) => setNewDate(event.target.value)}
        />
        <Input
          aria-label="Holiday name"
          placeholder="Name"
          className="h-9 flex-1"
          value={newLabel}
          onChange={(event) => setNewLabel(event.target.value)}
        />
        <Button
          size="sm"
          className="h-9"
          disabled={!canAdd}
          onClick={() => createMutation.mutate({ holiday_date: newDate, label: newLabel.trim() })}
        >
          <Plus className="h-4 w-4" />
          Add
        </Button>
      </div>
    </Modal>
  )
}
