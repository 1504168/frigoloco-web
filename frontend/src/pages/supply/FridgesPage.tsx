import * as React from 'react'
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarClock, MessageSquareText, Pencil, Search, Wrench } from 'lucide-react'
import { FilterBar } from '@/components/filters/FilterBar'
import { ALL_OPTION_VALUE } from '@/components/filters/filterValues'
import { DataTable, type DataTableColumn } from '@/components/shared/DataTable'
import { EmptyState } from '@/components/shared/EmptyState'
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
import { toast } from '@/components/ui/toast'
import { api, type Page } from '@/lib/api'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { EMPTY_PLACEHOLDER } from '@/lib/format'
import { REFERENCE_FRIDGES_KEY } from '@/lib/query-keys'
import { compareNatural } from '@/lib/naturalSort'
import { DeliveryConfigDialog } from './components/DeliveryConfigDialog'
import { EditFridgeDialog } from './components/EditFridgeDialog'
import { FridgeInterventionsDialog } from './components/FridgeInterventionsDialog'
import { NO_CLIENT_VALUE, WEEKDAYS, huskyStatusLabel } from './components/fridgeOptions'
import type { Client, Fridge } from './types'

const PAGE_SIZE = 25
const ALL_FRIDGES_LIMIT = 500
const ALL_CLIENTS_LIMIT = 500
const SEARCH_DEBOUNCE_MS = 500
const NOWRAP_HEADER = 'whitespace-nowrap'
const DEFAULT_STATUS_FILTER: StatusFilter = 'active'
const NO_MATCH_DESCRIPTION =
  'No fridge matches these filters. Try a different client, status, day or search.'
/** Husky statuses offered in the filter, in the fleet's lifecycle order. */
const HUSKY_STATUSES = [
  'LIVE',
  'READY_TO_USE',
  'SHIPPED',
  'READY_TO_SHIP',
  'AWAITING_ASSEMBLY',
  'DEFECTIVE',
  'END_OF_LIFE',
]

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
/** "07:30:00" from the API -> "07:30". */
const HOURS_AND_MINUTES_LENGTH = 5

export function FridgesPage() {
  const queryClient = useQueryClient()
  const [offset, setOffset] = React.useState(0)
  const [clientFilter, setClientFilter] = React.useState<string>(ALL_OPTION_VALUE)
  const [statusFilter, setStatusFilter] = React.useState<StatusFilter>(DEFAULT_STATUS_FILTER)
  const [dayFilter, setDayFilter] = React.useState<string>(ALL_OPTION_VALUE)
  const [huskyStatusFilter, setHuskyStatusFilter] = React.useState<string>(ALL_OPTION_VALUE)
  const [searchInput, setSearchInput] = React.useState('')
  const [editing, setEditing] = React.useState<Fridge | null>(null)
  const [configuring, setConfiguring] = React.useState<Fridge | null>(null)
  const [viewingInterventions, setViewingInterventions] = React.useState<Fridge | null>(null)

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
  }, [clientFilter, statusFilter, dayFilter, huskyStatusFilter, search])

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

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: FRIDGES_QUERY_KEY })
    // The planning grids read fridge names and preferences from the shared reference cache.
    queryClient.invalidateQueries({ queryKey: REFERENCE_FRIDGES_KEY })
  }

  const columns = React.useMemo<DataTableColumn<Fridge>[]>(
    () => [
      {
        id: 'friendly_name',
        header: 'Fridge',
        headerClassName: NOWRAP_HEADER,
        cell: (row) => (
          <span className="inline-flex items-center gap-1.5 font-medium">
            {row.friendly_name}
            {row.preferences ? (
              <MessageSquareText
                className="h-3.5 w-3.5 text-muted-foreground"
                aria-label={`Site preferences: ${row.preferences}`}
              >
                <title>{row.preferences}</title>
              </MessageSquareText>
            ) : null}
          </span>
        ),
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
        id: 'husky_status',
        header: 'Husky status',
        headerClassName: NOWRAP_HEADER,
        cell: (row) => (
          <span className="whitespace-nowrap text-muted-foreground">
            {huskyStatusLabel(row.husky_status)}
          </span>
        ),
        sortValue: (row) => huskyStatusLabel(row.husky_status),
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
        id: 'delivery_window',
        header: 'Delivery time',
        headerClassName: NOWRAP_HEADER,
        cell: (row) => <DeliveryWindowCell fridge={row} />,
        sortValue: (row) => row.delivery_time_from ?? '',
      },
      {
        id: 'weekends',
        header: 'Weekends',
        headerClassName: NOWRAP_HEADER,
        cell: (row) =>
          row.active_on_weekends ? (
            <span>Open</span>
          ) : (
            <span className="text-muted-foreground">Closed</span>
          ),
        sortValue: (row) => (row.active_on_weekends ? 1 : 0),
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
              size="sm"
              className="h-7 px-2"
              onClick={() => setViewingInterventions(row)}
            >
              <Wrench className="h-4 w-4" /> Interventions
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
      matchesHuskyStatusFilter(fridge, huskyStatusFilter) &&
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
    dayFilter !== ALL_OPTION_VALUE ||
    huskyStatusFilter !== ALL_OPTION_VALUE

  return (
    <div className="space-y-3">
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
              value={huskyStatusFilter}
              onValueChange={setHuskyStatusFilter}
            >
              <SelectTrigger
                className="w-44"
                aria-label="Husky status"
              >
                <SelectValue placeholder="All Husky statuses" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL_OPTION_VALUE}>All Husky statuses</SelectItem>
                {HUSKY_STATUSES.map((huskyStatus) => (
                  <SelectItem
                    key={huskyStatus}
                    value={huskyStatus}
                  >
                    {huskyStatusLabel(huskyStatus)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
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

      {viewingInterventions ? (
        <FridgeInterventionsDialog
          fridge={viewingInterventions}
          onClose={() => setViewingInterventions(null)}
        />
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

function matchesHuskyStatusFilter(fridge: Fridge, huskyStatusFilter: string): boolean {
  if (huskyStatusFilter === ALL_OPTION_VALUE) return true
  return fridge.husky_status === huskyStatusFilter
}

/** `search` is already lower-cased; matches the fridge name, Husky name or Husky id. */
function matchesFridgeSearch(fridge: Fridge, search: string): boolean {
  if (!search) return true
  const searchableTexts = [fridge.friendly_name, fridge.husky_name ?? '', fridge.husky_id]
  return searchableTexts.some((text) => text.toLowerCase().includes(search))
}

/** "07:00-10:00" plus a night marker; a dash when neither is set. */
function DeliveryWindowCell({ fridge }: { fridge: Fridge }) {
  const from = fridge.delivery_time_from?.slice(0, HOURS_AND_MINUTES_LENGTH)
  const to = fridge.delivery_time_to?.slice(0, HOURS_AND_MINUTES_LENGTH)
  const hasWindow = from !== undefined || to !== undefined
  if (!hasWindow && !fridge.night_delivery_ok) {
    return <span className="text-muted-foreground">-</span>
  }
  return (
    <span className="whitespace-nowrap">
      {hasWindow ? `${from ?? '…'}-${to ?? '…'}` : null}
      {fridge.night_delivery_ok ? <span className="ml-1 text-xs text-muted-foreground">night ok</span> : null}
    </span>
  )
}

export default FridgesPage
