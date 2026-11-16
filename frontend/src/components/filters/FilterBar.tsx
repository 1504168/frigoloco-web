import * as React from 'react'
import { cn } from '@/lib/utils'

export interface FilterBarProps {
  children: React.ReactNode
  className?: string
}

/** One row of filters that wraps only when the screen is too narrow. */
export function FilterBar({ children, className }: FilterBarProps) {
  return (
    <div className={cn('flex flex-wrap items-center gap-2 lg:flex-nowrap', className)}>
      {children}
    </div>
  )
}
