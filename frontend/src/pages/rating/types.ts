/**
 * Product rating scorecard types, mirrored from the FastAPI schema
 * (GET /api/v1/rating/scorecard, app/schemas/rating.py). Rows are the stored
 * product_scores of one window, not a live computation.
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
  supplier_name: string | null
  shelf_life_days: number | null
  buying_price: string
  sold_price: string
  vat_rate: string
  /** Fraction 0..1 - null when the sell price ex-VAT is not positive. */
  profit_margin: string | null
  /** Null on scores stored before sold and review counts were kept. */
  total_sold_qty: number | null
  total_added_qty: number
  /** Fraction 0..1 - null when nothing was added in the window. */
  pct_sold: string | null
  positive_reviews: number | null
  negative_reviews: number | null
  /** Fraction 0..1 - null when the product has no reviews in the window. */
  pct_positive_review: string | null
  final_score: string
  /** True when the product sold too little and shows the average established score. */
  uses_new_product_baseline: boolean
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
  /** Null when this window has never been computed. */
  period_end: string | null
  computed_at: string | null
  weights: ScorecardWeights
}

/** POST /api/v1/forecasts/scores/recompute body (schema: ScoreRecomputeRequest). */
export interface ScoreRecomputeRequest {
  window_days: number
}

/** POST /api/v1/forecasts/scores/recompute response (schema: ScoreRecomputeResult). */
export interface ScoreRecomputeResult {
  period_end: string
  window_days: number
  products_scored: number
}
