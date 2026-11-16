import * as React from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Pencil, Plus, Trash2 } from 'lucide-react'
import { DataTable, type DataTableColumn } from '@/components/shared/DataTable'
import { EmptyState } from '@/components/shared/EmptyState'
import { ErrorState } from '@/components/shared/ErrorState'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { toast } from '@/components/ui/toast'
import { api, ApiError, type Page } from '@/lib/api'
import { EMPTY_PLACEHOLDER, formatEuro } from '@/lib/format'
import { ClientContactsTab } from './components/ClientContactsTab'
import { ClientEquipmentTab } from './components/ClientEquipmentTab'
import { ClientRulesTab } from './components/ClientRulesTab'
import { Dialog } from './components/Dialog'
import { DialogTabs, type DialogTab } from './components/DialogTabs'
import { Field, Textarea, fieldErrorsFromApiError, generalErrorMessage } from './components/form'
import type {
  Client,
  ClientCreate,
  ClientFee,
} from './types'

const PAGE_SIZE = 25

interface ClientForm {
  name: string
  location: string
  preferences: string
  notes: string
}

const EMPTY_FORM: ClientForm = {
  name: '',
  location: '',
  preferences: '',
  notes: '',
}

function toCreatePayload(form: ClientForm): ClientCreate {
  return {
    name: form.name.trim(),
    location: form.location.trim() || null,
    preferences: form.preferences.trim() || null,
    notes: form.notes.trim() || null,
  }
}

export function ClientsPage() {
  const queryClient = useQueryClient()
  const [offset, setOffset] = React.useState(0)
  const [creating, setCreating] = React.useState(false)
  const [editing, setEditing] = React.useState<Client | null>(null)
  const [deleting, setDeleting] = React.useState<Client | null>(null)
  const [detail, setDetail] = React.useState<Client | null>(null)

  const clientsQuery = useQuery({
    queryKey: ['supply', 'clients', 'list', { offset }],
    queryFn: ({ signal }) =>
      api.get<Page<Client>>('/api/v1/clients', { params: { limit: PAGE_SIZE, offset }, signal }),
    placeholderData: keepPreviousData,
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['supply', 'clients'] })

  const columns = React.useMemo<DataTableColumn<Client>[]>(
    () => [
      {
        id: 'name',
        header: 'Name',
        cell: (row) => <span className="font-medium">{row.name}</span>,
        sortValue: (row) => row.name,
      },
      {
        id: 'location',
        header: 'Location',
        cell: (row) => <span className="text-muted-foreground">{row.location ?? EMPTY_PLACEHOLDER}</span>,
        sortValue: (row) => row.location ?? '',
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
              onClick={(event) => {
                event.stopPropagation()
                setEditing(row)
              }}
            >
              <Pencil className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Delete ${row.name}`}
              onClick={(event) => {
                event.stopPropagation()
                setDeleting(row)
              }}
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
            <Plus className="h-4 w-4" /> New client
          </Button>
        </div>
      </div>

      <DataTable
        columns={columns}
        page={clientsQuery.data}
        isLoading={clientsQuery.isLoading}
        isError={clientsQuery.isError}
        error={clientsQuery.error}
        onRetry={() => clientsQuery.refetch()}
        limit={PAGE_SIZE}
        offset={offset}
        onOffsetChange={setOffset}
        getRowId={(row) => row.id}
        onRowClick={(row) => setDetail(row)}
        emptyState={
          <EmptyState
            title="No clients yet"
            description="Add your first client to start tracking fees and contacts."
            action={
              <Button onClick={() => setCreating(true)}>
                <Plus className="h-4 w-4" /> New client
              </Button>
            }
          />
        }
      />

      {creating ? (
        <ClientFormDialog
          title="New client"
          initial={EMPTY_FORM}
          submitLabel="Create client"
          onClose={() => setCreating(false)}
          onSubmit={(form) => api.post<Client>('/api/v1/clients', toCreatePayload(form))}
          onSuccess={(created) => {
            toast.success(`Client “${created.name}” created`)
            invalidate()
            setCreating(false)
          }}
        />
      ) : null}

      {editing ? (
        <ClientFormDialog
          title={`Edit ${editing.name}`}
          initial={{
            name: editing.name,
            location: editing.location ?? '',
            preferences: editing.preferences ?? '',
            notes: editing.notes ?? '',
          }}
          submitLabel="Save changes"
          onClose={() => setEditing(null)}
          onSubmit={(form) => api.put<Client>(`/api/v1/clients/${editing.id}`, toCreatePayload(form))}
          onSuccess={(updated) => {
            toast.success(`Client “${updated.name}” updated`)
            invalidate()
            setEditing(null)
          }}
        />
      ) : null}

      {deleting ? (
        <DeleteClientDialog
          client={deleting}
          onClose={() => setDeleting(null)}
          onDeleted={() => {
            toast.success(`Client “${deleting.name}” deleted`)
            invalidate()
            setDeleting(null)
          }}
        />
      ) : null}

      {detail ? <ClientDetailDialog client={detail} onClose={() => setDetail(null)} /> : null}
    </div>
  )
}

interface ClientFormDialogProps {
  title: string
  initial: ClientForm
  submitLabel: string
  onClose: () => void
  onSubmit: (form: ClientForm) => Promise<Client>
  onSuccess: (client: Client) => void
}

function ClientFormDialog({
  title,
  initial,
  submitLabel,
  onClose,
  onSubmit,
  onSuccess,
}: ClientFormDialogProps) {
  const [form, setForm] = React.useState<ClientForm>(initial)

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
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Name" required error={fieldErrors.name}>
            <Input
              value={form.name}
              autoFocus
              onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
            />
          </Field>
          <Field label="Location" error={fieldErrors.location}>
            <Input
              value={form.location}
              onChange={(event) => setForm((prev) => ({ ...prev, location: event.target.value }))}
            />
          </Field>
        </div>
        <Field label="Preferences" error={fieldErrors.preferences}>
          <Textarea
            value={form.preferences}
            onChange={(event) => setForm((prev) => ({ ...prev, preferences: event.target.value }))}
          />
        </Field>
        <Field label="Notes" error={fieldErrors.notes}>
          <Textarea
            value={form.notes}
            onChange={(event) => setForm((prev) => ({ ...prev, notes: event.target.value }))}
          />
        </Field>
      </div>
    </Dialog>
  )
}

function DeleteClientDialog({
  client,
  onClose,
  onDeleted,
}: {
  client: Client
  onClose: () => void
  onDeleted: () => void
}) {
  const mutation = useMutation({
    mutationFn: () => api.del<void>(`/api/v1/clients/${client.id}`),
    onSuccess: onDeleted,
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Failed to delete client')
    },
  })

  return (
    <Dialog
      open
      onClose={onClose}
      title={`Delete ${client.name}?`}
      description="Clients referenced by a fridge cannot be deleted."
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
            {mutation.isPending ? 'Deleting…' : 'Delete client'}
          </Button>
        </>
      }
    >
      <p className="text-sm text-muted-foreground">
        Permanently delete <span className="font-medium text-foreground">{client.name}</span>?
      </p>
    </Dialog>
  )
}

// ─────────────────────── Client detail (tabs) ───────────────────────

type DetailTab = 'details' | 'contacts' | 'fees' | 'rules' | 'equipment'

const DETAIL_TABS: DialogTab<DetailTab>[] = [
  { id: 'details', label: 'Details' },
  { id: 'contacts', label: 'Contacts' },
  { id: 'fees', label: 'Fees' },
  { id: 'rules', label: 'Rules' },
  { id: 'equipment', label: 'Equipment' },
]

function ClientDetailDialog({ client, onClose }: { client: Client; onClose: () => void }) {
  const [tab, setTab] = React.useState<DetailTab>('details')

  return (
    <Dialog open onClose={onClose} title={client.name} widthClassName="max-w-3xl">
      <DialogTabs tabs={DETAIL_TABS} activeTab={tab} onChange={setTab} />
      {tab === 'details' ? <ClientDetailsTab client={client} /> : null}
      {tab === 'contacts' ? <ClientContactsTab clientId={client.id} /> : null}
      {tab === 'fees' ? <ClientFeesTab clientId={client.id} /> : null}
      {tab === 'rules' ? <ClientRulesTab clientId={client.id} /> : null}
      {tab === 'equipment' ? <ClientEquipmentTab clientId={client.id} /> : null}
    </Dialog>
  )
}

function DetailRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 border-b border-border py-2 text-sm last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium text-foreground">{value || EMPTY_PLACEHOLDER}</span>
    </div>
  )
}

function ClientDetailsTab({ client }: { client: Client }) {
  return (
    <div className="space-y-1">
      <DetailRow label="Location" value={client.location} />
      <DetailRow label="Preferences" value={client.preferences} />
      <DetailRow label="Notes" value={client.notes} />
    </div>
  )
}

function ClientFeesTab({ clientId }: { clientId: number }) {
  const queryClient = useQueryClient()
  const [yearlyFee, setYearlyFee] = React.useState('')
  const [contractStart, setContractStart] = React.useState('')
  const [contractEnd, setContractEnd] = React.useState('')

  const feesQuery = useQuery({
    queryKey: ['supply', 'client-fees', clientId],
    queryFn: ({ signal }) =>
      api.get<ClientFee[]>(`/api/v1/clients/${clientId}/fees`, { signal }),
  })

  const addMutation = useMutation({
    mutationFn: () =>
      api.post<ClientFee>(`/api/v1/clients/${clientId}/fees`, {
        yearly_fee: yearlyFee,
        contract_start: contractStart,
        contract_end: contractEnd || null,
      }),
    onSuccess: () => {
      toast.success('Fee added')
      setYearlyFee('')
      setContractStart('')
      setContractEnd('')
      queryClient.invalidateQueries({ queryKey: ['supply', 'client-fees', clientId] })
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Failed to add fee')
    },
  })

  const fieldErrors = fieldErrorsFromApiError(addMutation.error)
  const canSubmit = yearlyFee.trim() !== '' && contractStart.trim() !== ''

  return (
    <div className="space-y-4">
      {feesQuery.isLoading ? (
        <p className="py-4 text-center text-sm text-muted-foreground">Loading fees…</p>
      ) : feesQuery.isError ? (
        <ErrorState error={feesQuery.error} onRetry={() => feesQuery.refetch()} />
      ) : feesQuery.data && feesQuery.data.length > 0 ? (
        <div className="overflow-hidden rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Yearly fee</th>
                <th className="px-3 py-2 text-left font-medium">Contract start</th>
                <th className="px-3 py-2 text-left font-medium">Contract end</th>
              </tr>
            </thead>
            <tbody>
              {feesQuery.data.map((fee) => (
                <tr key={fee.id} className="border-t border-border">
                  <td className="px-3 py-2 font-medium tabular-nums">{formatEuro(fee.yearly_fee)}</td>
                  <td className="px-3 py-2">{fee.contract_start}</td>
                  <td className="px-3 py-2">{fee.contract_end ?? EMPTY_PLACEHOLDER}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="No fees" description="No fee contracts recorded for this client." />
      )}

      <div className="rounded-lg border border-border p-4">
        <h4 className="mb-3 text-sm font-semibold">Add fee</h4>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Field label="Yearly fee (€)" required error={fieldErrors.yearly_fee}>
            <Input
              type="number"
              step="0.01"
              min={0}
              value={yearlyFee}
              onChange={(event) => setYearlyFee(event.target.value)}
            />
          </Field>
          <Field label="Contract start" required error={fieldErrors.contract_start}>
            <Input
              type="date"
              value={contractStart}
              onChange={(event) => setContractStart(event.target.value)}
            />
          </Field>
          <Field label="Contract end" error={fieldErrors.contract_end}>
            <Input
              type="date"
              value={contractEnd}
              onChange={(event) => setContractEnd(event.target.value)}
            />
          </Field>
        </div>
        <div className="mt-3 flex justify-end">
          <Button
            size="sm"
            onClick={() => addMutation.mutate()}
            disabled={addMutation.isPending || !canSubmit}
          >
            {addMutation.isPending ? 'Adding…' : 'Add fee'}
          </Button>
        </div>
      </div>
    </div>
  )
}

export default ClientsPage
