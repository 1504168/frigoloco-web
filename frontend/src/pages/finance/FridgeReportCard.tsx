import * as React from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Download } from 'lucide-react'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { ErrorState } from '@/components/shared/ErrorState'
import { LoadingSkeleton } from '@/components/shared/LoadingSkeleton'
import { EmptyState } from '@/components/shared/EmptyState'
import { MoneyCell } from '@/components/shared/MoneyCell'
import { toast } from '@/components/ui/sonner'
import { formatEuro, formatFraction, formatFridgeName } from '@/lib/format'
import { api, type Page } from '@/lib/api'
import { REFERENCE_FRIDGES_KEY, REFERENCE_FRIDGES_LIMIT } from '@/lib/query-keys'
import type { Fridge, FridgeReport } from '@/pages/finance/types'
import { KpiTile, SectionCard, type KpiTileProps } from '@/pages/finance/components'
import { downloadFileFromApi, formatCount, toNumber } from '@/pages/finance/utils'

/** Shown wherever the backend sends null, matching the Excel export's own wording. */
const NOT_AVAILABLE = 'n/a'

/** First/last day of the previous calendar month, ISO date strings. */
function defaultRange(): { from: string; to: string } {
  const now = new Date()
  const firstOfThis = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1))
  const lastPrev = new Date(firstOfThis.getTime() - 86_400_000)
  const firstPrev = new Date(Date.UTC(lastPrev.getUTCFullYear(), lastPrev.getUTCMonth(), 1))
  const iso = (date: Date) => date.toISOString().slice(0, 10)
  return { from: iso(firstPrev), to: iso(lastPrev) }
}

/**
 * Format the backend margin fraction (e.g. "0.6000") for display. The backend
 * sends null when there is no ex-VAT revenue to divide by: that is an undefined
 * margin, not a 0% one, so it must not be coerced to a number.
 */
function formatMarginPct(value: string | null): string {
  if (value === null) return NOT_AVAILABLE
  return formatFraction(value, 1)
}

/** An undefined margin is neutral: only a real percentage earns good/critical. */
function marginPctTone(value: string | null): KpiTileProps['tone'] {
  if (value === null) return 'default'
  return toNumber(value) >= 0 ? 'good' : 'critical'
}

export function FridgeReportCard() {
  const initial = React.useMemo(defaultRange, [])
  const [fridgeId, setFridgeId] = React.useState<string>('')
  const [from, setFrom] = React.useState(initial.from)
  const [to, setTo] = React.useState(initial.to)

  const fridgesQuery = useQuery({
    queryKey: REFERENCE_FRIDGES_KEY,
    queryFn: ({ signal }) =>
      api.get<Page<Fridge>>('/api/v1/fridges', {
        params: { limit: REFERENCE_FRIDGES_LIMIT },
        signal,
      }),
    staleTime: 5 * 60_000,
  })

  const reportQuery = useQuery({
    queryKey: ['finance', 'fridge-report', fridgeId, from, to],
    queryFn: ({ signal }) =>
      api.get<FridgeReport>('/api/v1/finance/fridge-report', {
        params: { fridge_id: Number(fridgeId), from, to },
        signal,
      }),
    enabled: Boolean(fridgeId) && Boolean(from) && Boolean(to),
  })

  const exportMutation = useMutation({
    mutationFn: () =>
      downloadFileFromApi(
        `/api/v1/finance/fridge-report/export.xlsx?fridge_id=${Number(fridgeId)}&from=${from}&to=${to}`,
        `fridge-report_${fridgeId}_${from}_${to}.xlsx`,
      ),
    onSuccess: () => toast.success('Fridge report exported'),
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : 'Export failed'),
  })

  const fridges = fridgesQuery.data?.items ?? []
  const report = reportQuery.data
  const canExport = Boolean(fridgeId) && Boolean(from) && Boolean(to) && Boolean(report)

  return (
    <SectionCard
      title="Fridge report"
      description="Added quantity, food cost, revenue and margin for a single fridge over a date range."
      actions={
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
            Fridge
            <Select value={fridgeId} onValueChange={setFridgeId}>
              <SelectTrigger className="w-56">
                <SelectValue placeholder={fridgesQuery.isLoading ? 'Loading…' : 'Select a fridge…'} />
              </SelectTrigger>
              <SelectContent className="max-h-72">
                {fridges.map((fridge) => (
                  <SelectItem key={fridge.id} value={String(fridge.id)}>
                    {formatFridgeName(fridge)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
          <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
            From
            <Input type="date" value={from} onChange={(event) => setFrom(event.target.value)} className="w-40" />
          </label>
          <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
            To
            <Input type="date" value={to} onChange={(event) => setTo(event.target.value)} className="w-40" />
          </label>
          <Button
            variant="outline"
            disabled={!canExport || exportMutation.isPending}
            onClick={() => exportMutation.mutate()}
          >
            <Download className="h-4 w-4" />
            {exportMutation.isPending ? 'Exporting…' : 'Export to Excel'}
          </Button>
        </div>
      }
    >
      {!fridgeId ? (
        <EmptyState title="Select a fridge" description="Pick a fridge and date range to run the report." />
      ) : reportQuery.isError ? (
        <ErrorState error={reportQuery.error} onRetry={() => reportQuery.refetch()} />
      ) : reportQuery.isLoading || !report ? (
        <LoadingSkeleton rows={3} columns={5} />
      ) : (
        <div className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <KpiTile label="Added quantity" value={formatCount(report.added_qty)} caption="Items restocked (ADDED)" />
            <KpiTile label="Food cost" value={formatEuro(report.food_cost)} caption="ADDED / restock basis" />
            <KpiTile label="Revenue" value={formatEuro(report.revenue)} />
            <KpiTile
              label="Food margin"
              value={formatEuro(report.margin)}
              tone={toNumber(report.margin) >= 0 ? 'good' : 'critical'}
              caption="Revenue − food cost"
            />
            <KpiTile
              label="Margin %"
              value={formatMarginPct(report.margin_pct)}
              tone={marginPctTone(report.margin_pct)}
              caption="Food margin / revenue"
            />
          </div>

          {report.rows.length === 0 ? (
            <EmptyState
              title="No product rows"
              description="No restock activity for this fridge in the selected range."
            />
          ) : (
            <div className="overflow-x-auto rounded-xl border border-border bg-card">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Code</TableHead>
                    <TableHead>Product</TableHead>
                    <TableHead>Category</TableHead>
                    <TableHead className="text-right">Added qty</TableHead>
                    <TableHead className="text-right">Unit buy</TableHead>
                    <TableHead className="text-right">Unit sell</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {report.rows.map((row) => (
                    <TableRow key={row.product_id}>
                      <TableCell className="font-mono text-xs">{row.code}</TableCell>
                      <TableCell className="font-medium">{row.name}</TableCell>
                      <TableCell className="text-muted-foreground">
                        {row.category ?? NOT_AVAILABLE}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{formatCount(row.added_qty)}</TableCell>
                      <TableCell className="text-right">
                        <MoneyCell value={row.unit_buying_price} />
                      </TableCell>
                      <TableCell className="text-right">
                        <MoneyCell value={row.unit_selling_price} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </div>
      )}
    </SectionCard>
  )
}
