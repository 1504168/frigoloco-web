import * as React from 'react'
import { EMPTY_PLACEHOLDER, formatEuro, formatFraction } from '@/lib/format'
import type { ScorecardRow, ScorecardWeights } from '@/pages/rating/types'

/** A scorecard column. `sortKey` is the backend sort field. */
export interface ScoreColumn {
  id: string
  header: string
  /** Shown as the header tooltip. */
  hint?: string
  sortKey?: string
  align?: 'left' | 'right'
  cell: (row: ScorecardRow, rank: number) => React.ReactNode
}

const NEW_PRODUCT_BASELINE_HINT =
  'Too few sales in this window: shows the average score of established products until real data builds up.'

const PCT_SOLD_HINT = '% sold = units sold / units added (restocked) in the window.'
const MARGIN_HINT = 'Margin = (sell price ex VAT - buy price) / sell price ex VAT.'
const PCT_POSITIVE_HINT =
  '% positive = positive reviews / all reviews. The score uses (positive - negative) / all reviews.'

const INTEGER_FORMATTER = new Intl.NumberFormat('nl-BE')
/** One decimal on every row so a percent column lines up. */
const PERCENT_DIGITS = 1

export function formatInteger(value: number | null): string {
  if (value === null) return EMPTY_PLACEHOLDER
  return INTEGER_FORMATTER.format(value)
}

/** Columns in display order; the Score hint names the live weights. */
export function buildScoreColumns(weights: ScorecardWeights | undefined): ScoreColumn[] {
  return [
    {
      id: 'rank',
      header: 'Rank',
      hint: 'Position in the current sort order.',
      align: 'right',
      cell: (_row, rank) => <span className="tabular-nums text-muted-foreground">{rank}</span>,
    },
    {
      id: 'code',
      header: 'Code',
      sortKey: 'code',
      cell: (row) => <span className="font-mono text-xs">{row.code}</span>,
    },
    {
      id: 'name',
      header: 'Product',
      sortKey: 'name',
      cell: (row) => <span className="font-medium">{row.name}</span>,
    },
    {
      id: 'category',
      header: 'Category',
      sortKey: 'category',
      cell: (row) => <MutedText value={row.category} />,
    },
    {
      id: 'supplier',
      header: 'Supplier',
      sortKey: 'supplier',
      cell: (row) => <MutedText value={row.supplier_name} />,
    },
    {
      id: 'shelf_life_days',
      header: 'Shelf life',
      sortKey: 'shelf_life_days',
      align: 'right',
      cell: (row) => <Numeric>{formatInteger(row.shelf_life_days)}</Numeric>,
    },
    {
      id: 'buying_price',
      header: 'Buy',
      sortKey: 'buying_price',
      align: 'right',
      cell: (row) => <Numeric>{formatEuro(row.buying_price)}</Numeric>,
    },
    {
      id: 'sold_price',
      header: 'Sell',
      sortKey: 'sold_price',
      align: 'right',
      cell: (row) => <Numeric>{formatEuro(row.sold_price)}</Numeric>,
    },
    {
      id: 'vat_rate',
      header: 'VAT',
      sortKey: 'vat_rate',
      align: 'right',
      cell: (row) => <Numeric>{formatFraction(row.vat_rate)}</Numeric>,
    },
    {
      id: 'profit_margin',
      header: 'Margin',
      hint: MARGIN_HINT,
      sortKey: 'profit_margin',
      align: 'right',
      cell: (row) => <Numeric>{formatFraction(row.profit_margin, PERCENT_DIGITS)}</Numeric>,
    },
    {
      id: 'total_sold_qty',
      header: 'Sold qty',
      sortKey: 'total_sold_qty',
      align: 'right',
      cell: (row) => <Numeric>{formatInteger(row.total_sold_qty)}</Numeric>,
    },
    {
      id: 'total_added_qty',
      header: 'Added qty',
      sortKey: 'total_added_qty',
      align: 'right',
      cell: (row) => <Numeric>{formatInteger(row.total_added_qty)}</Numeric>,
    },
    {
      id: 'pct_sold',
      header: '% sold',
      hint: PCT_SOLD_HINT,
      sortKey: 'pct_sold',
      align: 'right',
      cell: (row) => <Numeric>{formatFraction(row.pct_sold, PERCENT_DIGITS)}</Numeric>,
    },
    {
      id: 'positive_reviews',
      header: '+ reviews',
      sortKey: 'positive_reviews',
      align: 'right',
      cell: (row) => (
        <span className="tabular-nums text-good-text">{formatInteger(row.positive_reviews)}</span>
      ),
    },
    {
      id: 'negative_reviews',
      header: '- reviews',
      sortKey: 'negative_reviews',
      align: 'right',
      cell: (row) => (
        <span className="tabular-nums text-critical">{formatInteger(row.negative_reviews)}</span>
      ),
    },
    {
      id: 'pct_positive_review',
      header: '% positive',
      hint: PCT_POSITIVE_HINT,
      sortKey: 'pct_positive_review',
      align: 'right',
      cell: (row) => <Numeric>{formatFraction(row.pct_positive_review, PERCENT_DIGITS)}</Numeric>,
    },
    {
      id: 'final_score',
      header: 'Score',
      hint: buildFinalScoreHint(weights),
      sortKey: 'final_score',
      align: 'right',
      cell: (row) => <FinalScoreCell row={row} />,
    },
  ]
}

function buildFinalScoreHint(weights: ScorecardWeights | undefined): string {
  if (weights === undefined) return 'Weighted blend of % sold, margin and review score.'
  return (
    `Score = ${weights.pct_sold} x % sold + ${weights.margin} x margin` +
    ` + ${weights.review} x review, where review = (positive - negative) / all reviews.`
  )
}

function FinalScoreCell({ row }: { row: ScorecardRow }) {
  const score = Number(row.final_score).toFixed(2)
  if (!row.uses_new_product_baseline) {
    return <span className="font-semibold tabular-nums">{score}</span>
  }
  return (
    <span
      className="inline-flex items-center gap-1.5"
      title={NEW_PRODUCT_BASELINE_HINT}
    >
      <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium uppercase text-muted-foreground">
        New
      </span>
      <span className="font-semibold tabular-nums">{score}</span>
    </span>
  )
}

function MutedText({ value }: { value: string | null }) {
  return <span className="text-muted-foreground">{value ?? EMPTY_PLACEHOLDER}</span>
}

function Numeric({ children }: { children: React.ReactNode }) {
  return <span className="tabular-nums">{children}</span>
}
