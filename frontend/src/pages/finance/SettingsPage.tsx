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
import { useCategories } from '@/pages/ops/lib/reference'

/** A settings group, matching the mockup's fees / thresholds / weights layout. */
interface SettingGroup {
  id: string
  title: string
  description: string
  match: (key: string) => boolean
}

/**
 * How a stored value is presented. `percent` values are stored as fractions
 * (0.09) but shown and entered as whole percentages (9); everything else is
 * shown exactly as stored.
 */
type SettingUnit = 'percent' | 'plain'

/**
 * Human-facing presentation for each known setting key. The raw key is never
 * shown in the UI - it stays an API/database detail.
 */
interface SettingMeta {
  label: string
  help: string
  group: string
  unit: SettingUnit
  /** Suffix rendered beside the input, e.g. "%" or "days". */
  suffix?: string
  /** Extra clarification rendered under the input. */
  hint?: string
  /** Labels for the fields of an object-valued setting, in display order. */
  fieldLabels?: Record<string, string>
  /** Object keys are category ids: label them with category names, in category order. */
  keyedByCategoryId?: boolean
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
    description: 'Operational limits and display thresholds, such as the expiry-alert window.',
    match: (key) => /day|threshold|alert|limit|expiry|column/i.test(key),
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

const SETTING_META: Record<string, SettingMeta> = {
  pos_fee_pct: {
    label: 'POS & software fee',
    help: 'Share of gross sales deducted as POS and software costs in the weekly and monthly P&L.',
    group: 'fees',
    unit: 'percent',
    suffix: '%',
  },
  rfid_fee_eur: {
    label: 'RFID fee per item sold',
    help: 'Charged once for every item sold, in cents.',
    group: 'fees',
    unit: 'plain',
    suffix: 'cents',
    hint: '10 cents = EUR 0.10 per item sold.',
  },
  expiry_alert_days: {
    label: 'Expiry alert window',
    help: 'Raise an expiry alert when a product is this many days away from its expiry date.',
    group: 'thresholds',
    unit: 'plain',
    suffix: 'days',
  },
  menu_category_columns: {
    label: 'Menu grid columns per category',
    help: 'Minimum number of product slots shown for each category in the Menu and Dispatch grids.',
    group: 'thresholds',
    unit: 'plain',
    suffix: 'columns',
  },
  scoring_weights: {
    label: 'Product score weights',
    help: 'How much each factor counts towards a product score. The three weights should add up to 100%.',
    group: 'weights',
    unit: 'percent',
    suffix: '%',
    fieldLabels: {
      pct_sold: '% Sold',
      margin: 'Margin',
      review: 'Review',
    },
  },
  forecast_margins: {
    label: 'Forecast margin per category',
    help: 'Extra buffer added on top of the forecast for each category. 0% means forecast the plain expected quantity.',
    group: 'weights',
    unit: 'percent',
    suffix: '%',
    keyedByCategoryId: true,
  },
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
  const meta = SETTING_META[setting.key]
  const label = meta?.label ?? humanizeKey(setting.key)

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
    onSuccess: () => {
      toast.success(`Saved "${label}"`)
      queryClient.invalidateQueries({ queryKey: ['settings'] })
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Failed to save setting')
    },
  })

  const help = meta?.help ?? setting.description

  return (
    <div className="flex flex-col gap-3 py-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0 sm:max-w-md">
        <div className="text-sm font-semibold text-foreground">{label}</div>
        {help ? <p className="mt-0.5 text-xs text-muted-foreground">{help}</p> : null}
        <p className="mt-1 text-[11px] text-muted-foreground">
          Updated {formatDateTime(setting.updated_at)}
        </p>
      </div>
      <div className="flex flex-col items-stretch gap-2 sm:min-w-[280px]">
        <SettingValueEditor value={draft} meta={meta} onChange={setDraft} />
        {meta?.hint ? (
          <p className="text-right text-[11px] text-muted-foreground">{meta.hint}</p>
        ) : null}
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
  meta,
  onChange,
}: {
  value: unknown
  meta?: SettingMeta
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
      <NumberField
        value={value}
        unit={meta?.unit ?? 'plain'}
        suffix={meta?.suffix}
        onChange={onChange}
      />
    )
  }

  if (typeof value === 'string') {
    return <Input value={value} onChange={(event) => onChange(event.target.value)} />
  }

  if (isPlainRecord(value)) {
    return <RecordEditor record={value} meta={meta} onChange={onChange} />
  }

  // Arrays / anything complex: edit as raw JSON.
  return <JsonEditor value={value} onChange={onChange} />
}

/** Editor for an object whose values are primitives (numbers or strings). */
function RecordEditor({
  record,
  meta,
  onChange,
}: {
  record: Record<string, unknown>
  meta?: SettingMeta
  onChange: (next: Record<string, unknown>) => void
}) {
  const unit = meta?.unit ?? 'plain'
  const categoriesQuery = useCategories()
  const categories = categoriesQuery.data?.ordered ?? []
  const categoryLabels = Object.fromEntries(
    categories.map((category) => [String(category.id), category.name]),
  )
  const categoryOrder = categories.map((category) => String(category.id))
  const fields = meta?.keyedByCategoryId
    ? recordFields(record, categoryLabels, categoryOrder)
    : recordFields(record, meta?.fieldLabels)
  return (
    <div className="grid gap-2">
      {fields.map((field) => (
        <label key={field.key} className="grid grid-cols-[1fr_auto] items-center gap-2 text-xs">
          <span className="truncate text-muted-foreground">{field.label}</span>
          {typeof field.value === 'number' || field.value === null ? (
            <NumberField
              value={field.value ?? 0}
              unit={unit}
              suffix={meta?.suffix}
              compact
              onChange={(next) => onChange({ ...record, [field.key]: next })}
            />
          ) : (
            <Input
              value={String(field.value)}
              onChange={(event) => onChange({ ...record, [field.key]: event.target.value })}
              className="h-8 w-28"
            />
          )}
        </label>
      ))}
    </div>
  )
}

/**
 * Numeric input that shows the display value (percent-scaled where the setting
 * is stored as a fraction) and writes back the stored value.
 */
function NumberField({
  value,
  unit,
  suffix,
  compact = false,
  onChange,
}: {
  value: number
  unit: SettingUnit
  suffix?: string
  compact?: boolean
  onChange: (next: number) => void
}) {
  return (
    <div className="flex items-center justify-end gap-1.5">
      <Input
        type="number"
        inputMode="decimal"
        value={String(toDisplayValue(value, unit))}
        onChange={(event) =>
          onChange(toStoredValue(event.target.value === '' ? 0 : Number(event.target.value), unit))
        }
        className={compact ? 'h-8 w-24 text-right tabular-nums' : 'text-right tabular-nums'}
      />
      {suffix ? (
        <span className="w-14 shrink-0 text-xs text-muted-foreground">{suffix}</span>
      ) : null}
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

function groupFor(key: string): string {
  const meta = SETTING_META[key]
  if (meta) return meta.group
  return GROUPS.find((group) => group.match(key))?.id ?? OTHER_GROUP.id
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** "some_setting_key" -> "Some setting key", for keys with no metadata entry. */
function humanizeKey(key: string): string {
  const words = key.replace(/[_-]+/g, ' ').trim()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

/**
 * Object fields with display labels, ordered by `fieldOrder` (default: the key
 * order of `fieldLabels`) when given, otherwise by the "N. " prefix the keys carry
 * (so "2. Warm Dishes" sorts before "10. Frozen Warm Dishes").
 */
function recordFields(
  record: Record<string, unknown>,
  fieldLabels?: Record<string, string>,
  fieldOrder: string[] | undefined = fieldLabels && Object.keys(fieldLabels),
): { key: string; label: string; value: unknown }[] {
  const fields = Object.entries(record).map(([key, value]) => ({
    key,
    label: fieldLabels?.[key] ?? stripOrderPrefix(key),
    value,
  }))

  if (fieldOrder) {
    return fields.sort((a, b) => rankIn(fieldOrder, a.key) - rankIn(fieldOrder, b.key))
  }
  return fields.sort((a, b) => orderPrefixOf(a.key) - orderPrefixOf(b.key))
}

function stripOrderPrefix(key: string): string {
  return key.replace(/^\s*\d+\.\s*/, '')
}

function orderPrefixOf(key: string): number {
  const match = /^\s*(\d+)\./.exec(key)
  return match ? Number(match[1]) : Number.MAX_SAFE_INTEGER
}

function rankIn(order: string[], key: string): number {
  const index = order.indexOf(key)
  return index === -1 ? order.length : index
}

/** Stored fraction -> displayed whole percentage (0.09 -> 9). */
function toDisplayValue(stored: number, unit: SettingUnit): number {
  return unit === 'percent' ? roundTo(stored * 100, 4) : stored
}

/** Entered whole percentage -> stored fraction (9 -> 0.09). */
function toStoredValue(displayed: number, unit: SettingUnit): number {
  return unit === 'percent' ? roundTo(displayed / 100, 6) : displayed
}

function roundTo(value: number, decimals: number): number {
  const factor = 10 ** decimals
  return Math.round(value * factor) / factor
}

export default SettingsPage
