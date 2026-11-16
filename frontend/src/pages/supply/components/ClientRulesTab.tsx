import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Trash2 } from 'lucide-react'
import { EmptyState } from '@/components/shared/EmptyState'
import { ErrorState } from '@/components/shared/ErrorState'
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
import { api, ApiError } from '@/lib/api'
import { EMPTY_PLACEHOLDER, formatDate, formatFridgeName } from '@/lib/format'
import type { ClientRule, ClientRuleType, Fridge } from '@/lib/types'
import { Field, Textarea, fieldErrorsFromApiError } from './form'
import { productTagLabel, useAllFridges, useProductTagOptions } from './masterLookups'

const ALL_FRIDGES_VALUE = 'all'
const RULE_TYPE_LABELS: Record<ClientRuleType, string> = {
  exclude_tag: 'Exclude products tagged',
  note: 'Note',
}
const RULE_TYPES = Object.keys(RULE_TYPE_LABELS) as ClientRuleType[]

/** Client rules: products to exclude by tag (no pork, ...) or a free note, per client or fridge. */
export function ClientRulesTab({ clientId }: { clientId: number }) {
  const queryClient = useQueryClient()
  const rulesUrl = `/api/v1/clients/${clientId}/rules`
  const rulesQueryKey = ['supply', 'client-rules', clientId]
  const fridgesQuery = useAllFridges()
  const tagsQuery = useProductTagOptions()

  const rulesQuery = useQuery({
    queryKey: rulesQueryKey,
    queryFn: ({ signal }) => api.get<ClientRule[]>(rulesUrl, { signal }),
  })

  const deleteMutation = useMutation({
    mutationFn: (ruleId: number) => api.del<void>(`${rulesUrl}/${ruleId}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: rulesQueryKey }),
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Failed to delete rule')
    },
  })

  const clientFridges = (fridgesQuery.data ?? []).filter((fridge) => fridge.client_id === clientId)
  const fridgeNameById = new Map(clientFridges.map((fridge) => [fridge.id, formatFridgeName(fridge)]))

  return (
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground">
        The menu and dispatch screens warn when a product breaks one of these rules; they never
        block it. Tag products on the Products page.
      </p>
      <RulesTable
        rules={rulesQuery.data}
        isLoading={rulesQuery.isLoading}
        error={rulesQuery.isError ? rulesQuery.error : null}
        onRetry={() => rulesQuery.refetch()}
        fridgeNameById={fridgeNameById}
        onDelete={(ruleId) => deleteMutation.mutate(ruleId)}
      />
      <AddRuleForm
        rulesUrl={rulesUrl}
        clientFridges={clientFridges}
        tagOptions={tagsQuery.data ?? []}
        onAdded={() => queryClient.invalidateQueries({ queryKey: rulesQueryKey })}
      />
    </div>
  )
}

interface RulesTableProps {
  rules: ClientRule[] | undefined
  isLoading: boolean
  error: unknown
  onRetry: () => void
  fridgeNameById: Map<number, string>
  onDelete: (ruleId: number) => void
}

function RulesTable({ rules, isLoading, error, onRetry, fridgeNameById, onDelete }: RulesTableProps) {
  if (isLoading) {
    return <p className="py-4 text-center text-sm text-muted-foreground">Loading rules…</p>
  }
  if (error) return <ErrorState error={error} onRetry={onRetry} />
  if (!rules || rules.length === 0) {
    return <EmptyState title="No rules" description="No rule recorded for this client." />
  }
  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead className="bg-muted/40 text-xs text-muted-foreground">
          <tr>
            <th className="px-3 py-2 text-left font-medium">Applies to</th>
            <th className="px-3 py-2 text-left font-medium">Rule</th>
            <th className="px-3 py-2 text-left font-medium">Note</th>
            <th className="px-3 py-2 text-left font-medium">Valid</th>
            <th className="px-3 py-2" />
          </tr>
        </thead>
        <tbody>
          {rules.map((rule) => (
            <tr key={rule.id} className="border-t border-border">
              <td className="px-3 py-2">{ruleScopeLabel(rule, fridgeNameById)}</td>
              <td className="px-3 py-2 font-medium">{ruleLabel(rule)}</td>
              <td className="px-3 py-2 text-muted-foreground">{rule.note ?? EMPTY_PLACEHOLDER}</td>
              <td className="px-3 py-2 text-muted-foreground">{validityLabel(rule)}</td>
              <td className="px-3 py-2 text-right">
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label="Delete rule"
                  onClick={() => onDelete(rule.id)}
                >
                  <Trash2 className="h-4 w-4 text-critical" />
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

interface AddRuleFormProps {
  rulesUrl: string
  clientFridges: Fridge[]
  tagOptions: string[]
  onAdded: () => void
}

function AddRuleForm({ rulesUrl, clientFridges, tagOptions, onAdded }: AddRuleFormProps) {
  const [scope, setScope] = React.useState(ALL_FRIDGES_VALUE)
  const [ruleType, setRuleType] = React.useState<ClientRuleType>('exclude_tag')
  const [tag, setTag] = React.useState('')
  const [note, setNote] = React.useState('')
  const [validFrom, setValidFrom] = React.useState('')
  const [validTo, setValidTo] = React.useState('')

  const addMutation = useMutation({
    mutationFn: () =>
      api.post<ClientRule>(rulesUrl, {
        fridge_id: scope === ALL_FRIDGES_VALUE ? null : Number(scope),
        rule_type: ruleType,
        tag: ruleType === 'exclude_tag' ? tag : null,
        note: note.trim() || null,
        valid_from: validFrom || null,
        valid_to: validTo || null,
      }),
    onSuccess: () => {
      toast.success('Rule added')
      setTag('')
      setNote('')
      onAdded()
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Failed to add rule')
    },
  })

  const fieldErrors = fieldErrorsFromApiError(addMutation.error)
  const hasRuleContent = ruleType === 'exclude_tag' ? tag !== '' : note.trim() !== ''

  return (
    <div className="rounded-lg border border-border p-4">
      <h4 className="mb-3 text-sm font-semibold">Add rule</h4>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Field label="Applies to" error={fieldErrors.fridge_id}>
          <Select value={scope} onValueChange={setScope}>
            <SelectTrigger aria-label="Applies to">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_FRIDGES_VALUE}>All fridges of the client</SelectItem>
              {clientFridges.map((fridge) => (
                <SelectItem key={fridge.id} value={String(fridge.id)}>
                  {formatFridgeName(fridge)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field label="Rule type" error={fieldErrors.rule_type}>
          <Select value={ruleType} onValueChange={(value) => setRuleType(value as ClientRuleType)}>
            <SelectTrigger aria-label="Rule type">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {RULE_TYPES.map((option) => (
                <SelectItem key={option} value={option}>
                  {RULE_TYPE_LABELS[option]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        {ruleType === 'exclude_tag' ? (
          <Field label="Product tag" required error={fieldErrors.tag}>
            <Select value={tag} onValueChange={setTag}>
              <SelectTrigger aria-label="Product tag">
                <SelectValue placeholder="Choose a tag" />
              </SelectTrigger>
              <SelectContent>
                {tagOptions.map((option) => (
                  <SelectItem key={option} value={option}>
                    {productTagLabel(option)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
        ) : null}
        <Field label="Valid from" error={fieldErrors.valid_from}>
          <Input type="date" value={validFrom} onChange={(event) => setValidFrom(event.target.value)} />
        </Field>
        <Field label="Valid to" error={fieldErrors.valid_to}>
          <Input type="date" value={validTo} onChange={(event) => setValidTo(event.target.value)} />
        </Field>
      </div>
      <Field
        label="Note"
        className="mt-3"
        required={ruleType === 'note'}
        error={fieldErrors.note}
        hint="E.g. deliver before 8:00, ask security for the badge."
      >
        <Textarea value={note} onChange={(event) => setNote(event.target.value)} />
      </Field>
      <div className="mt-3 flex justify-end">
        <Button
          size="sm"
          onClick={() => addMutation.mutate()}
          disabled={addMutation.isPending || !hasRuleContent}
        >
          {addMutation.isPending ? 'Adding…' : 'Add rule'}
        </Button>
      </div>
    </div>
  )
}

function ruleScopeLabel(rule: ClientRule, fridgeNameById: Map<number, string>): string {
  if (rule.fridge_id === null) return 'All fridges'
  return fridgeNameById.get(rule.fridge_id) ?? `Fridge #${rule.fridge_id}`
}

function ruleLabel(rule: ClientRule): string {
  if (rule.rule_type === 'note' || rule.tag === null) return RULE_TYPE_LABELS.note
  return `Exclude tag: ${productTagLabel(rule.tag)}`
}

function validityLabel(rule: ClientRule): string {
  if (rule.valid_from === null && rule.valid_to === null) return 'Always'
  const from = rule.valid_from === null ? 'start' : formatDate(rule.valid_from)
  const to = rule.valid_to === null ? 'open' : formatDate(rule.valid_to)
  return `${from} to ${to}`
}
