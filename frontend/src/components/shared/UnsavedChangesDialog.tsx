import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import type { UnsavedChangesGuard } from '@/hooks/useUnsavedChangesGuard'

export interface UnsavedChangesDialogProps {
  guard: UnsavedChangesGuard
}

/** Discard-edits prompt driven by {@link useUnsavedChangesGuard}; wording comes from the guard. */
export function UnsavedChangesDialog({ guard }: UnsavedChangesDialogProps) {
  return (
    <ConfirmDialog
      open={guard.isPromptOpen}
      onClose={guard.stay}
      onConfirm={guard.leave}
      title="Unsaved changes"
      description={guard.prompt.description}
      cancelLabel={guard.prompt.cancelLabel}
      confirmLabel={guard.prompt.confirmLabel}
      destructive
    />
  )
}
