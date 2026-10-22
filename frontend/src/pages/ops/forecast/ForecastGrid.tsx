import * as React from 'react'
import { ArrowDown, ArrowUp } from 'lucide-react'
import { EmptyState } from '@/components/shared/EmptyState'
import { Input } from '@/components/ui/input'
import { EMPTY_PLACEHOLDER } from '@/lib/format'
import { cn } from '@/lib/utils'
import { STICKY_GRID_BOX_CLASS, useStickyHeaderRows } from '@/pages/ops/lib/stickyHeaderRows'
import type { ForecastActualCell, ForecastActuals, ForecastRun } from '@/pages/ops/lib/types'
import { cellKey, parseQuantity, type ForecastDraft } from './forecastDraft'

const NUMBER_FMT = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 2 })
const LOW_RATIO = 0.7
const GOOD_RATIO = 0.9

const GROUP_ROW = 0
const CATEGORY_ROW = 1
const STICKY_HEADER_ROW_COUNT = 2
const HEADER_CELL_CLASS = 'sticky z-20 bg-card'
/** The fridge header also sticks sideways, so it sits above both. */
const HEADER_CORNER_CLASS = 'sticky z-30 bg-card'

const CATEGORY_HEAD_CLASS =
  'w-24 min-w-[6rem] max-w-[6rem] whitespace-normal break-words border-b border-l border-border bg-card px-2 py-2 text-center align-bottom font-semibold leading-tight text-foreground'

interface ForecastGridProps {
  run: ForecastRun
  draft: ForecastDraft
  onCellChange: (key: string, text: string) => void
  actuals: ForecastActuals | null
  fridgeName: (id: number) => string
  /** Visible category columns, in display order. */
  categoryIds: number[]
  categoryName: (id: number) => string
}

/**
 * Forecast grid: fridge rows (name, min, days-to-fill) x category columns of
 * editable quantities, then the same categories again as Added -> Sold actuals
 * so one fridge line shows its forecast and its sell-through together.
 */
export function ForecastGrid({
  run,
  draft,
  onCellChange,
  actuals,
  fridgeName,
  categoryIds,
  categoryName,
}: ForecastGridProps) {
  const { rowRef, stickyTop } = useStickyHeaderRows(STICKY_HEADER_ROW_COUNT)
  const originalQuantities = React.useMemo(() => {
    const quantities = new Map<string, number>()
    for (const result of run.results) {
      quantities.set(cellKey(result.fridge_id, result.category_id), Number(result.forecast_qty))
    }
    return quantities
  }, [run.results])

  const actualByKey = React.useMemo(() => {
    const cells = new Map<string, ForecastActualCell>()
    for (const cell of actuals?.cells ?? []) cells.set(cellKey(cell.fridge_id, cell.category_id), cell)
    return cells
  }, [actuals])

  const fridgeIds = React.useMemo(() => {
    const ids = Array.from(new Set(run.results.map((result) => result.fridge_id)))
    return ids.sort((a, b) => fridgeName(a).localeCompare(fridgeName(b)))
  }, [run.results, fridgeName])

  const fridgeConfig = run.params.fridge_config ?? {}

  if (fridgeIds.length === 0 || categoryIds.length === 0) {
    return (
      <EmptyState
        title="No forecast rows"
        description="This run produced no fridge × category results. Check that a fridge has a delivery configuration for this weekday."
      />
    )
  }

  const columnTotal = (categoryId: number) => {
    let total = 0
    for (const fridgeId of fridgeIds) {
      total += parseQuantity(draft[cellKey(fridgeId, categoryId)]) ?? 0
    }
    return total
  }

  return (
    <div className={cn(STICKY_GRID_BOX_CLASS, 'rounded-xl border border-border')}>
      <table className="min-w-full border-separate border-spacing-0 text-xs">
        <thead>
          <tr ref={rowRef(GROUP_ROW)}>
            <th
              rowSpan={2}
              className={cn(
                HEADER_CORNER_CLASS,
                'left-0 whitespace-nowrap border-b border-r border-border px-3 py-2 text-left align-bottom font-semibold text-foreground',
              )}
              style={stickyTop(GROUP_ROW)}
            >
              Fridge
            </th>
            <th
              rowSpan={2}
              className={cn(HEADER_CELL_CLASS, 'border-b border-border px-2 py-2 text-right align-bottom font-semibold text-muted-foreground')}
              style={stickyTop(GROUP_ROW)}
            >
              Min
            </th>
            <th
              rowSpan={2}
              className={cn(HEADER_CELL_CLASS, 'border-b border-border px-2 py-2 text-right align-bottom font-semibold text-muted-foreground')}
              style={stickyTop(GROUP_ROW)}
            >
              Days
            </th>
            <th
              colSpan={categoryIds.length}
              className={cn(HEADER_CELL_CLASS, 'border-b border-l-2 border-border px-3 py-1.5 text-center font-semibold text-foreground')}
              style={stickyTop(GROUP_ROW)}
            >
              Forecast (QTY)
            </th>
            <th
              colSpan={categoryIds.length}
              className={cn(HEADER_CELL_CLASS, 'border-b border-l-2 border-border px-3 py-1.5 text-center font-semibold text-foreground')}
              style={stickyTop(GROUP_ROW)}
            >
              Added → Sold Ratio
            </th>
          </tr>
          <tr ref={rowRef(CATEGORY_ROW)}>
            {categoryIds.map((categoryId, index) => (
              <th
                key={`f-${categoryId}`}
                className={cn(HEADER_CELL_CLASS, CATEGORY_HEAD_CLASS, index === 0 && 'border-l-2')}
                style={stickyTop(CATEGORY_ROW)}
              >
                {categoryName(categoryId)}
              </th>
            ))}
            {categoryIds.map((categoryId, index) => (
              <th
                key={`a-${categoryId}`}
                className={cn(HEADER_CELL_CLASS, CATEGORY_HEAD_CLASS, index === 0 && 'border-l-2')}
                style={stickyTop(CATEGORY_ROW)}
              >
                {categoryName(categoryId)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {fridgeIds.map((fridgeId) => {
            const config = fridgeConfig[String(fridgeId)]
            return (
              <tr key={fridgeId} className="hover:bg-accent/30">
                <td className="sticky left-0 z-10 whitespace-nowrap border-b border-r border-border bg-card px-3 py-1.5 font-medium text-foreground">
                  {fridgeName(fridgeId)}
                </td>
                <td className="border-b border-border px-2 py-1.5 text-right tabular-nums text-muted-foreground">
                  {config ? config.min_daily_qty : EMPTY_PLACEHOLDER}
                </td>
                <td className="border-b border-border px-2 py-1.5 text-right tabular-nums text-muted-foreground">
                  {config ? config.days_to_fill : EMPTY_PLACEHOLDER}
                </td>
                {categoryIds.map((categoryId, index) => {
                  const key = cellKey(fridgeId, categoryId)
                  return (
                    <td
                      key={`f-${categoryId}`}
                      className={cn(
                        'border-b border-l border-border px-1.5 py-1',
                        index === 0 && 'border-l-2',
                      )}
                    >
                      <QuantityInput
                        text={draft[key]}
                        originalQuantity={originalQuantities.get(key)}
                        label={`${fridgeName(fridgeId)}, ${categoryName(categoryId)}`}
                        onChange={(text) => onCellChange(key, text)}
                      />
                    </td>
                  )
                })}
                {categoryIds.map((categoryId, index) => (
                  <td
                    key={`a-${categoryId}`}
                    title="Added → Sold · ratio = sold ÷ added"
                    className={cn(
                      'border-b border-l border-border px-3 py-1.5 text-right',
                      index === 0 && 'border-l-2',
                    )}
                  >
                    {actuals !== null && (
                      <ActualsCell cell={actualByKey.get(cellKey(fridgeId, categoryId))} />
                    )}
                  </td>
                ))}
              </tr>
            )
          })}
        </tbody>
        <tfoot>
          <tr>
            <th className="sticky left-0 z-10 border-t-2 border-r border-border bg-card px-3 py-2 text-left font-semibold text-foreground">
              Total
            </th>
            <td className="border-t-2 border-border bg-card" />
            <td className="border-t-2 border-border bg-card" />
            {categoryIds.map((categoryId, index) => (
              <td
                key={`ft-${categoryId}`}
                className={cn(
                  'border-l border-t-2 border-border bg-card px-3 py-2 text-center font-semibold tabular-nums text-foreground',
                  index === 0 && 'border-l-2',
                )}
              >
                {NUMBER_FMT.format(columnTotal(categoryId))}
              </td>
            ))}
            {categoryIds.map((categoryId, index) => (
              <td
                key={`at-${categoryId}`}
                className={cn('border-l border-t-2 border-border bg-card', index === 0 && 'border-l-2')}
              />
            ))}
          </tr>
        </tfoot>
      </table>
    </div>
  )
}

interface QuantityInputProps {
  text: string
  originalQuantity: number | undefined
  label: string
  onChange: (text: string) => void
}

function QuantityInput({ text, originalQuantity, label, onChange }: QuantityInputProps) {
  const quantity = parseQuantity(text)
  const isInvalid = quantity === null
  const isEdited = !isInvalid && quantity !== originalQuantity
  return (
    <Input
      type="number"
      min={0}
      value={text}
      aria-label={label}
      aria-invalid={isInvalid}
      title={isInvalid ? 'Enter a number of 0 or more' : undefined}
      onChange={(event) => onChange(event.target.value)}
      className={cn(
        'h-7 w-20 px-1.5 text-center text-xs tabular-nums',
        isEdited && 'bg-accent font-semibold',
        isInvalid && 'border-critical',
      )}
    />
  )
}

function ActualsCell({ cell }: { cell: ForecastActualCell | undefined }) {
  const added = cell?.added_qty ?? 0
  const sold = cell?.sold_qty ?? 0
  return (
    <div className="flex items-center justify-center gap-1.5 whitespace-nowrap">
      <span className="tabular-nums text-foreground">
        {added} → {sold}
      </span>
      <RatioBadge ratio={cell?.ratio ?? null} />
    </div>
  )
}

/** Sell-through ratio as a colour-coded percentage with an up/down trend icon. */
function RatioBadge({ ratio }: { ratio: string | null }) {
  if (ratio === null) {
    return <span className="text-muted-foreground">{EMPTY_PLACEHOLDER}</span>
  }
  const value = Number(ratio)
  const Icon = value < LOW_RATIO ? ArrowDown : ArrowUp
  return (
    <span
      className={cn(
        'inline-flex items-center gap-0.5 font-medium tabular-nums',
        ratioClass(value),
      )}
    >
      <Icon className="h-3 w-3 shrink-0" />
      {Math.round(value * 100)}%
    </span>
  )
}

function ratioClass(ratio: number): string {
  if (ratio < LOW_RATIO) return 'text-critical'
  if (ratio >= GOOD_RATIO) return 'text-good-text'
  return 'text-warning'
}
