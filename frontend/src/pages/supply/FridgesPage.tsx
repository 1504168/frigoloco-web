import * as React from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarClock, Pencil, Search } from 'lucide-react'
import { DataTable, type DataTableColumn } from '@/components/shared/DataTable'
import { EmptyState } from '@/components/shared/EmptyState'
import { ErrorState } from '@/components/shared/ErrorState'
import {
  EffectiveStatusBadge,
  HuskySyncControl,
  StatusFilterSelect,
} from '@/pages/masters/sync/components'
import type { StatusFilter } from '@/pages/masters/sync/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { toast } from '@/components/ui/sonner'
import { api, ApiError, type Page } from '@/lib/api'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { EMPTY_PLACEHOLDER } from '@/lib/format'
import { Dialog } from './components/Dialog'
import { Field, Textarea, fieldErrorsFromApiError, generalErrorMessage } from './components/form'
import type {
  Client,
  DeliveryConfigItem,
  Fridge,
} from './types'

const PAGE_SIZE = 25

/**
 * Weekday labels by row index. The API uses ISO weekday numbers (Mon=1 … Sun=7),
 * so the integer sent/received is always `index + 1`.
 */
const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

/** Shared clients lookup (id -> name) used for the client column and the edit dialog. */
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
  const [searchInput, setSearchInput] = React.useState('')
  const [editing, setEditing] = React.useState<Fridge | null>(null)
  const [configuring, setConfiguring] = React.useState<Fridge | null>(null)

  // Client-side search over the fridge name + client name (both are the visible
  // text columns). Debounced so typing stays smooth.
  const search = useDebouncedValue(searchInput.trim().toLowerCase(), 500)

  const clientsQuery = useClientsLookup()
  const clientName = React.useCallback(
    (id: number | null) =>
      id === null
        ? EMPTY_PLACEHOLDER
        : clientsQuery.data?.find((c) => c.id === id)?.name ?? `#${id}`,
    [clientsQuery.data],
  )

  // Reset to first page whenever the status filter or search term changes.
  React.useEffect(() => {
    setOffset(0)
  }, [statusFilter, search])

  // Fetch the full (status-filtered) set once; search + pagination are applied
  // client-side. The fleet is small (~50 fridges), so this stays cheap and lets
  // us search the client name, which the list endpoint does not expose.
  const fridgesQuery = useQuery({
    queryKey: ['supply', 'fridges', { status: statusFilter }],
    queryFn: ({ signal }) =>
      api.get<Page<Fridge>>('/api/v1/fridges', {
        params: { limit: 500, offset: 0, status: statusFilter },
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
        id: 'actions',
        header: '',
        align: 'right',
        cell: (row) => (
          <div className="flex items-center justify-end gap-1">
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-2"
              onClick={() => setConfiguring(row)}
            >
              <CalendarClock className="h-4 w-4" /> Delivery
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              aria-label={`Edit ${row.friendly_name}`}
              onClick={() => setEditing(row)}
            >
              <Pencil className="h-4 w-4" />
            </Button>
          </div>
        ),
      },
    ],
    [clientName],
  )

  // Search matches the Fridge column (friendly_name), the Client column
  // (resolved client name) or the Husky ID; then paginate the result locally.
  const allFridges = fridgesQuery.data?.items ?? []
  const filteredFridges = search
    ? allFridges.filter(
        (fridge) =>
          fridge.friendly_name.toLowerCase().includes(search) ||
          fridge.husky_id.toLowerCase().includes(search) ||
          clientName(fridge.client_id).toLowerCase().includes(search),
      )
    : allFridges
  const pageData: Page<Fridge> | undefined = fridgesQuery.data
    ? {
        items: filteredFridges.slice(offset, offset + PAGE_SIZE),
        total: filteredFridges.length,
        limit: PAGE_SIZE,
        offset,
      }
    : undefined

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        <StatusFilterSelect value={statusFilter} onChange={setStatusFilter} />
        <HuskySyncControl
          feed="catalogue"
          endpoint="catalogue"
          invalidateKeys={[FRIDGES_QUERY_KEY]}
          itemLabel="fridge"
        />
        <div className="relative ml-auto w-full max-w-xs">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            placeholder="Search by fridge or client…"
            className="pl-8"
          />
        </div>
      </div>

      <DataTable
        columns={columns}
        dense
        page={pageData}
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
            title={search ? 'No matching fridges' : 'No fridges yet'}
            description={
              search
                ? `No fridge or client matches “${searchInput.trim()}”. Try a different term.`
                : 'Fridges are synced in from Husky. Run Sync from Husky to load them.'
            }
          />
        }
      />

      {editing ? (
        <EditFridgeDialog
          fridge={editing}
          clientName={clientName}
          onClose={() => setEditing(null)}
          onSuccess={(updated) => {
            toast.success(`Fridge “${updated.friendly_name}” updated`)
            invalidate()
            setEditing(null)
          }}
        />
      ) : null}

      {configuring ? (
        <DeliveryConfigDialog fridge={configuring} onClose={() => setConfiguring(null)} />
      ) : null}
    </div>
  )
}

interface EditFridgeDialogProps {
  fridge: Fridge
  clientName: (id: number | null) => string
  onClose: () => void
  onSuccess: (fridge: Fridge) => void
}

/** Read-only display of a Husky-owned field (overwritten on every sync). */
function ReadOnlyField({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <Field label={label}>
      <div
        className={`flex min-h-9 items-center rounded-md border border-border bg-muted/40 px-3 py-1.5 text-sm text-muted-foreground${
          mono ? ' font-mono text-xs' : ''
        }`}
      >
        {value}
      </div>
    </Field>
  )
}

/**
 * Edit a fridge's local-only delivery details. Identity, client and status are
 * Husky-owned (overwritten on every sync) and shown read-only here.
 */
function EditFridgeDialog({ fridge, clientName, onClose, onSuccess }: EditFridgeDialogProps) {
  const [deliveryAddress, setDeliveryAddress] = React.useState(fridge.delivery_address ?? '')
  const [deliveryInstructions, setDeliveryInstructions] = React.useState(
    fridge.delivery_instructions ?? '',
  )

  const mutation = useMutation({
    mutationFn: () =>
      api.put<Fridge>(`/api/v1/fridges/${fridge.id}`, {
        // Husky-owned fields are echoed back unchanged; only delivery details change.
        husky_id: fridge.husky_id,
        husky_name: fridge.husky_name,
        friendly_name: fridge.friendly_name,
        client_id: fridge.client_id,
        is_active: fridge.is_active,
        delivery_address: deliveryAddress.trim() || null,
        delivery_instructions: deliveryInstructions.trim() || null,
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
          <ReadOnlyField label="Client" value={clientName(fridge.client_id)} />
          <ReadOnlyField label="Status" value={fridge.is_active ? 'Active' : 'Inactive'} />
        </div>
        <p className="text-xs text-muted-foreground">
          Identity, client and status come from Husky and are not editable here.
        </p>
        <Field label="Delivery address" error={fieldErrors.delivery_address}>
          <Textarea
            value={deliveryAddress}
            autoFocus
            onChange={(event) => setDeliveryAddress(event.target.value)}
          />
        </Field>
        <Field label="Delivery instructions" error={fieldErrors.delivery_instructions}>
          <Textarea
            value={deliveryInstructions}
            onChange={(event) => setDeliveryInstructions(event.target.value)}
          />
        </Field>
      </div>
    </Dialog>
  )
}

// ─────────────────────── Delivery-config editor ───────────────────────

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
        }
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
          weekday: index + 1, // row index 0..6 -> ISO Mon=1 … Sun=7
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

  return (
    <Dialog
      open
      onClose={onClose}
      title={`Delivery schedule: ${fridge.friendly_name}`}
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
            <span>Days to fill (auto)</span>
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
              <div className="flex h-9 items-center rounded-md border border-transparent px-3 text-sm tabular-nums">
                {row.enabled ? (
                  <span>
                    {derivedDaysToFill[index]}
                    <span className="ml-1 text-xs text-muted-foreground">
                      day{derivedDaysToFill[index] === 1 ? '' : 's'}
                    </span>
                  </span>
                ) : (
                  <span className="text-muted-foreground">-</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </Dialog>
  )
}

export default FridgesPage
