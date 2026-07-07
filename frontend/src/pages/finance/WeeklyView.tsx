import * as React from 'react'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { Save } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { toast } from '@/components/ui/sonner'
import { ErrorState } from '@/components/shared/ErrorState'
import { LoadingSkeleton } from '@/components/shared/LoadingSkeleton'
import { api, ApiError } from '@/lib/api'
import { formatEuro } from '@/lib/format'
import type { WeeklyFinancialInputs, WeeklyPnl } from '@/pages/finance/types'
import { KpiTile, SectionCard } from '@/pages/finance/components'
import { TrendChart, type TrendPoint } from '@/pages/finance/charts/TrendChart'
import {
  formatIsoWeekRange,
  isoWeeksInYear,
  recentIsoWeeks,
  dateToIsoWeek,
} from '@/pages/finance/isoWeek'
import { formatCount, formatPercent, safeRatio, toNumber } from '@/pages/finance/utils'

const TREND_WEEKS = 9
const YEAR_OPTIONS = [2024, 2025, 2026, 2027, 2028, 2029, 2030]

/** Blank editable form state. */
interface FormState {
  catering_turnover: string
  catering_food_cost: string
  tgtg_turnover: string
  logistics_cost: string
  drops_count: string
  unsold_items: string
  num_fridges: string
  remarks: string
}

function weeklyKey(year: number, week: number) {
  return ['finance', 'weekly', year, week] as const
}

function fetchWeekly(year: number, week: number, signal?: AbortSignal) {
  return api.get<WeeklyPnl>(`/api/v1/finance/weekly/${year}/${week}`, { signal })
}

function inputsToForm(pnl: WeeklyPnl): FormState {
  return {
    catering_turnover: pnl.inputs.catering_turnover,
    catering_food_cost: pnl.inputs.catering_food_cost,
    tgtg_turnover: pnl.inputs.tgtg_turnover,
    logistics_cost: pnl.inputs.logistics_cost,
    drops_count: String(pnl.inputs.drops_count),
    unsold_items: String(pnl.inputs.unsold_items),
    num_fridges: pnl.inputs.fridge_count != null ? String(pnl.inputs.fridge_count) : '',
    remarks: pnl.inputs.remarks ?? '',
  }
}

export function WeeklyView() {
  const queryClient = useQueryClient()
  const current = React.useMemo(() => dateToIsoWeek(new Date()), [])
  const [year, setYear] = React.useState(current.year)
  const [week, setWeek] = React.useState(current.week)

  const weekOptions = React.useMemo(
    () => Array.from({ length: isoWeeksInYear(year) }, (_, index) => index + 1),
    [year],
  )

  const weeklyQuery = useQuery({
    queryKey: weeklyKey(year, week),
    queryFn: ({ signal }) => fetchWeekly(year, week, signal),
  })

  // 9 consecutive ISO weeks ending at the selected week, oldest first.
  const trendWeeks = React.useMemo(
    () => recentIsoWeeks(year, week, TREND_WEEKS),
    [year, week],
  )
  const trendQueries = useQueries({
    queries: trendWeeks.map((iso) => ({
      queryKey: weeklyKey(iso.year, iso.week),
      queryFn: ({ signal }: { signal?: AbortSignal }) => fetchWeekly(iso.year, iso.week, signal),
      staleTime: 60_000,
    })),
  })

  const trendData: TrendPoint[] = trendWeeks.map((iso, index) => {
    const data = trendQueries[index]?.data
    const turnover = toNumber(data?.turnover_ex_vat)
    return {
      label: `W${iso.week}`,
      turnover,
      marginPct: turnover ? safeRatio(toNumber(data?.net_margin), turnover) : null,
    }
  })
  const trendLoading = trendQueries.some((query) => query.isLoading)

  // Editable manual inputs — synced whenever a different week's data arrives.
  const [form, setForm] = React.useState<FormState | null>(null)
  const loadedKey = weeklyQuery.data ? `${weeklyQuery.data.year}-${weeklyQuery.data.iso_week}` : null
  React.useEffect(() => {
    if (weeklyQuery.data) setForm(inputsToForm(weeklyQuery.data))
  }, [loadedKey]) // eslint-disable-line react-hooks/exhaustive-deps

  const setField = (field: keyof FormState, value: string) =>
    setForm((prev) => (prev ? { ...prev, [field]: value } : prev))

  const saveMutation = useMutation({
    mutationFn: (payload: WeeklyFinancialInputs) =>
      api.put<WeeklyPnl>(`/api/v1/finance/weekly/${year}/${week}`, payload),
    onSuccess: (updated) => {
      queryClient.setQueryData(weeklyKey(year, week), updated)
      queryClient.invalidateQueries({ queryKey: ['finance', 'weekly'] })
      toast.success(`Saved week ${updated.year}-W${updated.iso_week}`)
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Failed to save week')
    },
  })

  function handleSave() {
    if (!form) return
    saveMutation.mutate({
      catering_turnover: form.catering_turnover || '0',
      catering_food_cost: form.catering_food_cost || '0',
      tgtg_turnover: form.tgtg_turnover || '0',
      logistics_cost: form.logistics_cost || '0',
      drops_count: Number(form.drops_count) || 0,
      unsold_items: Number(form.unsold_items) || 0,
      fridge_count: form.num_fridges.trim() === '' ? null : Number(form.num_fridges) || 0,
      remarks: form.remarks.trim() || null,
    })
  }

  const pnl = weeklyQuery.data

  return (
    <div className="space-y-6">
      {/* Picker */}
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
          Year
          <Select value={String(year)} onValueChange={(value) => setYear(Number(value))}>
            <SelectTrigger className="w-28">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {YEAR_OPTIONS.map((option) => (
                <SelectItem key={option} value={String(option)}>
                  {option}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
          Week
          <Select value={String(week)} onValueChange={(value) => setWeek(Number(value))}>
            <SelectTrigger className="w-56">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="max-h-72">
              {weekOptions.map((option) => (
                <SelectItem key={option} value={String(option)}>
                  {formatIsoWeekRange(year, option)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
        {pnl ? (
          <span className="pb-2 text-xs text-muted-foreground">
            Week start <span className="font-medium text-foreground">{pnl.week_start}</span>
          </span>
        ) : null}
      </div>

      {weeklyQuery.isError ? (
        <ErrorState error={weeklyQuery.error} onRetry={() => weeklyQuery.refetch()} />
      ) : weeklyQuery.isLoading || !pnl ? (
        <LoadingSkeleton rows={4} columns={3} />
      ) : (
        <>
          {/* Computed KPI tiles */}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <KpiTile
              hero
              label="Sales turnover (ex VAT)"
              value={formatEuro(pnl.turnover_ex_vat)}
              caption="(Sales + Credit − Refund) ÷ 1.06"
            />
            <KpiTile
              label="Fridge food cost"
              value={formatEuro(pnl.fridge_food_cost_added)}
              caption="ADDED / restock basis — not dispatched"
            />
            <KpiTile
              label="POS & software fee"
              value={formatEuro(pnl.pos_fee)}
              caption={`${formatPercent(toNumber(pnl.pos_fee_pct))} × VAT-inclusive gross`}
            />
            <KpiTile
              label="RFID & transaction fee"
              value={formatEuro(pnl.rfid_fee)}
              caption={`${formatEuro(pnl.rfid_fee_rate)} / item · ${formatCount(pnl.items_sold)} items`}
            />
            <KpiTile
              label="Net margin"
              value={formatEuro(pnl.net_margin)}
              tone={toNumber(pnl.net_margin) >= 0 ? 'good' : 'critical'}
              caption="(Turnover + Catering + TGTG) − (Food cost[ADDED] + Catering FC + Logistics) − POS − RFID"
            />
            <KpiTile
              label="Net margin %"
              value={formatPercent(safeRatio(toNumber(pnl.net_margin), toNumber(pnl.turnover_ex_vat)))}
              tone={toNumber(pnl.net_margin) >= 0 ? 'good' : 'critical'}
              caption="Net margin ÷ turnover ex VAT"
            />
          </div>

          {/* Trend chart */}
          <SectionCard
            title={`Sales turnover & net margin — last ${TREND_WEEKS} weeks`}
            description="Turnover ex VAT (blue, € left axis) and net margin % (green, right axis). Weeks with no recorded activity show no margin point. Rendered with d3."
          >
            {trendLoading ? (
              <LoadingSkeleton rows={3} columns={2} />
            ) : (
              <TrendChart data={trendData} />
            )}
            <div className="mt-3 flex flex-wrap gap-4 text-xs text-muted-foreground">
              <span className="inline-flex items-center gap-1.5">
                <span className="inline-block h-2 w-4 rounded-full bg-series-1" /> Sales turnover (€)
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span className="inline-block h-2 w-4 rounded-full bg-series-2" /> Net margin (%)
              </span>
            </div>
          </SectionCard>

          {/* Manual inputs form */}
          {form ? (
            <SectionCard
              title="Week entry — manual inputs"
              description="White fields are typed in; the KPI tiles above recalculate on the backend after saving."
              actions={
                <Button onClick={handleSave} disabled={saveMutation.isPending}>
                  <Save className="mr-1.5 h-4 w-4" />
                  {saveMutation.isPending ? 'Saving…' : `Save week ${week}`}
                </Button>
              }
            >
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                <FormField label="Business lunch CA (€)" hint="Catering turnover">
                  <Input
                    type="number"
                    inputMode="decimal"
                    value={form.catering_turnover}
                    onChange={(event) => setField('catering_turnover', event.target.value)}
                  />
                </FormField>
                <FormField label="Business lunch food cost (€)">
                  <Input
                    type="number"
                    inputMode="decimal"
                    value={form.catering_food_cost}
                    onChange={(event) => setField('catering_food_cost', event.target.value)}
                  />
                </FormField>
                <FormField label="TGTG CA (€)" hint="Too Good To Go">
                  <Input
                    type="number"
                    inputMode="decimal"
                    value={form.tgtg_turnover}
                    onChange={(event) => setField('tgtg_turnover', event.target.value)}
                  />
                </FormField>
                <FormField label="Logistics cost (€)">
                  <Input
                    type="number"
                    inputMode="decimal"
                    value={form.logistics_cost}
                    onChange={(event) => setField('logistics_cost', event.target.value)}
                  />
                </FormField>
                <FormField label="# of drops">
                  <Input
                    type="number"
                    value={form.drops_count}
                    onChange={(event) => setField('drops_count', event.target.value)}
                  />
                </FormField>
                <FormField label="Unsold items">
                  <Input
                    type="number"
                    value={form.unsold_items}
                    onChange={(event) => setField('unsold_items', event.target.value)}
                  />
                </FormField>
                <FormField label="# of Fridges" hint="Manual weekly input — persisted with the week">

                  <Input
                    type="number"
                    value={form.num_fridges}
                    onChange={(event) => setField('num_fridges', event.target.value)}
                  />
                </FormField>
                <FormField label="Remarks" className="sm:col-span-2">
                  <Input
                    value={form.remarks}
                    onChange={(event) => setField('remarks', event.target.value)}
                    placeholder="e.g. Friday refill @Neuhaus, panne électricité…"
                  />
                </FormField>
              </div>
              <div className="mt-4 rounded-lg border border-warning/40 bg-warning/10 p-3 text-xs text-foreground">
                <b>Cost basis — weekly view:</b> fridge food cost uses the <b>ADDED (restock)</b>{' '}
                value. The Monthly by-fridge P&amp;L uses <b>DISPATCHED</b> value — a deliberate
                legacy inconsistency, surfaced so the two are never mixed.
              </div>
            </SectionCard>
          ) : null}
        </>
      )}
    </div>
  )
}

function FormField({
  label,
  hint,
  className,
  children,
}: {
  label: string
  hint?: string
  className?: string
  children: React.ReactNode
}) {
  return (
    <div className={className}>
      <label className="mb-1 block text-xs font-semibold text-muted-foreground">{label}</label>
      {children}
      {hint ? <div className="mt-1 text-[11px] text-muted-foreground">{hint}</div> : null}
    </div>
  )
}
