import type { ComponentProps } from 'react'
import { Moon, Sun } from 'lucide-react'
import { useTheme } from '@/components/theme-provider'
import { Button } from '@/components/ui/button'

interface ThemeToggleProps {
  variant?: ComponentProps<typeof Button>['variant']
  className?: string
}

/** Icon button that flips between light and dark themes. */
export function ThemeToggle({ variant = 'outline', className }: ThemeToggleProps) {
  const { theme, toggleTheme } = useTheme()
  const isDark = theme === 'dark'
  return (
    <Button
      variant={variant}
      size="icon"
      className={className}
      onClick={toggleTheme}
      aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
      title={isDark ? 'Light mode' : 'Dark mode'}
    >
      {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </Button>
  )
}
