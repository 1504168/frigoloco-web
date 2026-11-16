import type { Hint } from '@/components/shared/InfoHint'
import { ImportOptionSwitch } from '@/pages/ops/menu/ImportOptionSwitch'

const SOLD_FIRST_HINT: Hint = {
  text:
    "Refills products sold since each fridge's last delivery first, then splits the rest by " +
    'rating. A product with no rating yet keeps its normal share.',
  example: 'Forecast 15, product B sold 11: B gets 11, the other 4 are split by rating.',
}
const FRIDGE_STOCK_HINT: Hint = {
  text:
    'Gives each product only what it needs beyond its units still good in the fridge until ' +
    'the next delivery (next delivery only). A well-stocked product can get 0.',
  example: 'Share 6, 3 good units in the fridge: it gets 3.',
}
const SALES_SPEED_HINT: Hint = {
  text:
    'Scales each fridge category by how fast it sells: (sold since the last delivery + what ' +
    "its hourly sales profile still expects before the next delivery) / that delivery's " +
    'forecast. Between 50% and 200%; a raise skips products that would expire first.',
  example:
    '12 cookies forecast Monday, 6 sold by Tuesday noon, 6 more expected in the evening: ' +
    '12 / 12 = 100%, no change.',
}
const FIT_TO_STOCK_HINT: Hint = {
  text:
    'Cuts each product to the warehouse stock in hand (units on order are not counted), in ' +
    'proportion to what each fridge gets. Cut units stay unallocated.',
  example: '30 units planned over 3 fridges, 15 in the warehouse: each fridge gets half.',
}

export interface MenuImportChoices {
  soldFirst: boolean
  useFridgeStock: boolean
  salesSpeed: boolean
  fitToStock: boolean
}

interface MenuImportOptionsProps {
  choices: MenuImportChoices
  onSoldFirstChange: (checked: boolean) => void
  onUseFridgeStockChange: (checked: boolean) => void
  onSalesSpeedChange: (checked: boolean) => void
  onFitToStockChange: (checked: boolean) => void
}

/** The toolbar switches that change how Import from Forecast computes quantities. */
export function MenuImportOptions({
  choices,
  onSoldFirstChange,
  onUseFridgeStockChange,
  onSalesSpeedChange,
  onFitToStockChange,
}: MenuImportOptionsProps) {
  return (
    <>
      <ImportOptionSwitch
        id="menu-sold-first"
        label="Sold first"
        hint={SOLD_FIRST_HINT}
        checked={choices.soldFirst}
        onCheckedChange={onSoldFirstChange}
      />
      <ImportOptionSwitch
        id="menu-use-fridge-stock"
        label="Use fridge stock"
        hint={FRIDGE_STOCK_HINT}
        checked={choices.useFridgeStock}
        onCheckedChange={onUseFridgeStockChange}
      />
      <ImportOptionSwitch
        id="menu-sales-speed"
        label="Sales speed"
        hint={SALES_SPEED_HINT}
        checked={choices.salesSpeed}
        onCheckedChange={onSalesSpeedChange}
      />
      <ImportOptionSwitch
        id="menu-fit-to-stock"
        label="Fit to stock"
        hint={FIT_TO_STOCK_HINT}
        checked={choices.fitToStock}
        onCheckedChange={onFitToStockChange}
      />
    </>
  )
}
