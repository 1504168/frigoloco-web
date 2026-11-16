import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Pencil, Plus, ShieldAlert } from 'lucide-react'
import { DataTable, type DataTableColumn } from '@/components/shared/DataTable'
import { EmptyState } from '@/components/shared/EmptyState'
import { PageHeader } from '@/components/shared/PageHeader'
import { StatusChip } from '@/components/shared/StatusChip'
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
import { api, ApiError, type Page } from '@/lib/api'
import { ROLE_LABELS, USER_ROLES, type UserRole } from '@/hooks/useCurrentUser'
import { Dialog } from '@/pages/supply/components/Dialog'
import { Field, fieldErrorsFromApiError, generalErrorMessage } from '@/pages/supply/components/form'

/** Query key for the admin user list; every mutation invalidates it. */
const USERS_QUERY_KEY = ['users'] as const

/** Shape of a managed user row returned by GET /api/v1/users. */
interface ManagedUser {
  id: number
  email: string
  full_name: string
  role: UserRole
  is_active: boolean
}

/** Editable fields shared by the create and edit dialogs. */
interface UserForm {
  email: string
  full_name: string
  role: UserRole
  password: string
}

const EMPTY_FORM: UserForm = {
  email: '',
  full_name: '',
  role: 'ops_manager',
  password: '',
}

/**
 * Admin-only user management. Lists every account, creates new users, toggles
 * active status inline, and edits name / role / password via a dialog.
 *
 * A non-admin who reaches this route gets a 403 from GET /api/v1/users; that is
 * surfaced as a friendly "Admin only" panel rather than a crash.
 */
export function UsersPage() {
  const queryClient = useQueryClient()
  const [creating, setCreating] = React.useState(false)
  const [editing, setEditing] = React.useState<ManagedUser | null>(null)

  const usersQuery = useQuery({
    queryKey: USERS_QUERY_KEY,
    queryFn: ({ signal }) => api.get<ManagedUser[]>('/api/v1/users', { signal }),
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: USERS_QUERY_KEY })

  const toggleActive = useMutation({
    mutationFn: (user: ManagedUser) =>
      api.patch<ManagedUser>(`/api/v1/users/${user.id}`, { is_active: !user.is_active }),
    onSuccess: (updated) => {
      toast.success(`${updated.email} ${updated.is_active ? 'activated' : 'deactivated'}`)
      invalidate()
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Failed to update user')
    },
  })

  const columns = React.useMemo<DataTableColumn<ManagedUser>[]>(
    () => [
      {
        id: 'email',
        header: 'Email',
        cell: (row) => <span className="font-medium">{row.email}</span>,
        sortValue: (row) => row.email,
      },
      {
        id: 'full_name',
        header: 'Full name',
        cell: (row) => <span>{row.full_name}</span>,
        sortValue: (row) => row.full_name,
      },
      {
        id: 'role',
        header: 'Role',
        cell: (row) => <StatusChip variant="info" label={ROLE_LABELS[row.role]} />,
        sortValue: (row) => row.role,
      },
      {
        id: 'active',
        header: 'Active',
        cell: (row) => (
          <div className="flex items-center gap-2">
            <Switch
              checked={row.is_active}
              disabled={toggleActive.isPending}
              onCheckedChange={() => toggleActive.mutate(row)}
              aria-label={`${row.is_active ? 'Deactivate' : 'Activate'} ${row.email}`}
            />
            <StatusChip status={row.is_active ? 'active' : 'inactive'} />
          </div>
        ),
        sortValue: (row) => (row.is_active ? 1 : 0),
      },
      {
        id: 'actions',
        header: '',
        align: 'right',
        cell: (row) => (
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Edit ${row.email}`}
            onClick={() => setEditing(row)}
          >
            <Pencil className="h-4 w-4" />
          </Button>
        ),
      },
    ],
    [toggleActive],
  )

  // A non-admin caller gets 403; render a friendly gate instead of the table.
  if (usersQuery.error instanceof ApiError && usersQuery.error.status === 403) {
    return (
      <div className="space-y-4">
        <PageHeader breadcrumb="System / Users" title="Users" />
        <EmptyState
          icon={<ShieldAlert className="h-6 w-6" />}
          title="Admin only"
          description="You need an administrator account to manage users."
        />
      </div>
    )
  }

  const users = usersQuery.data ?? []
  const page: Page<ManagedUser> = {
    items: users,
    total: users.length,
    limit: Math.max(users.length, 1),
    offset: 0,
  }

  return (
    <div className="space-y-3">
      <PageHeader
        title="Users"
        className="items-center border-b-0 pb-0"
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus className="h-4 w-4" /> New user
          </Button>
        }
      />

      <DataTable
        columns={columns}
        page={usersQuery.isError ? undefined : page}
        isLoading={usersQuery.isLoading}
        isError={usersQuery.isError}
        error={usersQuery.error}
        onRetry={() => usersQuery.refetch()}
        limit={page.limit}
        offset={0}
        onOffsetChange={() => undefined}
        getRowId={(row) => row.id}
        emptyState={
          <EmptyState
            title="No users yet"
            description="Create the first account to grant access to the app."
            action={
              <Button onClick={() => setCreating(true)}>
                <Plus className="h-4 w-4" /> New user
              </Button>
            }
          />
        }
      />

      {creating ? (
        <UserFormDialog
          mode="create"
          title="New user"
          initial={EMPTY_FORM}
          submitLabel="Create user"
          onClose={() => setCreating(false)}
          onSubmit={(form) =>
            api.post<ManagedUser>('/api/v1/users', {
              email: form.email.trim(),
              full_name: form.full_name.trim(),
              role: form.role,
              password: form.password,
            })
          }
          onSuccess={(created) => {
            toast.success(`User “${created.email}” created`)
            invalidate()
            setCreating(false)
          }}
        />
      ) : null}

      {editing ? (
        <UserFormDialog
          mode="edit"
          title={`Edit ${editing.email}`}
          initial={{
            email: editing.email,
            full_name: editing.full_name,
            role: editing.role,
            password: '',
          }}
          submitLabel="Save changes"
          onClose={() => setEditing(null)}
          onSubmit={(form) => {
            const payload: Record<string, unknown> = {
              full_name: form.full_name.trim(),
              role: form.role,
            }
            // Password is optional on edit: only send it when the admin typed one.
            if (form.password) payload.password = form.password
            return api.patch<ManagedUser>(`/api/v1/users/${editing.id}`, payload)
          }}
          onSuccess={(updated) => {
            toast.success(`User “${updated.email}” updated`)
            invalidate()
            setEditing(null)
          }}
        />
      ) : null}
    </div>
  )
}

interface UserFormDialogProps {
  mode: 'create' | 'edit'
  title: string
  initial: UserForm
  submitLabel: string
  onClose: () => void
  onSubmit: (form: UserForm) => Promise<ManagedUser>
  onSuccess: (user: ManagedUser) => void
}

function UserFormDialog({
  mode,
  title,
  initial,
  submitLabel,
  onClose,
  onSubmit,
  onSuccess,
}: UserFormDialogProps) {
  const [form, setForm] = React.useState<UserForm>(initial)

  const mutation = useMutation({
    mutationFn: () => onSubmit(form),
    onSuccess,
    onError: (error) => {
      // Duplicate email (409) has no field-level detail; surface it as a toast.
      if (error instanceof ApiError && error.status === 409) {
        toast.error('A user with that email already exists.')
      }
    },
  })

  const fieldErrors = fieldErrorsFromApiError(mutation.error)
  const conflict = mutation.error instanceof ApiError && mutation.error.status === 409
  const generalError =
    mutation.error && !conflict && Object.keys(fieldErrors).length === 0
      ? generalErrorMessage(mutation.error)
      : null

  const emailMissing = mode === 'create' && !form.email.trim()
  const passwordMissing = mode === 'create' && !form.password
  const submitDisabled = mutation.isPending || emailMissing || passwordMissing

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
          <Button onClick={() => mutation.mutate()} disabled={submitDisabled}>
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

        <Field
          label="Email"
          required={mode === 'create'}
          error={fieldErrors.email ?? (conflict ? 'This email is already in use.' : undefined)}
        >
          <Input
            type="email"
            value={form.email}
            autoFocus={mode === 'create'}
            disabled={mode === 'edit'}
            onChange={(event) => setForm((prev) => ({ ...prev, email: event.target.value }))}
            placeholder="user@alliedchb.com"
          />
        </Field>

        <Field label="Full name" error={fieldErrors.full_name}>
          <Input
            value={form.full_name}
            onChange={(event) => setForm((prev) => ({ ...prev, full_name: event.target.value }))}
            placeholder="Jane Doe"
          />
        </Field>

        <Field label="Role" required error={fieldErrors.role}>
          <Select
            value={form.role}
            onValueChange={(value) => setForm((prev) => ({ ...prev, role: value as UserRole }))}
          >
            <SelectTrigger>
              <SelectValue placeholder="Select a role" />
            </SelectTrigger>
            <SelectContent>
              {USER_ROLES.map((role) => (
                <SelectItem key={role} value={role}>
                  {ROLE_LABELS[role]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>

        <Field
          label={mode === 'create' ? 'Password' : 'New password'}
          required={mode === 'create'}
          error={fieldErrors.password}
          hint={mode === 'edit' ? 'Leave blank to keep the current password.' : undefined}
        >
          <Input
            type="password"
            value={form.password}
            autoComplete="new-password"
            onChange={(event) => setForm((prev) => ({ ...prev, password: event.target.value }))}
            placeholder={mode === 'edit' ? '••••••••' : 'Set an initial password'}
          />
        </Field>
      </div>
    </Dialog>
  )
}

export default UsersPage
