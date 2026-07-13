import * as React from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Search } from 'lucide-react'
import { DataTable, type DataTableColumn } from '@/components/shared/DataTable'
import { EmptyState } from '@/components/shared/EmptyState'
import { MoneyCell } from '@/components/shared/MoneyCell'
import { Input } from '@/components/ui/input'
import { api, type Page } from '@/lib/api'
import type { Product } from '@/lib/types'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import {
  EffectiveStatusBadge,
  HuskySyncControl,
  StatusFilterSelect,
  StatusOverrideSelect,
} from '@/pages/masters/sync/components'
import type { StatusFilter } from '@/pages/masters/sync/types'

const PAGE_SIZE = 25

/** Query key prefix for the products list — the sync flow invalidates this. */
const PRODUCTS_QUERY_KEY = ['products']

/** Percent display for the VAT decimal fraction (e.g. "0.0600" -> "6%"). */
function formatVat(fraction: string): string {
  const numeric = Number(fraction)
  if (Number.isNaN(numeric)) return '—'
  return `${(numeric * 100).toFixed(numeric * 100 % 1 === 0 ? 0 : 2)}%`
}

/**
 * FILTERS (backend reality, verified live against the API):
 *  - `search` is a real server-side query param and drives pagination totals.
 *  - `status` (active|inactive|cancelled|all) is now honored server-side and
 *    reflects the effective status (local override, else Husky-derived).
 */
export function ProductsPage() {
  const [searchInput, setSearchInput] = React.useState('')
  const [statusFilter, setStatusFilter] = React.useState<StatusFilter>('active')
  const [offset, setOffset] = React.useState(0)

  const search = useDebouncedValue(searchInput.trim(), 300)

  // Reset to the first page whenever the search term or status filter changes.
  React.useEffect(() => {
    setOffset(0)
  }, [search, statusFilter])

  const productsQuery = useQuery({
    queryKey: ['products', { search, status: statusFilter, limit: PAGE_SIZE, offset }],
    queryFn: ({ signal }) =>
      api.get<Page<Product>>('/api/v1/products', {
        params: {
          search: search || undefined,
          status: statusFilter,
          limit: PAGE_SIZE,
          offset,
        },
        signal,
      }),
    placeholderData: keepPreviousData,
  })

  // Note: GET /api/v1/categories returns a bare array (not a Page<T>).
  const categoriesQuery = useQuery({
    queryKey: ['categories'],
    queryFn: ({ signal }) =>
      api.get<Array<{ id: number; name: string }>>('/api/v1/categories', { signal }),
    staleTime: 5 * 60_000,
    select: (items) => new Map(items.map((category) => [category.id, category.name])),
  })

  const categoryName = React.useCallback(
    (id: number) => categoriesQuery.data?.get(id) ?? `#${id}`,
    [categoriesQuery.data],
  )

  const columns = React.useMemo<DataTableColumn<Product>[]>(
    () => [
      {
        id: 'code',
        header: 'Code',
        cell: (row) => <span className="font-mono text-xs">{row.code}</span>,
        sortValue: (row) => row.code,
      },
      {
        id: 'name',
        header: 'Name',
        cell: (row) => <span className="font-medium">{row.name}</span>,
        sortValue: (row) => row.name,
      },
      {
        id: 'category',
        header: 'Category',
        cell: (row) => (
          <span className="text-muted-foreground">{categoryName(row.category_id)}</span>
        ),
        sortValue: (row) => categoryName(row.category_id),
      },
      {
        id: 'purchase_price',
        header: 'Purchase',
        align: 'right',
        cell: (row) => <MoneyCell value={row.purchase_price} />,
        sortValue: (row) => Number(row.purchase_price),
      },
      {
        id: 'sales_price',
        header: 'Sales',
        align: 'right',
        cell: (row) => <MoneyCell value={row.sales_price} />,
        sortValue: (row) => Number(row.sales_price),
      },
      {
        id: 'vat',
        header: 'VAT',
        align: 'right',
        cell: (row) => <span className="tabular-nums">{formatVat(row.vat_rate)}</span>,
        sortValue: (row) => Number(row.vat_rate),
      },
      {
        id: 'status',
        header: 'Status',
        cell: (row) => <EffectiveStatusBadge status={row.effective_status} />,
        sortValue: (row) => row.effective_status,
      },
      {
        id: 'override',
        header: 'Override',
        cell: (row) => (
          <StatusOverrideSelect
            resourcePath={`/api/v1/products/${row.id}`}
            localStatus={row.local_status}
            invalidateKeys={[PRODUCTS_QUERY_KEY]}
            entityLabel={`Product ${row.code}`}
          />
        ),
      },
    ],
    [categoryName],
  )

  return (
    <div className="space-y-3">
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
        <StatusFilterSelect value={statusFilter} onChange={setStatusFilter} />
        <div className="ml-auto">
          <HuskySyncControl
            feed="catalogue"
            endpoint="catalogue"
            invalidateKeys={[PRODUCTS_QUERY_KEY]}
            itemLabel="product"
          />
        </div>
      </div>

      <DataTable
        columns={columns}
        page={productsQuery.data}
        isLoading={productsQuery.isLoading}
        isError={productsQuery.isError}
        error={productsQuery.error}
        onRetry={() => productsQuery.refetch()}
        limit={PAGE_SIZE}
        offset={offset}
        onOffsetChange={setOffset}
        getRowId={(row) => row.id}
        emptyState={
          <EmptyState
            title="No products found"
            description={
              search
                ? `No products match “${search}”. Try a different term.`
                : 'No products match the current filters.'
            }
          />
        }
      />
    </div>
  )
}

export default ProductsPage
