import { formatEuro, formatFraction } from '@/lib/format'
import { centsToEuros, type MenuTotals } from '@/pages/ops/menu/menuTotals'

const MARGIN_FRACTION_DIGITS = 1
const SUMMARY_BAR_CLASS = [
  'flex flex-wrap items-center gap-x-6 gap-y-1',
  'rounded-xl border border-border bg-card px-4 py-2 text-xs',
].join(' ')

export interface MenuSummaryProps {
  totals: MenuTotals
}

/** One-line value summary of the menu grid. */
export function MenuSummary({ totals }: MenuSummaryProps) {
  const marginLabel = `${formatEuro(centsToEuros(totals.marginExVatCents))} (${formatFraction(
    totals.marginFraction,
    MARGIN_FRACTION_DIGITS,
  )})`

  return (
    <div className={SUMMARY_BAR_CLASS}>
      <SummaryItem
        label="Units"
        value={String(totals.units)}
      />
      <SummaryItem
        label="Purchase value (ex VAT)"
        value={formatEuro(centsToEuros(totals.purchaseCents))}
      />
      <SummaryItem
        label="Sales value (incl VAT)"
        value={formatEuro(centsToEuros(totals.salesInclVatCents))}
      />
      <SummaryItem
        label="Sales value (ex VAT)"
        value={formatEuro(centsToEuros(totals.salesExVatCents))}
      />
      <SummaryItem
        label="Margin (ex VAT)"
        value={marginLabel}
      />
    </div>
  )
}

function SummaryItem({ label, value }: { label: string; value: string }) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-semibold tabular-nums text-foreground">{value}</span>
    </span>
  )
}
