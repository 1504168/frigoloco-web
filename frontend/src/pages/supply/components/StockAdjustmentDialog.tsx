import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { InfoHint, type Hint } from '@/components/shared/InfoHint'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { toast } from '@/components/ui/toast'
import { api, ApiError } from '@/lib/api'
import { cn } from '@/lib/utils'
import { STOCK_BALANCES_QUERY_KEY } from '@/pages/ops/menu/menuApi'
import type { ProductLocations, StockMovement } from '../types'
import { Dialog } from './Dialog'
import { Field, Textarea, fieldErrorsFromApiError } from './form'
import { ProductPicker } from './ProductPicker'
import { locationsQueryKey, locationsUrl } from './ProductLocationsPanel'

/** "delta" records a signed change; "counted" records counted minus current warehouse stock. */
export type AdjustmentMode = 'delta' | 'counted'

const MODE_LABELS: Record<AdjustmentMode, string> = {
  delta: 'Change by (±)',
  counted: 'Counted quantity',
}
const MODE_HINTS: Record<AdjustmentMode, Hint> = {
  delta: {
    text: 'Adds or removes units from the current warehouse stock.',
    example: '-3 for three broken bottles, 12 for a found box.',
  },
  counted: {
    text: 'Enter what you counted; the difference with the current stock is recorded.',
    example: 'Stock shows 30, you count 27: it records -3.',
  },
}
const ADJUSTMENT_MODES = Object.keys(MODE_LABELS) as AdjustmentMode[]
const WHOLE_NUMBER_PATTERN = /^-?\d+$/

export interface AdjustableProduct {
  id: number
  code: string
  name: string
}

interface StockAdjustmentDialogProps {
  /** Prefilled product (from the product detail); null lets the user pick one. */
  initialProduct: AdjustableProduct | null
  initialMode: AdjustmentMode
  onClose: () => void
  onDone: () => void
}

/** Record a warehouse stock adjustment, either as a signed change or as a counted quantity. */
export function StockAdjustmentDialog({
  initialProduct,
  initialMode,
  onClose,
  onDone,
}: StockAdjustmentDialogProps) {
  const queryClient = useQueryClient()
  const [product, setProduct] = React.useState<AdjustableProduct | null>(initialProduct)
  const [mode, setMode] = React.useState<AdjustmentMode>(initialMode)
  const [qtyInput, setQtyInput] = React.useState('')
  const [reason, setReason] = React.useState('')

  // Same cache entry as the product detail panel, so the on-hand figure is shared.
  const locationsQuery = useQuery({
    queryKey: locationsQueryKey(product?.id ?? 0),
    queryFn: ({ signal }) => api.get<ProductLocations>(locationsUrl(product!.id), { signal }),
    enabled: product !== null,
  })
  const onHandQty = locationsQuery.data?.physical_qty ?? null

  const enteredQty = WHOLE_NUMBER_PATTERN.test(qtyInput.trim()) ? Number(qtyInput) : null
  const adjustmentQty = computeAdjustmentQty(mode, enteredQty, onHandQty)

  const mutation = useMutation({
    mutationFn: () =>
      api.post<StockMovement>('/api/v1/stock/adjustments', {
        product_id: product?.id,
        qty: adjustmentQty,
        reason: reason.trim(),
      }),
    onSuccess: () => {
      toast.success('Stock adjustment recorded')
      queryClient.invalidateQueries({ queryKey: ['supply', 'stock-balances'] })
      queryClient.invalidateQueries({ queryKey: ['supply', 'stock-movements'] })
      queryClient.invalidateQueries({ queryKey: ['supply', 'product-locations'] })
      queryClient.invalidateQueries({ queryKey: STOCK_BALANCES_QUERY_KEY })
      onDone()
    },
  })

  const fieldErrors = fieldErrorsFromApiError(mutation.error)
  const businessError =
    mutation.error instanceof ApiError && mutation.error.code !== 'validation_error'
      ? mutation.error.message
      : null
  const canSubmit =
    product !== null && adjustmentQty !== null && adjustmentQty !== 0 && reason.trim() !== ''

  return (
    <Dialog
      open
      onClose={onClose}
      title="Adjust warehouse stock"
      description="Record a change, or the quantity you counted. A reason is required for the audit log."
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
        {businessError ? (
          <div className="rounded-md border border-critical/40 bg-critical/5 px-3 py-2 text-sm text-critical">
            {businessError}
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

        <div className="flex gap-1 rounded-md border border-border p-1">
          {ADJUSTMENT_MODES.map((adjustmentMode) => (
            <Button
              key={adjustmentMode}
              variant={mode === adjustmentMode ? 'default' : 'ghost'}
              size="sm"
              className="flex-1"
              onClick={() => setMode(adjustmentMode)}
            >
              {MODE_LABELS[adjustmentMode]}
              <InfoHint {...MODE_HINTS[adjustmentMode]} />
            </Button>
          ))}
        </div>

        <Field
          label={MODE_LABELS[mode]}
          required
          error={fieldErrors.qty}
          hint={
            <AdjustmentPreview
              mode={mode}
              onHandQty={onHandQty}
              adjustmentQty={adjustmentQty}
            />
          }
        >
          <Input
            inputMode="numeric"
            value={qtyInput}
            onChange={(event) => setQtyInput(event.target.value)}
            placeholder={mode === 'counted' ? 'Units counted in the warehouse' : 'e.g. 12 or -3'}
          />
        </Field>

        <Field label="Reason" required error={fieldErrors.reason}>
          <Textarea
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="Stock count, breakage, …"
          />
        </Field>
      </div>
    </Dialog>
  )
}

/** The signed movement to record, or null while the input or the on-hand figure is missing. */
function computeAdjustmentQty(
  mode: AdjustmentMode,
  enteredQty: number | null,
  onHandQty: number | null,
): number | null {
  if (enteredQty === null) return null
  if (mode === 'delta') return enteredQty
  if (onHandQty === null) return null
  return enteredQty - onHandQty
}

interface AdjustmentPreviewProps {
  mode: AdjustmentMode
  onHandQty: number | null
  adjustmentQty: number | null
}

function AdjustmentPreview({ mode, onHandQty, adjustmentQty }: AdjustmentPreviewProps) {
  const onHandText = onHandQty === null ? 'Warehouse stock loading…' : `In warehouse now: ${onHandQty}`
  if (adjustmentQty === null) return <span>{onHandText}</span>
  if (adjustmentQty === 0) {
    const sameMessage =
      mode === 'counted' ? 'Matches the current stock: nothing to record.' : 'Enter a non-zero change.'
    return <span>{`${onHandText}. ${sameMessage}`}</span>
  }
  const signedQty = adjustmentQty > 0 ? `+${adjustmentQty}` : String(adjustmentQty)
  return (
    <span>
      {onHandText}. Records{' '}
      <span className={cn('font-semibold', adjustmentQty < 0 ? 'text-critical' : 'text-good-text')}>
        {signedQty}
      </span>
    </span>
  )
}
