import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query'
import { RefreshCw, SlidersHorizontal } from 'lucide-react'
import { ErrorState } from '@/components/shared/ErrorState'
import { WithInfoHint, type Hint } from '@/components/shared/InfoHint'
import { StatusChip } from '@/components/shared/StatusChip'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { toast } from '@/components/ui/toast'
import { api, ApiError } from '@/lib/api'
import { formatDate, formatDateTime12Hour } from '@/lib/format'
import type { FridgeUnits, ProductLocations, SameNameProduct, StockBalance } from '../types'
import { MinimumStockEditor } from './MinimumStockEditor'

const ADJUST_STOCK_HINT: Hint = {
  text:
    'Corrects the warehouse stock of this product, for example after a count. A reason is ' +
    'required.',
  example: 'The system shows 30, you count 27: enter counted quantity 27 and it records -3.',
}
const LIVE_REFRESH_HINT = 'Reads every fridge live from Husky (takes 5 to 10 seconds).'

export function locationsUrl(productId: number): string {
  return `/api/v1/stock/products/${productId}/fridges`
}

export function locationsQueryKey(productId: number) {
  return ['supply', 'product-locations', productId]
}

interface ProductLocationsPanelProps {
  selected: StockBalance
  onAdjustStock: () => void
}

/** Units of the selected product in every fridge (latest 15-min reading) plus the warehouse. */
export function ProductLocationsPanel({ selected, onAdjustStock }: ProductLocationsPanelProps) {
  const queryClient = useQueryClient()
  const productId = selected.product_id

  const locationsQuery = useQuery({
    queryKey: locationsQueryKey(productId),
    queryFn: ({ signal }) => api.get<ProductLocations>(locationsUrl(productId), { signal }),
  })

  const refreshMutation = useMutation({
    mutationFn: () => api.post<ProductLocations>(`${locationsUrl(productId)}/refresh`),
    onSuccess: (freshLocations) => {
      queryClient.setQueryData(locationsQueryKey(productId), freshLocations)
      toast.success('Fridge stock refreshed from Husky')
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : 'Refresh failed'
      toast.error(message)
    },
  })

  return (
    <Card className="flex flex-col p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-foreground">
            Where it is now
            <span className="ml-1 text-muted-foreground">- {selected.product_name}</span>
          </h3>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Fridge stock as of {formatDateTime12Hour(locationsQuery.data?.latest_taken_at)}
          </p>
        </div>
        <WithInfoHint hint={ADJUST_STOCK_HINT}>
          <Button
            variant="outline"
            size="sm"
            className="shrink-0"
            onClick={onAdjustStock}
          >
            <SlidersHorizontal className="h-4 w-4" /> Adjust stock
          </Button>
        </WithInfoHint>
        <Button
          variant="outline"
          size="sm"
          className="shrink-0"
          title={LIVE_REFRESH_HINT}
          disabled={refreshMutation.isPending}
          onClick={() => refreshMutation.mutate()}
        >
          <RefreshCw className={refreshMutation.isPending ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} />
          {refreshMutation.isPending ? 'Reading fridges…' : 'Refresh now'}
        </Button>
      </div>

      <div className="mt-3">
        <MinimumStockEditor
          key={`${productId}-${selected.min_stock_qty}`}
          selected={selected}
        />
      </div>

      <div className="mt-4">
        <LocationsBody locationsQuery={locationsQuery} />
      </div>
    </Card>
  )
}

interface LocationsBodyProps {
  locationsQuery: UseQueryResult<ProductLocations>
}

function LocationsBody({ locationsQuery }: LocationsBodyProps) {
  if (locationsQuery.isLoading) {
    return <p className="py-4 text-center text-sm text-muted-foreground">Loading fridge stock…</p>
  }
  if (locationsQuery.isError) {
    return <ErrorState error={locationsQuery.error} onRetry={() => locationsQuery.refetch()} />
  }
  const locations = locationsQuery.data
  if (!locations) return null

  return (
    <div className="space-y-3">
      <SameNameNotice
        isActive={locations.is_active}
        sameNameProducts={locations.same_name_products}
      />
      <div className="grid grid-cols-3 gap-2">
        <StockTile label="In fridges" value={locations.fridge_units_total} />
        <StockTile label="In warehouse" value={locations.physical_qty} />
        <StockTile label="On order" value={locations.on_order_qty} />
      </div>
      {locations.fridges.length === 0 ? (
        <p className="py-2 text-center text-sm text-muted-foreground">
          Not in any fridge right now.
        </p>
      ) : (
        <FridgeUnitsTable fridges={locations.fridges} />
      )}
    </div>
  )
}

interface SameNameNoticeProps {
  isActive: boolean
  sameNameProducts: SameNameProduct[]
}

/** Old short codes share names with today's EAN products; say which code holds the stock. */
function SameNameNotice({ isActive, sameNameProducts }: SameNameNoticeProps) {
  if (sameNameProducts.length === 0) return null
  const otherCodes = sameNameProducts.map(describeSameNameProduct).join(', ')
  const statusText = isActive ? '' : 'This code is inactive (an old code from history). '
  return (
    <p className="rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-xs">
      {statusText}Other products have the same name: {otherCodes}. Search by code to open one.
    </p>
  )
}

function describeSameNameProduct(product: SameNameProduct): string {
  const status = product.is_active ? 'active' : 'inactive'
  return `code ${product.product_code} (${status}, ${product.fridge_units} in fridges)`
}

function StockTile({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-border px-3 py-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-lg font-semibold tabular-nums">{value}</div>
    </div>
  )
}

function FridgeUnitsTable({ fridges }: { fridges: FridgeUnits[] }) {
  return (
    <div className="max-h-80 overflow-y-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-muted text-xs text-muted-foreground">
          <tr>
            <th className="px-3 py-2 text-left font-medium">Fridge</th>
            <th className="px-3 py-2 text-right font-medium">Units</th>
            <th className="px-3 py-2 text-left font-medium">Next expiry</th>
          </tr>
        </thead>
        <tbody>
          {fridges.map((fridge) => (
            <tr key={fridge.fridge_id} className="border-t border-border">
              <td className="px-3 py-2">
                {fridge.fridge_name}
                {fridge.is_stale ? (
                  <span
                    className="ml-2"
                    title={`Last reading ${formatDateTime12Hour(fridge.taken_at)}`}
                  >
                    <StatusChip status="warning" label="Stale" />
                  </span>
                ) : null}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">{fridge.units}</td>
              <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
                {formatDate(fridge.next_expiry_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
