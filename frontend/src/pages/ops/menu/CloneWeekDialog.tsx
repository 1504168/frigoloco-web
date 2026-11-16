import * as React from 'react'
import { useMutation } from '@tanstack/react-query'
import { Modal } from '@/components/shared/Modal'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { toast } from '@/components/ui/toast'
import { api, ApiError } from '@/lib/api'
import type { WeekDayKey } from '@/pages/ops/lib/pipelineKey'
import type { WeekMenu } from '@/pages/ops/lib/types'

/** Week number used when stepping back from week 1 into the previous ISO year. */
const LAST_WEEK_OF_USUAL_YEAR = 52
const NON_DIGITS = /\D/g

interface SourceWeek {
  year: string
  week: string
}

export interface CloneWeekDialogProps {
  open: boolean
  onClose: () => void
  targetKey: WeekDayKey
  /** Receives the source week's menu; the page shows its products as unsaved columns. */
  onClone: (weekMenu: WeekMenu) => void
}

/** Pick another ISO week and copy its menu's product list into this week's grid. */
export function CloneWeekDialog({ open, onClose, targetKey, onClone }: CloneWeekDialogProps) {
  const [sourceWeek, setSourceWeek] = React.useState<SourceWeek>(() => previousWeek(targetKey))

  const cloneMutation = useMutation({
    mutationFn: () =>
      api.get<WeekMenu>('/api/v1/menus/week', {
        params: {
          year: Number(sourceWeek.year),
          week: Number(sourceWeek.week),
        },
      }),
    onSuccess: (weekMenu) => {
      if (weekMenu.categories.length === 0) {
        toast.error(`Week ${weekMenu.week} of ${weekMenu.year} has no saved menu to clone.`)
        return
      }
      onClone(weekMenu)
      onClose()
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Failed to load that week menu')
    },
  })

  const canClone = sourceWeek.year !== '' && sourceWeek.week !== '' && !cloneMutation.isPending

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Clone a week menu"
      description={
        `Copy another week's products into week ${targetKey.week}. ` +
        `Adjust them, then press Save to store them as this week's menu.`
      }
      footer={
        <>
          <Button
            variant="outline"
            onClick={onClose}
          >
            Cancel
          </Button>
          <Button
            onClick={() => cloneMutation.mutate()}
            disabled={!canClone}
          >
            {cloneMutation.isPending ? 'Loading…' : 'Clone'}
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <Label htmlFor="clone-week-year">Year</Label>
          <Input
            id="clone-week-year"
            inputMode="numeric"
            value={sourceWeek.year}
            onChange={(event) =>
              setSourceWeek({ ...sourceWeek, year: digitsOnly(event.target.value) })
            }
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="clone-week-number">Week</Label>
          <Input
            id="clone-week-number"
            inputMode="numeric"
            value={sourceWeek.week}
            onChange={(event) =>
              setSourceWeek({ ...sourceWeek, week: digitsOnly(event.target.value) })
            }
          />
        </div>
      </div>
    </Modal>
  )
}

function digitsOnly(text: string): string {
  return text.replace(NON_DIGITS, '')
}

function previousWeek(key: WeekDayKey): SourceWeek {
  if (key.week > 1) return { year: String(key.year), week: String(key.week - 1) }
  return { year: String(key.year - 1), week: String(LAST_WEEK_OF_USUAL_YEAR) }
}
