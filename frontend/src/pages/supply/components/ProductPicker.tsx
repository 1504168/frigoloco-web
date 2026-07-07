import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Search } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { api, type Page } from '@/lib/api'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { cn } from '@/lib/utils'
import type { ProductLite } from '../types'

/**
 * Server-side product search box with a results dropdown. Emits the chosen
 * product to `onSelect`. Used by the PO line editor and the stock adjustment
 * dialog so product lookup lives in exactly one place.
 *
 * OWNED BY: the supply page-agent (local to src/pages/supply/).
 */
export interface ProductPickerProps {
  onSelect: (product: ProductLite) => void
  placeholder?: string
  /** Product ids already chosen elsewhere, greyed out to avoid duplicates. */
  disabledIds?: Set<number>
  className?: string
}

const SEARCH_LIMIT = 10

export function ProductPicker({
  onSelect,
  placeholder = 'Search product code or name…',
  disabledIds,
  className,
}: ProductPickerProps) {
  const [input, setInput] = React.useState('')
  const [open, setOpen] = React.useState(false)
  const search = useDebouncedValue(input.trim(), 300)
  const containerRef = React.useRef<HTMLDivElement>(null)

  React.useEffect(() => {
    function onClick(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  const productsQuery = useQuery({
    queryKey: ['supply', 'product-search', search],
    queryFn: ({ signal }) =>
      api.get<Page<ProductLite>>('/api/v1/products', {
        params: { search: search || undefined, limit: SEARCH_LIMIT, offset: 0 },
        signal,
      }),
    enabled: open && search.length > 0,
  })

  const items = productsQuery.data?.items ?? []

  function handleSelect(product: ProductLite) {
    onSelect(product)
    setInput('')
    setOpen(false)
  }

  return (
    <div ref={containerRef} className={cn('relative', className)}>
      <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
      <Input
        value={input}
        onChange={(event) => {
          setInput(event.target.value)
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        placeholder={placeholder}
        className="pl-8"
      />
      {open && search.length > 0 ? (
        <div className="absolute z-30 mt-1 max-h-64 w-full overflow-y-auto rounded-md border border-border bg-popover text-popover-foreground shadow-md">
          {productsQuery.isLoading ? (
            <div className="px-3 py-2 text-sm text-muted-foreground">Searching…</div>
          ) : productsQuery.isError ? (
            <div className="px-3 py-2 text-sm text-critical">Search failed. Try again.</div>
          ) : items.length === 0 ? (
            <div className="px-3 py-2 text-sm text-muted-foreground">No products found.</div>
          ) : (
            items.map((product) => {
              const disabled = disabledIds?.has(product.id) ?? false
              return (
                <button
                  key={product.id}
                  type="button"
                  disabled={disabled}
                  onClick={() => handleSelect(product)}
                  className={cn(
                    'flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-accent hover:text-accent-foreground disabled:cursor-not-allowed disabled:opacity-40',
                  )}
                >
                  <span className="min-w-0 truncate">
                    <span className="font-medium">{product.name}</span>
                    <span className="ml-2 font-mono text-xs text-muted-foreground">
                      {product.code}
                    </span>
                  </span>
                  {disabled ? (
                    <span className="text-xs text-muted-foreground">added</span>
                  ) : null}
                </button>
              )
            })
          )}
        </div>
      ) : null}
    </div>
  )
}
