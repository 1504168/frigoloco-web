import * as React from 'react'
import { Download } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Toolbar } from '@/components/shared/Toolbar'
import { localIsoDate, localIsoDatePlusDays } from '@/lib/dates'
import { useCategories, useFridgeMap } from '@/pages/ops/lib/reference'
import type { ReportScope } from '@/pages/reports/types'

/** Select value meaning "no filter" (Radix Select items cannot use an empty value). */
const ALL_OPTION = 'all'

/** Scope state for a report page: today and the `days - 1` days before it, no filters. */
export function useReportScope(days: number) {
  return React.useState<ReportScope>(() => ({
    from: localIsoDatePlusDays(1 - days),
    to: localIsoDate(),
    fridgeId: null,
    categoryId: null,
  }))
}

function toOptionValue(id: number | null): string {
  if (id === null) return ALL_OPTION
  return String(id)
}

function fromOptionValue(value: string): number | null {
  if (value === ALL_OPTION) return null
  return Number(value)
}

function compareFridgeNames([, nameA]: [number, string], [, nameB]: [number, string]): number {
  return nameA.localeCompare(nameB)
}

interface ReportToolbarProps {
  scope: ReportScope
  onScopeChange: (scope: ReportScope) => void
  onExport: () => void
  isExporting: boolean
  canExport: boolean
}

/** Date range, fridge and category filters plus the Excel export button. */
export function ReportToolbar({
  scope,
  onScopeChange,
  onExport,
  isExporting,
  canExport,
}: ReportToolbarProps) {
  const fridgeMapQuery = useFridgeMap()
  const categoriesQuery = useCategories()

  const fridgeNamesById = fridgeMapQuery.data ?? new Map<number, string>()
  const fridgeOptions = [...fridgeNamesById.entries()].sort(compareFridgeNames)
  const categoryOptions = categoriesQuery.data?.ordered ?? []

  const updateScope = (changes: Partial<ReportScope>) => onScopeChange({ ...scope, ...changes })

  return (
    <Toolbar
      left={
        <>
          <Input
            type="date"
            aria-label="From"
            value={scope.from}
            onChange={(event) => updateScope({ from: event.target.value })}
            className="h-9 w-40"
          />
          <Input
            type="date"
            aria-label="To"
            value={scope.to}
            onChange={(event) => updateScope({ to: event.target.value })}
            className="h-9 w-40"
          />
          <Select
            value={toOptionValue(scope.fridgeId)}
            onValueChange={(value) => updateScope({ fridgeId: fromOptionValue(value) })}
          >
            <SelectTrigger className="h-9 w-56" aria-label="Fridge">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="max-h-72">
              <SelectItem value={ALL_OPTION}>All fridges</SelectItem>
              {fridgeOptions.map(([fridgeId, fridgeName]) => (
                <SelectItem key={fridgeId} value={String(fridgeId)}>
                  {fridgeName}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select
            value={toOptionValue(scope.categoryId)}
            onValueChange={(value) => updateScope({ categoryId: fromOptionValue(value) })}
          >
            <SelectTrigger className="h-9 w-48" aria-label="Category">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="max-h-72">
              <SelectItem value={ALL_OPTION}>All categories</SelectItem>
              {categoryOptions.map((category) => (
                <SelectItem key={category.id} value={String(category.id)}>
                  {category.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </>
      }
      right={
        <Button variant="outline" className="h-9" disabled={!canExport || isExporting} onClick={onExport}>
          <Download className="h-4 w-4" />
          {isExporting ? 'Exporting...' : 'Export to Excel'}
        </Button>
      }
    />
  )
}
