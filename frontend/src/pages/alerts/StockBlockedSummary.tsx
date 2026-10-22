import * as React from 'react'
import { Link } from 'react-router-dom'
import { formatDateTime12Hour } from '@/lib/format'
import type { AlertDispatchRef, StockBlockedDetails } from '@/lib/types'
import { type DayName, weekDayKeySearch } from '@/pages/ops/lib/pipelineKey'

/** Offending products listed before the "Show all" toggle. */
const VISIBLE_LINE_COUNT = 3
const DISPATCH_PATH = '/dispatch'
const SHORT_DAY_NAME_LENGTH = 3

// delivery_date is a plain calendar date; formatting in UTC keeps it from shifting a day.
const DELIVERY_DAY_FORMAT = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  timeZone: 'UTC',
})

/** A blocked dispatch: link to it, one line per short product, and how often it was retried. */
export function StockBlockedSummary({ details }: { details: StockBlockedDetails }) {
  const [expanded, setExpanded] = React.useState(false)
  const hasHiddenLines = details.lines.length > VISIBLE_LINE_COUNT
  const visibleLines = expanded ? details.lines : details.lines.slice(0, VISIBLE_LINE_COUNT)

  return (
    <div className="max-w-xl space-y-1">
      {details.dispatch ? (
        <DispatchLink dispatch={details.dispatch} />
      ) : (
        <p className="text-muted-foreground">Dispatch since deleted</p>
      )}
      <ul className="text-muted-foreground">
        {visibleLines.map((line) => (
          <li key={line.product_id}>
            <span className="text-foreground">{line.product_name}</span>: need {line.requested},
            have {line.available}
          </li>
        ))}
      </ul>
      {hasHiddenLines && (
        <button
          type="button"
          className="text-xs font-medium text-primary hover:underline"
          onClick={() => setExpanded((wasExpanded) => !wasExpanded)}
        >
          {expanded ? 'Show less' : `Show all ${details.lines.length}`}
        </button>
      )}
      {details.occurrences > 1 && (
        <p className="text-xs text-muted-foreground">
          Blocked {details.occurrences} times, last {formatDateTime12Hour(details.last_raised_at)}
        </p>
      )}
    </div>
  )
}

function DispatchLink({ dispatch }: { dispatch: AlertDispatchRef }) {
  const weekDayKey = {
    year: dispatch.iso_year,
    week: dispatch.iso_week,
    // The backend always sends the canonical Monday..Sunday name.
    dayName: dispatch.day_name as DayName,
  }
  const week = String(dispatch.iso_week).padStart(2, '0')
  const shortDay = dispatch.day_name.slice(0, SHORT_DAY_NAME_LENGTH)
  const deliveryDay = DELIVERY_DAY_FORMAT.format(new Date(dispatch.delivery_date))

  return (
    <Link
      to={`${DISPATCH_PATH}${weekDayKeySearch(weekDayKey)}`}
      className="font-medium text-primary hover:underline"
    >
      Dispatch {dispatch.iso_year} W{week} {shortDay} {deliveryDay}
    </Link>
  )
}
