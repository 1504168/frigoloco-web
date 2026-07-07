import { Toaster as SonnerToaster } from 'sonner'
import { useTheme } from '@/components/theme-provider'

/** App-wide toast surface. Re-exports sonner's `toast` for convenience. */
export function Toaster() {
  const { theme } = useTheme()
  return (
    <SonnerToaster
      theme={theme}
      position="top-right"
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

export { toast } from 'sonner'
