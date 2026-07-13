import * as React from 'react'
import { FileText } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { EMPTY_PLACEHOLDER, formatEuro } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { GridCategory, GridFridge } from '@/pages/ops/lib/types'

/** Per-product metadata resolved from the catalogue + score map by the parent. */
export interface ProductMeta {
  productName: string
  code: string
  purchasePrice: string
  salesPrice: string
  vatRate: string
  /** Fraction in [0,1] or null when it can't be computed. */
  marginPct: number | null
  score: string | null
  shelfLifeDays: number | null
  supplierId: number | null
  supplierName: string
}

/** Left-border accent cycled per category column group (brand series tokens). */
const CATEGORY_ACCENTS = [
  'border-l-series-1',
  'border-l-teal',
  'border-l-good',
  'border-l-warning',
  'border-l-critical',
]

/** Padding column with no product yet (an "add here" slot). */
const EMPTY_SLOT_SUPPLIER = -1
/** A real product that has no supplier linked in the catalogue. */
const UNASSIGNED_SUPPLIER = -2

interface FlatColumn {
  key: string
  productId: number | null
  categoryId: number
  supplierId: number
  supplierName: string
  isCategoryStart: boolean
}

interface CategoryBand {
  categoryId: number
  categoryName: string
  span: number
  accent: string
}

interface SupplierBand {
  key: string
  supplierId: number
  supplierName: string
  span: number
  accent: string
  isPlaceholder: boolean
}

function cellKey(fridgeId: number, productId: number): string {
  return `${fridgeId}:${productId}`
}

export interface PlanningGridProps {
  fridges: GridFridge[]
  /** Categories in display order; each carries its product_ids in column order. */
  categories: GridCategory[]
  /** Resolve a product's detail metadata; return null for unknown ids. */
  productMeta: (productId: number) => ProductMeta | null
  draft: Map<string, number>
  onCellChange: (fridgeId: number, productId: number, rawValue: string) => void
  /** Keys the operator edited this session (highlighted, saved as manual). */
  editedKeys?: Set<string>
  /** Minimum column slots rendered per category (config; more allowed). */
  columnsPerCategory: number
  /** Optional per-supplier action shown in the supplier band (Menu: Draft PO). */
  onDraftPo?: (supplierId: number) => void
  draftPoPendingSupplierId?: number | null
  /** Disable every qty cell (e.g. a dispatched, read-only key). */
  readOnly?: boolean
}

/**
 * Excel-like planning grid shared by the Menu and Dispatch pages. Products are
 * columns (grouped category → supplier), fridges are rows. The first column is
 * sticky; the whole table lives in a horizontal-scroll container so the page
 * body never scrolls sideways. Column groups pad out to the configured minimum
 * slots-per-category so operators always have empty cells to fill.
 */
export function PlanningGrid({
  fridges,
  categories,
  productMeta,
  draft,
  onCellChange,
  editedKeys,
  columnsPerCategory,
  onDraftPo,
  draftPoPendingSupplierId,
  readOnly = false,
}: PlanningGridProps) {
  const { columns, categoryBands, supplierBands } = React.useMemo(() => {
    const flat: FlatColumn[] = []
    const catBands: CategoryBand[] = []
    categories.forEach((category, categoryIndex) => {
      const accent = CATEGORY_ACCENTS[categoryIndex % CATEGORY_ACCENTS.length]
      const startIndex = flat.length
      category.product_ids.forEach((productId, productIndex) => {
        const meta = productMeta(productId)
        flat.push({
          key: `p-${productId}`,
          productId,
          categoryId: category.category_id,
          supplierId: meta?.supplierId ?? UNASSIGNED_SUPPLIER,
          supplierName: meta?.supplierId ? meta.supplierName : 'Unassigned',
          isCategoryStart: productIndex === 0,
        })
      })
      // Pad to the configured minimum with empty (add-here) slots.
      const padding = Math.max(columnsPerCategory - category.product_ids.length, 0)
      for (let slot = 0; slot < padding; slot += 1) {
        flat.push({
          key: `c${category.category_id}-slot${slot}`,
          productId: null,
          categoryId: category.category_id,
          supplierId: EMPTY_SLOT_SUPPLIER,
          supplierName: '',
          isCategoryStart: category.product_ids.length === 0 && slot === 0,
        })
      }
      catBands.push({
        categoryId: category.category_id,
        categoryName: category.category_name,
        span: flat.length - startIndex,
        accent,
      })
    })

    // Supplier bands: merge consecutive columns sharing (category, supplier).
    const supBands: SupplierBand[] = []
    let cursor = 0
    while (cursor < flat.length) {
      const current = flat[cursor]
      const accent =
        catBands.find((band) => band.categoryId === current.categoryId)?.accent ?? CATEGORY_ACCENTS[0]
      let span = 1
      while (
        cursor + span < flat.length &&
        flat[cursor + span].categoryId === current.categoryId &&
        flat[cursor + span].supplierId === current.supplierId
      ) {
        span += 1
      }
      supBands.push({
        key: `${current.categoryId}-${current.supplierId}-${cursor}`,
        supplierId: current.supplierId,
        supplierName: current.supplierName,
        span,
        accent,
        isPlaceholder: current.supplierId === EMPTY_SLOT_SUPPLIER,
      })
      cursor += span
    }

    return { columns: flat, categoryBands: catBands, supplierBands: supBands }
  }, [categories, productMeta, columnsPerCategory])

  const columnTotals = React.useMemo(() => {
    const totals = new Map<string, number>()
    for (const column of columns) {
      if (column.productId === null) continue
      let sum = 0
      for (const fridge of fridges) sum += draft.get(cellKey(fridge.fridge_id, column.productId)) ?? 0
      totals.set(column.key, sum)
    }
    return totals
  }, [columns, fridges, draft])

  const rowTotals = React.useMemo(() => {
    const totals = new Map<number, number>()
    for (const fridge of fridges) {
      let sum = 0
      for (const column of columns) {
        if (column.productId === null) continue
        sum += draft.get(cellKey(fridge.fridge_id, column.productId)) ?? 0
      }
      totals.set(fridge.fridge_id, sum)
    }
    return totals
  }, [columns, fridges, draft])

  const grandTotal = React.useMemo(
    () => Array.from(rowTotals.values()).reduce((sum, value) => sum + value, 0),
    [rowTotals],
  )

  // Sticky first column + right total column styling helpers.
  const stickyLeft =
    'sticky left-0 z-10 border-r border-border bg-card text-left align-middle'
  const detailLabel =
    'sticky left-0 z-10 border-r border-b border-border bg-card px-3 py-1 text-left text-[11px] font-medium text-muted-foreground'

  function detailRow(label: string, render: (column: FlatColumn) => React.ReactNode) {
    return (
      <tr>
        <th scope="row" className={detailLabel}>
          {label}
        </th>
        {columns.map((column) => (
          <td
            key={column.key}
            className={cn(
              'border-b border-border px-2 py-1 text-right text-[11px] tabular-nums text-muted-foreground',
              column.productId === null && 'bg-muted/20',
            )}
          >
            {column.productId === null ? '' : render(column)}
          </td>
        ))}
        <td className="sticky right-0 z-10 border-b border-l border-border bg-card" />
      </tr>
    )
  }

  const columnCount = columns.length

  return (
    <div className="overflow-x-auto overflow-y-auto rounded-xl border border-border">
      <table className="border-separate border-spacing-0 text-xs">
        <thead>
          {/* Category band */}
          <tr>
            <th className={cn(stickyLeft, 'border-b px-3 py-1.5')} />
            {categoryBands.map((band) => (
              <th
                key={`cat-${band.categoryId}`}
                colSpan={band.span}
                className={cn(
                  'border-b border-l-2 border-border px-2 py-1.5 text-left text-[11px] font-bold uppercase tracking-wide text-foreground',
                  band.accent,
                )}
              >
                {band.categoryName}
              </th>
            ))}
            <th className="sticky right-0 z-10 border-b border-l border-border bg-card px-2 py-1.5 text-[11px] font-bold uppercase text-muted-foreground">
              Total
            </th>
          </tr>
          {/* Supplier band */}
          <tr>
            <th
              scope="row"
              className={cn(stickyLeft, 'border-b px-3 py-1 text-[11px] font-medium text-muted-foreground')}
            >
              Supplier
            </th>
            {supplierBands.map((band) => (
              <th
                key={`sup-${band.key}`}
                colSpan={band.span}
                className={cn(
                  'border-b border-l-2 border-border px-2 py-1 text-left text-[11px] font-semibold text-muted-foreground',
                  band.accent,
                )}
              >
                {band.isPlaceholder ? (
                  <span className="italic text-muted-foreground/60">Add products…</span>
                ) : (
                  <span className="flex items-center justify-between gap-2">
                    <span className="truncate">{band.supplierName}</span>
                    {onDraftPo && band.supplierId > 0 ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 px-1.5 text-[10px]"
                        onClick={() => onDraftPo(band.supplierId)}
                        disabled={draftPoPendingSupplierId === band.supplierId}
                        title="Draft a purchase order for this supplier"
                      >
                        <FileText className="h-3 w-3" />
                        {draftPoPendingSupplierId === band.supplierId ? '…' : 'PO'}
                      </Button>
                    ) : null}
                  </span>
                )}
              </th>
            ))}
            <th className="sticky right-0 z-10 border-b border-l border-border bg-card" />
          </tr>
          {/* Product name */}
          <tr>
            <th scope="col" className={cn(stickyLeft, 'border-b px-3 py-2 font-semibold text-foreground')}>
              Fridge
            </th>
            {columns.map((column) => {
              const meta = column.productId === null ? null : productMeta(column.productId)
              return (
                <th
                  key={column.key}
                  className={cn(
                    'min-w-[92px] max-w-[120px] border-b border-border px-2 py-2 text-left align-bottom text-[11px] font-semibold leading-tight text-foreground',
                    column.isCategoryStart && 'border-l-2',
                    column.productId === null && 'bg-muted/20',
                  )}
                  title={meta?.productName}
                >
                  {meta?.productName ?? ''}
                </th>
              )
            })}
            <th className="sticky right-0 z-10 border-b border-l border-border bg-card px-2 py-2" />
          </tr>
          {/* Detail rows */}
          {detailRow('Code', (column) => productMeta(column.productId!)?.code ?? EMPTY_PLACEHOLDER)}
          {detailRow('Purchase', (column) => formatEuro(productMeta(column.productId!)?.purchasePrice))}
          {detailRow('Sales', (column) => formatEuro(productMeta(column.productId!)?.salesPrice))}
          {detailRow('VAT %', (column) => {
            const rate = Number(productMeta(column.productId!)?.vatRate)
            return Number.isFinite(rate) ? `${(rate * 100).toFixed(0)}%` : EMPTY_PLACEHOLDER
          })}
          {detailRow('Margin', (column) => {
            const margin = productMeta(column.productId!)?.marginPct
            return margin === null || margin === undefined ? EMPTY_PLACEHOLDER : `${(margin * 100).toFixed(0)}%`
          })}
          {detailRow('Score', (column) => {
            const score = productMeta(column.productId!)?.score
            return score ? Number(score).toFixed(2) : EMPTY_PLACEHOLDER
          })}
          {detailRow('Shelf life', (column) => {
            const days = productMeta(column.productId!)?.shelfLifeDays
            return days === null || days === undefined ? EMPTY_PLACEHOLDER : `${days}d`
          })}
          {/* Total qty per product column */}
          <tr>
            <th scope="row" className={cn(detailLabel, 'font-semibold text-foreground')}>
              Total qty
            </th>
            {columns.map((column) => (
              <td
                key={column.key}
                className={cn(
                  'border-b border-border bg-muted/30 px-2 py-1 text-right text-[11px] font-semibold tabular-nums text-foreground',
                  column.productId === null && 'bg-muted/20',
                )}
              >
                {column.productId === null ? '' : columnTotals.get(column.key) ?? 0}
              </td>
            ))}
            <td className="sticky right-0 z-10 border-b border-l border-border bg-card" />
          </tr>
        </thead>
        <tbody>
          {fridges.map((fridge) => (
            <tr key={fridge.fridge_id} className="hover:bg-accent/30">
              <th
                scope="row"
                className={cn(stickyLeft, 'border-b px-3 py-1 font-medium text-foreground')}
              >
                {fridge.friendly_name}
              </th>
              {columns.map((column) => {
                if (column.productId === null) {
                  return (
                    <td key={column.key} className="border-b border-border bg-muted/10 p-0" />
                  )
                }
                const key = cellKey(fridge.fridge_id, column.productId)
                const value = draft.get(key) ?? 0
                const isEdited = editedKeys?.has(key) ?? false
                return (
                  <td key={column.key} className="border-b border-border p-0 text-center">
                    <input
                      type="number"
                      inputMode="numeric"
                      min={0}
                      disabled={readOnly}
                      value={value === 0 ? '' : value}
                      placeholder="0"
                      aria-label={`${fridge.friendly_name} · ${
                        productMeta(column.productId)?.productName ?? column.productId
                      }`}
                      onChange={(event) =>
                        onCellChange(fridge.fridge_id, column.productId!, event.target.value)
                      }
                      className={cn(
                        'h-8 w-full min-w-[56px] bg-transparent px-1 text-center text-xs tabular-nums outline-none focus:bg-primary/10 disabled:cursor-not-allowed',
                        isEdited
                          ? 'font-bold text-series-1'
                          : value === 0
                            ? 'text-muted-foreground/40'
                            : 'text-foreground',
                      )}
                    />
                  </td>
                )
              })}
              <td className="sticky right-0 z-10 border-b border-l border-border bg-card px-3 py-1 text-right font-semibold tabular-nums text-foreground">
                {rowTotals.get(fridge.fridge_id) ?? 0}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <th
              scope="row"
              className={cn(stickyLeft, 'border-t-2 px-3 py-2 font-semibold text-foreground')}
            >
              Column total
            </th>
            {columns.map((column) => (
              <td
                key={column.key}
                className="border-t-2 border-border bg-card px-2 py-2 text-right font-semibold tabular-nums text-foreground"
              >
                {column.productId === null ? '' : columnTotals.get(column.key) ?? 0}
              </td>
            ))}
            <td className="sticky right-0 z-10 border-l border-t-2 border-border bg-card px-3 py-2 text-right font-bold tabular-nums text-foreground">
              {grandTotal}
            </td>
          </tr>
          <tr aria-hidden>
            <td colSpan={columnCount + 2} className="px-3 py-1 text-[11px] text-muted-foreground">
              {fridges.length} fridges × {columns.filter((c) => c.productId !== null).length} products ·{' '}
              grand total <span className="font-semibold text-foreground">{grandTotal}</span> units
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  )
}
