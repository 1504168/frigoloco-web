import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useSupplierOptions } from '@/hooks/useSupplierOptions'
import { cn } from '@/lib/utils'
import {
  ALL_OPTION_VALUE,
  fromSelectValue,
  toSelectValue,
} from '@/components/filters/filterValues'

export interface SupplierFilterProps {
  /** Selected supplier id; null means all suppliers. */
  value: number | null
  onChange: (supplierId: number | null) => void
  /** Limits the options to suppliers with at least one product in this category. */
  categoryId?: number | null
  className?: string
}

/**
 * "All suppliers" plus suppliers sorted naturally by name. When `categoryId`
 * changes, the caller decides whether a selected supplier that is no longer
 * listed should be cleared.
 */
export function SupplierFilter({
  value,
  onChange,
  categoryId = null,
  className,
}: SupplierFilterProps) {
  const suppliersQuery = useSupplierOptions(categoryId)
  const suppliers = suppliersQuery.data ?? []

  return (
    <Select
      value={toSelectValue(value)}
      onValueChange={(next) => onChange(fromSelectValue(next))}
    >
      <SelectTrigger
        className={cn('w-48', className)}
        aria-label="Supplier"
      >
        <SelectValue placeholder="All suppliers" />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL_OPTION_VALUE}>All suppliers</SelectItem>
        {suppliers.map((supplier) => (
          <SelectItem
            key={supplier.id}
            value={String(supplier.id)}
          >
            {supplier.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
