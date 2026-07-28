import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useCategories } from '@/pages/ops/lib/reference'

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
  const categoriesQuery = useCategories()
  const ordered = categoriesQuery.data?.ordered ?? []

  return (
    <Select
      value={value === null ? ALL : String(value)}
      onValueChange={(next) => onChange(next === ALL ? null : Number(next))}
    >
      <SelectTrigger className="h-9 w-[13rem]">
        <SelectValue placeholder="All categories" />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL}>All categories</SelectItem>
        {ordered.map((category) => (
          <SelectItem key={category.id} value={String(category.id)}>
            {category.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
