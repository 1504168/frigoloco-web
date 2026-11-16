import { AlertTriangle } from 'lucide-react'

interface MenuImportNoticeProps {
  /** One line per sales-speed change: "Fridge A Salads: sold 6 + 9.5 still expected ...". */
  speedLines: string[]
  /** One line per product a raise skipped for shelf life: "Fridge A Sushi: not raised ...". */
  shelfLifeLines: string[]
  staleStockFridgeNames: string[]
  /** Products split with their category's mean score because they have no score yet. */
  defaultScoreProductNames: string[]
  /** One line per client-rule violation: "Fridge A: Pork wrap (contains_pork)". */
  ruleViolationLines: string[]
}

/** What the last forecast import adjusted, kept on screen above the grid. */
export function MenuImportNotice({
  speedLines,
  shelfLifeLines,
  staleStockFridgeNames,
  defaultScoreProductNames,
  ruleViolationLines,
}: MenuImportNoticeProps) {
  const hasNothingToShow =
    speedLines.length === 0 &&
    shelfLifeLines.length === 0 &&
    staleStockFridgeNames.length === 0 &&
    defaultScoreProductNames.length === 0 &&
    ruleViolationLines.length === 0
  if (hasNothingToShow) return null
  return (
    <div
      role="status"
      className="flex items-start gap-2 rounded-lg border border-warning/50 bg-warning/10 px-3 py-2 text-xs text-foreground"
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="space-y-1">
        {ruleViolationLines.length > 0 && (
          <details open>
            <summary className="cursor-pointer">
              {ruleViolationLines.length} products the client excludes (check before saving)
            </summary>
            <ul className="mt-1 list-disc pl-5">
              {ruleViolationLines.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </details>
        )}
        {staleStockFridgeNames.length > 0 && (
          <p>
            Fridge stock reading older than 2 hours for {staleStockFridgeNames.join(', ')}: their
            stock cut uses the last known units.
          </p>
        )}
        {defaultScoreProductNames.length > 0 && (
          <details>
            <summary className="cursor-pointer">
              {defaultScoreProductNames.length} products on this menu have no rating yet and got
              units with their category's average score
            </summary>
            <p className="mt-1 text-muted-foreground">{defaultScoreProductNames.join(', ')}</p>
          </details>
        )}
        {speedLines.length > 0 && (
          <details>
            <summary className="cursor-pointer">
              Sales speed changed {speedLines.length} fridge categories
            </summary>
            <ul className="mt-1 list-disc pl-5">
              {speedLines.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </details>
        )}
        {shelfLifeLines.length > 0 && (
          <details>
            <summary className="cursor-pointer">
              {shelfLifeLines.length} products not raised: they would expire before the next
              delivery
            </summary>
            <ul className="mt-1 list-disc pl-5">
              {shelfLifeLines.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </div>
  )
}
