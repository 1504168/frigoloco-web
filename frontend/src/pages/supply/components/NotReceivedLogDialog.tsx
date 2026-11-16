import * as React from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { api, type Page } from '@/lib/api'
import { formatDateTime12Hour } from '@/lib/format'
import type { PoDiscrepancy, PoDiscrepancyKind, Supplier } from '../types'
import { Dialog } from './Dialog'
import { DISCREPANCY_REASON_LABELS } from './poLabels'

const LOG_PAGE_SIZE = 200
const ALL = 'all'

type KindFilter = typeof ALL | PoDiscrepancyKind

const KIND_LABELS: Record<PoDiscrepancyKind, string> = {
  short: 'Not received',
  over: 'Received too many',
}

interface NotReceivedLogDialogProps {
  suppliers: Supplier[]
  onClose: () => void
  onOpenOrder: (poId: number) => void
}

export function NotReceivedLogDialog({
  suppliers,
  onClose,
  onOpenOrder,
}: NotReceivedLogDialogProps) {
  const [kind, setKind] = React.useState<KindFilter>('short')
  const [supplierId, setSupplierId] = React.useState(ALL)
  const [dateFrom, setDateFrom] = React.useState('')
  const [dateTo, setDateTo] = React.useState('')

  const logQuery = useQuery({
    queryKey: [
      'supply',
      'purchase-orders',
      'discrepancies',
      { kind, supplierId, dateFrom, dateTo },
    ],
    queryFn: ({ signal }) =>
      api.get<Page<PoDiscrepancy>>('/api/v1/purchase-orders/discrepancies', {
        params: {
          kind: kind === ALL ? undefined : kind,
          supplier_id: supplierId === ALL ? undefined : Number(supplierId),
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
          limit: LOG_PAGE_SIZE,
          offset: 0,
        },
        signal,
      }),
    placeholderData: keepPreviousData,
  })

  const discrepancies = logQuery.data?.items ?? []
  const total = logQuery.data?.total ?? 0

  return (
    <Dialog
      open
      onClose={onClose}
      title="Not received log"
      description="Every PO line closed with fewer units than ordered, and every over-receipt."
      widthClassName="max-w-5xl"
    >
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <Select value={kind} onValueChange={(value) => setKind(value as KindFilter)}>
            <SelectTrigger className="w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="short">{KIND_LABELS.short}</SelectItem>
              <SelectItem value="over">{KIND_LABELS.over}</SelectItem>
              <SelectItem value={ALL}>Both</SelectItem>
            </SelectContent>
          </Select>
          <Select value={supplierId} onValueChange={setSupplierId}>
            <SelectTrigger className="w-52">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All suppliers</SelectItem>
              {suppliers.map((supplier) => (
                <SelectItem key={supplier.id} value={String(supplier.id)}>
                  {supplier.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Input
            type="date"
            value={dateFrom}
            onChange={(event) => setDateFrom(event.target.value)}
            aria-label="Logged from"
            className="w-40"
          />
          <Input
            type="date"
            value={dateTo}
            onChange={(event) => setDateTo(event.target.value)}
            aria-label="Logged to"
            className="w-40"
          />
        </div>

        <LogContent
          isError={logQuery.isError}
          isLoading={logQuery.isLoading}
          discrepancies={discrepancies}
          onOpenOrder={onOpenOrder}
        />
        {total > discrepancies.length ? (
          <p className="text-xs text-muted-foreground">
            Showing the latest {discrepancies.length} of {total}. Narrow the dates to see older rows.
          </p>
        ) : null}
      </div>
    </Dialog>
  )
}

interface LogContentProps {
  isError: boolean
  isLoading: boolean
  discrepancies: PoDiscrepancy[]
  onOpenOrder: (poId: number) => void
}

function LogContent({ isError, isLoading, discrepancies, onOpenOrder }: LogContentProps) {
  if (isError) {
    return <p className="text-sm text-critical">Failed to load the log.</p>
  }
  if (discrepancies.length === 0) {
    return (
      <p className="rounded-md border border-dashed border-border px-3 py-6 text-center text-sm text-muted-foreground">
        {isLoading ? 'Loading…' : 'Nothing logged for these filters.'}
      </p>
    )
  }
  return <DiscrepancyTable discrepancies={discrepancies} onOpenOrder={onOpenOrder} />
}

interface DiscrepancyTableProps {
  discrepancies: PoDiscrepancy[]
  onOpenOrder: (poId: number) => void
}

function DiscrepancyTable({ discrepancies, onOpenOrder }: DiscrepancyTableProps) {
  return (
    <div className="max-h-[60vh] overflow-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-muted text-xs text-muted-foreground">
          <tr>
            <th className="px-3 py-2 text-left font-medium">Logged</th>
            <th className="px-3 py-2 text-left font-medium">Order</th>
            <th className="px-3 py-2 text-left font-medium">Supplier</th>
            <th className="px-3 py-2 text-left font-medium">Product</th>
            <th className="px-3 py-2 text-right font-medium">Ordered</th>
            <th className="px-3 py-2 text-right font-medium">Received</th>
            <th className="px-3 py-2 text-right font-medium">Difference</th>
            <th className="px-3 py-2 text-left font-medium">Reason / comment</th>
          </tr>
        </thead>
        <tbody>
          {discrepancies.map((discrepancy) => (
            <DiscrepancyRow
              key={discrepancy.id}
              discrepancy={discrepancy}
              onOpenOrder={onOpenOrder}
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}

interface DiscrepancyRowProps {
  discrepancy: PoDiscrepancy
  onOpenOrder: (poId: number) => void
}

function DiscrepancyRow({ discrepancy, onOpenOrder }: DiscrepancyRowProps) {
  const isShort = discrepancy.kind === 'short'
  const signedDifference = isShort
    ? `-${discrepancy.qty_difference}`
    : `+${discrepancy.qty_difference}`
  const reasonLabel = discrepancy.reason ? DISCREPANCY_REASON_LABELS[discrepancy.reason] : null
  const reasonAndComment = [reasonLabel, discrepancy.comment].filter(Boolean).join(': ')

  return (
    <tr className="border-t border-border align-top">
      <td className="px-3 py-2 text-xs text-muted-foreground">
        <div>{formatDateTime12Hour(discrepancy.created_at)}</div>
        {discrepancy.created_by_name ? <div>{discrepancy.created_by_name}</div> : null}
      </td>
      <td className="px-3 py-2">
        <button
          type="button"
          className="font-mono text-xs text-primary underline-offset-2 hover:underline"
          onClick={() => onOpenOrder(discrepancy.po_id)}
        >
          {discrepancy.order_no}
        </button>
      </td>
      <td className="px-3 py-2">{discrepancy.supplier_name}</td>
      <td className="px-3 py-2">
        <div className="font-medium">{discrepancy.product_name}</div>
        <div className="font-mono text-xs text-muted-foreground">{discrepancy.product_code}</div>
      </td>
      <td className="px-3 py-2 text-right tabular-nums">{discrepancy.qty_ordered}</td>
      <td className="px-3 py-2 text-right tabular-nums">{discrepancy.qty_received}</td>
      <td
        className={
          isShort
            ? 'px-3 py-2 text-right font-semibold tabular-nums text-critical'
            : 'px-3 py-2 text-right font-semibold tabular-nums text-warning'
        }
      >
        {signedDifference}
      </td>
      <td className="px-3 py-2 text-xs">{reasonAndComment || '-'}</td>
    </tr>
  )
}
