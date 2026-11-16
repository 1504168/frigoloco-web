import * as React from 'react'
import { keepPreviousData, useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { SlidersHorizontal } from 'lucide-react'
import { CategoryFilter } from '@/components/filters/CategoryFilter'
import { FilterBar } from '@/components/filters/FilterBar'
import { ProductSearchInput } from '@/components/filters/ProductSearchInput'
import { SupplierFilter } from '@/components/filters/SupplierFilter'
import { DataTable, type DataTableColumn } from '@/components/shared/DataTable'
import { EmptyState } from '@/components/shared/EmptyState'
import { ErrorState } from '@/components/shared/ErrorState'
import { StatusChip } from '@/components/shared/StatusChip'
import { Toolbar } from '@/components/shared/Toolbar'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Switch } from '@/components/ui/switch'
import { useCategorySupplierFilter } from '@/hooks/useCategorySupplierFilter'
import { api, type Page } from '@/lib/api'
import { EMPTY_PLACEHOLDER, formatDateTime12Hour } from '@/lib/format'
import { cn } from '@/lib/utils'
import { InfoHint, WithInfoHint, type Hint } from '@/components/shared/InfoHint'
import { ProductLocationsPanel } from './components/ProductLocationsPanel'
import {
  StockAdjustmentDialog,
  type AdjustableProduct,
  type AdjustmentMode,
} from './components/StockAdjustmentDialog'
import type {
  MovementsPage,
  StockBalance,
  StockMovementType,
} from './types'

const PAGE_SIZE = 25
const MOVEMENTS_LIMIT = 20

const INCLUDE_INACTIVE_HINT: Hint = {
  text:
    'Also lists inactive products with no stock, such as old short codes from the sales ' +
    'history.',
  example:
    '"Cantonese Rice" has the live code 0000042047681 and old codes 2016 and 4326; only the ' +
    'live code holds fridge stock.',
}
const MANUAL_ADJUSTMENT_HINT: Hint = {
  text: 'Records a warehouse stock change by hand: a signed change or the quantity you counted.',
  example: '3 salads thrown away: change by -3, reason "expired".',
}

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

function StockStatusChip({ balance }: { balance: StockBalance }) {
  if (!balance.is_active) return <StatusChip status="inactive" label="Inactive" />
  if (balance.available_qty < 0) return <StatusChip status="critical" label="Negative" />
  if (balance.is_low_stock) {
    return (
      <span title={`Fewer than the minimum of ${balance.min_stock_qty} in the warehouse`}>
        <StatusChip status="warning" label={`Low stock (min ${balance.min_stock_qty})`} />
      </span>
    )
  }
  if (balance.available_qty === 0) return <StatusChip status="warning" label="Empty" />
  return <StatusChip status="active" label="In stock" />
}

interface AdjustmentRequest {
  product: AdjustableProduct | null
  mode: AdjustmentMode
}

const STOCK_COLUMNS: DataTableColumn<StockBalance>[] = [
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
    id: 'category',
    header: 'Category',
    cell: (row) => <span className="text-muted-foreground">{row.category_name}</span>,
    sortValue: (row) => row.category_name,
  },
  {
    id: 'supplier',
    header: 'Supplier',
    cell: (row) => (
      <span className="text-muted-foreground">{row.supplier_name ?? EMPTY_PLACEHOLDER}</span>
    ),
    sortValue: (row) => row.supplier_name,
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
    id: 'fridges',
    header: 'In fridges',
    align: 'right',
    cell: (row) => <QtyCell value={row.fridge_units} />,
    sortValue: (row) => row.fridge_units,
  },
  {
    id: 'minimum',
    header: 'Minimum',
    align: 'right',
    cell: (row) => (
      <span className="tabular-nums text-muted-foreground">
        {row.min_stock_qty ?? EMPTY_PLACEHOLDER}
      </span>
    ),
    sortValue: (row) => row.min_stock_qty,
  },
  {
    id: 'status',
    header: 'Status',
    cell: (row) => <StockStatusChip balance={row} />,
    sortValue: (row) => row.available_qty,
  },
]

export function StockPage() {
  const {
    categoryId,
    supplierId,
    isSupplierSettled,
    setCategoryId,
    setSupplierId,
  } = useCategorySupplierFilter()
  const [search, setSearch] = React.useState('')
  const [offset, setOffset] = React.useState(0)
  const [includeInactive, setIncludeInactive] = React.useState(false)
  const [clickedRow, setClickedRow] = React.useState<StockBalance | null>(null)
  const [adjustment, setAdjustment] = React.useState<AdjustmentRequest | null>(null)

  React.useEffect(() => {
    setOffset(0)
  }, [search, categoryId, supplierId, includeInactive])

  const balancesQuery = useQuery({
    queryKey: [
      'supply',
      'stock-balances',
      { search, categoryId, supplierId, includeInactive, offset },
    ],
    queryFn: ({ signal }) =>
      api.get<Page<StockBalance>>('/api/v1/stock/balances', {
        params: {
          search: search || undefined,
          category_id: categoryId,
          supplier_id: supplierId,
          include_inactive: includeInactive || undefined,
          limit: PAGE_SIZE,
          offset,
        },
        signal,
      }),
    placeholderData: keepPreviousData,
    enabled: isSupplierSettled,
  })

  // Re-read the clicked row from the latest page so a saved minimum or adjustment shows at once.
  const refreshedRow = balancesQuery.data?.items.find(
    (row) => row.product_id === clickedRow?.product_id,
  )
  const selected = refreshedRow ?? clickedRow

  return (
    <div className="space-y-3">
      <Toolbar
        left={
          <FilterBar>
            <CategoryFilter
              value={categoryId}
              onChange={setCategoryId}
            />
            <SupplierFilter
              value={supplierId}
              onChange={setSupplierId}
              categoryId={categoryId}
            />
            <ProductSearchInput onSearchChange={setSearch} />
            <label
              className="flex items-center gap-2 whitespace-nowrap text-xs text-muted-foreground"
            >
              <Switch
                checked={includeInactive}
                onCheckedChange={setIncludeInactive}
              />
              Show inactive
              <InfoHint {...INCLUDE_INACTIVE_HINT} />
            </label>
          </FilterBar>
        }
        right={
          <WithInfoHint hint={MANUAL_ADJUSTMENT_HINT}>
            <Button
              variant="outline"
              onClick={() => setAdjustment({ product: null, mode: 'delta' })}
            >
              <SlidersHorizontal className="h-4 w-4" /> Manual adjustment
            </Button>
          </WithInfoHint>
        }
      />

      <div className="grid flex-1 grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <div className="flex flex-col">
          <DataTable
            columns={STOCK_COLUMNS}
            page={balancesQuery.data}
            isLoading={balancesQuery.isLoading}
            isError={balancesQuery.isError}
            error={balancesQuery.error}
            onRetry={() => balancesQuery.refetch()}
            limit={PAGE_SIZE}
            offset={offset}
            onOffsetChange={setOffset}
            getRowId={(row) => row.product_id}
            onRowClick={(row) => setClickedRow(row)}
            emptyState={
              <EmptyState
                title="No stock rows"
                description="No products match the current filters."
              />
            }
          />
        </div>

        <div className="flex min-w-0 flex-col gap-6 self-start">
          {selected ? (
            <ProductLocationsPanel
              selected={selected}
              onAdjustStock={() =>
                setAdjustment({ product: toAdjustableProduct(selected), mode: 'counted' })
              }
            />
          ) : null}
          <MovementsPanel selected={selected} />
        </div>
      </div>

      {adjustment ? (
        <StockAdjustmentDialog
          initialProduct={adjustment.product}
          initialMode={adjustment.mode}
          onClose={() => setAdjustment(null)}
          onDone={() => setAdjustment(null)}
        />
      ) : null}
    </div>
  )
}

function toAdjustableProduct(balance: StockBalance): AdjustableProduct {
  return {
    id: balance.product_id,
    code: balance.product_code,
    name: balance.product_name,
  }
}

function MovementsPanel({ selected }: { selected: StockBalance | null }) {
  const productId = selected?.product_id ?? null
  // An infinite query refetches every loaded page on invalidation, so a new adjustment
  // appears at the top straight away.
  const movementsQuery = useInfiniteQuery({
    queryKey: ['supply', 'stock-movements', { productId }],
    queryFn: ({ pageParam, signal }) =>
      api.get<MovementsPage>('/api/v1/stock/movements', {
        params: {
          product_id: productId,
          before_id: pageParam ?? undefined,
          limit: MOVEMENTS_LIMIT,
        },
        signal,
      }),
    initialPageParam: null as number | null,
    getNextPageParam: (lastPage) => lastPage.next_before_id,
    enabled: productId !== null,
  })

  const movements = movementsQuery.data?.pages.flatMap((page) => page.items) ?? []

  return (
    <Card className="flex flex-col p-5">
      <h3 className="text-sm font-semibold text-foreground">
        Movement history
        {selected ? <span className="ml-1 text-muted-foreground">- {selected.product_name}</span> : null}
      </h3>
      <p className="mt-0.5 text-xs text-muted-foreground">
        {selected
          ? `Code ${selected.product_code} · newest first; every change traces to a PO, dispatch or adjustment.`
          : 'Select a product on the left to view its movements.'}
      </p>

      <div className="mt-4">
        {!selected ? (
          <EmptyState title="No product selected" description="Pick a product to inspect its movements." />
        ) : movementsQuery.isLoading ? (
          <p className="py-6 text-center text-sm text-muted-foreground">Loading movements…</p>
        ) : movementsQuery.isError ? (
          <ErrorState error={movementsQuery.error} onRetry={() => movementsQuery.refetch()} />
        ) : movements.length === 0 ? (
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
                  {movements.map((movement) => (
                    <tr key={movement.id} className="border-t border-border">
                      <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
                        {formatDateTime12Hour(movement.created_at)}
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
            {movementsQuery.hasNextPage ? (
              <div className="mt-3 flex justify-center">
                <Button
                  variant="outline"
                  size="sm"
                  title="Load older movements"
                  disabled={movementsQuery.isFetchingNextPage}
                  onClick={() => movementsQuery.fetchNextPage()}
                >
                  {movementsQuery.isFetchingNextPage ? 'Loading…' : 'Load older'}
                </Button>
              </div>
            ) : null}
          </>
        )}
      </div>
    </Card>
  )
}

export default StockPage
