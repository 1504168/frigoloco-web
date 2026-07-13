import * as React from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Search, SlidersHorizontal } from 'lucide-react'
import { PageHeader } from '@/components/shared/PageHeader'
import { DataTable, type DataTableColumn } from '@/components/shared/DataTable'
import { EmptyState } from '@/components/shared/EmptyState'
import { ErrorState } from '@/components/shared/ErrorState'
import { StatusChip } from '@/components/shared/StatusChip'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card } from '@/components/ui/card'
import { toast } from '@/components/ui/sonner'
import { api, ApiError, type Page } from '@/lib/api'
import { EMPTY_PLACEHOLDER, formatDateTime } from '@/lib/format'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { cn } from '@/lib/utils'
import { Dialog } from './components/Dialog'
import { Field, Textarea, fieldErrorsFromApiError } from './components/form'
import { ProductPicker } from './components/ProductPicker'
import type {
  MovementsPage,
  ProductLite,
  StockBalance,
  StockMovement,
  StockMovementType,
} from './types'

const PAGE_SIZE = 25
const MOVEMENTS_LIMIT = 20

const MOVEMENT_LABELS: Record<StockMovementType, string> = {
  po_receipt: 'PO receipt',
  dispatch: 'Dispatch',
  adjustment: 'Manual adjustment',
  cancellation_reversal: 'Cancellation reversal',
}

/** Red text for negative quantities so shortages jump out. */
function QtyCell({ value }: { value: number }) {
  return (
    <span className={cn('tabular-nums', value < 0 && 'font-semibold text-critical')}>{value}</span>
  )
}

export function StockPage() {
  const [searchInput, setSearchInput] = React.useState('')
  const [offset, setOffset] = React.useState(0)
  const [selected, setSelected] = React.useState<StockBalance | null>(null)
  const [adjusting, setAdjusting] = React.useState(false)

  const search = useDebouncedValue(searchInput.trim(), 300)

  React.useEffect(() => {
    setOffset(0)
  }, [search])

  const balancesQuery = useQuery({
    queryKey: ['supply', 'stock-balances', { search, offset }],
    queryFn: ({ signal }) =>
      api.get<Page<StockBalance>>('/api/v1/stock/balances', {
        params: { search: search || undefined, limit: PAGE_SIZE, offset },
        signal,
      }),
    placeholderData: keepPreviousData,
  })

  const columns = React.useMemo<DataTableColumn<StockBalance>[]>(
    () => [
      {
        id: 'code',
        header: 'Code',
        cell: (row) => <span className="font-mono text-xs">{row.product_code}</span>,
        sortValue: (row) => row.product_code,
      },
      {
        id: 'name',
        header: 'Product',
        cell: (row) => <span className="font-medium">{row.product_name}</span>,
        sortValue: (row) => row.product_name,
      },
      {
        id: 'on_order',
        header: 'On order',
        align: 'right',
        cell: (row) => <QtyCell value={row.on_order_qty} />,
        sortValue: (row) => row.on_order_qty,
      },
      {
        id: 'physical',
        header: 'In warehouse',
        align: 'right',
        cell: (row) => <QtyCell value={row.physical_qty} />,
        sortValue: (row) => row.physical_qty,
      },
      {
        id: 'available',
        header: 'Available',
        align: 'right',
        cell: (row) => <QtyCell value={row.available_qty} />,
        sortValue: (row) => row.available_qty,
      },
      {
        id: 'status',
        header: 'Status',
        cell: (row) =>
          row.available_qty < 0 ? (
            <StatusChip status="critical" label="Negative" />
          ) : row.available_qty === 0 ? (
            <StatusChip status="warning" label="Empty" />
          ) : (
            <StatusChip status="active" label="In stock" />
          ),
        sortValue: (row) => row.available_qty,
      },
    ],
    [],
  )

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumb="Operations / Stock"
        title="Stock"
        description="Balances and movement history. Available = on order + physical − dispatched."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                placeholder="Search code or name…"
                className="w-64 pl-8"
              />
            </div>
            <Button variant="outline" onClick={() => setAdjusting(true)}>
              <SlidersHorizontal className="h-4 w-4" /> Manual adjustment
            </Button>
          </div>
        }
      />

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1.4fr_1fr]">
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-foreground">Stock levels</h3>
          <p className="text-xs text-muted-foreground">Click a row to see its movement history.</p>
          <DataTable
            columns={columns}
            page={balancesQuery.data}
            isLoading={balancesQuery.isLoading}
            isError={balancesQuery.isError}
            error={balancesQuery.error}
            onRetry={() => balancesQuery.refetch()}
            limit={PAGE_SIZE}
            offset={offset}
            onOffsetChange={setOffset}
            getRowId={(row) => row.product_id}
            onRowClick={(row) => setSelected(row)}
            emptyState={
              <EmptyState
                title="No stock rows"
                description={
                  search ? `No products match “${search}”.` : 'No stock balances available.'
                }
              />
            }
          />
        </div>

        <MovementsPanel selected={selected} />
      </div>

      {adjusting ? (
        <AdjustmentDialog
          onClose={() => setAdjusting(false)}
          onDone={() => {
            balancesQuery.refetch()
            setAdjusting(false)
          }}
        />
      ) : null}
    </div>
  )
}

function MovementsPanel({ selected }: { selected: StockBalance | null }) {
  const [afterId, setAfterId] = React.useState<number | null>(null)
  const [accumulated, setAccumulated] = React.useState<StockMovement[]>([])

  // Reset the keyset cursor whenever the selected product changes.
  React.useEffect(() => {
    setAfterId(null)
    setAccumulated([])
  }, [selected?.product_id])

  const movementsQuery = useQuery({
    queryKey: ['supply', 'stock-movements', { productId: selected?.product_id ?? null, afterId }],
    queryFn: ({ signal }) =>
      api.get<MovementsPage>('/api/v1/stock/movements', {
        params: {
          product_id: selected?.product_id,
          after_id: afterId ?? undefined,
          limit: MOVEMENTS_LIMIT,
        },
        signal,
      }),
    placeholderData: keepPreviousData,
  })

  // Append each freshly-loaded keyset page to the running list.
  React.useEffect(() => {
    const data = movementsQuery.data
    if (!data) return
    setAccumulated((prev) => {
      const seen = new Set(prev.map((movement) => movement.id))
      const fresh = data.items.filter((movement) => !seen.has(movement.id))
      return [...prev, ...fresh]
    })
  }, [movementsQuery.data])

  const nextAfterId = movementsQuery.data?.next_after_id ?? null

  return (
    <Card className="flex flex-col self-start p-5">
      <h3 className="text-sm font-semibold text-foreground">
        Movement history
        {selected ? <span className="ml-1 text-muted-foreground">- {selected.product_name}</span> : null}
      </h3>
      <p className="mt-0.5 text-xs text-muted-foreground">
        {selected
          ? `Code ${selected.product_code} · every change traces to a PO, dispatch or adjustment.`
          : 'Select a product on the left to view its movements.'}
      </p>

      <div className="mt-4">
        {!selected ? (
          <EmptyState title="No product selected" description="Pick a product to inspect its movements." />
        ) : movementsQuery.isLoading && accumulated.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">Loading movements…</p>
        ) : movementsQuery.isError ? (
          <ErrorState error={movementsQuery.error} onRetry={() => movementsQuery.refetch()} />
        ) : accumulated.length === 0 ? (
          <EmptyState title="No movements" description="This product has no recorded stock movements." />
        ) : (
          <>
            <div className="overflow-hidden rounded-lg border border-border">
              <table className="w-full text-sm">
                <thead className="bg-muted/40 text-xs text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">When</th>
                    <th className="px-3 py-2 text-left font-medium">Movement</th>
                    <th className="px-3 py-2 text-right font-medium">Qty</th>
                    <th className="px-3 py-2 text-left font-medium">Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {accumulated.map((movement) => (
                    <tr key={movement.id} className="border-t border-border">
                      <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
                        {formatDateTime(movement.created_at)}
                      </td>
                      <td className="px-3 py-2">{MOVEMENT_LABELS[movement.movement_type]}</td>
                      <td
                        className={cn(
                          'px-3 py-2 text-right tabular-nums',
                          movement.qty < 0 ? 'text-critical' : 'text-good-text',
                        )}
                      >
                        {movement.qty > 0 ? `+${movement.qty}` : movement.qty}
                      </td>
                      <td className="px-3 py-2 text-muted-foreground">{movement.reason ?? EMPTY_PLACEHOLDER}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {nextAfterId !== null ? (
              <div className="mt-3 flex justify-center">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={movementsQuery.isFetching}
                  onClick={() => setAfterId(nextAfterId)}
                >
                  {movementsQuery.isFetching ? 'Loading…' : 'Load more'}
                </Button>
              </div>
            ) : null}
          </>
        )}
      </div>
    </Card>
  )
}

function AdjustmentDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const queryClient = useQueryClient()
  const [product, setProduct] = React.useState<ProductLite | null>(null)
  const [qty, setQty] = React.useState('')
  const [reason, setReason] = React.useState('')

  const mutation = useMutation({
    mutationFn: () =>
      api.post<StockMovement>('/api/v1/stock/adjustments', {
        product_id: product?.id,
        qty: Number(qty),
        reason: reason.trim(),
      }),
    onSuccess: () => {
      toast.success('Stock adjustment recorded')
      queryClient.invalidateQueries({ queryKey: ['supply', 'stock-balances'] })
      queryClient.invalidateQueries({ queryKey: ['supply', 'stock-movements'] })
      onDone()
    },
  })

  const fieldErrors = fieldErrorsFromApiError(mutation.error)
  // stock_blocked (409) is a business error, surfaced inline rather than as a field error.
  const blockedError =
    mutation.error instanceof ApiError && mutation.error.code === 'stock_blocked'
      ? mutation.error.message
      : null
  const otherError =
    mutation.error instanceof ApiError &&
    mutation.error.code !== 'validation_error' &&
    mutation.error.code !== 'stock_blocked'
      ? mutation.error.message
      : null

  const qtyNumber = Number(qty)
  const canSubmit = product !== null && qty.trim() !== '' && !Number.isNaN(qtyNumber) && reason.trim() !== ''

  return (
    <Dialog
      open
      onClose={onClose}
      title="Manual stock adjustment"
      description="Positive quantity adds stock, negative removes it. A reason is required for the audit log."
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button onClick={() => mutation.mutate()} disabled={mutation.isPending || !canSubmit}>
            {mutation.isPending ? 'Saving…' : 'Record adjustment'}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {blockedError ? (
          <div className="rounded-md border border-critical/40 bg-critical/5 px-3 py-2 text-sm text-critical">
            {blockedError}
          </div>
        ) : null}
        {otherError ? (
          <div className="rounded-md border border-critical/40 bg-critical/5 px-3 py-2 text-sm text-critical">
            {otherError}
          </div>
        ) : null}

        <Field label="Product" required error={fieldErrors.product_id}>
          {product ? (
            <div className="flex items-center justify-between gap-2 rounded-md border border-border px-3 py-2 text-sm">
              <span>
                <span className="font-medium">{product.name}</span>
                <span className="ml-2 font-mono text-xs text-muted-foreground">{product.code}</span>
              </span>
              <Button variant="ghost" size="sm" onClick={() => setProduct(null)}>
                Change
              </Button>
            </div>
          ) : (
            <ProductPicker onSelect={setProduct} />
          )}
        </Field>

        <Field label="Quantity (±)" required error={fieldErrors.qty} hint="e.g. 12 to add, -3 to remove">
          <Input
            type="number"
            value={qty}
            onChange={(event) => setQty(event.target.value)}
            placeholder="0"
          />
        </Field>

        <Field label="Reason" required error={fieldErrors.reason}>
          <Textarea
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="Stock count correction, breakage, …"
          />
        </Field>
      </div>
    </Dialog>
  )
}

export default StockPage
