import * as React from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarClock, Pencil, Search } from 'lucide-react'
import { FilterBar } from '@/components/filters/FilterBar'
import { ALL_OPTION_VALUE } from '@/components/filters/filterValues'
import { DataTable, type DataTableColumn } from '@/components/shared/DataTable'
import { EmptyState } from '@/components/shared/EmptyState'
import { ErrorState } from '@/components/shared/ErrorState'
import { Toolbar } from '@/components/shared/Toolbar'
import {
  EffectiveStatusBadge,
  HuskySyncControl,
  StatusFilterSelect,
} from '@/pages/masters/sync/components'
import type { StatusFilter } from '@/pages/masters/sync/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { toast } from '@/components/ui/sonner'
import { api, ApiError, type Page } from '@/lib/api'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { EMPTY_PLACEHOLDER } from '@/lib/format'
import { compareNatural } from '@/lib/naturalSort'
import { Dialog } from './components/Dialog'
import { Field, Textarea, fieldErrorsFromApiError, generalErrorMessage } from './components/form'
import type {
  Client,
  DeliveryConfigItem,
  Fridge,
} from './types'

const PAGE_SIZE = 25
const ALL_FRIDGES_LIMIT = 500
const ALL_CLIENTS_LIMIT = 500
const SEARCH_DEBOUNCE_MS = 500
/** Select value for fridges that have no client yet. */
const NO_CLIENT_VALUE = 'none'
const NOWRAP_HEADER = 'whitespace-nowrap'
const DEFAULT_STATUS_FILTER: StatusFilter = 'active'
const NO_MATCH_DESCRIPTION =
  'No fridge matches these filters. Try a different client, status, day or search.'

/**
 * Weekday labels by row index. The API uses ISO weekday numbers (Mon=1 … Sun=7),
 * so the integer sent/received is always `index + 1`.
 */
const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

/** All clients sorted naturally by name, for the client column, filter and edit dialog. */
function useClientsLookup() {
  return useQuery({
    queryKey: ['supply', 'clients', 'all'],
    queryFn: ({ signal }) =>
      api.get<Page<Client>>('/api/v1/clients', {
        params: { limit: ALL_CLIENTS_LIMIT, offset: 0 },
        signal,
      }),
    staleTime: 60_000,
    select: (page) => [...page.items].sort((a, b) => compareNatural(a.name, b.name)),
  })
}

const FRIDGES_QUERY_KEY = ['supply', 'fridges']

export function FridgesPage() {
  const queryClient = useQueryClient()
  const [offset, setOffset] = React.useState(0)
  const [clientFilter, setClientFilter] = React.useState<string>(ALL_OPTION_VALUE)
  const [statusFilter, setStatusFilter] = React.useState<StatusFilter>(DEFAULT_STATUS_FILTER)
  const [dayFilter, setDayFilter] = React.useState<string>(ALL_OPTION_VALUE)
  const [searchInput, setSearchInput] = React.useState('')
  const [editing, setEditing] = React.useState<Fridge | null>(null)
  const [configuring, setConfiguring] = React.useState<Fridge | null>(null)

  const search = useDebouncedValue(searchInput.trim().toLowerCase(), SEARCH_DEBOUNCE_MS)

  const clientsQuery = useClientsLookup()
  const clients = React.useMemo(() => clientsQuery.data ?? [], [clientsQuery.data])
  const clientName = React.useCallback(
    (id: number | null) =>
      id === null ? EMPTY_PLACEHOLDER : clients.find((c) => c.id === id)?.name ?? `#${id}`,
    [clients],
  )

  React.useEffect(() => {
    setOffset(0)
  }, [clientFilter, statusFilter, dayFilter, search])

  // The fleet is small, so the status-filtered set is fetched once and the
  // client, day and search filters plus pagination run here in the browser.
  const fridgesQuery = useQuery({
    queryKey: ['supply', 'fridges', { status: statusFilter }],
    queryFn: ({ signal }) =>
      api.get<Page<Fridge>>('/api/v1/fridges', {
        params: { limit: ALL_FRIDGES_LIMIT, offset: 0, status: statusFilter },
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
        headerClassName: NOWRAP_HEADER,
        cell: (row) => <span className="font-medium">{row.friendly_name}</span>,
        sortValue: (row) => row.friendly_name,
      },
      {
        id: 'husky_id',
        header: 'Husky ID',
        headerClassName: NOWRAP_HEADER,
        cell: (row) => <span className="font-mono text-xs">{row.husky_id}</span>,
        sortValue: (row) => row.husky_id,
      },
      {
        id: 'client',
        header: 'Client',
        headerClassName: NOWRAP_HEADER,
        cell: (row) => <span className="text-muted-foreground">{clientName(row.client_id)}</span>,
        sortValue: (row) => clientName(row.client_id),
      },
      {
        id: 'status',
        header: 'Status',
        headerClassName: NOWRAP_HEADER,
        cell: (row) => <EffectiveStatusBadge status={row.effective_status} />,
        sortValue: (row) => row.effective_status,
      },
      {
        id: 'delivery_days',
        header: 'Delivery days',
        headerClassName: NOWRAP_HEADER,
        cell: (row) =>
          row.delivery_weekdays.length ? (
            <span>{row.delivery_weekdays.map((w) => WEEKDAYS[w - 1].slice(0, 3)).join(', ')}</span>
          ) : (
            <span className="text-muted-foreground">-</span>
          ),
        sortValue: (row) => row.delivery_weekdays.length,
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

  const allFridges = fridgesQuery.data?.items ?? []
  const filteredFridges = allFridges.filter(
    (fridge) =>
      matchesClientFilter(fridge, clientFilter) &&
      matchesDayFilter(fridge, dayFilter) &&
      matchesFridgeSearch(fridge, search),
  )
  const pageData: Page<Fridge> | undefined = fridgesQuery.data
    ? {
        items: filteredFridges.slice(offset, offset + PAGE_SIZE),
        total: filteredFridges.length,
        limit: PAGE_SIZE,
        offset,
      }
    : undefined
  const isFiltered =
    search !== '' ||
    clientFilter !== ALL_OPTION_VALUE ||
    statusFilter !== DEFAULT_STATUS_FILTER ||
    dayFilter !== ALL_OPTION_VALUE

  return (
    <div className="space-y-6">
      <Toolbar
        left={
          <FilterBar>
            <Select
              value={clientFilter}
              onValueChange={setClientFilter}
            >
              <SelectTrigger
                className="w-48"
                aria-label="Client"
              >
                <SelectValue placeholder="All clients" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL_OPTION_VALUE}>All clients</SelectItem>
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
            <StatusFilterSelect
              value={statusFilter}
              onChange={setStatusFilter}
              className="w-32"
            />
            <Select
              value={dayFilter}
              onValueChange={setDayFilter}
            >
              <SelectTrigger
                className="w-36"
                aria-label="Delivery day"
              >
                <SelectValue placeholder="All days" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL_OPTION_VALUE}>All days</SelectItem>
                {WEEKDAYS.map((name, i) => (
                  <SelectItem
                    key={name}
                    value={String(i + 1)}
                  >
                    {name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <div className="relative w-56">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                placeholder="Fridge name or if-ID"
                aria-label="Search fridge name or Husky fridge ID"
                className="h-9 pl-8"
              />
            </div>
          </FilterBar>
        }
        right={
          <HuskySyncControl
            feed="catalogue"
            endpoint="catalogue"
            invalidateKeys={[FRIDGES_QUERY_KEY]}
            itemLabel="fridge"
          />
        }
      />

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
          isFiltered ? (
            <EmptyState
              title="No matching fridges"
              description={NO_MATCH_DESCRIPTION}
            />
          ) : (
            <EmptyState
              title="No fridges yet"
              description="Fridges are synced in from Husky. Run Sync from Husky to load them."
            />
          )
        }
      />

      {editing ? (
        <EditFridgeDialog
          fridge={editing}
          clients={clients}
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

function matchesClientFilter(fridge: Fridge, clientFilter: string): boolean {
  if (clientFilter === ALL_OPTION_VALUE) return true
  if (clientFilter === NO_CLIENT_VALUE) return fridge.client_id === null
  return fridge.client_id === Number(clientFilter)
}

function matchesDayFilter(fridge: Fridge, dayFilter: string): boolean {
  if (dayFilter === ALL_OPTION_VALUE) return true
  return fridge.delivery_weekdays.includes(Number(dayFilter))
}

/** `search` is already lower-cased; matches the fridge name, Husky name or Husky id. */
function matchesFridgeSearch(fridge: Fridge, search: string): boolean {
  if (!search) return true
  const searchableTexts = [fridge.friendly_name, fridge.husky_name ?? '', fridge.husky_id]
  return searchableTexts.some((text) => text.toLowerCase().includes(search))
}

interface EditFridgeDialogProps {
  fridge: Fridge
  clients: Client[]
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
 * Edit a fridge's client and local delivery details. Identity and status are
 * Husky-owned and shown read-only; Husky sync only fills a client that is empty.
 */
function EditFridgeDialog({ fridge, clients, onClose, onSuccess }: EditFridgeDialogProps) {
  const [clientValue, setClientValue] = React.useState(
    fridge.client_id === null ? NO_CLIENT_VALUE : String(fridge.client_id),
  )
  const [deliveryAddress, setDeliveryAddress] = React.useState(fridge.delivery_address ?? '')
  const [deliveryInstructions, setDeliveryInstructions] = React.useState(
    fridge.delivery_instructions ?? '',
  )

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
          <ReadOnlyField label="Status" value={fridge.is_active ? 'Active' : 'Inactive'} />
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
          Identity and status come from Husky. Husky sync fills the client only when it is
          empty, so a client chosen here is kept.
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
                type="number"
                min={0}
                value={row.min_daily_qty}
                disabled={!row.enabled}
                onChange={(event) => updateRow(index, { min_daily_qty: event.target.value })}
              />
              <div className="flex h-9 items-center text-sm tabular-nums">
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
