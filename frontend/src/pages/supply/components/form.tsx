import * as React from 'react'
import { ApiError } from '@/lib/api'
import { cn } from '@/lib/utils'

/**
 * Small form primitives shared by the supply CRUD dialogs. The design system
 * ships Input/Select/Switch but no Label/Textarea/Checkbox, so those live here,
 * styled to match the existing tokens.
 *
 * OWNED BY: the supply page-agent (local to src/pages/supply/).
 */

export function Label({
  className,
  ...props
}: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label
      className={cn('text-xs font-medium text-muted-foreground', className)}
      {...props}
    />
  )
}

/** A labelled field wrapper with optional inline error and hint. */
export interface FieldProps {
  label: React.ReactNode
  htmlFor?: string
  error?: string | null
  hint?: React.ReactNode
  required?: boolean
  className?: string
  children: React.ReactNode
}

export function Field({
  label,
  htmlFor,
  error,
  hint,
  required,
  className,
  children,
}: FieldProps) {
  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <Label htmlFor={htmlFor}>
        {label}
        {required ? <span className="ml-0.5 text-critical">*</span> : null}
      </Label>
      {children}
      {error ? (
        <p className="text-xs text-critical">{error}</p>
      ) : hint ? (
        <p className="text-xs text-muted-foreground">{hint}</p>
      ) : null}
    </div>
  )
}

export const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea
    ref={ref}
    className={cn(
      'flex min-h-[72px] w-full rounded-md border border-input bg-card px-3 py-2 text-sm text-foreground shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50',
      className,
    )}
    {...props}
  />
))
Textarea.displayName = 'Textarea'

export interface CheckboxProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type'> {
  label?: React.ReactNode
}

export const Checkbox = React.forwardRef<HTMLInputElement, CheckboxProps>(
  ({ className, label, id, ...props }, ref) => (
    <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-foreground">
      <input
        ref={ref}
        id={id}
        type="checkbox"
        className={cn(
          'h-4 w-4 rounded border-input text-primary accent-[var(--primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
          className,
        )}
        {...props}
      />
      {label ? <span>{label}</span> : null}
    </label>
  ),
)
Checkbox.displayName = 'Checkbox'

/** A single entry of the backend `validation_error` (422) details array. */
interface ValidationDetail {
  type?: string
  loc?: Array<string | number>
  msg?: string
}

/**
 * Extract a field -> message map from an ApiError's `validation_error` envelope.
 * The backend `loc` is like ["body", "field_name"]; we key on the last segment.
 * Non-validation errors return an empty map (the caller surfaces those as toasts).
 */
export function fieldErrorsFromApiError(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError)) return {}
  if (error.code !== 'validation_error') return {}
  const details = error.details
  if (!Array.isArray(details)) return {}
  const map: Record<string, string> = {}
  for (const raw of details as ValidationDetail[]) {
    const loc = raw.loc
    if (!Array.isArray(loc) || loc.length === 0) continue
    const key = String(loc[loc.length - 1])
    if (!(key in map)) map[key] = raw.msg ?? 'Invalid value'
  }
  return map
}

/** A non-field envelope message (used to show a general banner inside a form). */
export function generalErrorMessage(error: unknown): string | null {
  if (!(error instanceof ApiError)) {
    if (error instanceof Error) return error.message
    return null
  }
  return error.message
}
