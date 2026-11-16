import * as React from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { toast } from '@/components/ui/toast'
import { ALERTS_COUNT_KEY } from '@/hooks/useAlertsCount'
import { api, ApiError } from '@/lib/api'
import { InfoHint, type Hint } from '@/components/shared/InfoHint'
import type { MinimumStock, StockBalance } from '../types'

const MINIMUM_HINT: Hint = {
  text:
    'Warehouse minimum for this product. Below it, a "Low stock" alert opens on the Alerts ' +
    'page (checked every hour and right after you save). Leave empty for no alert.',
  example: 'Minimum 24 for a drink: at 20 in the warehouse the alert opens, at 30 it closes.',
}

interface MinimumStockEditorProps {
  selected: StockBalance
}

/** Edit the warehouse minimum that drives the hourly low-stock alert.
 * Render with a key of product id + saved minimum so the box resets when either changes. */
export function MinimumStockEditor({ selected }: MinimumStockEditorProps) {
  const queryClient = useQueryClient()
  const savedText = selected.min_stock_qty === null ? '' : String(selected.min_stock_qty)
  const [minimumText, setMinimumText] = React.useState(savedText)

  const saveMutation = useMutation({
    mutationFn: (minStockQty: number | null) =>
      api.put<MinimumStock>(`/api/v1/stock/products/${selected.product_id}/minimum`, {
        min_stock_qty: minStockQty,
      }),
    onSuccess: (saved) => {
      const message =
        saved.min_stock_qty === null
          ? 'Minimum removed: no low-stock alert for this product'
          : `Minimum set to ${saved.min_stock_qty}`
      toast.success(message)
      queryClient.invalidateQueries({ queryKey: ['supply', 'stock-balances'] })
      queryClient.invalidateQueries({ queryKey: ['alerts'] })
      queryClient.invalidateQueries({ queryKey: ALERTS_COUNT_KEY })
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : 'Could not save the minimum'
      toast.error(message)
    },
  })

  const trimmedText = minimumText.trim()
  const enteredMinimum = trimmedText === '' ? null : Number(trimmedText)
  const isUnchanged = trimmedText === savedText

  return (
    <div className="flex items-center gap-2">
      <label
        htmlFor="min-stock-qty"
        className="flex items-center gap-1 whitespace-nowrap text-xs text-muted-foreground"
      >
        Warehouse minimum <InfoHint {...MINIMUM_HINT} />
      </label>
      <Input
        id="min-stock-qty"
        type="number"
        min={0}
        step={1}
        placeholder="None"
        className="h-8 w-20"
        value={minimumText}
        onChange={(event) => setMinimumText(event.target.value)}
      />
      <Button
        variant="outline"
        size="sm"
        title="Save the minimum and update the low-stock alert now"
        disabled={isUnchanged || saveMutation.isPending}
        onClick={() => saveMutation.mutate(enteredMinimum)}
      >
        {saveMutation.isPending ? 'Saving…' : 'Save'}
      </Button>
    </div>
  )
}
