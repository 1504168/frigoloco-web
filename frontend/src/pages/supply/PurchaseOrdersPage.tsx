import * as React from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Search, Trash2 } from 'lucide-react'
import { PageHeader } from '@/components/shared/PageHeader'
import { DataTable, type DataTableColumn } from '@/components/shared/DataTable'
import { EmptyState } from '@/components/shared/EmptyState'
import { StatusChip } from '@/components/shared/StatusChip'
import { MoneyCell } from '@/components/shared/MoneyCell'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { toast } from '@/components/ui/sonner'
import { api, ApiError, type Page } from '@/lib/api'
import { formatEuro } from '@/lib/format'
import { cn } from '@/lib/utils'
import { Dialog } from './components/Dialog'
import { Field, Textarea, fieldErrorsFromApiError, generalErrorMessage } from './components/form'
import { ProductPicker } from './components/ProductPicker'
import type {
  OverReceiptDetail,
  PoLineCreate,
  PoStatus,
  ProductLite,
  PurchaseOrder,
  PurchaseOrderCreate,
  Supplier,
} from './types'

const PAGE_SIZE = 25

type StatusFilter = 'all' | PoStatus

/** Local, editable representation of a PO line while composing a new order. */
interface DraftLine {
  product: ProductLite
  qty: string
  /** Unit price in euros, as a string for controlled input. */
  unitPrice: string
  /** VAT as a percentage (e.g. "6"), converted to a fraction on submit. */
  vatPercent: string
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

function isoPlusDays(days: number): string {
  const date = new Date()
  date.setDate(date.getDate() + days)
  return date.toISOString().slice(0, 10)
}

/** Compute ex-VAT / VAT / incl totals for a set of draft lines. */
function computeTotals(lines: DraftLine[]) {
  let ex = 0
  let vat = 0
  for (const line of lines) {
    const qty = Number(line.qty) || 0
    const price = Number(line.unitPrice) || 0
    const rate = (Number(line.vatPercent) || 0) / 100
    const lineEx = qty * price
    ex += lineEx
    vat += lineEx * rate
  }
  return { ex, vat, incl: ex + vat }
}

/** Shared suppliers lookup (id -> name) for the list column and create select. */
function useSuppliers() {
  return useQuery({
    queryKey: ['supply', 'suppliers', 'all'],
    queryFn: ({ signal }) =>
      api.get<Page<Supplier>>('/api/v1/suppliers', { params: { limit: 200, offset: 0 }, signal }),
    staleTime: 60_000,
    select: (page) => page.items,
  })
}

export function PurchaseOrdersPage() {
  const [statusFilter, setStatusFilter] = React.useState<StatusFilter>('all')
  const [supplierFilter, setSupplierFilter] = React.useState<string>('all')
  const [searchInput, setSearchInput] = React.useState('')
  const [offset, setOffset] = React.useState(0)
  const [creating, setCreating] = React.useState(false)
  const [detailId, setDetailId] = React.useState<number | null>(null)

  const suppliersQuery = useSuppliers()
  const supplierName = React.useCallback(
    (id: number) => suppliersQuery.data?.find((s) => s.id === id)?.name ?? `#${id}`,
    [suppliersQuery.data],
  )

  React.useEffect(() => {
    setOffset(0)
  }, [statusFilter, supplierFilter])

  const posQuery = useQuery({
    queryKey: ['supply', 'purchase-orders', { statusFilter, supplierFilter, offset }],
    queryFn: ({ signal }) =>
      api.get<Page<PurchaseOrder>>('/api/v1/purchase-orders', {
        params: {
          status: statusFilter === 'all' ? undefined : statusFilter,
          supplier_id: supplierFilter === 'all' ? undefined : Number(supplierFilter),
          limit: PAGE_SIZE,
          offset,
        },
        signal,
      }),
    placeholderData: keepPreviousData,
  })

  // order_no / supplier search is client-side: the API exposes no text filter for POs.
  const pageForTable = React.useMemo<Page<PurchaseOrder> | undefined>(() => {
    if (!posQuery.data) return undefined
    const term = searchInput.trim().toLowerCase()
    if (!term) return posQuery.data
    const items = posQuery.data.items.filter(
      (po) =>
        po.order_no.toLowerCase().includes(term) ||
        supplierName(po.supplier_id).toLowerCase().includes(term),
    )
    return { ...posQuery.data, items }
  }, [posQuery.data, searchInput, supplierName])

  const columns = React.useMemo<DataTableColumn<PurchaseOrder>[]>(
    () => [
      {
        id: 'order_no',
        header: 'Order no',
        cell: (row) => <span className="font-mono text-xs">{row.order_no}</span>,
        sortValue: (row) => row.order_no,
      },
      {
        id: 'supplier',
        header: 'Supplier',
        cell: (row) => <span className="font-medium">{supplierName(row.supplier_id)}</span>,
        sortValue: (row) => supplierName(row.supplier_id),
      },
      {
        id: 'order_date',
        header: 'Order date',
        cell: (row) => <span className="text-muted-foreground">{row.order_date}</span>,
        sortValue: (row) => row.order_date,
      },
      {
        id: 'expected',
        header: 'Expected delivery',
        cell: (row) => <span className="text-muted-foreground">{row.expected_delivery_date}</span>,
        sortValue: (row) => row.expected_delivery_date,
      },
      {
        id: 'total',
        header: 'Total incl. VAT',
        align: 'right',
        cell: (row) => <MoneyCell value={row.total_incl_vat} />,
        sortValue: (row) => Number(row.total_incl_vat),
      },
      {
        id: 'status',
        header: 'Status',
        cell: (row) => <StatusChip status={row.status} />,
        sortValue: (row) => row.status,
      },
    ],
    [supplierName],
  )

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumb="Operations / Purchase Orders"
        title="Purchase Orders"
        description="Supplier POs: raise, receive stock, and cancel with reversal."
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus className="h-4 w-4" /> New PO
          </Button>
        }
      />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Select value={statusFilter} onValueChange={(value) => setStatusFilter(value as StatusFilter)}>
            <SelectTrigger className="w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              <SelectItem value="pending">Pending</SelectItem>
              <SelectItem value="received">Received</SelectItem>
              <SelectItem value="cancelled">Cancelled</SelectItem>
            </SelectContent>
          </Select>
          <Select value={supplierFilter} onValueChange={setSupplierFilter}>
            <SelectTrigger className="w-52">
              <SelectValue placeholder="All suppliers" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All suppliers</SelectItem>
              {(suppliersQuery.data ?? []).map((supplier) => (
                <SelectItem key={supplier.id} value={String(supplier.id)}>
                  {supplier.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            placeholder="Search order no / supplier…"
            className="w-64 pl-8"
          />
        </div>
      </div>

      <DataTable
        columns={columns}
        page={pageForTable}
        isLoading={posQuery.isLoading}
        isError={posQuery.isError}
        error={posQuery.error}
        onRetry={() => posQuery.refetch()}
        limit={PAGE_SIZE}
        offset={offset}
        onOffsetChange={setOffset}
        getRowId={(row) => row.id}
        onRowClick={(row) => setDetailId(row.id)}
        emptyState={
          <EmptyState
            title="No purchase orders"
            description={
              searchInput.trim()
                ? 'No POs match your search.'
                : 'Raise your first purchase order to order stock from a supplier.'
            }
            action={
              <Button onClick={() => setCreating(true)}>
                <Plus className="h-4 w-4" /> New PO
              </Button>
            }
          />
        }
      />

      {creating ? (
        <CreatePoDialog
          suppliers={suppliersQuery.data ?? []}
          onClose={() => setCreating(false)}
          onCreated={(po) => {
            setCreating(false)
            posQuery.refetch()
            setDetailId(po.id)
          }}
        />
      ) : null}

      {detailId !== null ? (
        <PoDetailDialog
          poId={detailId}
          supplierName={supplierName}
          onClose={() => setDetailId(null)}
        />
      ) : null}
    </div>
  )
}

// ─────────────────────────── Create PO ───────────────────────────

interface CreatePoDialogProps {
  suppliers: Supplier[]
  onClose: () => void
  onCreated: (po: PurchaseOrder) => void
}

function CreatePoDialog({ suppliers, onClose, onCreated }: CreatePoDialogProps) {
  const queryClient = useQueryClient()
  const [supplierId, setSupplierId] = React.useState('')
  const [orderDate, setOrderDate] = React.useState(todayIso())
  const [expectedDate, setExpectedDate] = React.useState(isoPlusDays(2))
  const [deliveryAddress, setDeliveryAddress] = React.useState('')
  const [comment, setComment] = React.useState('')
  const [lines, setLines] = React.useState<DraftLine[]>([])

  const chosenIds = React.useMemo(() => new Set(lines.map((line) => line.product.id)), [lines])
  const totals = React.useMemo(() => computeTotals(lines), [lines])

  const mutation = useMutation({
    mutationFn: () => {
      const payloadLines: PoLineCreate[] = lines.map((line) => ({
        product_id: line.product.id,
        qty: Number(line.qty) || 0,
        unit_price: Number(line.unitPrice) || 0,
        vat_rate: (Number(line.vatPercent) || 0) / 100,
      }))
      const body: PurchaseOrderCreate = {
        supplier_id: Number(supplierId),
        order_date: orderDate,
        expected_delivery_date: expectedDate,
        delivery_address: deliveryAddress.trim() || null,
        comment: comment.trim() || null,
        lines: payloadLines,
      }
      return api.post<PurchaseOrder>('/api/v1/purchase-orders', body)
    },
    onSuccess: (po) => {
      toast.success(`PO ${po.order_no} created`)
      queryClient.invalidateQueries({ queryKey: ['supply', 'purchase-orders'] })
      onCreated(po)
    },
  })

  const fieldErrors = fieldErrorsFromApiError(mutation.error)
  const generalError =
    mutation.error && Object.keys(fieldErrors).length === 0
      ? generalErrorMessage(mutation.error)
      : null

  function addProduct(product: ProductLite) {
    const vatPercent = ((Number(product.vat_rate) || 0) * 100).toString()
    setLines((prev) => [
      ...prev,
      { product, qty: '1', unitPrice: product.purchase_price ?? '0', vatPercent },
    ])
  }

  function updateLine(productId: number, patch: Partial<DraftLine>) {
    setLines((prev) =>
      prev.map((line) => (line.product.id === productId ? { ...line, ...patch } : line)),
    )
  }

  function removeLine(productId: number) {
    setLines((prev) => prev.filter((line) => line.product.id !== productId))
  }

  const hasValidLines =
    lines.length > 0 && lines.every((line) => Number(line.qty) > 0 && Number(line.unitPrice) >= 0)
  const canSubmit = supplierId !== '' && orderDate !== '' && expectedDate !== '' && hasValidLines

  return (
    <Dialog
      open
      onClose={onClose}
      title="New purchase order"
      description="Pick a supplier, add product lines, and totals compute live."
      widthClassName="max-w-3xl"
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button onClick={() => mutation.mutate()} disabled={mutation.isPending || !canSubmit}>
            {mutation.isPending ? 'Creating…' : 'Create PO'}
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        {generalError ? (
          <div className="rounded-md border border-critical/40 bg-critical/5 px-3 py-2 text-sm text-critical">
            {generalError}
          </div>
        ) : null}

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Field label="Supplier" required error={fieldErrors.supplier_id}>
            <Select value={supplierId} onValueChange={setSupplierId}>
              <SelectTrigger>
                <SelectValue placeholder="Select supplier" />
              </SelectTrigger>
              <SelectContent>
                {suppliers.map((supplier) => (
                  <SelectItem key={supplier.id} value={String(supplier.id)}>
                    {supplier.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Order date" required error={fieldErrors.order_date}>
            <Input type="date" value={orderDate} onChange={(event) => setOrderDate(event.target.value)} />
          </Field>
          <Field label="Expected delivery" required error={fieldErrors.expected_delivery_date}>
            <Input
              type="date"
              value={expectedDate}
              onChange={(event) => setExpectedDate(event.target.value)}
            />
          </Field>
        </div>

        <Field label="Deliver to (warehouse address)" error={fieldErrors.delivery_address}>
          <Input
            value={deliveryAddress}
            onChange={(event) => setDeliveryAddress(event.target.value)}
            placeholder="FrigoLoco Depot - Nivelles"
          />
        </Field>

        <Field label="Comment to supplier" error={fieldErrors.comment}>
          <Textarea value={comment} onChange={(event) => setComment(event.target.value)} />
        </Field>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-semibold">Order lines</h4>
          </div>
          <ProductPicker onSelect={addProduct} disabledIds={chosenIds} />
          {fieldErrors.lines ? (
            <p className="text-xs text-critical">{fieldErrors.lines}</p>
          ) : null}

          {lines.length === 0 ? (
            <p className="rounded-md border border-dashed border-border px-3 py-6 text-center text-sm text-muted-foreground">
              Search and add products above to build the order.
            </p>
          ) : (
            <div className="overflow-hidden rounded-lg border border-border">
              <table className="w-full text-sm">
                <thead className="bg-muted/40 text-xs text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">Product</th>
                    <th className="px-3 py-2 text-right font-medium">Qty</th>
                    <th className="px-3 py-2 text-right font-medium">Unit €</th>
                    <th className="px-3 py-2 text-right font-medium">VAT %</th>
                    <th className="px-3 py-2 text-right font-medium">Line incl.</th>
                    <th className="px-2 py-2" />
                  </tr>
                </thead>
                <tbody>
                  {lines.map((line) => {
                    const qty = Number(line.qty) || 0
                    const price = Number(line.unitPrice) || 0
                    const rate = (Number(line.vatPercent) || 0) / 100
                    const lineIncl = qty * price * (1 + rate)
                    return (
                      <tr key={line.product.id} className="border-t border-border">
                        <td className="px-3 py-2">
                          <div className="font-medium">{line.product.name}</div>
                          <div className="font-mono text-xs text-muted-foreground">
                            {line.product.code}
                          </div>
                        </td>
                        <td className="px-3 py-2 text-right">
                          <Input
                            type="number"
                            min={1}
                            value={line.qty}
                            onChange={(event) => updateLine(line.product.id, { qty: event.target.value })}
                            className="ml-auto h-8 w-20 text-right"
                          />
                        </td>
                        <td className="px-3 py-2 text-right">
                          <Input
                            type="number"
                            step="0.01"
                            min={0}
                            value={line.unitPrice}
                            onChange={(event) =>
                              updateLine(line.product.id, { unitPrice: event.target.value })
                            }
                            className="ml-auto h-8 w-24 text-right"
                          />
                        </td>
                        <td className="px-3 py-2 text-right">
                          <Input
                            type="number"
                            step="0.1"
                            min={0}
                            value={line.vatPercent}
                            onChange={(event) =>
                              updateLine(line.product.id, { vatPercent: event.target.value })
                            }
                            className="ml-auto h-8 w-20 text-right"
                          />
                        </td>
                        <td className="px-3 py-2 text-right font-medium tabular-nums">
                          {formatEuro(lineIncl)}
                        </td>
                        <td className="px-2 py-2 text-right">
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label="Remove line"
                            onClick={() => removeLine(line.product.id)}
                          >
                            <Trash2 className="h-4 w-4 text-critical" />
                          </Button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}

          <div className="flex justify-end">
            <table className="w-auto min-w-[240px] text-sm">
              <tbody>
                <tr>
                  <td className="py-1 pr-6 text-muted-foreground">Total ex VAT</td>
                  <td className="py-1 text-right tabular-nums">{formatEuro(totals.ex)}</td>
                </tr>
                <tr>
                  <td className="py-1 pr-6 text-muted-foreground">VAT</td>
                  <td className="py-1 text-right tabular-nums">{formatEuro(totals.vat)}</td>
                </tr>
                <tr className="border-t border-border font-semibold">
                  <td className="py-1 pr-6">Total incl. VAT</td>
                  <td className="py-1 text-right tabular-nums">{formatEuro(totals.incl)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </Dialog>
  )
}

// ─────────────────────────── PO detail + receive/cancel ───────────────────────────

interface PoDetailDialogProps {
  poId: number
  supplierName: (id: number) => string
  onClose: () => void
}

function PoDetailDialog({ poId, supplierName, onClose }: PoDetailDialogProps) {
  const queryClient = useQueryClient()
  const [receiveQty, setReceiveQty] = React.useState<Record<number, string>>({})
  const [confirmingCancel, setConfirmingCancel] = React.useState(false)
  const [overReceipt, setOverReceipt] = React.useState<OverReceiptDetail[] | null>(null)

  const poQuery = useQuery({
    queryKey: ['supply', 'purchase-order', poId],
    queryFn: ({ signal }) => api.get<PurchaseOrder>(`/api/v1/purchase-orders/${poId}`, { signal }),
  })

  const po = poQuery.data
  const isPending = po?.status === 'pending'

  // Seed receive inputs with each line's outstanding quantity once the PO loads.
  React.useEffect(() => {
    if (!po) return
    const seed: Record<number, string> = {}
    for (const line of po.lines) {
      seed[line.id] = String(Math.max(0, line.qty_ordered - line.qty_received))
    }
    setReceiveQty(seed)
  }, [po])

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ['supply', 'purchase-order', poId] })
    queryClient.invalidateQueries({ queryKey: ['supply', 'purchase-orders'] })
    queryClient.invalidateQueries({ queryKey: ['supply', 'stock-balances'] })
    queryClient.invalidateQueries({ queryKey: ['supply', 'stock-movements'] })
  }

  const receiveMutation = useMutation({
    mutationFn: (acknowledge: boolean) => {
      const received = Object.entries(receiveQty)
        .map(([lineId, qty]) => ({ po_line_id: Number(lineId), qty_received: Number(qty) || 0 }))
        .filter((line) => line.qty_received > 0)
      return api.post<unknown>(`/api/v1/purchase-orders/${poId}/receive`, {
        received,
        acknowledge_over_receipt: acknowledge,
      })
    },
    onSuccess: () => {
      toast.success('Stock received')
      setOverReceipt(null)
      invalidateAll()
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === 'over_receipt') {
        // Surface the acknowledge dialog with the offending lines.
        setOverReceipt(Array.isArray(error.details) ? (error.details as OverReceiptDetail[]) : [])
        return
      }
      const message = error instanceof ApiError ? error.message : 'Failed to receive stock'
      toast.error(message)
    },
  })

  const cancelMutation = useMutation({
    mutationFn: () => api.post<unknown>(`/api/v1/purchase-orders/${poId}/cancel`),
    onSuccess: () => {
      toast.success('Purchase order cancelled')
      setConfirmingCancel(false)
      invalidateAll()
    },
    onError: (error) => {
      // cancel_blocked (409): received stock already dispatched.
      const message = error instanceof ApiError ? error.message : 'Failed to cancel PO'
      toast.error(message)
      setConfirmingCancel(false)
    },
  })

  const receivingTotal = Object.values(receiveQty).reduce((sum, qty) => sum + (Number(qty) || 0), 0)

  return (
    <Dialog
      open
      onClose={onClose}
      title={po ? `PO ${po.order_no}` : 'Purchase order'}
      description={po ? supplierName(po.supplier_id) : undefined}
      widthClassName="max-w-3xl"
      footer={
        po ? (
          <div className="flex w-full flex-wrap items-center gap-2">
            <StatusChip status={po.status} className="mr-auto" />
            {isPending ? (
              <Button
                onClick={() => receiveMutation.mutate(false)}
                disabled={receiveMutation.isPending || receivingTotal <= 0}
              >
                {receiveMutation.isPending ? 'Receiving…' : 'Mark received'}
              </Button>
            ) : null}
            {po.status !== 'cancelled' ? (
              <Button
                variant="destructive"
                onClick={() => setConfirmingCancel(true)}
                disabled={cancelMutation.isPending}
              >
                Cancel with reversal
              </Button>
            ) : null}
            <Button variant="outline" onClick={onClose}>
              Close
            </Button>
          </div>
        ) : null
      }
    >
      {poQuery.isLoading ? (
        <p className="py-8 text-center text-sm text-muted-foreground">Loading purchase order…</p>
      ) : poQuery.isError ? (
        <div className="py-4">
          <p className="text-sm text-critical">
            {poQuery.error instanceof ApiError ? poQuery.error.message : 'Failed to load PO'}
          </p>
        </div>
      ) : po ? (
        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <Meta label="Order date" value={po.order_date} />
            <Meta label="Expected" value={po.expected_delivery_date} />
            <Meta label="Total ex VAT" value={formatEuro(po.total_ex_vat)} />
            <Meta label="Total incl." value={formatEuro(po.total_incl_vat)} />
          </div>
          {po.delivery_address ? <Meta label="Deliver to" value={po.delivery_address} /> : null}
          {po.comment ? <Meta label="Comment" value={po.comment} /> : null}

          {isPending ? (
            <div className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-[#8a6100] dark:text-warning">
              Receiving fewer units than ordered? Enter the actual quantity received per line - the
              difference is logged and stock increases only by the received amount.
            </div>
          ) : null}

          <div className="overflow-hidden rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">Product</th>
                  <th className="px-3 py-2 text-right font-medium">Unit €</th>
                  <th className="px-3 py-2 text-right font-medium">Ordered</th>
                  <th className="px-3 py-2 text-right font-medium">Received</th>
                  {isPending ? (
                    <th className="px-3 py-2 text-right font-medium">Receive now</th>
                  ) : null}
                  <th className="px-3 py-2 text-right font-medium">Line incl.</th>
                </tr>
              </thead>
              <tbody>
                {po.lines.map((line) => (
                  <tr key={line.id} className="border-t border-border">
                    <td className="px-3 py-2">
                      <div className="font-medium">{line.product_name}</div>
                      <div className="font-mono text-xs text-muted-foreground">
                        {line.product_code}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">{formatEuro(line.unit_price)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{line.qty_ordered}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{line.qty_received}</td>
                    {isPending ? (
                      <td className="px-3 py-2 text-right">
                        <Input
                          type="number"
                          min={0}
                          value={receiveQty[line.id] ?? '0'}
                          onChange={(event) =>
                            setReceiveQty((prev) => ({ ...prev, [line.id]: event.target.value }))
                          }
                          className="ml-auto h-8 w-20 text-right"
                        />
                      </td>
                    ) : null}
                    <td className="px-3 py-2 text-right font-medium tabular-nums">
                      {formatEuro(line.line_incl_vat)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      {confirmingCancel ? (
        <Dialog
          open
          onClose={() => setConfirmingCancel(false)}
          title="Cancel this purchase order?"
          description="Received stock is reversed out. If it has already been dispatched, the cancel is refused."
          footer={
            <>
              <Button variant="outline" onClick={() => setConfirmingCancel(false)} disabled={cancelMutation.isPending}>
                Keep PO
              </Button>
              <Button
                variant="destructive"
                onClick={() => cancelMutation.mutate()}
                disabled={cancelMutation.isPending}
              >
                {cancelMutation.isPending ? 'Cancelling…' : 'Cancel PO'}
              </Button>
            </>
          }
        >
          <p className="text-sm text-muted-foreground">This action reverses any received stock movements.</p>
        </Dialog>
      ) : null}

      {overReceipt !== null ? (
        <Dialog
          open
          onClose={() => setOverReceipt(null)}
          title="Over-receipt detected"
          description="One or more lines receive more than was ordered. Acknowledge to record the over-receipt."
          footer={
            <>
              <Button variant="outline" onClick={() => setOverReceipt(null)} disabled={receiveMutation.isPending}>
                Go back
              </Button>
              <Button onClick={() => receiveMutation.mutate(true)} disabled={receiveMutation.isPending}>
                {receiveMutation.isPending ? 'Confirming…' : 'Acknowledge & receive'}
              </Button>
            </>
          }
        >
          <ul className="space-y-1 text-sm">
            {overReceipt.map((detail) => {
              const line = po?.lines.find((candidate) => candidate.id === detail.po_line_id)
              return (
                <li
                  key={detail.po_line_id}
                  className="flex justify-between rounded-md border border-border px-3 py-2"
                >
                  <span className="text-xs">
                    {line ? `${line.product_name} (${line.product_code})` : `line ${detail.po_line_id}`}
                  </span>
                  <span className="text-muted-foreground">
                    ordered {detail.qty_ordered}, receiving {detail.qty_received}
                  </span>
                </li>
              )
            })}
          </ul>
        </Dialog>
      ) : null}
    </Dialog>
  )
}

function Meta({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className={cn('min-w-0')}>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="truncate font-medium text-foreground">{value}</div>
    </div>
  )
}

export default PurchaseOrdersPage
