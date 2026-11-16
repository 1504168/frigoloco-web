import * as React from 'react'
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { Pencil } from 'lucide-react'
import { CategoryFilter } from '@/components/filters/CategoryFilter'
import { FilterBar } from '@/components/filters/FilterBar'
import { ProductSearchInput } from '@/components/filters/ProductSearchInput'
import { SupplierFilter } from '@/components/filters/SupplierFilter'
import { DataTable, type DataTableColumn } from '@/components/shared/DataTable'
import { EmptyState } from '@/components/shared/EmptyState'
import { MoneyCell } from '@/components/shared/MoneyCell'
import { Toolbar } from '@/components/shared/Toolbar'
import { Button } from '@/components/ui/button'
import { toast } from '@/components/ui/toast'
import { api, type Page } from '@/lib/api'
import { EMPTY_PLACEHOLDER } from '@/lib/format'
import { REFERENCE_CATEGORIES_KEY } from '@/lib/query-keys'
import type { Category, Product } from '@/lib/types'
import { useCategorySupplierFilter } from '@/hooks/useCategorySupplierFilter'
import {
  EffectiveStatusBadge,
  HuskySyncControl,
  StatusFilterSelect,
} from '@/pages/masters/sync/components'
import type { StatusFilter } from '@/pages/masters/sync/types'
import { ProductSettingsDialog } from './ProductSettingsDialog'

const PAGE_SIZE = 25

/** Query key prefix for the products list: the sync flow invalidates this. */
const PRODUCTS_QUERY_KEY = ['products']

/** Percent display for the VAT decimal fraction (e.g. "0.0600" -> "6%"). */
function formatVat(fraction: string): string {
  const numeric = Number(fraction)
  if (Number.isNaN(numeric)) return EMPTY_PLACEHOLDER
  return `${(numeric * 100).toFixed(numeric * 100 % 1 === 0 ? 0 : 2)}%`
}

export function ProductsPage() {
  const {
    categoryId,
    supplierId,
    isSupplierSettled,
    setCategoryId,
    setSupplierId,
  } = useCategorySupplierFilter()
  const [search, setSearch] = React.useState('')
  const [statusFilter, setStatusFilter] = React.useState<StatusFilter>('active')
  const [offset, setOffset] = React.useState(0)
  const [editing, setEditing] = React.useState<Product | null>(null)
  const queryClient = useQueryClient()

  React.useEffect(() => {
    setOffset(0)
  }, [search, statusFilter, categoryId, supplierId])

  const productsQuery = useQuery({
    queryKey: [
      ...PRODUCTS_QUERY_KEY,
      {
        search,
        status: statusFilter,
        categoryId,
        supplierId,
        limit: PAGE_SIZE,
        offset,
      },
    ],
    queryFn: ({ signal }) =>
      api.get<Page<Product>>('/api/v1/products', {
        params: {
          search: search || undefined,
          status: statusFilter,
          category_id: categoryId,
          supplier_id: supplierId,
          limit: PAGE_SIZE,
          offset,
        },
        signal,
      }),
    placeholderData: keepPreviousData,
    enabled: isSupplierSettled,
  })

  // Note: GET /api/v1/categories returns a bare array (not a Page<T>).
  const categoriesQuery = useQuery({
    queryKey: REFERENCE_CATEGORIES_KEY,
    queryFn: ({ signal }) => api.get<Category[]>('/api/v1/categories', { signal }),
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
        id: 'supplier',
        header: 'Supplier',
        cell: (row) => (
          <span className="text-muted-foreground">{row.supplier_name ?? EMPTY_PLACEHOLDER}</span>
        ),
        sortValue: (row) => row.supplier_name,
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
        id: 'min_stock',
        header: 'Min stock',
        align: 'right',
        cell: (row) => <OptionalNumberCell value={row.min_stock_qty} />,
        sortValue: (row) => row.min_stock_qty,
      },
      {
        id: 'print_order',
        header: 'Print order',
        align: 'right',
        cell: (row) => <OptionalNumberCell value={row.print_order} />,
        sortValue: (row) => row.print_order,
      },
      {
        id: 'actions',
        header: '',
        align: 'right',
        cell: (row) => (
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            aria-label={`Edit settings of ${row.name}`}
            onClick={() => setEditing(row)}
          >
            <Pencil className="h-4 w-4" />
          </Button>
        ),
      },
    ],
    [categoryName],
  )

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
            <StatusFilterSelect
              value={statusFilter}
              onChange={setStatusFilter}
            />
          </FilterBar>
        }
        right={
          <HuskySyncControl
            feed="catalogue"
            endpoint="catalogue"
            invalidateKeys={[PRODUCTS_QUERY_KEY]}
            itemLabel="product"
          />
        }
      />

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
            description="No products match the current filters."
          />
        }
      />

      {editing ? (
        <ProductSettingsDialog
          product={editing}
          onClose={() => setEditing(null)}
          onSuccess={(updated) => {
            toast.success(`Product “${updated.name}” updated`)
            queryClient.invalidateQueries({ queryKey: PRODUCTS_QUERY_KEY })
            setEditing(null)
          }}
        />
      ) : null}
    </div>
  )
}

function OptionalNumberCell({ value }: { value: number | null }) {
  if (value === null) return <span className="text-muted-foreground">{EMPTY_PLACEHOLDER}</span>
  return <span className="tabular-nums">{value}</span>
}

export default ProductsPage
