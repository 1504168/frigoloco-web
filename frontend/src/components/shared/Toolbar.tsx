import * as React from 'react'
import { cn } from '@/lib/utils'

export interface ToolbarProps {
  /** Pickers and filters, aligned left. */
  left?: React.ReactNode
  /** Actions (buttons), aligned right. */
  right?: React.ReactNode
  className?: string
}

/**
 * Compact page toolbar: one row when both groups fit, otherwise the actions
 * wrap below the filters instead of overlapping them.
 * Children should use h-9 controls so both groups fit one row at 1440px.
 */
export function Toolbar({ left, right, className }: ToolbarProps) {
  return (
    <div className={cn('flex flex-wrap items-center justify-between gap-2', className)}>
      <div className="flex min-w-0 flex-wrap items-center gap-2 lg:flex-nowrap">{left}</div>
      <div className="flex shrink-0 flex-wrap items-center gap-2 lg:flex-nowrap">{right}</div>
    </div>
  )
}
