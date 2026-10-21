import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { sortCategories } from '@/lib/naturalSort'
import { cn } from '@/lib/utils'
import { useCategories } from '@/pages/ops/lib/reference'
import {
  ALL_OPTION_VALUE,
  fromSelectValue,
  toSelectValue,
} from '@/components/filters/filterValues'

export interface CategoryFilterProps {
  /** Selected category id; null means all categories. */
  value: number | null
  onChange: (categoryId: number | null) => void
  className?: string
}

/** "All categories" plus every category, display_order then natural name. */
export function CategoryFilter({ value, onChange, className }: CategoryFilterProps) {
  const categoriesQuery = useCategories()
  const sortedCategories = sortCategories(categoriesQuery.data?.ordered ?? [])

  return (
    <Select
      value={toSelectValue(value)}
      onValueChange={(next) => onChange(fromSelectValue(next))}
    >
      <SelectTrigger
        className={cn('w-44', className)}
        aria-label="Category"
      >
        <SelectValue placeholder="All categories" />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL_OPTION_VALUE}>All categories</SelectItem>
        {sortedCategories.map((category) => (
          <SelectItem
            key={category.id}
            value={String(category.id)}
          >
            {category.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
