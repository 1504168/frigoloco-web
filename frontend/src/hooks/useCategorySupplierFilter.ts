import * as React from 'react'
import { useSupplierOptions } from '@/hooks/useSupplierOptions'

/**
 * Category and supplier filter state where the supplier is cleared once the chosen
 * category has no products from it (the SupplierFilter would no longer list it).
 * `isSupplierSettled` is false while that check is still open, so pages can hold their
 * list query instead of fetching a category + supplier pair that has no products.
 */
export function useCategorySupplierFilter() {
  const [categoryId, setCategoryId] = React.useState<number | null>(null)
  const [supplierId, setSupplierId] = React.useState<number | null>(null)
  const suppliersInCategory = useSupplierOptions(categoryId).data
  const supplierStillListed = suppliersInCategory?.some((supplier) => supplier.id === supplierId)
  const isSupplierSettled = supplierId === null || supplierStillListed === true

  React.useEffect(() => {
    if (supplierStillListed === false) setSupplierId(null)
  }, [supplierStillListed])

  return {
    categoryId,
    supplierId,
    isSupplierSettled,
    setCategoryId,
    setSupplierId,
  }
}
