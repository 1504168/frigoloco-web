/**
 * Product rating scorecard types, mirrored from the FastAPI schema
 * (GET /api/v1/rating/scorecard, verified live against http://localhost:8100).
 *
 * MONEY / RATIO CONTRACT: money fields arrive as decimal-euro strings ("8.50").
 * `profit_margin` and `pct_positive_review` are fraction strings (0..1);
 * `pct_sold` is already expressed in percent units. `final_score` is a decimal
 * string. Nulls are possible for brand, supplier, shelf life and review ratio.
 */

/** One row of the scorecard (schema: ScorecardRow). */
export interface ScorecardRow {
  product_id: number
  name: string
  code: string
  category: string
  brand: string | null
  supplier_id: number | null
  shelf_life_days: number | null
  buying_price: string
  sold_price: string
  vat_rate: string
  profit_margin: string
  total_sold_qty: number
  total_added_qty: number
  pct_sold: string
  positive_reviews: number
  negative_reviews: number
  pct_positive_review: string | null
  final_score: string
}

/** Weight blend applied to the final score (schema: ScorecardWeights). */
export interface ScorecardWeights {
  pct_sold: string
  margin: string
  review: string
}

/** GET /api/v1/rating/scorecard response (schema: ScorecardResponse). */
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
