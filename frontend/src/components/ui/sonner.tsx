import { Toaster as SonnerToaster } from 'sonner'
import { useTheme } from '@/components/theme-provider'

const DEFAULT_TOAST_DURATION_MS = 4_000
const MAX_VISIBLE_TOASTS = 3

/** App-wide toast surface, bottom-right so it never covers the page toolbars. */
export function Toaster() {
  const { theme } = useTheme()
  return (
    <SonnerToaster
      theme={theme}
      position="bottom-right"
      duration={DEFAULT_TOAST_DURATION_MS}
      visibleToasts={MAX_VISIBLE_TOASTS}
      richColors
      closeButton
      toastOptions={{
        classNames: {
          toast:
            'group border-border bg-card text-card-foreground shadow-md rounded-lg',
        },
      }}
    />
  )
}
