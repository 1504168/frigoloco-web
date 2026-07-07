import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

/**
 * Pill/chip used for statuses across the app. Variants mirror the mockup's
 * `.chip.*` / `.badge.*` palette (mockups/frigoloco-forecasting-app-mockup.html).
 */
const chipVariants = cva(
  'inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-bold whitespace-nowrap',
  {
    variants: {
      variant: {
        neutral: 'bg-muted-foreground/15 text-muted-foreground',
        draft: 'bg-muted-foreground/15 text-secondary-foreground',
        new: 'bg-series-1/15 text-series-1',
        info: 'bg-series-1/15 text-series-1',
        success: 'bg-good/15 text-good-text',
        warning: 'bg-warning/20 text-[#8a6100] dark:text-warning',
        critical: 'bg-critical/15 text-critical',
        verified: 'bg-teal/15 text-teal',
      },
    },
    defaultVariants: {
      variant: 'neutral',
    },
  },
)

export type ChipVariant = NonNullable<VariantProps<typeof chipVariants>['variant']>

/**
 * Map a raw backend status/severity string onto a chip variant. Unknown values
 * fall back to `neutral`. Extend here as new status vocabularies appear.
 */
const STATUS_TO_VARIANT: Record<string, ChipVariant> = {
  // generic lifecycle
  draft: 'draft',
  new: 'new',
  open: 'info',
  pending: 'warning',
  sent: 'success',
  confirmed: 'success',
  received: 'success',
  dispatched: 'success',
  done: 'success',
  active: 'success',
  acknowledged: 'neutral',
  resolved: 'success',
  partial: 'warning',
  cancelled: 'critical',
  canceled: 'critical',
  inactive: 'neutral',
  verified: 'verified',
  // severities
  info: 'info',
  warning: 'warning',
  warn: 'warning',
  critical: 'critical',
  error: 'critical',
}

export function statusToVariant(status: string): ChipVariant {
  return STATUS_TO_VARIANT[status.toLowerCase()] ?? 'neutral'
}

export interface StatusChipProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof chipVariants> {
  /** Raw status string; when provided it is auto-mapped to a variant. */
  status?: string
  /** Optional explicit label; defaults to the humanized status. */
  label?: string
}

function humanize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1).replace(/[_-]/g, ' ')
}

export function StatusChip({
  status,
  label,
  variant,
  className,
  ...props
}: StatusChipProps) {
  const resolvedVariant = variant ?? (status ? statusToVariant(status) : 'neutral')
  const text = label ?? (status ? humanize(status) : '')
  return (
    <span className={cn(chipVariants({ variant: resolvedVariant }), className)} {...props}>
      {text}
    </span>
  )
}
