import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import type { UnsavedChangesGuard } from '@/hooks/useUnsavedChangesGuard'

export interface UnsavedChangesDialogProps {
  guard: UnsavedChangesGuard
}

/** Stay / Leave prompt driven by {@link useUnsavedChangesGuard}. */
export function UnsavedChangesDialog({ guard }: UnsavedChangesDialogProps) {
  return (
    <ConfirmDialog
      open={guard.isPromptOpen}
      onClose={guard.stay}
      onConfirm={guard.leave}
      title="Unsaved changes"
      description="You have unsaved changes. Leave this page and lose them?"
      cancelLabel="Stay"
      confirmLabel="Leave"
      destructive
    />
  )
}
