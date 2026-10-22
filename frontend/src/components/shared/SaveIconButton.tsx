import { Loader2, Save } from 'lucide-react'
import { Button, type ButtonProps } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export interface SaveIconButtonProps {
  /** Hover tooltip and screen-reader name, e.g. "Save menu". */
  label: string
  onClick: () => void
  disabled?: boolean
  isSaving?: boolean
  /** Replaces the tooltip, e.g. to say why saving is blocked. */
  disabledReason?: string
  variant?: ButtonProps['variant']
  className?: string
}

/** App-wide Save button: icon only, with the action spelled out in its tooltip. */
export function SaveIconButton({
  label,
  onClick,
  disabled = false,
  isSaving = false,
  disabledReason,
  variant,
  className,
}: SaveIconButtonProps) {
  const tooltip = isSaving ? 'Saving…' : (disabledReason ?? label)
  const Icon = isSaving ? Loader2 : Save

  return (
    <Button
      variant={variant}
      size="icon"
      className={cn('shrink-0', className)}
      onClick={onClick}
      disabled={disabled || isSaving}
      title={tooltip}
      aria-label={label}
    >
      <Icon className={cn('h-4 w-4', isSaving && 'animate-spin')} />
    </Button>
  )
}
