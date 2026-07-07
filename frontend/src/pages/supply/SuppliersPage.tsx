import * as React from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Pencil, Plus, Trash2 } from 'lucide-react'
import { PageHeader } from '@/components/shared/PageHeader'
import { DataTable, type DataTableColumn } from '@/components/shared/DataTable'
import { EmptyState } from '@/components/shared/EmptyState'
import { StatusChip } from '@/components/shared/StatusChip'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { toast } from '@/components/ui/sonner'
import { api, ApiError, type Page } from '@/lib/api'
import { Dialog } from './components/Dialog'
import { Field, Textarea, fieldErrorsFromApiError, generalErrorMessage } from './components/form'
import type { Supplier, SupplierCreate } from './types'

const PAGE_SIZE = 25

interface SupplierForm {
  name: string
  email: string
  warehouse_address: string
  is_active: boolean
}

const EMPTY_FORM: SupplierForm = {
  name: '',
  email: '',
  warehouse_address: '',
  is_active: true,
}

function toCreatePayload(form: SupplierForm): SupplierCreate {
  return {
    name: form.name.trim(),
    email: form.email.trim() || null,
    warehouse_address: form.warehouse_address.trim() || null,
    is_active: form.is_active,
  }
}

export function SuppliersPage() {
  const queryClient = useQueryClient()
  const [offset, setOffset] = React.useState(0)
  const [editing, setEditing] = React.useState<Supplier | null>(null)
  const [creating, setCreating] = React.useState(false)
  const [deleting, setDeleting] = React.useState<Supplier | null>(null)

  const suppliersQuery = useQuery({
    queryKey: ['supply', 'suppliers', { offset }],
    queryFn: ({ signal }) =>
      api.get<Page<Supplier>>('/api/v1/suppliers', {
        params: { limit: PAGE_SIZE, offset },
        signal,
      }),
    placeholderData: keepPreviousData,
  })

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['supply', 'suppliers'] })

  const columns = React.useMemo<DataTableColumn<Supplier>[]>(
    () => [
      {
        id: 'name',
        header: 'Name',
        cell: (row) => <span className="font-medium">{row.name}</span>,
        sortValue: (row) => row.name,
      },
      {
        id: 'email',
        header: 'Email',
        cell: (row) => (
          <span className="text-muted-foreground">{row.email ?? '—'}</span>
        ),
        sortValue: (row) => row.email ?? '',
      },
      {
        id: 'warehouse',
        header: 'Warehouse address',
        cell: (row) => (
          <span className="text-muted-foreground">{row.warehouse_address ?? '—'}</span>
        ),
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
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Edit ${row.name}`}
              onClick={() => setEditing(row)}
            >
              <Pencil className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Delete ${row.name}`}
              onClick={() => setDeleting(row)}
            >
              <Trash2 className="h-4 w-4 text-critical" />
            </Button>
          </div>
        ),
      },
    ],
    [],
  )

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumb="Masters / Suppliers"
        title="Suppliers"
        description="Vendors that fulfil purchase orders. Names must be unique."
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus className="h-4 w-4" /> New supplier
          </Button>
        }
      />

      <DataTable
        columns={columns}
        page={suppliersQuery.data}
        isLoading={suppliersQuery.isLoading}
        isError={suppliersQuery.isError}
        error={suppliersQuery.error}
        onRetry={() => suppliersQuery.refetch()}
        limit={PAGE_SIZE}
        offset={offset}
        onOffsetChange={setOffset}
        getRowId={(row) => row.id}
        emptyState={
          <EmptyState
            title="No suppliers yet"
            description="Create your first supplier to start raising purchase orders."
            action={
              <Button onClick={() => setCreating(true)}>
                <Plus className="h-4 w-4" /> New supplier
              </Button>
            }
          />
        }
      />

      {creating ? (
        <SupplierFormDialog
          title="New supplier"
          initial={EMPTY_FORM}
          submitLabel="Create supplier"
          onClose={() => setCreating(false)}
          onSubmit={(form) => api.post<Supplier>('/api/v1/suppliers', toCreatePayload(form))}
          onSuccess={(created) => {
            toast.success(`Supplier “${created.name}” created`)
            invalidate()
            setCreating(false)
          }}
        />
      ) : null}

      {editing ? (
        <SupplierFormDialog
          title={`Edit ${editing.name}`}
          initial={{
            name: editing.name,
            email: editing.email ?? '',
            warehouse_address: editing.warehouse_address ?? '',
            is_active: editing.is_active,
          }}
          submitLabel="Save changes"
          onClose={() => setEditing(null)}
          onSubmit={(form) =>
            api.put<Supplier>(`/api/v1/suppliers/${editing.id}`, toCreatePayload(form))
          }
          onSuccess={(updated) => {
            toast.success(`Supplier “${updated.name}” updated`)
            invalidate()
            setEditing(null)
          }}
        />
      ) : null}

      {deleting ? (
        <DeleteSupplierDialog
          supplier={deleting}
          onClose={() => setDeleting(null)}
          onDeleted={() => {
            toast.success(`Supplier “${deleting.name}” deleted`)
            invalidate()
            setDeleting(null)
          }}
        />
      ) : null}
    </div>
  )
}

interface SupplierFormDialogProps {
  title: string
  initial: SupplierForm
  submitLabel: string
  onClose: () => void
  onSubmit: (form: SupplierForm) => Promise<Supplier>
  onSuccess: (supplier: Supplier) => void
}

function SupplierFormDialog({
  title,
  initial,
  submitLabel,
  onClose,
  onSubmit,
  onSuccess,
}: SupplierFormDialogProps) {
  const [form, setForm] = React.useState<SupplierForm>(initial)

  const mutation = useMutation({
    mutationFn: () => onSubmit(form),
    onSuccess,
    onError: (error) => {
      if (error instanceof ApiError && error.code === 'conflict') {
        toast.error(error.message)
      }
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
      title={title}
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button onClick={() => mutation.mutate()} disabled={mutation.isPending || !form.name.trim()}>
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
        <Field label="Name" required error={fieldErrors.name}>
          <Input
            value={form.name}
            autoFocus
            onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
            placeholder="Supplier name"
          />
        </Field>
        <Field label="Email" error={fieldErrors.email}>
          <Input
            type="email"
            value={form.email}
            onChange={(event) => setForm((prev) => ({ ...prev, email: event.target.value }))}
            placeholder="orders@supplier.example"
          />
        </Field>
        <Field label="Warehouse address" error={fieldErrors.warehouse_address}>
          <Textarea
            value={form.warehouse_address}
            onChange={(event) =>
              setForm((prev) => ({ ...prev, warehouse_address: event.target.value }))
            }
            placeholder="Street, postal code, city"
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

interface DeleteSupplierDialogProps {
  supplier: Supplier
  onClose: () => void
  onDeleted: () => void
}

function DeleteSupplierDialog({ supplier, onClose, onDeleted }: DeleteSupplierDialogProps) {
  const mutation = useMutation({
    mutationFn: () => api.del<void>(`/api/v1/suppliers/${supplier.id}`),
    onSuccess: onDeleted,
    onError: (error) => {
      const message =
        error instanceof ApiError ? error.message : 'Failed to delete supplier'
      toast.error(message)
    },
  })

  return (
    <Dialog
      open
      onClose={onClose}
      title={`Delete ${supplier.name}?`}
      description="This cannot be undone. Suppliers referenced by a purchase order cannot be deleted."
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
            {mutation.isPending ? 'Deleting…' : 'Delete supplier'}
          </Button>
        </>
      }
    >
      <p className="text-sm text-muted-foreground">
        Are you sure you want to permanently delete{' '}
        <span className="font-medium text-foreground">{supplier.name}</span>?
      </p>
    </Dialog>
  )
}

export default SuppliersPage
