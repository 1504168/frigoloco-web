import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { EmptyState } from '@/components/shared/EmptyState'
import { ErrorState } from '@/components/shared/ErrorState'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { toast } from '@/components/ui/toast'
import { api, ApiError } from '@/lib/api'
import { formatDateTime12Hour } from '@/lib/format'
import { Dialog } from './Dialog'
import { Field, fieldErrorsFromApiError } from './form'
import type { Fridge, FridgeIntervention, FridgeInterventionCreate } from '../types'

const MS_PER_MINUTE = 60_000
// "YYYY-MM-DDTHH:mm", the value format of an <input type="datetime-local">.
const DATETIME_LOCAL_VALUE_LENGTH = 16

interface FridgeInterventionsDialogProps {
  fridge: Fridge
  onClose: () => void
}

/** Maintenance and intervention log of one fridge, with a form to log a new one. */
export function FridgeInterventionsDialog({ fridge, onClose }: FridgeInterventionsDialogProps) {
  const queryClient = useQueryClient()
  const [type, setType] = React.useState('')
  const [description, setDescription] = React.useState('')
  const [occurredAt, setOccurredAt] = React.useState(currentLocalDateTimeValue)

  const interventionsQueryKey = ['supply', 'fridge-interventions', fridge.id]
  const interventionsUrl = `/api/v1/fridges/${fridge.id}/interventions`

  const interventionsQuery = useQuery({
    queryKey: interventionsQueryKey,
    queryFn: ({ signal }) => api.get<FridgeIntervention[]>(interventionsUrl, { signal }),
  })

  const addMutation = useMutation({
    mutationFn: () => {
      const body: FridgeInterventionCreate = {
        intervention_type: type.trim(),
        description: description.trim() || null,
        occurred_at: new Date(occurredAt).toISOString(),
      }
      return api.post<FridgeIntervention>(interventionsUrl, body)
    },
    onSuccess: () => {
      toast.success('Intervention logged')
      setType('')
      setDescription('')
      setOccurredAt(currentLocalDateTimeValue())
      queryClient.invalidateQueries({ queryKey: interventionsQueryKey })
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Failed to log intervention')
    },
  })

  const fieldErrors = fieldErrorsFromApiError(addMutation.error)
  const canSubmit = type.trim() !== '' && occurredAt !== ''

  return (
    <Dialog
      open
      onClose={onClose}
      title={`Interventions: ${fridge.friendly_name}`}
      description="Maintenance and interventions on this fridge."
      widthClassName="max-w-2xl"
    >
      <div className="space-y-4">
        <InterventionList
          isLoading={interventionsQuery.isLoading}
          error={interventionsQuery.isError ? interventionsQuery.error : null}
          onRetry={() => interventionsQuery.refetch()}
          interventions={interventionsQuery.data ?? []}
        />

        <div className="rounded-lg border border-border p-4">
          <h4 className="mb-3 text-sm font-semibold">Log intervention</h4>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="Type" required error={fieldErrors.intervention_type}>
              <Input
                value={type}
                onChange={(event) => setType(event.target.value)}
                placeholder="maintenance, cleaning…"
              />
            </Field>
            <Field label="Occurred at" required error={fieldErrors.occurred_at}>
              <Input
                type="datetime-local"
                value={occurredAt}
                onChange={(event) => setOccurredAt(event.target.value)}
              />
            </Field>
          </div>
          <div className="mt-3">
            <Field label="Description" error={fieldErrors.description}>
              <Input
                value={description}
                onChange={(event) => setDescription(event.target.value)}
              />
            </Field>
          </div>
          <div className="mt-3 flex justify-end">
            <Button
              size="sm"
              onClick={() => addMutation.mutate()}
              disabled={addMutation.isPending || !canSubmit}
            >
              {addMutation.isPending ? 'Logging…' : 'Log intervention'}
            </Button>
          </div>
        </div>
      </div>
    </Dialog>
  )
}

interface InterventionListProps {
  isLoading: boolean
  error: Error | null
  onRetry: () => void
  interventions: FridgeIntervention[]
}

function InterventionList({ isLoading, error, onRetry, interventions }: InterventionListProps) {
  if (isLoading) {
    return <p className="py-4 text-center text-sm text-muted-foreground">Loading interventions…</p>
  }
  if (error) {
    return <ErrorState error={error} onRetry={onRetry} />
  }
  if (interventions.length === 0) {
    return <EmptyState title="No interventions" description="Nothing logged for this fridge yet." />
  }
  return (
    <div className="space-y-2">
      {interventions.map((intervention) => (
        <div key={intervention.id} className="rounded-lg border border-border p-3 text-sm">
          <div className="flex items-center justify-between gap-2">
            <span className="font-medium">{intervention.intervention_type}</span>
            <span className="text-xs text-muted-foreground">
              {formatDateTime12Hour(intervention.occurred_at)}
            </span>
          </div>
          {intervention.description ? (
            <p className="mt-1 text-muted-foreground">{intervention.description}</p>
          ) : null}
        </div>
      ))}
    </div>
  )
}

/** Now in the browser's local time, as an <input type="datetime-local"> value. */
function currentLocalDateTimeValue(): string {
  const now = new Date()
  const localClockAsUtc = new Date(now.getTime() - now.getTimezoneOffset() * MS_PER_MINUTE)
  return localClockAsUtc.toISOString().slice(0, DATETIME_LOCAL_VALUE_LENGTH)
}
