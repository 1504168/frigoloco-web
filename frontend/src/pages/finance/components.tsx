import * as React from 'react'
import { cn } from '@/lib/utils'

/**
 * Small presentation primitives shared across the finance pages. Kept local to
 * the finance domain (no changes to the shared components/ library).
 */

export interface KpiTileProps {
  label: string
  /** Pre-formatted main value (money, percent, count). */
  value: React.ReactNode
  /** Small caption under the value - used for formula/basis captions. */
  caption?: React.ReactNode
  /** Highlight the value in the good/critical token, e.g. for net margin sign. */
  tone?: 'default' | 'good' | 'critical'
  /** Render as the emphasized hero tile (larger value). */
  hero?: boolean
  className?: string
}

const toneClass: Record<NonNullable<KpiTileProps['tone']>, string> = {
  default: 'text-foreground',
  good: 'text-good-text',
  critical: 'text-critical',
}

/** KPI stat tile from the mockup's `.tile` pattern. */
export function KpiTile({ label, value, caption, tone = 'default', hero, className }: KpiTileProps) {
  return (
    <div
      className={cn(
        'rounded-xl border border-border bg-card p-4 shadow-sm',
        hero && 'ring-1 ring-primary/20',
        className,
      )}
    >
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div
        className={cn(
          'mt-1 font-semibold tabular-nums',
          hero ? 'text-3xl' : 'text-2xl',
          toneClass[tone],
        )}
      >
        {value}
      </div>
      {caption ? <div className="mt-1 text-xs text-muted-foreground">{caption}</div> : null}
    </div>
  )
}

export interface SegmentTab<T extends string> {
  value: T
  label: React.ReactNode
}

export interface SegmentTabsProps<T extends string> {
  tabs: SegmentTab<T>[]
  value: T
  onChange: (value: T) => void
  className?: string
}

/** Underline tab bar mirroring the mockup's `.tabs` component. */
export function SegmentTabs<T extends string>({
  tabs,
  value,
  onChange,
  className,
}: SegmentTabsProps<T>) {
  return (
    <div className={cn('flex gap-1 border-b border-border', className)} role="tablist">
      {tabs.map((tab) => {
        const active = tab.value === value
        return (
          <button
            key={tab.value}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(tab.value)}
            className={cn(
              '-mb-px border-b-2 px-4 py-2 text-sm font-semibold transition-colors',
              active
                ? 'border-primary text-foreground'
                : 'border-transparent text-muted-foreground hover:text-foreground',
            )}
          >
            {tab.label}
          </button>
        )
      })}
    </div>
  )
}

/** A card shell matching the shared `.card` look with an optional header. */
export function SectionCard({
  title,
  description,
  actions,
  children,
  className,
}: {
  title?: React.ReactNode
  description?: React.ReactNode
  actions?: React.ReactNode
  children: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn('rounded-xl border border-border bg-card p-5 shadow-sm', className)}>
      {(title || actions) && (
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            {title ? (
              <h3 className="text-sm font-semibold tracking-tight text-foreground">{title}</h3>
            ) : null}
            {description ? (
              <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
            ) : null}
          </div>
          {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
        </div>
      )}
      {children}
    </div>
  )
}
