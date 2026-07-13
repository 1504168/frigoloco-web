/**
 * Product rating scorecard types, mirrored from the FastAPI schema
 * (GET /api/v1/rating/scorecard, app/schemas/rating.py).
 *
 * MONEY / RATIO CONTRACT: money fields (`buying_price`, `sold_price`) arrive as
 * decimal-euro strings ("8.50"). Every ratio the backend emits is a 0..1
 * FRACTION string: `vat_rate` ("0.0600"), `profit_margin`, `pct_sold`,
 * `pct_positive_review` and the `ScorecardWeights` blend. None of them is
 * pre-multiplied into percent units. `final_score` is a plain decimal string.
 */

/** One row of the scorecard (schema: ScorecardRow). */
export interface ScorecardRow {
  product_id: number
  name: string
  code: string
  category: string | null
  brand: string | null
  supplier_id: number | null
  shelf_life_days: number | null
  buying_price: string
  sold_price: string
  vat_rate: string
  /** Fraction 0..1 - null when the sell price ex-VAT is not positive. */
  profit_margin: string | null
  total_sold_qty: number
  total_added_qty: number
  /** Fraction 0..1 - null when nothing was added in the window. */
  pct_sold: string | null
  positive_reviews: number
  negative_reviews: number
  /** Fraction 0..1 - null when the product has no reviews in the window. */
  pct_positive_review: string | null
  final_score: string
}

/** Weight blend applied to the final score (schema: ScorecardWeights). */
export interface ScorecardWeights {
  pct_sold: string
  margin: string
  review: string
}

/** GET /api/v1/rating/scorecard response (schema: ScorecardPage). */
export interface ScorecardResponse {
  items: ScorecardRow[]
  total: number
  limit: number
  offset: number
  window_days: number
  period_end: string
  weights: ScorecardWeights
}

/** POST /api/v1/forecasts/scores/recompute response (schema: ScoreRecomputeResult). */
export interface ScoreRecomputeResult {
  period_end: string
  products_scored: number
}
