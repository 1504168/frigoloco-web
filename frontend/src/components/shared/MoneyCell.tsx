import { cn } from '@/lib/utils'
import { formatEuro } from '@/lib/format'

export interface MoneyCellProps {
  /** Decimal string (e.g. "2.45") or number as returned by the backend. */
  value: string | number | null | undefined
  className?: string
}

/**
 * Right-aligned, tabular-nums euro amount. Use inside a `<TableCell>` for
 * money columns. Renders the empty placeholder for null/blank values.
 */
export function MoneyCell({ value, className }: MoneyCellProps) {
  return (
    <span className={cn('block text-right font-variant-numeric tabular-nums', className)}>
      {formatEuro(value)}
    </span>
  )
}
