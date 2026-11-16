import * as React from 'react'
import { useMutation, useQuery, type UseQueryResult } from '@tanstack/react-query'
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
import { InfoHint, type Hint } from '@/components/shared/InfoHint'
import { LoadingSkeleton } from '@/components/shared/LoadingSkeleton'
import { EmptyState } from '@/components/shared/EmptyState'
import { MoneyCell } from '@/components/shared/MoneyCell'
import { toast } from '@/components/ui/toast'
import { formatFridgeName } from '@/lib/format'
import { api, downloadFile, type Page } from '@/lib/api'
import { REFERENCE_FRIDGES_KEY, REFERENCE_FRIDGES_LIMIT } from '@/lib/query-keys'
import type { AllFridgesReport, Fridge, FridgeReport } from '@/pages/finance/types'
import { SectionCard } from '@/pages/finance/components'
import { AllFridgesReportTable } from '@/pages/finance/AllFridgesReportTable'
import { NOT_AVAILABLE, ReportKpiTiles } from '@/pages/finance/ReportKpiTiles'
import { formatCount } from '@/pages/finance/utils'

/** Select value for the all-fridges report (fridge ids are numeric, so it cannot clash). */
const ALL_FRIDGES = 'all'
const FRIDGE_CHOICE_HINT: Hint = {
  text:
    'Pick one fridge for its product detail, or All fridges for one row per fridge plus totals ' +
    '(also as Excel).',
  example: 'All fridges over last month compares the margin of every fridge side by side.',
}
const FRIDGE_REPORT_PATH = '/api/v1/finance/fridge-report'
const ALL_FRIDGES_REPORT_PATH = '/api/v1/finance/all-fridges-report'

/** First/last day of the previous calendar month, ISO date strings. */
function defaultRange(): { from: string; to: string } {
  const now = new Date()
  const firstOfThis = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1))
  const lastPrev = new Date(firstOfThis.getTime() - 86_400_000)
  const firstPrev = new Date(Date.UTC(lastPrev.getUTCFullYear(), lastPrev.getUTCMonth(), 1))
  const iso = (date: Date) => date.toISOString().slice(0, 10)
  return { from: iso(firstPrev), to: iso(lastPrev) }
}

function exportRequest(fridgeId: string, from: string, to: string) {
  if (fridgeId === ALL_FRIDGES) {
    return {
      path: `${ALL_FRIDGES_REPORT_PATH}/export.xlsx`,
      fallbackFilename: `all-fridges-report_${from}_${to}.xlsx`,
      params: { from, to },
    }
  }
  return {
    path: `${FRIDGE_REPORT_PATH}/export.xlsx`,
    fallbackFilename: `fridge-report_${fridgeId}_${from}_${to}.xlsx`,
    params: { fridge_id: Number(fridgeId), from, to },
  }
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

  const isAllFridges = fridgeId === ALL_FRIDGES
  const hasRange = Boolean(from) && Boolean(to)

  const reportQuery = useQuery({
    queryKey: ['finance', 'fridge-report', fridgeId, from, to],
    queryFn: ({ signal }) =>
      api.get<FridgeReport>(FRIDGE_REPORT_PATH, {
        params: { fridge_id: Number(fridgeId), from, to },
        signal,
      }),
    enabled: Boolean(fridgeId) && !isAllFridges && hasRange,
  })

  const allFridgesQuery = useQuery({
    queryKey: ['finance', 'all-fridges-report', from, to],
    queryFn: ({ signal }) =>
      api.get<AllFridgesReport>(ALL_FRIDGES_REPORT_PATH, { params: { from, to }, signal }),
    enabled: isAllFridges && hasRange,
  })

  const exportMutation = useMutation({
    mutationFn: () => {
      const request = exportRequest(fridgeId, from, to)
      return downloadFile(request.path, request.fallbackFilename, request.params)
    },
    onSuccess: () => toast.success('Fridge report exported'),
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : 'Export failed'),
  })

  const fridges = fridgesQuery.data?.items ?? []
  const activeQuery = isAllFridges ? allFridgesQuery : reportQuery
  const canExport = hasRange && Boolean(activeQuery.data)

  return (
    <SectionCard
      title="Fridge report"
      description="Added quantity, food cost, revenue and margin for one fridge, or all fridges, over a date range."
      actions={
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
            <span className="inline-flex items-center gap-1">
              Fridge <InfoHint {...FRIDGE_CHOICE_HINT} />
            </span>
            <Select value={fridgeId} onValueChange={setFridgeId}>
              <SelectTrigger className="w-56">
                <SelectValue placeholder={fridgesQuery.isLoading ? 'Loading…' : 'Select a fridge…'} />
              </SelectTrigger>
              <SelectContent className="max-h-72">
                <SelectItem value={ALL_FRIDGES}>All fridges</SelectItem>
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
      <ReportBody
        fridgeId={fridgeId}
        reportQuery={reportQuery}
        allFridgesQuery={allFridgesQuery}
      />
    </SectionCard>
  )
}

function ReportBody({
  fridgeId,
  reportQuery,
  allFridgesQuery,
}: {
  fridgeId: string
  reportQuery: UseQueryResult<FridgeReport>
  allFridgesQuery: UseQueryResult<AllFridgesReport>
}) {
  if (!fridgeId) {
    return (
      <EmptyState
        title="Select a fridge"
        description="Pick a fridge (or All fridges) and a date range to run the report."
      />
    )
  }
  const activeQuery = fridgeId === ALL_FRIDGES ? allFridgesQuery : reportQuery
  if (activeQuery.isError) {
    return <ErrorState error={activeQuery.error} onRetry={() => activeQuery.refetch()} />
  }
  if (fridgeId === ALL_FRIDGES) {
    if (!allFridgesQuery.data) return <LoadingSkeleton rows={6} columns={8} />
    return (
      <div className="space-y-5">
        <ReportKpiTiles figures={allFridgesQuery.data.totals} />
        <AllFridgesReportTable report={allFridgesQuery.data} />
      </div>
    )
  }
  if (!reportQuery.data) return <LoadingSkeleton rows={3} columns={5} />
  return <SingleFridgeReport report={reportQuery.data} />
}

function SingleFridgeReport({ report }: { report: FridgeReport }) {
  return (
    <div className="space-y-5">
      <ReportKpiTiles figures={report} />
      {report.rows.length === 0 ? (
        <EmptyState
          title="No product rows"
          description="No restock activity for this fridge in the selected range."
        />
      ) : (
        <div className="overflow-x-auto overflow-y-hidden rounded-xl border border-border bg-card">
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
  )
}
