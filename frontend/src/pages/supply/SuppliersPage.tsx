import * as React from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Pencil, Plus, Trash2 } from 'lucide-react'
import { DataTable, type DataTableColumn } from '@/components/shared/DataTable'
import { EmptyState } from '@/components/shared/EmptyState'
import { InfoHint, type Hint } from '@/components/shared/InfoHint'
import { StatusChip } from '@/components/shared/StatusChip'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { toast } from '@/components/ui/toast'
import { api, ApiError, type Page } from '@/lib/api'
import { EMPTY_PLACEHOLDER } from '@/lib/format'
import { Dialog } from './components/Dialog'
import { DialogTabs, type DialogTab } from './components/DialogTabs'
import { Field, Textarea, fieldErrorsFromApiError, generalErrorMessage } from './components/form'
import { SupplierAgreementsTab } from './components/SupplierAgreementsTab'
import { SupplierScheduleTab } from './components/SupplierScheduleTab'
import type { Supplier, SupplierCreate } from './types'

const PAGE_SIZE = 25
const PAYMENT_TERMS_HINT: Hint = {
  text: 'How many days after the invoice the supplier must be paid. Leave empty when unknown.',
  example: '30: an invoice of 10 March is due on 9 April.',
}
const END_OF_MONTH_HINT: Hint = {
  text: 'The payment days start at the end of the invoice month instead of the invoice date.',
  example: '30 days end of month: an invoice of 10 March is due on 30 April.',
}
const WHOLE_NUMBER_PATTERN = /^\d+$/

type SupplierDialogTab = 'details' | 'agreements' | 'schedule'

const EDIT_DIALOG_TABS: DialogTab<SupplierDialogTab>[] = [
  { id: 'details', label: 'Details' },
  { id: 'agreements', label: 'Agreements' },
  { id: 'schedule', label: 'Schedule' },
]

type SupplierPayload = SupplierCreate & {
  payment_terms_days: number | null
  payment_terms_end_of_month: boolean
}

interface SupplierForm {
  name: string
  email: string
  warehouse_address: string
  contact_name: string
  contact_phone: string
  payment_terms_days: string
  payment_terms_end_of_month: boolean
  is_active: boolean
}

const EMPTY_FORM: SupplierForm = {
  name: '',
  email: '',
  warehouse_address: '',
  contact_name: '',
  contact_phone: '',
  payment_terms_days: '',
  payment_terms_end_of_month: false,
  is_active: true,
}

function toCreatePayload(form: SupplierForm): SupplierPayload {
  const paymentTermsText = form.payment_terms_days.trim()
  return {
    name: form.name.trim(),
    email: form.email.trim() || null,
    warehouse_address: form.warehouse_address.trim() || null,
    contact_name: form.contact_name.trim() || null,
    contact_phone: form.contact_phone.trim() || null,
    payment_terms_days: paymentTermsText === '' ? null : Number(paymentTermsText),
    payment_terms_end_of_month: form.payment_terms_end_of_month,
    is_active: form.is_active,
  }
}

function toSupplierForm(supplier: Supplier): SupplierForm {
  return {
    name: supplier.name,
    email: supplier.email ?? '',
    warehouse_address: supplier.warehouse_address ?? '',
    contact_name: supplier.contact_name ?? '',
    contact_phone: supplier.contact_phone ?? '',
    payment_terms_days:
      supplier.payment_terms_days === null ? '' : String(supplier.payment_terms_days),
    payment_terms_end_of_month: supplier.payment_terms_end_of_month,
    is_active: supplier.is_active,
  }
}

/** "30 days", "60 days end of month", or the placeholder when not recorded. */
function formatPaymentTerms(supplier: Supplier): string {
  if (supplier.payment_terms_days === null) return EMPTY_PLACEHOLDER
  const days = `${supplier.payment_terms_days} days`
  return supplier.payment_terms_end_of_month ? `${days} end of month` : days
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
          <span className="text-muted-foreground">{row.email ?? EMPTY_PLACEHOLDER}</span>
        ),
        sortValue: (row) => row.email ?? '',
      },
      {
        id: 'contact',
        header: 'Contact person',
        cell: (row) => <SupplierContactCell supplier={row} />,
        sortValue: (row) => row.contact_name ?? '',
      },
      {
        id: 'warehouse',
        header: 'Warehouse address',
        cell: (row) => (
          <span className="text-muted-foreground">{row.warehouse_address ?? EMPTY_PLACEHOLDER}</span>
        ),
        sortValue: (row) => row.warehouse_address ?? '',
      },
      {
        id: 'payment_terms',
        header: 'Payment terms',
        cell: (row) => <span className="text-muted-foreground">{formatPaymentTerms(row)}</span>,
        sortValue: (row) => row.payment_terms_days ?? -1,
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
    <div className="space-y-3">
      <div className="flex items-center">
        <div className="ml-auto">
          <Button onClick={() => setCreating(true)}>
            <Plus className="h-4 w-4" /> New supplier
          </Button>
        </div>
      </div>

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
          supplierId={editing.id}
          initial={toSupplierForm(editing)}
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
  /** Set when editing: adds the Agreements and Schedule tabs. */
  supplierId?: number
  initial: SupplierForm
  submitLabel: string
  onClose: () => void
  onSubmit: (form: SupplierForm) => Promise<Supplier>
  onSuccess: (supplier: Supplier) => void
}

function SupplierFormDialog({
  title,
  supplierId,
  initial,
  submitLabel,
  onClose,
  onSubmit,
  onSuccess,
}: SupplierFormDialogProps) {
  const [form, setForm] = React.useState<SupplierForm>(initial)
  const [activeTab, setActiveTab] = React.useState<SupplierDialogTab>('details')

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

  const paymentTermsText = form.payment_terms_days.trim()
  const hasInvalidPaymentTerms =
    paymentTermsText !== '' && !WHOLE_NUMBER_PATTERN.test(paymentTermsText)
  const canSave = form.name.trim() !== '' && !hasInvalidPaymentTerms
  const detailsFooter = (
    <>
      <Button variant="outline" onClick={onClose} disabled={mutation.isPending}>
        Cancel
      </Button>
      <Button onClick={() => mutation.mutate()} disabled={mutation.isPending || !canSave}>
        {mutation.isPending ? 'Saving…' : submitLabel}
      </Button>
    </>
  )
  const closeFooter = (
    <Button variant="outline" onClick={onClose}>
      Close
    </Button>
  )

  return (
    <Dialog
      open
      onClose={onClose}
      title={title}
      widthClassName={supplierId === undefined ? undefined : 'max-w-3xl'}
      footer={activeTab === 'details' ? detailsFooter : closeFooter}
    >
      {supplierId === undefined ? null : (
        <DialogTabs tabs={EDIT_DIALOG_TABS} activeTab={activeTab} onChange={setActiveTab} />
      )}
      {supplierId !== undefined && activeTab === 'agreements' ? (
        <SupplierAgreementsTab supplierId={supplierId} />
      ) : null}
      {supplierId !== undefined && activeTab === 'schedule' ? (
        <SupplierScheduleTab supplierId={supplierId} />
      ) : null}
      <div className={activeTab === 'details' ? 'space-y-4' : 'hidden'}>
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
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field
            label="Contact person"
            hint="Who to call when goods do not arrive"
            error={fieldErrors.contact_name}
          >
            <Input
              value={form.contact_name}
              onChange={(event) =>
                setForm((prev) => ({ ...prev, contact_name: event.target.value }))
              }
              placeholder="Full name"
            />
          </Field>
          <Field label="Contact phone" error={fieldErrors.contact_phone}>
            <Input
              type="tel"
              value={form.contact_phone}
              onChange={(event) =>
                setForm((prev) => ({ ...prev, contact_phone: event.target.value }))
              }
              placeholder="+32 …"
            />
          </Field>
        </div>
        <div className="grid grid-cols-1 items-end gap-4 sm:grid-cols-2">
          <Field
            label="Payment terms (days)"
            info={PAYMENT_TERMS_HINT}
            error={
              hasInvalidPaymentTerms
                ? 'Enter a whole number of days, or leave empty.'
                : fieldErrors.payment_terms_days
            }
          >
            <Input
              inputMode="numeric"
              value={form.payment_terms_days}
              onChange={(event) =>
                setForm((prev) => ({ ...prev, payment_terms_days: event.target.value }))
              }
              placeholder="30"
            />
          </Field>
          <label className="flex items-center justify-between gap-3 pb-6">
            <span className="flex items-center gap-1 text-sm font-medium text-foreground">
              Counted from end of month <InfoHint {...END_OF_MONTH_HINT} />
            </span>
            <Switch
              checked={form.payment_terms_end_of_month}
              onCheckedChange={(checked) =>
                setForm((prev) => ({ ...prev, payment_terms_end_of_month: checked }))
              }
            />
          </label>
        </div>
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

function SupplierContactCell({ supplier }: { supplier: Supplier }) {
  if (!supplier.contact_name && !supplier.contact_phone) {
    return <span className="text-muted-foreground">{EMPTY_PLACEHOLDER}</span>
  }
  return (
    <div className="leading-tight">
      <div>{supplier.contact_name ?? EMPTY_PLACEHOLDER}</div>
      {supplier.contact_phone ? (
        <a
          href={`tel:${supplier.contact_phone}`}
          className="text-xs text-muted-foreground hover:underline"
        >
          {supplier.contact_phone}
        </a>
      ) : null}
    </div>
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
