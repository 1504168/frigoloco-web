import * as React from 'react'
import { useMutation } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { toast } from '@/components/ui/toast'
import { useSingleSubmit } from '@/hooks/useSingleSubmit'
import { api, ApiError } from '@/lib/api'
import type {
  PoCloseShortRequest,
  PoDiscrepancyReason,
  PurchaseOrder,
} from '../types'
import { Dialog } from './Dialog'
import {
  CLOSE_SHORT_LABEL,
  DISCREPANCY_REASONS,
  DISCREPANCY_REASON_LABELS,
  shortfallOf,
} from './poLabels'

/** Radix Select cannot hold an empty value, so "no reason" gets its own key. */
const NO_REASON = 'none'

const CLOSE_SHORT_EXPLANATION =
  'The order is closed with what actually arrived. The missing units no longer count as on ' +
  'order, and each shortfall below is saved in the Not received log.'

interface ShortLineNote {
  reason: PoDiscrepancyReason | typeof NO_REASON
  comment: string
}

interface PoCloseShortDialogProps {
  po: PurchaseOrder
  onClose: () => void
  onClosedShort: () => void
}

export function PoCloseShortDialog({ po, onClose, onClosedShort }: PoCloseShortDialogProps) {
  const [notes, setNotes] = React.useState<Record<number, ShortLineNote>>({})
  const shortLines = po.lines.filter((line) => shortfallOf(line) > 0)

  function noteFor(lineId: number): ShortLineNote {
    return notes[lineId] ?? { reason: NO_REASON, comment: '' }
  }

  function updateNote(lineId: number, change: Partial<ShortLineNote>) {
    setNotes((previous) => ({ ...previous, [lineId]: { ...noteFor(lineId), ...change } }))
  }

  const mutation = useMutation({
    mutationFn: () => {
      const request: PoCloseShortRequest = {
        lines: shortLines.map((line) => {
          const note = noteFor(line.id)
          return {
            po_line_id: line.id,
            reason: note.reason === NO_REASON ? null : note.reason,
            comment: note.comment.trim() || null,
          }
        }),
      }
      return api.post<PurchaseOrder>(`/api/v1/purchase-orders/${po.id}/close-short`, request)
    },
    onSuccess: () => {
      toast.success(`PO ${po.order_no} closed with the received quantities`)
      onClosedShort()
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : 'Failed to close the PO'
      toast.error(message)
    },
  })
  const submit = useSingleSubmit(mutation)

  return (
    <Dialog
      open
      onClose={onClose}
      title={`${CLOSE_SHORT_LABEL}?`}
      description={CLOSE_SHORT_EXPLANATION}
      widthClassName="max-w-3xl"
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={mutation.isPending}>
            Go back
          </Button>
          <Button onClick={() => submit()} disabled={mutation.isPending}>
            {mutation.isPending ? 'Closing…' : CLOSE_SHORT_LABEL}
          </Button>
        </>
      }
    >
      <div className="overflow-hidden rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Product</th>
              <th className="px-3 py-2 text-right font-medium">Ordered</th>
              <th className="px-3 py-2 text-right font-medium">Received</th>
              <th className="px-3 py-2 text-right font-medium">Short</th>
              <th className="px-3 py-2 text-left font-medium">Reason (optional)</th>
              <th className="px-3 py-2 text-left font-medium">Comment</th>
            </tr>
          </thead>
          <tbody>
            {shortLines.map((line) => {
              const note = noteFor(line.id)
              return (
                <tr key={line.id} className="border-t border-border">
                  <td className="px-3 py-2 font-medium">{line.product_name}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{line.qty_ordered}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{line.qty_received}</td>
                  <td className="px-3 py-2 text-right font-semibold tabular-nums text-critical">
                    {shortfallOf(line)}
                  </td>
                  <td className="px-3 py-2">
                    <Select
                      value={note.reason}
                      onValueChange={(reason) =>
                        updateNote(line.id, { reason: reason as ShortLineNote['reason'] })
                      }
                    >
                      <SelectTrigger className="h-8 w-36">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={NO_REASON}>No reason</SelectItem>
                        {DISCREPANCY_REASONS.map((reason) => (
                          <SelectItem key={reason} value={reason}>
                            {DISCREPANCY_REASON_LABELS[reason]}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </td>
                  <td className="px-3 py-2">
                    <Input
                      value={note.comment}
                      onChange={(event) => updateNote(line.id, { comment: event.target.value })}
                      placeholder="e.g. supplier out of stock"
                      className="h-8"
                    />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </Dialog>
  )
}
