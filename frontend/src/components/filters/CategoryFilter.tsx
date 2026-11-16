import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'
import {
  ALL_OPTION_VALUE,
  fromSelectValue,
  toSelectValue,
} from '@/components/filters/filterValues'
import {
  HistoricCategoriesItem,
  TOGGLE_HISTORIC_VALUE,
  useCategoryOptions,
} from '@/components/filters/categoryOptions'

export interface CategoryFilterProps {
  /** Selected category id; null means all categories. */
  value: number | null
  onChange: (categoryId: number | null) => void
  className?: string
}

/** "All categories" plus the current categories, display_order then natural name. */
export function CategoryFilter({ value, onChange, className }: CategoryFilterProps) {
  const categoryOptions = useCategoryOptions(value)

  function handleValueChange(next: string) {
    if (next === TOGGLE_HISTORIC_VALUE) {
      categoryOptions.toggleShowHistoric()
      return
    }
    onChange(fromSelectValue(next))
  }

  return (
    <Select
      value={toSelectValue(value)}
      onValueChange={handleValueChange}
    >
      <SelectTrigger
        className={cn('w-44', className)}
        aria-label="Category"
      >
        <SelectValue placeholder="All categories" />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL_OPTION_VALUE}>All categories</SelectItem>
        {categoryOptions.visibleCategories.map((category) => (
          <SelectItem
            key={category.id}
            value={String(category.id)}
          >
            {category.name}
          </SelectItem>
        ))}
        <HistoricCategoriesItem
          historicCount={categoryOptions.historicCount}
          showHistoric={categoryOptions.showHistoric}
        />
      </SelectContent>
    </Select>
  )
}
