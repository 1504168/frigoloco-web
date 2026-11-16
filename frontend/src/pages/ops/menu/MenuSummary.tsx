import { formatEuro, formatFraction } from '@/lib/format'
import { cn } from '@/lib/utils'
import { centsToEuros, type MenuTotals } from '@/pages/ops/menu/menuTotals'

const MARGIN_FRACTION_DIGITS = 1
const PURCHASE_SEGMENT_CLASS = 'bg-[var(--baseline)] text-foreground'
const MARGIN_SEGMENT_CLASS = 'bg-primary text-primary-foreground'
const VAT_SEGMENT_CLASS = 'bg-amber-200 text-amber-950 dark:bg-amber-700 dark:text-amber-50'

export interface MenuSummaryProps {
  totals: MenuTotals
}

/**
 * Menu totals as one bar: the sales value incl VAT split into purchase cost,
 * margin and VAT, with units on the left and the sales total on the right.
 */
export function MenuSummary({ totals }: MenuSummaryProps) {
  const vatCents = totals.salesInclVatCents - totals.salesExVatCents
  const isLoss = totals.marginExVatCents < 0
  // A loss has no margin slice; the purchase slice then covers it.
  const marginSliceCents = Math.max(totals.marginExVatCents, 0)
  const barTotalCents = totals.purchaseCents + marginSliceCents + vatCents
  const marginPercent = formatFraction(totals.marginFraction, MARGIN_FRACTION_DIGITS)
  const purchaseLabel = `Purchase ${formatEuro(centsToEuros(totals.purchaseCents))}`
  const marginLabel = `Margin ${formatEuro(centsToEuros(totals.marginExVatCents))} · ${marginPercent}`
  const vatLabel = `VAT ${formatEuro(centsToEuros(vatCents))}`

  return (
    <div className="grid grid-cols-[auto_1fr_auto] items-center gap-5 rounded-xl border border-border bg-card px-4 py-2.5">
      <div className="text-xs text-muted-foreground">
        Units
        <p className="text-xl font-semibold tabular-nums text-foreground">{totals.units}</p>
      </div>

      <div className="min-w-0">
        <div className="flex h-7 overflow-hidden rounded-md bg-muted text-xs font-semibold tabular-nums">
          {barTotalCents > 0 && (
            <>
              <BarSegment
                cents={totals.purchaseCents}
                totalCents={barTotalCents}
                label={purchaseLabel}
                className={PURCHASE_SEGMENT_CLASS}
              />
              {!isLoss && (
                <BarSegment
                  cents={marginSliceCents}
                  totalCents={barTotalCents}
                  label={marginLabel}
                  className={MARGIN_SEGMENT_CLASS}
                />
              )}
              <BarSegment
                cents={vatCents}
                totalCents={barTotalCents}
                label={vatLabel}
                className={VAT_SEGMENT_CLASS}
              />
            </>
          )}
        </div>
        <div className="mt-1 flex flex-wrap gap-x-4 text-xs text-muted-foreground">
          <LegendItem
            swatchClass={PURCHASE_SEGMENT_CLASS}
            text="Purchase (ex VAT)"
          />
          <LegendItem
            swatchClass={MARGIN_SEGMENT_CLASS}
            text={isLoss ? `Loss ${marginLabel}` : 'Margin (ex VAT)'}
            textClass={isLoss ? 'font-semibold text-critical' : undefined}
          />
          <LegendItem
            swatchClass={VAT_SEGMENT_CLASS}
            text={vatLabel}
          />
        </div>
      </div>

      <div className="text-right text-xs text-muted-foreground">
        Sales incl VAT
        <p className="text-xl font-semibold tabular-nums text-foreground">
          {formatEuro(centsToEuros(totals.salesInclVatCents))}
        </p>
        <p className="tabular-nums">{formatEuro(centsToEuros(totals.salesExVatCents))} ex VAT</p>
      </div>
    </div>
  )
}

interface BarSegmentProps {
  cents: number
  totalCents: number
  label: string
  className: string
}

// Each slice grows with its value but never gets narrower than its own label.
function BarSegment({ cents, totalCents, label, className }: BarSegmentProps) {
  const shareOfBar = cents / totalCents
  return (
    <div
      className={cn('flex min-w-fit items-center justify-center whitespace-nowrap px-2.5', className)}
      style={{ flexGrow: shareOfBar, flexBasis: 0 }}
      title={label}
    >
      {label}
    </div>
  )
}

interface LegendItemProps {
  swatchClass: string
  text: string
  textClass?: string
}

function LegendItem({ swatchClass, text, textClass }: LegendItemProps) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={cn('h-2.5 w-2.5 rounded-sm', swatchClass)} />
      <span className={textClass}>{text}</span>
    </span>
  )
}
