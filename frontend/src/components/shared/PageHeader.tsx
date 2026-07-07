import { cn } from '@/lib/utils'

export interface PageHeaderProps {
  /** Small breadcrumb line above the title (e.g. "Masters / Products"). */
  breadcrumb?: string
  title: React.ReactNode
  description?: React.ReactNode
  /** Right-aligned action controls (buttons, filters). */
  actions?: React.ReactNode
  className?: string
}

/**
 * Standard page header pattern from the mockup topbar: a muted breadcrumb, an
 * h1 title, and an optional actions cluster on the right.
 */
export function PageHeader({
  breadcrumb,
  title,
  description,
  actions,
  className,
}: PageHeaderProps) {
  return (
    <div
      className={cn(
        'flex flex-wrap items-start justify-between gap-4 border-b border-border pb-4',
        className,
      )}
    >
      <div className="min-w-0">
        {breadcrumb ? (
          <div className="mb-1 text-xs text-muted-foreground">{breadcrumb}</div>
        ) : null}
        <h1 className="text-xl font-semibold tracking-tight text-foreground">{title}</h1>
        {description ? (
          <p className="mt-1 text-sm text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </div>
  )
}
