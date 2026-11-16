import * as React from 'react'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import {
  linesCutByStockFit,
  type DispatchStockCut,
  type QuantityLine,
  type StockFit,
} from '@/pages/ops/dispatch/dispatchApi'

/** A fit result together with the lines that were sent, so cuts can be shown per fridge. */
export interface StockFitPreview {
  sentLines: QuantityLine[]
  stockFit: StockFit
}

interface FridgeCut {
  fridgeId: number
  asked: number
  kept: number
}

const PREVIEW_DESCRIPTION =
  'These products are short in the warehouse. Each fridge is cut in proportion to what it ' +
  'asked. Untick a product to leave it as planned and adjust it by hand.'

interface StockFitPreviewDialogProps {
  preview: StockFitPreview
  productName: (productId: number) => string
  fridgeName: (fridgeId: number) => string
  onApply: (productIds: Set<number>) => void
  onClose: () => void
}

/** Shows who loses how many units per product; only the ticked products are cut on Apply. */
export function StockFitPreviewDialog({
  preview,
  productName,
  fridgeName,
  onApply,
  onClose,
}: StockFitPreviewDialogProps) {
  const { cuts } = preview.stockFit
  const [tickedProductIds, setTickedProductIds] = React.useState(
    () => new Set(cuts.map((stockCut) => stockCut.product_id)),
  )
  const fridgeCutsByProduct = groupFridgeCutsByProduct(preview)

  function toggleProduct(productId: number) {
    setTickedProductIds((previous) => {
      const next = new Set(previous)
      if (next.has(productId)) {
        next.delete(productId)
      } else {
        next.add(productId)
      }
      return next
    })
  }

  return (
    <ConfirmDialog
      open
      onClose={onClose}
      onConfirm={() => onApply(tickedProductIds)}
      title="Review the cuts before applying"
      description={PREVIEW_DESCRIPTION}
      confirmLabel={`Apply cuts (${tickedProductIds.size})`}
    >
      <ul className="max-h-96 space-y-2 overflow-y-auto text-sm">
        {cuts.map((stockCut) => (
          <li key={stockCut.product_id} className="rounded-md border border-border p-2">
            <label className="flex items-start gap-2">
              <input
                type="checkbox"
                checked={tickedProductIds.has(stockCut.product_id)}
                onChange={() => toggleProduct(stockCut.product_id)}
                className="mt-0.5 h-4 w-4"
              />
              <span>
                <span className="font-medium">{productName(stockCut.product_id)}</span>
                <span className="text-muted-foreground"> {describeProductCut(stockCut)}</span>
              </span>
            </label>
            <ul className="mt-1 pl-6 text-xs text-muted-foreground">
              {(fridgeCutsByProduct.get(stockCut.product_id) ?? []).map((fridgeCut) => (
                <li key={fridgeCut.fridgeId}>
                  {fridgeName(fridgeCut.fridgeId)}: {fridgeCut.asked} to {fridgeCut.kept} (
                  <span className="font-medium text-foreground">
                    -{fridgeCut.asked - fridgeCut.kept}
                  </span>
                  )
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </ConfirmDialog>
  )
}

function describeProductCut(stockCut: DispatchStockCut): string {
  const orderedPart = stockCut.on_order > 0 ? ` (${stockCut.on_order} on order)` : ''
  const available = `available ${stockCut.in_stock}${orderedPart}`
  return `asked ${stockCut.requested}, ${available}, cut ${stockCut.cut}`
}

function groupFridgeCutsByProduct({ sentLines, stockFit }: StockFitPreview) {
  const askedByLine = new Map(
    sentLines.map((line) => [`${line.fridge_id}:${line.product_id}`, line.qty]),
  )
  const fridgeCutsByProduct = new Map<number, FridgeCut[]>()
  for (const cutLine of linesCutByStockFit(sentLines, stockFit)) {
    const fridgeCuts = fridgeCutsByProduct.get(cutLine.product_id) ?? []
    fridgeCuts.push({
      fridgeId: cutLine.fridge_id,
      asked: askedByLine.get(`${cutLine.fridge_id}:${cutLine.product_id}`) ?? 0,
      kept: cutLine.qty,
    })
    fridgeCutsByProduct.set(cutLine.product_id, fridgeCuts)
  }
  return fridgeCutsByProduct
}
