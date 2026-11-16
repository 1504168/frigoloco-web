import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ErrorState } from '@/components/shared/ErrorState'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { toast } from '@/components/ui/toast'
import { api, ApiError } from '@/lib/api'
import { Field } from './form'
import type { ClientContact, ClientContactRole } from '../types'

const CONTACT_ROLES: Array<{ role: ClientContactRole; label: string }> = [
  { role: 'account_finance', label: 'Account management / Finance' },
  { role: 'operations', label: 'Daily operations' },
  { role: 'it', label: 'IT' },
]

type ContactForm = Omit<ClientContact, 'role'>
type ContactFormField = keyof ContactForm
type ContactFormsByRole = Record<ClientContactRole, ContactForm>

const EMPTY_CONTACT: ContactForm = {
  name: '',
  job_title: '',
  phone: '',
  email: '',
}

/** The client's three contacts (finance, operations, IT), edited in place and saved together. */
export function ClientContactsTab({ clientId }: { clientId: number }) {
  const queryClient = useQueryClient()
  const contactsQueryKey = ['supply', 'client-contacts', clientId]
  const contactsUrl = `/api/v1/clients/${clientId}/contacts`

  const contactsQuery = useQuery({
    queryKey: contactsQueryKey,
    queryFn: ({ signal }) => api.get<ClientContact[]>(contactsUrl, { signal }),
  })

  const [forms, setForms] = React.useState<ContactFormsByRole | null>(null)
  const savedForms = contactsQuery.data ? toFormsByRole(contactsQuery.data) : null
  const shownForms = forms ?? savedForms

  const saveMutation = useMutation({
    mutationFn: (formsToSave: ContactFormsByRole) =>
      api.put<ClientContact[]>(contactsUrl, { items: toContactItems(formsToSave) }),
    onSuccess: (saved) => {
      toast.success('Contacts saved')
      queryClient.setQueryData(contactsQueryKey, saved)
      setForms(null)
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Failed to save contacts')
    },
  })

  if (contactsQuery.isLoading) {
    return <p className="py-4 text-center text-sm text-muted-foreground">Loading contacts…</p>
  }
  if (contactsQuery.isError || !shownForms) {
    return <ErrorState error={contactsQuery.error} onRetry={() => contactsQuery.refetch()} />
  }

  const currentForms = shownForms

  function updateField(role: ClientContactRole, field: ContactFormField, value: string) {
    setForms({ ...currentForms, [role]: { ...currentForms[role], [field]: value } })
  }

  return (
    <div className="space-y-3">
      {CONTACT_ROLES.map(({ role, label }) => (
        <ContactCard
          key={role}
          label={label}
          contact={currentForms[role]}
          onChange={(field, value) => updateField(role, field, value)}
        />
      ))}
      {/* Sticky so Save stays reachable while the dialog body scrolls on short screens. */}
      <div className="sticky bottom-0 -mx-5 -mb-4 flex justify-end gap-2 border-t border-border bg-card px-5 py-3">
        <Button
          variant="outline"
          size="sm"
          onClick={() => setForms(null)}
          disabled={forms === null || saveMutation.isPending}
        >
          Discard changes
        </Button>
        <Button
          size="sm"
          onClick={() => saveMutation.mutate(currentForms)}
          disabled={forms === null || saveMutation.isPending}
        >
          {saveMutation.isPending ? 'Saving…' : 'Save contacts'}
        </Button>
      </div>
    </div>
  )
}

interface ContactCardProps {
  label: string
  contact: ContactForm
  onChange: (field: ContactFormField, value: string) => void
}

function ContactCard({ label, contact, onChange }: ContactCardProps) {
  return (
    <div className="rounded-lg border border-border p-3">
      <h4 className="mb-2 text-sm font-semibold">{label}</h4>
      <div className="grid grid-cols-1 gap-x-3 gap-y-2 sm:grid-cols-2">
        <Field label="Name">
          <Input
            value={contact.name ?? ''}
            onChange={(event) => onChange('name', event.target.value)}
          />
        </Field>
        <Field label="Job title">
          <Input
            value={contact.job_title ?? ''}
            onChange={(event) => onChange('job_title', event.target.value)}
          />
        </Field>
        <Field label="Phone">
          <Input
            type="tel"
            value={contact.phone ?? ''}
            onChange={(event) => onChange('phone', event.target.value)}
          />
        </Field>
        <Field label="Email">
          <Input
            type="email"
            value={contact.email ?? ''}
            onChange={(event) => onChange('email', event.target.value)}
          />
        </Field>
      </div>
    </div>
  )
}

function toFormsByRole(contacts: ClientContact[]): ContactFormsByRole {
  const forms: ContactFormsByRole = {
    account_finance: EMPTY_CONTACT,
    operations: EMPTY_CONTACT,
    it: EMPTY_CONTACT,
  }
  for (const { role, ...details } of contacts) {
    forms[role] = details
  }
  return forms
}

/** One item per role; the server drops a role whose fields are all blank. */
function toContactItems(forms: ContactFormsByRole): ClientContact[] {
  return CONTACT_ROLES.map(({ role }) => ({ role, ...forms[role] }))
}
