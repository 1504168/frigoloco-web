import * as React from 'react'
import { Search } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { cn } from '@/lib/utils'

export interface ProductSearchInputProps {
  /** Receives the trimmed search text once typing pauses. */
  onSearchChange: (search: string) => void
  initialValue?: string
  className?: string
}

/** Debounced product search box. Filter rows with `matchesProductSearch` from productSearch.ts. */
export function ProductSearchInput({
  onSearchChange,
  initialValue = '',
  className,
}: ProductSearchInputProps) {
  const [typedText, setTypedText] = React.useState(initialValue)
  const debouncedText = useDebouncedValue(typedText)
  // Report only when the debounced text changes: an inline onSearchChange from the
  // page (e.g. one that also resets pagination) must not fire on every render.
  const onSearchChangeRef = React.useRef(onSearchChange)

  React.useEffect(() => {
    onSearchChangeRef.current = onSearchChange
  }, [onSearchChange])

  React.useEffect(() => {
    onSearchChangeRef.current(debouncedText.trim())
  }, [debouncedText])

  return (
    <div className={cn('relative w-64', className)}>
      <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
      <Input
        value={typedText}
        onChange={(event) => setTypedText(event.target.value)}
        placeholder="Search product code or name"
        aria-label="Search product code or name"
        className="h-9 pl-8"
      />
    </div>
  )
}
