import * as React from 'react'
import { X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export interface ModalProps {
  open: boolean
  onClose: () => void
  title: React.ReactNode
  description?: React.ReactNode
  children?: React.ReactNode
  /** Right-aligned footer actions (buttons). */
  footer?: React.ReactNode
  className?: string
}

/**
 * Lightweight modal dialog (the ui library ships no Dialog). Closes on backdrop
 * click and Escape.
 */
export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  className,
}: ModalProps) {
  React.useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      // An open dropdown inside the modal handles Escape first and marks it handled.
      if (event.key === 'Escape' && !event.defaultPrevented) onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        className={cn(
          'max-h-[calc(100vh-2rem)] w-full max-w-md overflow-y-auto rounded-xl border border-border bg-card p-5 shadow-lg',
          className,
        )}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-3 flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h2 className="text-base font-semibold tracking-tight text-foreground">{title}</h2>
            {description ? (
              <p className="mt-1 text-sm text-muted-foreground">{description}</p>
            ) : null}
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="-mr-1 -mt-1 h-8 w-8 shrink-0"
            onClick={onClose}
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
        {children ? <div className="space-y-3">{children}</div> : null}
        {footer ? <div className="mt-5 flex justify-end gap-2">{footer}</div> : null}
      </div>
    </div>
  )
}
