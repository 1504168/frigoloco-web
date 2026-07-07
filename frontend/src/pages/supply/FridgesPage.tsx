import * as React from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarClock, Pencil, Plus, Trash2 } from 'lucide-react'
import { PageHeader } from '@/components/shared/PageHeader'
import { DataTable, type DataTableColumn } from '@/components/shared/DataTable'
import { EmptyState } from '@/components/shared/EmptyState'
import { ErrorState } from '@/components/shared/ErrorState'
import {
  EffectiveStatusBadge,
  HuskySyncControl,
  StatusFilterSelect,
  StatusOverrideSelect,
} from '@/pages/masters/sync/components'
import type { StatusFilter } from '@/pages/masters/sync/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { toast } from '@/components/ui/sonner'
import { api, ApiError, type Page } from '@/lib/api'
import { Dialog } from './components/Dialog'
import { Field, Textarea, fieldErrorsFromApiError, generalErrorMessage } from './components/form'
import type {
  Client,
  DeliveryConfigItem,
  Fridge,
  FridgeCreate,
} from './types'

const PAGE_SIZE = 25

/**
 * Weekday labels by row index. The API uses ISO weekday numbers (Mon=1 … Sun=7),
 * so the integer sent/received is always `index + 1`.
 */
const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

interface FridgeForm {
  husky_id: string
  husky_name: string
  friendly_name: string
  client_id: number | null
  delivery_address: string
  delivery_instructions: string
  is_active: boolean
}

const EMPTY_FORM: FridgeForm = {
  husky_id: '',
  husky_name: '',
  friendly_name: '',
  client_id: null,
  delivery_address: '',
  delivery_instructions: '',
  is_active: true,
}

const NO_CLIENT = '__none__'

function toCreatePayload(form: FridgeForm): FridgeCreate {
  return {
    husky_id: form.husky_id.trim(),
    husky_name: form.husky_name.trim() || null,
    friendly_name: form.friendly_name.trim(),
    client_id: form.client_id,
    delivery_address: form.delivery_address.trim() || null,
    delivery_instructions: form.delivery_instructions.trim() || null,
    is_active: form.is_active,
  }
}

/** Shared clients lookup (id -> name) used for the client column and the form select. */
function useClientsLookup() {
  return useQuery({
    queryKey: ['supply', 'clients', 'all'],
    queryFn: ({ signal }) =>
      api.get<Page<Client>>('/api/v1/clients', { params: { limit: 200, offset: 0 }, signal }),
    staleTime: 60_000,
    select: (page) => page.items,
  })
}

const FRIDGES_QUERY_KEY = ['supply', 'fridges']

export function FridgesPage() {
  const queryClient = useQueryClient()
  const [offset, setOffset] = React.useState(0)
  const [statusFilter, setStatusFilter] = React.useState<StatusFilter>('active')
  const [editing, setEditing] = React.useState<Fridge | null>(null)
  const [creating, setCreating] = React.useState(false)
  const [deleting, setDeleting] = React.useState<Fridge | null>(null)
  const [configuring, setConfiguring] = React.useState<Fridge | null>(null)

  const clientsQuery = useClientsLookup()
  const clientName = React.useCallback(
    (id: number | null) =>
      id === null ? '—' : clientsQuery.data?.find((c) => c.id === id)?.name ?? `#${id}`,
    [clientsQuery.data],
  )

  // Reset to first page whenever the status filter changes.
  React.useEffect(() => {
    setOffset(0)
  }, [statusFilter])

  const fridgesQuery = useQuery({
    queryKey: ['supply', 'fridges', { offset, status: statusFilter }],
    queryFn: ({ signal }) =>
      api.get<Page<Fridge>>('/api/v1/fridges', {
        params: { limit: PAGE_SIZE, offset, status: statusFilter },
        signal,
      }),
    placeholderData: keepPreviousData,
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: FRIDGES_QUERY_KEY })

  const columns = React.useMemo<DataTableColumn<Fridge>[]>(
    () => [
      {
        id: 'friendly_name',
        header: 'Fridge',
        cell: (row) => <span className="font-medium">{row.friendly_name}</span>,
        sortValue: (row) => row.friendly_name,
      },
      {
        id: 'husky_id',
        header: 'Husky ID',
        cell: (row) => <span className="font-mono text-xs">{row.husky_id}</span>,
        sortValue: (row) => row.husky_id,
      },
      {
        id: 'client',
        header: 'Client',
        cell: (row) => <span className="text-muted-foreground">{clientName(row.client_id)}</span>,
        sortValue: (row) => clientName(row.client_id),
      },
      {
        id: 'status',
        header: 'Status',
        cell: (row) => <EffectiveStatusBadge status={row.effective_status} />,
        sortValue: (row) => row.effective_status,
      },
      {
        id: 'override',
        header: 'Override',
        cell: (row) => (
          <StatusOverrideSelect
            resourcePath={`/api/v1/fridges/${row.id}`}
            localStatus={row.local_status}
            invalidateKeys={[FRIDGES_QUERY_KEY]}
            entityLabel={`Fridge ${row.friendly_name}`}
          />
        ),
      },
      {
        id: 'actions',
        header: '',
        align: 'right',
        cell: (row) => (
          <div className="flex items-center justify-end gap-1">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setConfiguring(row)}
            >
              <CalendarClock className="h-4 w-4" /> Delivery
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Edit ${row.friendly_name}`}
              onClick={() => setEditing(row)}
            >
              <Pencil className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Delete ${row.friendly_name}`}
              onClick={() => setDeleting(row)}
            >
              <Trash2 className="h-4 w-4 text-critical" />
            </Button>
          </div>
        ),
      },
    ],
    [clientName],
  )

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumb="Masters / Fridges"
        title="Fridges"
        description="Husky fridge units and their delivery schedules. Delivery config gates the forecast feature."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <StatusFilterSelect value={statusFilter} onChange={setStatusFilter} />
            <HuskySyncControl
              feed="catalogue"
              endpoint="catalogue"
              invalidateKeys={[FRIDGES_QUERY_KEY]}
              itemLabel="fridge"
            />
            <Button onClick={() => setCreating(true)}>
              <Plus className="h-4 w-4" /> New fridge
            </Button>
          </div>
        }
      />

      <DataTable
        columns={columns}
        page={fridgesQuery.data}
        isLoading={fridgesQuery.isLoading}
        isError={fridgesQuery.isError}
        error={fridgesQuery.error}
        onRetry={() => fridgesQuery.refetch()}
        limit={PAGE_SIZE}
        offset={offset}
        onOffsetChange={setOffset}
        getRowId={(row) => row.id}
        emptyState={
          <EmptyState
            title="No fridges yet"
            description="Create a fridge to configure its delivery schedule."
            action={
              <Button onClick={() => setCreating(true)}>
                <Plus className="h-4 w-4" /> New fridge
              </Button>
            }
          />
        }
      />

      {creating ? (
        <FridgeFormDialog
          title="New fridge"
          initial={EMPTY_FORM}
          submitLabel="Create fridge"
          clients={clientsQuery.data ?? []}
          onClose={() => setCreating(false)}
          onSubmit={(form) => api.post<Fridge>('/api/v1/fridges', toCreatePayload(form))}
          onSuccess={(created) => {
            toast.success(`Fridge “${created.friendly_name}” created`)
            invalidate()
            setCreating(false)
          }}
        />
      ) : null}

      {editing ? (
        <FridgeFormDialog
          title={`Edit ${editing.friendly_name}`}
          initial={{
            husky_id: editing.husky_id,
            husky_name: editing.husky_name ?? '',
            friendly_name: editing.friendly_name,
            client_id: editing.client_id,
            delivery_address: editing.delivery_address ?? '',
            delivery_instructions: editing.delivery_instructions ?? '',
            is_active: editing.is_active,
          }}
          submitLabel="Save changes"
          clients={clientsQuery.data ?? []}
          onClose={() => setEditing(null)}
          onSubmit={(form) =>
            api.put<Fridge>(`/api/v1/fridges/${editing.id}`, toCreatePayload(form))
          }
          onSuccess={(updated) => {
            toast.success(`Fridge “${updated.friendly_name}” updated`)
            invalidate()
            setEditing(null)
          }}
        />
      ) : null}

      {deleting ? (
        <DeleteFridgeDialog
          fridge={deleting}
          onClose={() => setDeleting(null)}
          onDeleted={() => {
            toast.success(`Fridge “${deleting.friendly_name}” deleted`)
            invalidate()
            setDeleting(null)
          }}
        />
      ) : null}

      {configuring ? (
        <DeliveryConfigDialog fridge={configuring} onClose={() => setConfiguring(null)} />
      ) : null}
    </div>
  )
}

interface FridgeFormDialogProps {
  title: string
  initial: FridgeForm
  submitLabel: string
  clients: Client[]
  onClose: () => void
  onSubmit: (form: FridgeForm) => Promise<Fridge>
  onSuccess: (fridge: Fridge) => void
}

function FridgeFormDialog({
  title,
  initial,
  submitLabel,
  clients,
  onClose,
  onSubmit,
  onSuccess,
}: FridgeFormDialogProps) {
  const [form, setForm] = React.useState<FridgeForm>(initial)

  const mutation = useMutation({
    mutationFn: () => onSubmit(form),
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

  const canSubmit = form.husky_id.trim() !== '' && form.friendly_name.trim() !== ''

  return (
    <Dialog
      open
      onClose={onClose}
      title={title}
      widthClassName="max-w-xl"
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button onClick={() => mutation.mutate()} disabled={mutation.isPending || !canSubmit}>
            {mutation.isPending ? 'Saving…' : submitLabel}
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
          <Field label="Husky ID" required error={fieldErrors.husky_id}>
            <Input
              value={form.husky_id}
              autoFocus
              onChange={(event) => setForm((prev) => ({ ...prev, husky_id: event.target.value }))}
              placeholder="if-0001327"
            />
          </Field>
          <Field label="Friendly name" required error={fieldErrors.friendly_name}>
            <Input
              value={form.friendly_name}
              onChange={(event) =>
                setForm((prev) => ({ ...prev, friendly_name: event.target.value }))
              }
              placeholder="Abbott Wavre"
            />
          </Field>
          <Field label="Husky name" error={fieldErrors.husky_name}>
            <Input
              value={form.husky_name}
              onChange={(event) => setForm((prev) => ({ ...prev, husky_name: event.target.value }))}
            />
          </Field>
          <Field label="Client" error={fieldErrors.client_id}>
            <Select
              value={form.client_id === null ? NO_CLIENT : String(form.client_id)}
              onValueChange={(value) =>
                setForm((prev) => ({
                  ...prev,
                  client_id: value === NO_CLIENT ? null : Number(value),
                }))
              }
            >
              <SelectTrigger>
                <SelectValue placeholder="No client" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_CLIENT}>No client</SelectItem>
                {clients.map((client) => (
                  <SelectItem key={client.id} value={String(client.id)}>
                    {client.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
        </div>
        <Field label="Delivery address" error={fieldErrors.delivery_address}>
          <Textarea
            value={form.delivery_address}
            onChange={(event) =>
              setForm((prev) => ({ ...prev, delivery_address: event.target.value }))
            }
          />
        </Field>
        <Field label="Delivery instructions" error={fieldErrors.delivery_instructions}>
          <Textarea
            value={form.delivery_instructions}
            onChange={(event) =>
              setForm((prev) => ({ ...prev, delivery_instructions: event.target.value }))
            }
          />
        </Field>
        <label className="flex items-center justify-between gap-3">
          <span className="text-sm font-medium text-foreground">Active</span>
          <Switch
            checked={form.is_active}
            onCheckedChange={(checked) => setForm((prev) => ({ ...prev, is_active: checked }))}
          />
        </label>
      </div>
    </Dialog>
  )
}

interface DeleteFridgeDialogProps {
  fridge: Fridge
  onClose: () => void
  onDeleted: () => void
}

function DeleteFridgeDialog({ fridge, onClose, onDeleted }: DeleteFridgeDialogProps) {
  const mutation = useMutation({
    mutationFn: () => api.del<void>(`/api/v1/fridges/${fridge.id}`),
    onSuccess: onDeleted,
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Failed to delete fridge')
    },
  })

  return (
    <Dialog
      open
      onClose={onClose}
      title={`Delete ${fridge.friendly_name}?`}
      description="Fridges referenced by dispatches or config cannot be deleted."
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending}
          >
            {mutation.isPending ? 'Deleting…' : 'Delete fridge'}
          </Button>
        </>
      }
    >
      <p className="text-sm text-muted-foreground">
        Permanently delete <span className="font-medium text-foreground">{fridge.friendly_name}</span>?
      </p>
    </Dialog>
  )
}

// ─────────────────────── Delivery-config editor ───────────────────────

interface WeekdayRow {
  enabled: boolean
  min_daily_qty: string
  days_to_fill: string
}

function emptyWeek(): WeekdayRow[] {
  return WEEKDAYS.map(() => ({ enabled: false, min_daily_qty: '0', days_to_fill: '1' }))
}

function DeliveryConfigDialog({ fridge, onClose }: { fridge: Fridge; onClose: () => void }) {
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
      const index = item.weekday - 1 // ISO Mon=1 … Sun=7 -> row index 0..6
      if (index >= 0 && index < 7) {
        next[index] = {
          enabled: true,
          min_daily_qty: String(item.min_daily_qty),
          days_to_fill: String(item.days_to_fill),
        }
      }
    }
    setRows(next)
  }, [configQuery.data])

  const saveMutation = useMutation({
    mutationFn: () => {
      const items: DeliveryConfigItem[] = rows
        .map((row, index) => ({ row, index }))
        .filter(({ row }) => row.enabled)
        .map(({ row, index }) => ({
          weekday: index + 1, // row index 0..6 -> ISO Mon=1 … Sun=7
          min_daily_qty: Number(row.min_daily_qty) || 0,
          days_to_fill: Number(row.days_to_fill) || 1,
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

  return (
    <Dialog
      open
      onClose={onClose}
      title={`Delivery schedule — ${fridge.friendly_name}`}
      description="Tick each weekday this fridge is restocked. Min daily qty and days-to-fill drive the forecast."
      widthClassName="max-w-2xl"
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={saveMutation.isPending}>
            Cancel
          </Button>
          <Button onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending || configQuery.isLoading}>
            {saveMutation.isPending ? 'Saving…' : `Save schedule (${enabledCount} day${enabledCount === 1 ? '' : 's'})`}
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
          <div className="grid grid-cols-[auto_1fr_1fr] items-center gap-3 px-1 text-xs font-medium text-muted-foreground">
            <span>Weekday</span>
            <span>Min daily qty</span>
            <span>Days to fill</span>
          </div>
          {rows.map((row, index) => (
            <div
              key={WEEKDAYS[index]}
              className="grid grid-cols-[auto_1fr_1fr] items-center gap-3 rounded-md border border-border px-3 py-2"
            >
              <label className="flex w-32 items-center gap-2 text-sm font-medium">
                <input
                  type="checkbox"
                  checked={row.enabled}
                  onChange={(event) => updateRow(index, { enabled: event.target.checked })}
                  className="h-4 w-4 rounded border-input accent-[var(--primary)]"
                />
                {WEEKDAYS[index]}
              </label>
              <Input
                type="number"
                min={0}
                value={row.min_daily_qty}
                disabled={!row.enabled}
                onChange={(event) => updateRow(index, { min_daily_qty: event.target.value })}
              />
              <Input
                type="number"
                min={1}
                value={row.days_to_fill}
                disabled={!row.enabled}
                onChange={(event) => updateRow(index, { days_to_fill: event.target.value })}
              />
            </div>
          ))}
        </div>
      )}
    </Dialog>
  )
}

export default FridgesPage
