/** Case-insensitive "contains" match of the search text on a product code or name. */
export function matchesProductSearch(
  search: string,
  productCode: string,
  productName: string,
): boolean {
  const needle = search.toLowerCase()
  return (
    productCode.toLowerCase().includes(needle) ||
    productName.toLowerCase().includes(needle)
  )
}
