import * as React from 'react'
import { SelectItem } from '@/components/ui/select'
import { sortCategories } from '@/lib/naturalSort'
import { useCategories } from '@/pages/ops/lib/reference'

/** Select value of the item that shows or hides historic categories; never a category id. */
export const TOGGLE_HISTORIC_VALUE = '__toggle_historic__'

/**
 * Categories for a category select: historic ones (no active product left) are
 * hidden until the user asks for them, but the selected category always stays visible.
 */
export function useCategoryOptions(selectedCategoryId: number | null) {
  const categoriesQuery = useCategories()
  const [showHistoric, setShowHistoric] = React.useState(false)

  const sortedCategories = sortCategories(categoriesQuery.data?.ordered ?? [])
  const historicCount = sortedCategories.filter((category) => !category.has_active_products).length
  const visibleCategories = sortedCategories.filter(
    (category) =>
      showHistoric || category.has_active_products || category.id === selectedCategoryId,
  )

  return {
    visibleCategories,
    historicCount,
    showHistoric,
    toggleShowHistoric: () => setShowHistoric((shown) => !shown),
  }
}

interface HistoricCategoriesItemProps {
  historicCount: number
  showHistoric: boolean
}

/** Last select item: picking it shows or hides the historic categories. */
export function HistoricCategoriesItem({ historicCount, showHistoric }: HistoricCategoriesItemProps) {
  if (historicCount === 0) return null
  const label = showHistoric ? 'Hide historic categories' : 'Show historic categories'
  return (
    <SelectItem
      value={TOGGLE_HISTORIC_VALUE}
      className="text-xs text-muted-foreground"
    >
      {label} ({historicCount})
    </SelectItem>
  )
}
