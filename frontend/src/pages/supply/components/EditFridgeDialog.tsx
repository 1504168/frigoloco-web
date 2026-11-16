import * as React from 'react'
import { useMutation } from '@tanstack/react-query'
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
import { Switch } from '@/components/ui/switch'
import { toast } from '@/components/ui/toast'
import { api, ApiError } from '@/lib/api'
import { EMPTY_PLACEHOLDER } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { Client, Fridge } from '../types'
import { Dialog } from './Dialog'
import { Field, Textarea, fieldErrorsFromApiError, generalErrorMessage } from './form'
import { NO_CLIENT_VALUE, huskyStatusLabel } from './fridgeOptions'

/** "07:30:00" from the API -> "07:30" for the time input. */
const HOURS_AND_MINUTES_LENGTH = 5
const NIGHT_DELIVERY_HINT: Hint = {
  text: 'The site can be reached outside office hours, so the driver may deliver at night.',
  example: 'A hospital open 24/7: switch on, the fridge can be filled at 5 AM.',
}
const SITE_PREFERENCES_HINT: Hint = {
  text:
    'Free text on what this site likes or refuses. It shows next to the fridge on the planning ' +
    'pages.',
  example: 'No pork, more vegetarian, no glass bottles.',
}
const WEEKENDS_HINT: Hint = {
  text:
    'Turn off when the site is closed on Saturday and Sunday: the forecast then skips weekend ' +
    'days.',
  example: 'Closed on weekends: a Friday delivery covers 1 selling day, not 3.',
}

interface EditFridgeDialogProps {
  fridge: Fridge
  clients: Client[]
  onClose: () => void
  onSuccess: (fridge: Fridge) => void
}

/**
 * Edit a fridge's client and local details. Identity and status are Husky-owned
 * and shown read-only; Husky sync only fills a client that is empty.
 */
export function EditFridgeDialog({ fridge, clients, onClose, onSuccess }: EditFridgeDialogProps) {
  const [clientValue, setClientValue] = React.useState(
    fridge.client_id === null ? NO_CLIENT_VALUE : String(fridge.client_id),
  )
  const [deliveryAddress, setDeliveryAddress] = React.useState(fridge.delivery_address ?? '')
  const [deliveryInstructions, setDeliveryInstructions] = React.useState(
    fridge.delivery_instructions ?? '',
  )
  const [preferences, setPreferences] = React.useState(fridge.preferences ?? '')
  const [modemNumber, setModemNumber] = React.useState(fridge.modem_number ?? '')
  const [simCardNumber, setSimCardNumber] = React.useState(fridge.sim_card_number ?? '')
  const [activeOnWeekends, setActiveOnWeekends] = React.useState(fridge.active_on_weekends)
  const [deliveryTimeFrom, setDeliveryTimeFrom] = React.useState(
    toTimeInputValue(fridge.delivery_time_from),
  )
  const [deliveryTimeTo, setDeliveryTimeTo] = React.useState(
    toTimeInputValue(fridge.delivery_time_to),
  )
  const [nightDeliveryOk, setNightDeliveryOk] = React.useState(fridge.night_delivery_ok)

  const mutation = useMutation({
    mutationFn: () =>
      api.put<Fridge>(`/api/v1/fridges/${fridge.id}`, {
        // Husky-owned fields are echoed back unchanged.
        husky_id: fridge.husky_id,
        husky_name: fridge.husky_name,
        friendly_name: fridge.friendly_name,
        client_id: clientValue === NO_CLIENT_VALUE ? null : Number(clientValue),
        is_active: fridge.is_active,
        delivery_address: deliveryAddress.trim() || null,
        delivery_instructions: deliveryInstructions.trim() || null,
        preferences: preferences.trim() || null,
        modem_number: modemNumber.trim() || null,
        sim_card_number: simCardNumber.trim() || null,
        active_on_weekends: activeOnWeekends,
        delivery_time_from: deliveryTimeFrom || null,
        delivery_time_to: deliveryTimeTo || null,
        night_delivery_ok: nightDeliveryOk,
      }),
    onSuccess,
    onError: (error) => {
      if (error instanceof ApiError && error.code === 'conflict') toast.error(error.message)
    },
  })

  const fieldErrors = fieldErrorsFromApiError(mutation.error)
  const generalError =
    mutation.error && Object.keys(fieldErrors).length === 0
      ? generalErrorMessage(mutation.error)
      : null
  const activityLabel = fridge.is_active ? 'active' : 'inactive'

  return (
    <Dialog
      open
      onClose={onClose}
      title={`Edit ${fridge.friendly_name}`}
      widthClassName="max-w-xl"
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button onClick={() => mutation.mutate()} disabled={mutation.isPending}>
            {mutation.isPending ? 'Saving…' : 'Save changes'}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {generalError ? (
          <div className="rounded-md border border-critical/40 bg-critical/5 px-3 py-2 text-sm text-critical">
            {generalError}
          </div>
        ) : null}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <ReadOnlyField label="Husky ID" value={fridge.husky_id} mono />
          <ReadOnlyField label="Husky name" value={fridge.husky_name || EMPTY_PLACEHOLDER} />
          <ReadOnlyField label="Friendly name" value={fridge.friendly_name} />
          <ReadOnlyField
            label="Husky status"
            value={`${huskyStatusLabel(fridge.husky_status)} (${activityLabel})`}
          />
        </div>
        <Field label="Client" error={fieldErrors.client_id}>
          <Select
            value={clientValue}
            onValueChange={setClientValue}
          >
            <SelectTrigger aria-label="Client">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_CLIENT_VALUE}>No client</SelectItem>
              {clients.map((client) => (
                <SelectItem
                  key={client.id}
                  value={String(client.id)}
                >
                  {client.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <p className="text-xs text-muted-foreground">
          Identity and status come from Husky: only a LIVE fridge is active. Husky sync fills
          the client only when it is empty, so a client chosen here is kept.
        </p>
        <Field label="Delivery address" error={fieldErrors.delivery_address}>
          <Textarea
            value={deliveryAddress}
            onChange={(event) => setDeliveryAddress(event.target.value)}
          />
        </Field>
        <Field label="Delivery instructions" error={fieldErrors.delivery_instructions}>
          <Textarea
            value={deliveryInstructions}
            onChange={(event) => setDeliveryInstructions(event.target.value)}
          />
        </Field>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field
            label="Deliver from"
            error={fieldErrors.delivery_time_from}
            hint="Special delivery time. Empty = any time."
          >
            <Input
              type="time"
              value={deliveryTimeFrom}
              onChange={(event) => setDeliveryTimeFrom(event.target.value)}
            />
          </Field>
          <Field
            label="Deliver until"
            error={fieldErrors.delivery_time_to}
            hint="Earlier than 'from' = a window across midnight."
          >
            <Input
              type="time"
              value={deliveryTimeTo}
              onChange={(event) => setDeliveryTimeTo(event.target.value)}
            />
          </Field>
        </div>
        <label className="flex cursor-pointer items-center justify-between gap-3 rounded-md border border-border p-3">
          <span>
            <span className="flex items-center gap-1 text-sm font-medium text-foreground">
              Night delivery possible <InfoHint {...NIGHT_DELIVERY_HINT} />
            </span>
            <span className="block text-xs text-muted-foreground">
              The driver can deliver outside office hours (site reachable at night).
            </span>
          </span>
          <Switch
            checked={nightDeliveryOk}
            onCheckedChange={setNightDeliveryOk}
            aria-label="Night delivery possible"
          />
        </label>
        <Field
          label="Site preferences"
          error={fieldErrors.preferences}
          info={SITE_PREFERENCES_HINT}
        >
          <Textarea
            value={preferences}
            onChange={(event) => setPreferences(event.target.value)}
          />
        </Field>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="4G/5G modem number" error={fieldErrors.modem_number}>
            <Input
              value={modemNumber}
              onChange={(event) => setModemNumber(event.target.value)}
            />
          </Field>
          <Field label="SIM card number" error={fieldErrors.sim_card_number}>
            <Input
              value={simCardNumber}
              onChange={(event) => setSimCardNumber(event.target.value)}
            />
          </Field>
        </div>
        <WeekendsToggle
          activeOnWeekends={activeOnWeekends}
          onChange={setActiveOnWeekends}
        />
      </div>
    </Dialog>
  )
}

/** Read-only display of a Husky-owned field (overwritten on every sync). */
function ReadOnlyField({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <Field label={label}>
      <div
        className={cn(
          'flex min-h-9 items-center rounded-md border border-border bg-muted/40 px-3 py-1.5 text-sm text-muted-foreground',
          mono && 'font-mono text-xs',
        )}
      >
        {value}
      </div>
    </Field>
  )
}

interface WeekendsToggleProps {
  activeOnWeekends: boolean
  onChange: (activeOnWeekends: boolean) => void
}

/** The whole area turns grey when the site is closed on weekends, so "off" is visible. */
function WeekendsToggle({ activeOnWeekends, onChange }: WeekendsToggleProps) {
  return (
    <label
      className={cn(
        'flex cursor-pointer items-start justify-between gap-3 rounded-md border border-border p-3',
        !activeOnWeekends && 'bg-muted',
      )}
    >
      <span>
        <span
          className={cn(
            'flex items-center gap-1 text-sm font-medium',
            activeOnWeekends ? 'text-foreground' : 'text-muted-foreground',
          )}
        >
          {activeOnWeekends ? 'Open on weekends' : 'Closed on weekends'}
          <InfoHint {...WEEKENDS_HINT} />
        </span>
        <span className="block text-xs text-muted-foreground">
          Turn off when the site is closed on Saturday and Sunday: the forecast then
          ignores weekend days.
        </span>
      </span>
      <Switch
        checked={activeOnWeekends}
        onCheckedChange={onChange}
        aria-label="Active on weekends"
      />
    </label>
  )
}

function toTimeInputValue(apiTime: string | null): string {
  return apiTime === null ? '' : apiTime.slice(0, HOURS_AND_MINUTES_LENGTH)
}
