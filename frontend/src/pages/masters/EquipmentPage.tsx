import * as React from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Pencil, Plus, Search, Trash2 } from 'lucide-react'
import { FilterBar } from '@/components/filters/FilterBar'
import { DataTable, type DataTableColumn } from '@/components/shared/DataTable'
import { EmptyState } from '@/components/shared/EmptyState'
import { StatusChip } from '@/components/shared/StatusChip'
import { Toolbar } from '@/components/shared/Toolbar'
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
import { useSupplierOptions } from '@/hooks/useSupplierOptions'
import { api, ApiError, type Page } from '@/lib/api'
import { EMPTY_PLACEHOLDER, formatDate, formatEuro } from '@/lib/format'
import type { Equipment } from '@/lib/types'
import { Dialog } from '@/pages/supply/components/Dialog'
import { useAllClients } from '@/pages/supply/components/masterLookups'
import { EquipmentFormDialog } from './EquipmentFormDialog'
import {
  EQUIPMENT_CATEGORIES,
  EQUIPMENT_CATEGORY_LABELS,
  OWNERSHIPS,
  OWNERSHIP_LABELS,
  formatEquipmentCost,
  formatFinancing,
} from './equipmentOptions'

const PAGE_SIZE = 25
const ALL_VALUE = 'all'
const EQUIPMENT_QUERY_KEY = ['masters', 'equipment']

interface EquipmentFilters {
  search: string
  category: string
  ownership: string
  client: string
}

const NO_FILTERS: EquipmentFilters = {
  search: '',
  category: ALL_VALUE,
  ownership: ALL_VALUE,
  client: ALL_VALUE,
}

/** Equipment register: coffee machines, water filters and vending machines with their client. */
export function EquipmentPage() {
  const queryClient = useQueryClient()
  const [offset, setOffset] = React.useState(0)
  const [filters, setFilters] = React.useState<EquipmentFilters>(NO_FILTERS)
  const [editing, setEditing] = React.useState<Equipment | null>(null)
  const [creating, setCreating] = React.useState(false)
  const [deleting, setDeleting] = React.useState<Equipment | null>(null)
  const clients = useAllClients().data ?? []
  const suppliers = useSupplierOptions().data ?? []
  const clientNameById = new Map(clients.map((client) => [client.id, client.name]))
  const supplierNameById = new Map(suppliers.map((supplier) => [supplier.id, supplier.name]))

  const equipmentQuery = useQuery({
    queryKey: [...EQUIPMENT_QUERY_KEY, { offset, filters }],
    queryFn: ({ signal }) =>
      api.get<Page<Equipment>>('/api/v1/equipment', {
        params: { limit: PAGE_SIZE, offset, ...toQueryParams(filters) },
        signal,
      }),
    placeholderData: keepPreviousData,
  })

  const refreshEquipment = () => queryClient.invalidateQueries({ queryKey: EQUIPMENT_QUERY_KEY })
  const changeFilter = (change: Partial<EquipmentFilters>) => {
    setFilters((previous) => ({ ...previous, ...change }))
    setOffset(0)
  }

  const columns: DataTableColumn<Equipment>[] = [
    {
      id: 'code',
      header: 'Machine code',
      cell: (row) => <span className="font-mono text-xs font-medium">{row.machine_code}</span>,
      sortValue: (row) => row.machine_code,
    },
    {
      id: 'type',
      header: 'Machine type',
      cell: (row) => (
        <div className="leading-tight">
          <div>{row.machine_type}</div>
          <div className="text-xs text-muted-foreground">
            {EQUIPMENT_CATEGORY_LABELS[row.equipment_category]}
          </div>
        </div>
      ),
      sortValue: (row) => row.machine_type,
    },
    {
      id: 'supplier',
      header: 'Supplier',
      cell: (row) => lookupName(supplierNameById, row.supplier_id),
      sortValue: (row) => lookupName(supplierNameById, row.supplier_id),
    },
    {
      id: 'client',
      header: 'Client',
      cell: (row) => lookupName(clientNameById, row.client_id),
      sortValue: (row) => lookupName(clientNameById, row.client_id),
    },
    {
      id: 'ownership',
      header: 'Bought / rented',
      cell: (row) => OWNERSHIP_LABELS[row.ownership],
      sortValue: (row) => row.ownership,
    },
    {
      id: 'cost',
      header: 'Our cost',
      align: 'right',
      cell: (row) => <span className="tabular-nums">{formatEquipmentCost(row)}</span>,
    },
    {
      id: 'monthly_fee',
      header: 'Monthly fee',
      align: 'right',
      cell: (row) => <span className="tabular-nums">{formatEuro(row.monthly_fee)}</span>,
      sortValue: (row) => Number(row.monthly_fee ?? 0),
    },
    {
      id: 'purchase_date',
      header: 'Purchase / start',
      cell: (row) => formatDate(row.purchase_date),
      sortValue: (row) => row.purchase_date ?? '',
    },
    {
      id: 'financing',
      header: 'Financing',
      cell: (row) => <span className="text-muted-foreground">{formatFinancing(row)}</span>,
    },
    {
      id: 'status',
      header: 'Status',
      cell: (row) => <StatusChip status={row.is_active ? 'active' : 'inactive'} />,
      sortValue: (row) => (row.is_active ? 1 : 0),
    },
    {
      id: 'actions',
      header: '',
      align: 'right',
      cell: (row) => (
        <div className="flex items-center justify-end gap-1">
          <Button variant="ghost" size="icon" aria-label={`Edit ${row.machine_code}`} onClick={() => setEditing(row)}>
            <Pencil className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="icon" aria-label={`Delete ${row.machine_code}`} onClick={() => setDeleting(row)}>
            <Trash2 className="h-4 w-4 text-critical" />
          </Button>
        </div>
      ),
    },
  ]

  return (
    <div className="space-y-3">
      <Toolbar
        left={
          <FilterBar>
            <div className="relative w-56">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={filters.search}
                onChange={(event) => changeFilter({ search: event.target.value })}
                placeholder="Machine code or type"
                aria-label="Search machine code or type"
                className="h-9 pl-8"
              />
            </div>
            <Select value={filters.category} onValueChange={(value) => changeFilter({ category: value })}>
              <SelectTrigger className="w-44" aria-label="Category">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL_VALUE}>All categories</SelectItem>
                {EQUIPMENT_CATEGORIES.map((category) => (
                  <SelectItem key={category} value={category}>
                    {EQUIPMENT_CATEGORY_LABELS[category]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={filters.ownership} onValueChange={(value) => changeFilter({ ownership: value })}>
              <SelectTrigger className="w-36" aria-label="Bought or rented">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL_VALUE}>Bought and rented</SelectItem>
                {OWNERSHIPS.map((ownership) => (
                  <SelectItem key={ownership} value={ownership}>
                    {OWNERSHIP_LABELS[ownership]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={filters.client} onValueChange={(value) => changeFilter({ client: value })}>
              <SelectTrigger className="w-48" aria-label="Client">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL_VALUE}>All clients</SelectItem>
                {clients.map((client) => (
                  <SelectItem key={client.id} value={String(client.id)}>
                    {client.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FilterBar>
        }
        right={
          <Button onClick={() => setCreating(true)}>
            <Plus className="h-4 w-4" /> New equipment
          </Button>
        }
      />

      <DataTable
        columns={columns}
        page={equipmentQuery.data}
        isLoading={equipmentQuery.isLoading}
        isError={equipmentQuery.isError}
        error={equipmentQuery.error}
        onRetry={() => equipmentQuery.refetch()}
        limit={PAGE_SIZE}
        offset={offset}
        onOffsetChange={setOffset}
        getRowId={(row) => row.id}
        emptyState={
          <EmptyState
            title="No equipment"
            description="Add coffee machines, water filters and vending machines to link them to clients."
            action={
              <Button onClick={() => setCreating(true)}>
                <Plus className="h-4 w-4" /> New equipment
              </Button>
            }
          />
        }
      />

      {creating || editing ? (
        <EquipmentFormDialog
          equipment={editing}
          onClose={() => {
            setCreating(false)
            setEditing(null)
          }}
          onSuccess={(saved) => {
            toast.success(`Equipment “${saved.machine_code}” saved`)
            refreshEquipment()
            setCreating(false)
            setEditing(null)
          }}
        />
      ) : null}

      {deleting ? (
        <DeleteEquipmentDialog
          equipment={deleting}
          onClose={() => setDeleting(null)}
          onDeleted={() => {
            toast.success(`Equipment “${deleting.machine_code}” deleted`)
            refreshEquipment()
            setDeleting(null)
          }}
        />
      ) : null}
    </div>
  )
}

interface DeleteEquipmentDialogProps {
  equipment: Equipment
  onClose: () => void
  onDeleted: () => void
}

function DeleteEquipmentDialog({ equipment, onClose, onDeleted }: DeleteEquipmentDialogProps) {
  const mutation = useMutation({
    mutationFn: () => api.del<void>(`/api/v1/equipment/${equipment.id}`),
    onSuccess: onDeleted,
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Failed to delete equipment')
    },
  })

  return (
    <Dialog
      open
      onClose={onClose}
      title={`Delete ${equipment.machine_code}?`}
      description="To keep its history, switch the machine to not in use instead."
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={() => mutation.mutate()} disabled={mutation.isPending}>
            {mutation.isPending ? 'Deleting…' : 'Delete equipment'}
          </Button>
        </>
      }
    >
      <p className="text-sm text-muted-foreground">
        Permanently delete <span className="font-medium text-foreground">{equipment.machine_code}</span>?
      </p>
    </Dialog>
  )
}

function toQueryParams(filters: EquipmentFilters): Record<string, string> {
  const params: Record<string, string> = {}
  if (filters.search.trim() !== '') params.search = filters.search.trim()
  if (filters.category !== ALL_VALUE) params.equipment_category = filters.category
  if (filters.ownership !== ALL_VALUE) params.ownership = filters.ownership
  if (filters.client !== ALL_VALUE) params.client_id = filters.client
  return params
}

function lookupName(nameById: Map<number, string>, id: number | null): string {
  if (id === null) return EMPTY_PLACEHOLDER
  return nameById.get(id) ?? `#${id}`
}

export default EquipmentPage
