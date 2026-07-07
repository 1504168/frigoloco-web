import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RotateCcw, Save } from 'lucide-react'
import { PageHeader } from '@/components/shared/PageHeader'
import { ErrorState } from '@/components/shared/ErrorState'
import { LoadingSkeleton } from '@/components/shared/LoadingSkeleton'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { toast } from '@/components/ui/sonner'
import { api, ApiError } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import type { Setting } from '@/pages/finance/types'
import { SectionCard } from '@/pages/finance/components'

/** A settings group, matching the mockup's fees / thresholds / weights layout. */
interface SettingGroup {
  id: string
  title: string
  description: string
  match: (key: string) => boolean
}

const GROUPS: SettingGroup[] = [
  {
    id: 'fees',
    title: 'Fees',
    description: 'POS / software and RFID fee rates applied to weekly & monthly P&L.',
    match: (key) => /fee|pct|rate/i.test(key),
  },
  {
    id: 'thresholds',
    title: 'Thresholds',
    description: 'Operational thresholds such as expiry-alert windows.',
    match: (key) => /day|threshold|alert|limit|expiry/i.test(key),
  },
  {
    id: 'weights',
    title: 'Weights & margins',
    description: 'Per-category scoring weights and forecast margin targets.',
    match: (key) => /weight|margin|score/i.test(key),
  },
]

const OTHER_GROUP: Omit<SettingGroup, 'match'> = {
  id: 'other',
  title: 'Other',
  description: 'Uncategorised settings.',
}

function groupFor(key: string): string {
  return GROUPS.find((group) => group.match(key))?.id ?? OTHER_GROUP.id
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function SettingsPage() {
  const settingsQuery = useQuery({
    queryKey: ['settings'],
    queryFn: ({ signal }) => api.get<Setting[]>('/api/v1/settings', { signal }),
  })

  if (settingsQuery.isError) {
    return (
      <div className="space-y-6">
        <PageHeader breadcrumb="System / Settings" title="Settings" />
        <ErrorState error={settingsQuery.error} onRetry={() => settingsQuery.refetch()} />
      </div>
    )
  }

  const settings = settingsQuery.data ?? []
  const grouped = [...GROUPS, OTHER_GROUP].map((group) => ({
    group,
    items: settings.filter((setting) => groupFor(setting.key) === group.id),
  }))

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumb="System / Settings"
        title="Settings"
        description="Business settings that drive finance formulas and forecasting. Each value is typed to its stored shape."
      />

      {settingsQuery.isLoading ? (
        <LoadingSkeleton rows={6} columns={2} />
      ) : (
        grouped
          .filter((section) => section.items.length > 0)
          .map((section) => (
            <SectionCard
              key={section.group.id}
              title={section.group.title}
              description={section.group.description}
            >
              <div className="divide-y divide-border">
                {section.items.map((setting) => (
                  <SettingRow key={setting.key} setting={setting} />
                ))}
              </div>
            </SectionCard>
          ))
      )}
    </div>
  )
}

function SettingRow({ setting }: { setting: Setting }) {
  const queryClient = useQueryClient()
  const [draft, setDraft] = React.useState<unknown>(setting.value)

  // Re-sync when the upstream value changes (e.g. after a save elsewhere).
  const originalJson = JSON.stringify(setting.value)
  React.useEffect(() => {
    setDraft(setting.value)
  }, [originalJson]) // eslint-disable-line react-hooks/exhaustive-deps

  const dirty = JSON.stringify(draft) !== originalJson

  const mutation = useMutation({
    mutationFn: (value: unknown) =>
      api.put<Setting>(`/api/v1/settings/${encodeURIComponent(setting.key)}`, {
        value,
        description: setting.description,
      }),
    onSuccess: (updated) => {
      toast.success(`Saved "${updated.key}"`)
      queryClient.invalidateQueries({ queryKey: ['settings'] })
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Failed to save setting')
    },
  })

  return (
    <div className="flex flex-col gap-3 py-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0 sm:max-w-md">
        <div className="font-mono text-sm font-semibold text-foreground">{setting.key}</div>
        {setting.description ? (
          <p className="mt-0.5 text-xs text-muted-foreground">{setting.description}</p>
        ) : null}
        <p className="mt-1 text-[11px] text-muted-foreground">
          Updated {formatDateTime(setting.updated_at)}
        </p>
      </div>
      <div className="flex flex-col items-stretch gap-2 sm:min-w-[280px]">
        <SettingValueEditor value={draft} onChange={setDraft} />
        <div className="flex items-center justify-end gap-2">
          {dirty ? (
            <Button variant="ghost" size="sm" onClick={() => setDraft(setting.value)}>
              <RotateCcw className="mr-1 h-3.5 w-3.5" /> Reset
            </Button>
          ) : null}
          <Button
            size="sm"
            disabled={!dirty || mutation.isPending}
            onClick={() => mutation.mutate(draft)}
          >
            <Save className="mr-1 h-3.5 w-3.5" />
            {mutation.isPending ? 'Saving…' : 'Save'}
          </Button>
        </div>
      </div>
    </div>
  )
}

/** Dispatches to a typed editor based on the runtime shape of the value. */
function SettingValueEditor({
  value,
  onChange,
}: {
  value: unknown
  onChange: (next: unknown) => void
}) {
  if (typeof value === 'boolean') {
    return (
      <div className="flex items-center justify-end gap-2">
        <span className="text-xs text-muted-foreground">{value ? 'Enabled' : 'Disabled'}</span>
        <Switch checked={value} onCheckedChange={onChange} />
      </div>
    )
  }

  if (typeof value === 'number') {
    return (
      <Input
        type="number"
        inputMode="decimal"
        value={String(value)}
        onChange={(event) => onChange(event.target.value === '' ? 0 : Number(event.target.value))}
        className="text-right tabular-nums"
      />
    )
  }

  if (typeof value === 'string') {
    return <Input value={value} onChange={(event) => onChange(event.target.value)} />
  }

  if (isPlainRecord(value)) {
    return <RecordEditor record={value} onChange={onChange} />
  }

  // Arrays / anything complex: edit as raw JSON.
  return <JsonEditor value={value} onChange={onChange} />
}

/** Editor for an object whose values are primitives (numbers or strings). */
function RecordEditor({
  record,
  onChange,
}: {
  record: Record<string, unknown>
  onChange: (next: Record<string, unknown>) => void
}) {
  const entries = Object.entries(record)
  return (
    <div className="grid gap-2">
      {entries.map(([key, fieldValue]) => (
        <label key={key} className="grid grid-cols-[1fr_auto] items-center gap-2 text-xs">
          <span className="truncate text-muted-foreground">{key}</span>
          {typeof fieldValue === 'number' || fieldValue === null ? (
            <Input
              type="number"
              inputMode="decimal"
              value={fieldValue === null ? '' : String(fieldValue)}
              onChange={(event) =>
                onChange({
                  ...record,
                  [key]: event.target.value === '' ? 0 : Number(event.target.value),
                })
              }
              className="h-8 w-28 text-right tabular-nums"
            />
          ) : (
            <Input
              value={String(fieldValue)}
              onChange={(event) => onChange({ ...record, [key]: event.target.value })}
              className="h-8 w-28"
            />
          )}
        </label>
      ))}
    </div>
  )
}

/** Fallback raw-JSON editor for arrays / deeply-nested values. */
function JsonEditor({ value, onChange }: { value: unknown; onChange: (next: unknown) => void }) {
  const [text, setText] = React.useState(() => JSON.stringify(value, null, 2))
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    setText(JSON.stringify(value, null, 2))
  }, [value])

  return (
    <div>
      <textarea
        value={text}
        spellCheck={false}
        onChange={(event) => {
          const next = event.target.value
          setText(next)
          try {
            onChange(JSON.parse(next))
            setError(null)
          } catch {
            setError('Invalid JSON')
          }
        }}
        className="h-28 w-full rounded-md border border-input bg-background p-2 font-mono text-xs"
      />
      {error ? <div className="mt-1 text-[11px] text-critical">{error}</div> : null}
    </div>
  )
}

export default SettingsPage
