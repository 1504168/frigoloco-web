import * as React from 'react'
import { EmptyState } from '@/components/shared/EmptyState'
import { InfoHint } from '@/components/shared/InfoHint'
import { Input } from '@/components/ui/input'
import { EMPTY_PLACEHOLDER } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useFridgePreferences } from '@/pages/ops/lib/reference'
import {
  FRIDGE_PREFERENCES_HINT_CLASS,
  FRIDGE_ROW_CLASS,
  FRIDGE_ROW_STICKY_CELL_CLASS,
  STICKY_GRID_BOX_CLASS,
  useStickyHeaderRows,
} from '@/pages/ops/lib/stickyHeaderRows'
import type {
  ForecastActualCell,
  ForecastActuals,
  ForecastResult,
  ForecastRun,
  FridgeConfig,
} from '@/pages/ops/lib/types'
import { ActualsCell } from './ActualsCells'
import { cellKey, parseQuantity, type ForecastDraft } from './forecastDraft'
import { ADDED_SOLD_EXAMPLE, DAYS_TO_FILL_HINT, SOLD_IN_WINDOW_HINT } from './forecastHints'
import { perWeekDivisor, windowWeeksLabel } from './forecastWeeks'

const NUMBER_FMT = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 2 })
const WINDOW_TOTALS_DIVISOR = 1
const COMPARE_BLOCK_ID = 'c'

const GROUP_ROW = 0
const CATEGORY_ROW = 1
const STICKY_HEADER_ROW_COUNT = 2
const NO_FRIDGE_PREFERENCES = new Map<number, string>()
const HEADER_CELL_CLASS = 'sticky z-20 bg-card'
/** The fridge header also sticks sideways, so it sits above both. */
const HEADER_CORNER_CLASS = 'sticky z-30 bg-card'
const FIXED_HEAD_CLASS =
  'border-b border-border px-2 py-2 text-right align-bottom font-semibold text-muted-foreground'
const FIXED_CELL_CLASS =
  'border-b border-border px-2 py-1.5 text-right tabular-nums text-muted-foreground'
const GROUP_HEAD_CLASS =
  'border-b border-l-2 border-border px-3 py-1.5 text-center font-semibold text-foreground'

const CATEGORY_HEAD_CLASS =
  'w-24 min-w-[6rem] max-w-[6rem] whitespace-normal break-words border-b border-l border-border bg-card px-2 py-2 text-center align-bottom font-semibold leading-tight text-foreground'

/** One Added → Sold column group: the forecast window or a compare window. */
interface ActualsBlock {
  id: string
  title: string
  hint: string
  cellsByKey: Map<string, ForecastActualCell>
  divisor: number
}

interface ForecastGridProps {
  run: ForecastRun
  draft: ForecastDraft
  onCellChange: (key: string, text: string) => void
  actuals: ForecastActuals | null
  /** Actuals over the "Compare with" window, shown right after the forecast window block. */
  compareActuals: ForecastActuals | null
  compareLabel: string | null
  /** Show added/sold of windows of a week or more as an average per week instead of totals. */
  perWeekAverage: boolean
  fridgeName: (id: number) => string
  /** Visible category columns, in display order. */
  categoryIds: number[]
  categoryName: (id: number) => string
}

/**
 * Forecast grid: fridge rows (name, min, days-to-fill, sold in window) x category
 * columns of editable quantities, then the same categories again as Added -> Sold
 * actuals (and optionally a compare period) so one fridge line shows its forecast
 * and its sell-through together.
 */
export function ForecastGrid({
  run,
  draft,
  onCellChange,
  actuals,
  compareActuals,
  compareLabel,
  perWeekAverage,
  fridgeName,
  categoryIds,
  categoryName,
}: ForecastGridProps) {
  const { rowRef, stickyTop } = useStickyHeaderRows(STICKY_HEADER_ROW_COUNT)
  const fridgePreferences = useFridgePreferences().data ?? NO_FRIDGE_PREFERENCES
  const resultByKey = React.useMemo(() => {
    const results = new Map<string, ForecastResult>()
    for (const result of run.results) results.set(cellKey(result.fridge_id, result.category_id), result)
    return results
  }, [run.results])

  const soldByFridge = React.useMemo(() => {
    const sold = new Map<number, number>()
    for (const row of run.window_sales_by_fridge) sold.set(row.fridge_id, row.sold_units)
    return sold
  }, [run.window_sales_by_fridge])

  const fridgeIds = React.useMemo(() => {
    const ids = Array.from(new Set(run.results.map((result) => result.fridge_id)))
    return ids.sort((a, b) => fridgeName(a).localeCompare(fridgeName(b)))
  }, [run.results, fridgeName])

  const actualsBlocks = buildActualsBlocks(actuals, compareActuals, compareLabel, perWeekAverage)
  const compareBlock = actualsBlocks.find((block) => block.id === COMPARE_BLOCK_ID)
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
              className={cn(HEADER_CELL_CLASS, FIXED_HEAD_CLASS)}
              style={stickyTop(GROUP_ROW)}
            >
              Min
            </th>
            <th
              rowSpan={2}
              className={cn(HEADER_CELL_CLASS, FIXED_HEAD_CLASS)}
              style={stickyTop(GROUP_ROW)}
            >
              <span className="inline-flex items-center gap-1">
                Days <InfoHint {...DAYS_TO_FILL_HINT} />
              </span>
            </th>
            <th
              rowSpan={2}
              className={cn(HEADER_CELL_CLASS, FIXED_HEAD_CLASS)}
              style={stickyTop(GROUP_ROW)}
            >
              <span className="inline-flex items-center gap-1">
                Sold in window <InfoHint {...SOLD_IN_WINDOW_HINT} />
              </span>
            </th>
            <th
              colSpan={categoryIds.length}
              className={cn(HEADER_CELL_CLASS, GROUP_HEAD_CLASS)}
              style={stickyTop(GROUP_ROW)}
            >
              Forecast (QTY)
            </th>
            {actualsBlocks.map((block) => (
              <th
                key={block.id}
                colSpan={categoryIds.length}
                className={cn(HEADER_CELL_CLASS, GROUP_HEAD_CLASS)}
                style={stickyTop(GROUP_ROW)}
              >
                <span className="inline-flex items-center gap-1">
                  {block.title} <InfoHint text={block.hint} example={ADDED_SOLD_EXAMPLE} />
                </span>
              </th>
            ))}
          </tr>
          <tr ref={rowRef(CATEGORY_ROW)}>
            <CategoryHeads
              prefix="f"
              categoryIds={categoryIds}
              categoryName={categoryName}
              style={stickyTop(CATEGORY_ROW)}
            />
            {actualsBlocks.map((block) => (
              <CategoryHeads
                key={block.id}
                prefix={block.id}
                categoryIds={categoryIds}
                categoryName={categoryName}
                style={stickyTop(CATEGORY_ROW)}
              />
            ))}
          </tr>
        </thead>
        <tbody>
          {fridgeIds.map((fridgeId) => {
            const config = fridgeConfig[String(fridgeId)]
            const preferences = fridgePreferences.get(fridgeId)
            return (
              <tr key={fridgeId} className={FRIDGE_ROW_CLASS}>
                <td
                  title={preferences}
                  className={cn(
                    'sticky left-0 z-10 whitespace-nowrap border-b border-r border-border bg-card px-3 py-1.5 font-medium text-foreground',
                    FRIDGE_ROW_STICKY_CELL_CLASS,
                  )}
                >
                  <span className={cn(preferences && FRIDGE_PREFERENCES_HINT_CLASS)}>
                    {fridgeName(fridgeId)}
                  </span>
                </td>
                <td className={FIXED_CELL_CLASS}>
                  {config ? config.min_daily_qty : EMPTY_PLACEHOLDER}
                </td>
                <DaysToFillCell config={config} />
                <td className={FIXED_CELL_CLASS}>{soldByFridge.get(fridgeId) ?? 0}</td>
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
                        result={resultByKey.get(key)}
                        label={`${fridgeName(fridgeId)}, ${categoryName(categoryId)}`}
                        onChange={(text) => onCellChange(key, text)}
                      />
                      {compareBlock && compareLabel && (
                        <div className="mt-0.5 whitespace-nowrap text-center text-[10px] tabular-nums text-muted-foreground">
                          {compareLabel}: {NUMBER_FMT.format(soldInBlock(compareBlock, key))} sold
                        </div>
                      )}
                    </td>
                  )
                })}
                {actualsBlocks.map((block) =>
                  categoryIds.map((categoryId, index) => (
                    <td
                      key={`${block.id}-${categoryId}`}
                      title="Added → Sold · ratio = sold ÷ added"
                      className={cn(
                        'border-b border-l border-border px-3 py-1.5 text-right',
                        index === 0 && 'border-l-2',
                      )}
                    >
                      <ActualsCell
                        cell={block.cellsByKey.get(cellKey(fridgeId, categoryId))}
                        divisor={block.divisor}
                      />
                    </td>
                  )),
                )}
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
            <td className="border-t-2 border-border bg-card px-2 py-2 text-right font-semibold tabular-nums">
              {run.window_sales_units}
            </td>
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
            {actualsBlocks.map((block) =>
              categoryIds.map((categoryId, index) => (
                <td
                  key={`${block.id}-t-${categoryId}`}
                  className={cn('border-l border-t-2 border-border bg-card', index === 0 && 'border-l-2')}
                />
              )),
            )}
          </tr>
        </tfoot>
      </table>
    </div>
  )
}

function buildActualsBlocks(
  actuals: ForecastActuals | null,
  compareActuals: ForecastActuals | null,
  compareLabel: string | null,
  perWeekAverage: boolean,
): ActualsBlock[] {
  const blocks: ActualsBlock[] = []
  // The compare block sits right after the forecast columns so the two read side by side.
  if (compareActuals !== null && compareLabel !== null) {
    const divisor = blockDivisor(compareActuals, perWeekAverage)
    blocks.push({
      id: COMPARE_BLOCK_ID,
      title: `Compare: Added → Sold, ${compareLabel}${averageSuffix(divisor)}`,
      hint: `Units added and sold in the compare period (${compareLabel})`,
      cellsByKey: actualsByKey(compareActuals),
      divisor,
    })
  }
  if (actuals !== null) {
    const windowLabel = windowWeeksLabel(actuals.window_start, actuals.window_end)
    const divisor = blockDivisor(actuals, perWeekAverage)
    blocks.push({
      id: 'a',
      title: `Added → Sold, ${windowLabel}${averageSuffix(divisor)}`,
      hint: `Units added to and sold from each fridge in the forecast's sales window (${windowLabel})`,
      cellsByKey: actualsByKey(actuals),
      divisor,
    })
  }
  return blocks
}

/** Units sold of one cell in a block, averaged per week when the block is. */
function soldInBlock(block: ActualsBlock, key: string): number {
  return (block.cellsByKey.get(key)?.sold_qty ?? 0) / block.divisor
}

function blockDivisor(actuals: ForecastActuals, perWeekAverage: boolean): number {
  if (!perWeekAverage) return WINDOW_TOTALS_DIVISOR
  return perWeekDivisor(actuals.window_start, actuals.window_end)
}

function averageSuffix(divisor: number): string {
  return divisor === WINDOW_TOTALS_DIVISOR ? '' : ', per week average'
}

function actualsByKey(actuals: ForecastActuals): Map<string, ForecastActualCell> {
  const cells = new Map<string, ForecastActualCell>()
  for (const cell of actuals.cells) cells.set(cellKey(cell.fridge_id, cell.category_id), cell)
  return cells
}

interface CategoryHeadsProps {
  prefix: string
  categoryIds: number[]
  categoryName: (id: number) => string
  style: React.CSSProperties
}

function CategoryHeads({ prefix, categoryIds, categoryName, style }: CategoryHeadsProps) {
  return (
    <>
      {categoryIds.map((categoryId, index) => (
        <th
          key={`${prefix}-${categoryId}`}
          className={cn(HEADER_CELL_CLASS, CATEGORY_HEAD_CLASS, index === 0 && 'border-l-2')}
          style={style}
        >
          {categoryName(categoryId)}
        </th>
      ))}
    </>
  )
}

/** Selling days the delivery covers; the calendar days show in the tooltip when they differ. */
function DaysToFillCell({ config }: { config: FridgeConfig | undefined }) {
  if (config === undefined) return <td className={FIXED_CELL_CLASS}>{EMPTY_PLACEHOLDER}</td>
  // Runs computed before selling days were stored only know the calendar days.
  const sellingDays = config.selling_days_to_fill ?? config.days_to_fill
  const differs = sellingDays !== config.days_to_fill
  const hint = differs
    ? `${sellingDays} selling days (${config.days_to_fill} calendar days)`
    : `${sellingDays} days`
  return (
    <td className={cn(FIXED_CELL_CLASS, differs && 'underline decoration-dotted')} title={hint}>
      {sellingDays}
    </td>
  )
}

interface QuantityInputProps {
  text: string
  result: ForecastResult | undefined
  label: string
  onChange: (text: string) => void
}

function QuantityInput({ text, result, label, onChange }: QuantityInputProps) {
  const quantity = parseQuantity(text)
  const isInvalid = quantity === null
  const originalQuantity = result === undefined ? undefined : Number(result.forecast_qty)
  const isEdited = !isInvalid && quantity !== originalQuantity
  const hint = isInvalid ? 'Enter a number of 0 or more' : grossToNetHint(result)
  return (
    <Input
      type="number"
      min={0}
      value={text}
      aria-label={label}
      aria-invalid={isInvalid}
      title={hint}
      onChange={(event) => onChange(event.target.value)}
      className={cn(
        'h-7 w-20 px-1.5 text-center text-xs tabular-nums',
        isEdited && 'bg-accent font-semibold',
        isInvalid && 'border-critical',
      )}
    />
  )
}

/** "gross 3 - fridge stock 2 = net 1": why a cell shows less than the sales suggest. */
function grossToNetHint(result: ForecastResult | undefined): string | undefined {
  if (result === undefined || result.gross_qty === null || result.residual_units === null) {
    return undefined
  }
  const gross = NUMBER_FMT.format(Number(result.gross_qty))
  const net = NUMBER_FMT.format(Number(result.forecast_qty))
  return `Gross ${gross} - fridge stock ${result.residual_units} = net ${net}`
}
