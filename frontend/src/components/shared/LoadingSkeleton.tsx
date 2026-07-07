import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

export interface LoadingSkeletonProps {
  /** Number of placeholder rows. */
  rows?: number
  /** Number of placeholder columns per row. */
  columns?: number
  className?: string
}

/** Table-shaped loading placeholder used while list queries are in flight. */
export function LoadingSkeleton({
  rows = 8,
  columns = 4,
  className,
}: LoadingSkeletonProps) {
  return (
    <div className={cn('space-y-2', className)} aria-busy="true" aria-live="polite">
      <Skeleton className="h-9 w-full" />
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <div key={rowIndex} className="flex gap-3">
          {Array.from({ length: columns }).map((_, colIndex) => (
            <Skeleton
              key={colIndex}
              className={cn('h-8 flex-1', colIndex === 0 && 'max-w-[40%]')}
            />
          ))}
        </div>
      ))}
    </div>
  )
}
