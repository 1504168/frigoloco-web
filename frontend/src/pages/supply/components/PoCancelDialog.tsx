import { useMutation } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { toast } from '@/components/ui/toast'
import { useSingleSubmit } from '@/hooks/useSingleSubmit'
import { api, ApiError } from '@/lib/api'
import type { PurchaseOrder } from '../types'
import { Dialog } from './Dialog'
import { CLOSE_SHORT_LABEL } from './poLabels'

interface PoCancelDialogProps {
  po: PurchaseOrder
  /** True for a pending PO that already has received units. */
  isPartlyReceived: boolean
  onClose: () => void
  onCancelled: () => void
  onCloseShortInstead: () => void
}

export function PoCancelDialog({
  po,
  isPartlyReceived,
  onClose,
  onCancelled,
  onCloseShortInstead,
}: PoCancelDialogProps) {
  const receivedLines = po.lines.filter((line) => line.qty_received > 0)
  const receivedUnits = receivedLines.reduce((sum, line) => sum + line.qty_received, 0)

  const mutation = useMutation({
    mutationFn: () => api.post<unknown>(`/api/v1/purchase-orders/${po.id}/cancel`),
    onSuccess: () => {
      toast.success(`PO ${po.order_no} cancelled`)
      onCancelled()
    },
    onError: (error) => {
      // cancel_blocked (409): received stock already dispatched.
      const message = error instanceof ApiError ? error.message : 'Failed to cancel PO'
      toast.error(message)
      onClose()
    },
  })
  const submit = useSingleSubmit(mutation)

  return (
    <Dialog
      open
      onClose={onClose}
      title={`Cancel PO ${po.order_no}?`}
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={mutation.isPending}>
            Keep PO
          </Button>
          {isPartlyReceived ? (
            <Button variant="outline" onClick={onCloseShortInstead} disabled={mutation.isPending}>
              {CLOSE_SHORT_LABEL}
            </Button>
          ) : null}
          <Button variant="destructive" onClick={() => submit()} disabled={mutation.isPending}>
            {mutation.isPending ? 'Cancelling…' : 'Cancel PO'}
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-sm">
        {receivedLines.length === 0 ? (
          <p>Nothing has been received on this order, so warehouse stock does not change.</p>
        ) : (
          <>
            <p>
              Cancelling takes the {receivedUnits} received units back out of warehouse stock. If
              any of them were already dispatched, the cancel is refused.
            </p>
            <ul className="space-y-1">
              {receivedLines.map((line) => (
                <li
                  key={line.id}
                  className="flex justify-between rounded-md border border-border px-3 py-1.5"
                >
                  <span>{line.product_name}</span>
                  <span className="tabular-nums text-critical">-{line.qty_received}</span>
                </li>
              ))}
            </ul>
          </>
        )}
        {isPartlyReceived ? (
          <p className="rounded-md border border-border bg-muted/40 px-3 py-2">
            Keeping what arrived and not waiting for the rest? Use{' '}
            <span className="font-medium">{CLOSE_SHORT_LABEL}</span> instead: the received units
            stay in stock and the shortfall is logged.
          </p>
        ) : null}
      </div>
    </Dialog>
  )
}
