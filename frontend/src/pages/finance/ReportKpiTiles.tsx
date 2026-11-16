import { formatEuro, formatFraction } from '@/lib/format'
import type { FridgeReport } from '@/pages/finance/types'
import { KpiTile, type KpiTileProps } from '@/pages/finance/components'
import { formatCount, toNumber } from '@/pages/finance/utils'

/** Shown wherever the backend sends null, matching the Excel export's own wording. */
export const NOT_AVAILABLE = 'n/a'

/** The summary figures shared by the single-fridge and all-fridges reports. */
export type ReportFigures = Pick<
  FridgeReport,
  'added_qty' | 'food_cost' | 'revenue' | 'revenue_ex_vat' | 'margin' | 'margin_pct'
>

/**
 * Format the backend margin fraction (e.g. "0.6000") for display. The backend
 * sends null when there is no ex-VAT revenue to divide by: that is an undefined
 * margin, not a 0% one, so it must not be coerced to a number.
 */
export function formatMarginPct(value: string | null): string {
  if (value === null) return NOT_AVAILABLE
  return formatFraction(value, 1)
}

/** An undefined margin is neutral: only a real percentage earns good/critical. */
export function marginPctTone(value: string | null): KpiTileProps['tone'] {
  if (value === null) return 'default'
  return toNumber(value) >= 0 ? 'good' : 'critical'
}

export function signedTone(value: string): KpiTileProps['tone'] {
  return toNumber(value) >= 0 ? 'good' : 'critical'
}

/** Margin is computed on ex-VAT revenue, so ex-VAT revenue is the headline figure. */
export function ReportKpiTiles({ figures }: { figures: ReportFigures }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
      <KpiTile
        label="Added quantity"
        value={formatCount(figures.added_qty)}
        caption="Items restocked (ADDED)"
      />
      <KpiTile label="Food cost" value={formatEuro(figures.food_cost)} caption="ADDED / restock basis" />
      <KpiTile
        label="Revenue ex VAT"
        value={formatEuro(figures.revenue_ex_vat)}
        caption={`Incl. VAT ${formatEuro(figures.revenue)} ÷ 1.06`}
      />
      <KpiTile
        label="Food margin"
        value={formatEuro(figures.margin)}
        tone={signedTone(figures.margin)}
        caption="Revenue ex VAT − food cost"
      />
      <KpiTile
        label="Margin %"
        value={formatMarginPct(figures.margin_pct)}
        tone={marginPctTone(figures.margin_pct)}
        caption="Food margin / revenue ex VAT"
      />
    </div>
  )
}
