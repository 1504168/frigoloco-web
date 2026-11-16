import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { formatDateTime12Hour } from '@/lib/format'
import type { PoHistoryEvent } from '../types'
import { HISTORY_ACTION_LABELS } from './poLabels'

export function PoActivityTimeline({ poId }: { poId: number }) {
  const historyQuery = useQuery({
    // Nested under the PO's own key, so invalidating the PO refreshes its history too.
    queryKey: ['supply', 'purchase-order', poId, 'history'],
    queryFn: ({ signal }) =>
      api.get<PoHistoryEvent[]>(`/api/v1/purchase-orders/${poId}/history`, { signal }),
  })

  const events = historyQuery.data ?? []
  if (events.length === 0) return null

  return (
    <section className="space-y-2">
      <h3 className="text-sm font-medium text-foreground">Activity</h3>
      <ol className="space-y-2 border-l border-border pl-4">
        {events.map((event) => (
          <HistoryEntry key={`${event.action}-${event.at}`} event={event} />
        ))}
      </ol>
    </section>
  )
}

function HistoryEntry({ event }: { event: PoHistoryEvent }) {
  return (
    <li className="relative text-sm">
      <span className="absolute -left-[1.3rem] top-1.5 h-2 w-2 rounded-full bg-primary" />
      <div className="flex flex-wrap justify-between gap-x-3">
        <span className="font-medium">{HISTORY_ACTION_LABELS[event.action]}</span>
        <span className="text-xs text-muted-foreground">
          {formatDateTime12Hour(event.at)}
          {event.user_name ? ` - ${event.user_name}` : ''}
        </span>
      </div>
      {event.lines.length > 0 ? (
        <ul className="mt-0.5 text-xs text-muted-foreground">
          {event.lines.map((line) => (
            <li key={`${line.label}-${line.detail}`}>
              {line.label}: {line.detail}
            </li>
          ))}
        </ul>
      ) : null}
      {event.comment ? (
        <p className="mt-1 whitespace-pre-wrap text-foreground">{event.comment}</p>
      ) : null}
    </li>
  )
}
