import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  HistoricCategoriesItem,
  TOGGLE_HISTORIC_VALUE,
  useCategoryOptions,
} from '@/components/filters/categoryOptions'

const ALL = '__all__'

export interface CategoryScopeSelectProps {
  /** null = all categories; a number scopes pull/save to that one category. */
  value: number | null
  onChange: (categoryId: number | null) => void
}

/**
 * "All categories" vs one-category scope selector for the Menu/Dispatch
 * toolbars. Mirrors the legacy Excel choice of pulling/saving a single
 * category or the whole grid at once.
 */
export function CategoryScopeSelect({ value, onChange }: CategoryScopeSelectProps) {
  const categoryOptions = useCategoryOptions(value)

  function handleValueChange(next: string) {
    if (next === TOGGLE_HISTORIC_VALUE) {
      categoryOptions.toggleShowHistoric()
      return
    }
    onChange(next === ALL ? null : Number(next))
  }

  return (
    <Select
      value={value === null ? ALL : String(value)}
      onValueChange={handleValueChange}
    >
      <SelectTrigger className="h-9 w-40">
        <SelectValue placeholder="All categories" />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL}>All categories</SelectItem>
        {categoryOptions.visibleCategories.map((category) => (
          <SelectItem key={category.id} value={String(category.id)}>
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
