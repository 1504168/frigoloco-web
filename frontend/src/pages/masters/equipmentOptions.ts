import type { Equipment, EquipmentCategory, EquipmentOwnership } from '@/lib/types'
import { EMPTY_PLACEHOLDER, formatEuro } from '@/lib/format'

export const EQUIPMENT_CATEGORY_LABELS: Record<EquipmentCategory, string> = {
  coffee: 'Coffee machine',
  water_filter: 'Water filter',
  vending: 'Vending machine',
  fridge: 'Fridge',
  other: 'Other',
}
export const EQUIPMENT_CATEGORIES = Object.keys(EQUIPMENT_CATEGORY_LABELS) as EquipmentCategory[]

export const OWNERSHIP_LABELS: Record<EquipmentOwnership, string> = {
  bought: 'Bought',
  rent: 'Rented',
}
export const OWNERSHIPS = Object.keys(OWNERSHIP_LABELS) as EquipmentOwnership[]

const PERCENT = 100
const PERCENT_FRACTION_DIGITS = 2

/** What the machine costs us: the purchase price when bought, the monthly rent when rented. */
export function formatEquipmentCost(equipment: Equipment): string {
  if (equipment.ownership === 'rent') {
    if (equipment.monthly_rent_cost === null) return EMPTY_PLACEHOLDER
    return `${formatEuro(equipment.monthly_rent_cost)} / month`
  }
  return formatEuro(equipment.purchase_price)
}

/** "3 yrs at 4% (BNP Bank)", or the placeholder when the machine is not financed. */
export function formatFinancing(equipment: Equipment): string {
  if (equipment.financing_years === null) return EMPTY_PLACEHOLDER
  const parts = [`${equipment.financing_years} yrs`]
  if (equipment.financing_rate !== null) {
    const percent = (Number(equipment.financing_rate) * PERCENT).toFixed(PERCENT_FRACTION_DIGITS)
    parts.push(`at ${Number(percent)}%`)
  }
  if (equipment.financed_by !== null) parts.push(`(${equipment.financed_by})`)
  return parts.join(' ')
}
