import { AlertTriangle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ApiError } from '@/lib/api'
import { cn } from '@/lib/utils'

export interface ErrorStateProps {
  /** The thrown error (ApiError is unwrapped for code + message). */
  error?: unknown
  title?: string
  onRetry?: () => void
  className?: string
}

function describeError(error: unknown): { message: string; code?: string } {
  if (error instanceof ApiError) {
    return { message: error.message, code: error.code }
  }
  if (error instanceof Error) {
    return { message: error.message }
  }
  return { message: 'An unexpected error occurred.' }
}

/** Failure surface for a query/mutation, with an optional retry action. */
export function ErrorState({
  error,
  title = 'Something went wrong',
  onRetry,
  className,
}: ErrorStateProps) {
  const { message, code } = describeError(error)
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-critical/40 bg-critical/5 px-6 py-12 text-center',
        className,
      )}
    >
      <AlertTriangle className="h-8 w-8 text-critical" />
      <div className="text-sm font-semibold text-foreground">{title}</div>
      <p className="max-w-md text-sm text-muted-foreground">
        {message}
        {code ? <span className="ml-1 opacity-70">({code})</span> : null}
      </p>
      {onRetry ? (
        <Button variant="outline" size="sm" className="mt-2" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  )
}
