import * as React from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Search, Trash2 } from 'lucide-react'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { DataTable, type DataTableColumn } from '@/components/shared/DataTable'
import { EmptyState } from '@/components/shared/EmptyState'
import { StatusChip } from '@/components/shared/StatusChip'
import { MoneyCell } from '@/components/shared/MoneyCell'
import { UnsavedChangesDialog } from '@/components/shared/UnsavedChangesDialog'
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
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { useSingleSubmit } from '@/hooks/useSingleSubmit'
import { useUnsavedChangesGuard } from '@/hooks/useUnsavedChangesGuard'
import { api, ApiError, type Page } from '@/lib/api'
import { formatEuro, formatFraction } from '@/lib/format'
import { cn } from '@/lib/utils'
import { WeekDayPicker } from '@/pages/ops/components/WeekDayPicker'
import { currentWeekDayKey, type WeekDayKey } from '@/pages/ops/lib/pipelineKey'
import { Dialog } from './components/Dialog'
import { Field, Textarea, fieldErrorsFromApiError, generalErrorMessage } from './components/form'
import { ProductPicker } from './components/ProductPicker'
import type {
  MenuDraftLineOut,
  OverReceiptDetail,
  PoLineCreate,
  PoStatus,
  ProductLite,
  PurchaseOrder,
  PurchaseOrderCreate,
  Supplier,
} from './types'

const PAGE_SIZE = 25
const SEARCH_DEBOUNCE_MS = 300
const DEFAULT_DELIVERY_LEAD_DAYS = 2
const LOAD_FROM_MENU_HELP =
  "Copies the saved menu quantities for this supplier's products for the chosen week and day."

const CANCEL_PO_DESCRIPTION =
  'Any received stock, including a partial receipt, is reversed out. ' +
  'If it has already been dispatched, the cancel is refused.'

type StatusFilter = 'all' | PoStatus

/** Local, editable PO line while composing a new order. Price and VAT stay the catalogue's. */
interface DraftLine {
  product: ProductLite
  qty: string
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

function isoPlusDays(days: number): string {
  const date = new Date()
  date.setDate(date.getDate() + days)
  return date.toISOString().slice(0, 10)
}

/** Order quantities are whole units; the API rejects fractions. */
function isWholePositive(qty: string): boolean {
  const units = Number(qty)
  return Number.isInteger(units) && units > 0
}

function lineExVat(line: DraftLine): number {
  return (Number(line.qty) || 0) * Number(line.product.purchase_price)
}

function lineVat(line: DraftLine): number {
  return lineExVat(line) * Number(line.product.vat_rate)
}

/** Live preview of the totals; the server recomputes them from the catalogue on create. */
function computeTotals(lines: DraftLine[]) {
  let ex = 0
  let vat = 0
  for (const line of lines) {
    ex += lineExVat(line)
    vat += lineVat(line)
  }
  return { ex, vat, incl: ex + vat }
}

/** A pending PO with some units already received: still open, stock partly booked. */
function isPartlyReceived(po: PurchaseOrder): boolean {
  return po.status === 'pending' && po.lines.some((line) => line.qty_received > 0)
}

function PoStatusChip({ po, className }: { po: PurchaseOrder; className?: string }) {
  if (isPartlyReceived(po)) {
    return <StatusChip status="partial" label="Partly received" className={className} />
  }
  return <StatusChip status={po.status} className={className} />
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
  const search = useDebouncedValue(searchInput.trim(), SEARCH_DEBOUNCE_MS)

  const suppliersQuery = useSuppliers()
  const supplierName = React.useCallback(
    (id: number) => suppliersQuery.data?.find((s) => s.id === id)?.name ?? `#${id}`,
    [suppliersQuery.data],
  )

  React.useEffect(() => {
    setOffset(0)
  }, [statusFilter, supplierFilter, search])

  const posQuery = useQuery({
    queryKey: ['supply', 'purchase-orders', { statusFilter, supplierFilter, search, offset }],
    queryFn: ({ signal }) =>
      api.get<Page<PurchaseOrder>>('/api/v1/purchase-orders', {
        params: {
          status: statusFilter === 'all' ? undefined : statusFilter,
          supplier_id: supplierFilter === 'all' ? undefined : Number(supplierFilter),
          search: search || undefined,
          limit: PAGE_SIZE,
          offset,
        },
        signal,
      }),
    placeholderData: keepPreviousData,
  })

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
        cell: (row) => <PoStatusChip po={row} />,
        sortValue: (row) => row.status,
      },
    ],
    [supplierName],
  )

  return (
    <div className="space-y-6">
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
        <Button onClick={() => setCreating(true)}>
          <Plus className="h-4 w-4" /> New PO
        </Button>
      </div>

      <DataTable
        columns={columns}
        page={posQuery.data}
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
              search
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
  const [initialOrderDate] = React.useState(todayIso)
  const [initialExpectedDate] = React.useState(() => isoPlusDays(DEFAULT_DELIVERY_LEAD_DAYS))
  const [supplierId, setSupplierId] = React.useState('')
  const [orderDate, setOrderDate] = React.useState(initialOrderDate)
  const [expectedDate, setExpectedDate] = React.useState(initialExpectedDate)
  const [deliveryAddress, setDeliveryAddress] = React.useState('')
  const [comment, setComment] = React.useState('')
  const [lines, setLines] = React.useState<DraftLine[]>([])
  const [weekKey, setWeekKey] = React.useState<WeekDayKey>(() => currentWeekDayKey())
  const [pendingSupplierId, setPendingSupplierId] = React.useState<string | null>(null)
  const [confirmingMenuLoad, setConfirmingMenuLoad] = React.useState(false)

  const isDirty =
    supplierId !== '' ||
    orderDate !== initialOrderDate ||
    expectedDate !== initialExpectedDate ||
    deliveryAddress !== '' ||
    comment !== '' ||
    lines.length > 0
  const guard = useUnsavedChangesGuard(isDirty)
  // Dialog refocuses its panel whenever onClose changes, so the handler must stay stable
  // while isDirty flips; the ref always holds the latest guard.
  const confirmDiscardRef = React.useRef(guard.confirmDiscard)
  React.useEffect(() => {
    confirmDiscardRef.current = guard.confirmDiscard
  }, [guard.confirmDiscard])
  const requestClose = React.useCallback(() => confirmDiscardRef.current(onClose), [onClose])

  const chosenIds = React.useMemo(() => new Set(lines.map((line) => line.product.id)), [lines])
  const totals = React.useMemo(() => computeTotals(lines), [lines])

  const loadFromMenu = useMutation({
    mutationFn: () =>
      api.get<MenuDraftLineOut[]>('/api/v1/menus/draft-purchase-order-lines', {
        params: {
          year: weekKey.year,
          week: weekKey.week,
          day_name: weekKey.dayName,
          supplier_id: Number(supplierId),
        },
      }),
    onSuccess: (draftLines) => {
      if (draftLines.length === 0) {
        toast.info('No menu items for this supplier')
        return
      }
      const mapped: DraftLine[] = draftLines.map((line) => ({
        product: {
          id: line.product_id,
          code: line.code,
          name: line.name,
          purchase_price: line.unit_price,
          vat_rate: line.vat_rate,
        },
        qty: String(line.qty),
      }))
      setLines(mapped)
      toast.success(`Loaded ${mapped.length} line(s) from the menu`)
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 404) {
        toast.error('No saved menu for that week/day')
        return
      }
      const message = error instanceof ApiError ? error.message : 'Failed to load from menu'
      toast.error(message)
    },
  })

  const mutation = useMutation({
    mutationFn: () => {
      const payloadLines: PoLineCreate[] = lines.map((line) => ({
        product_id: line.product.id,
        qty: Number(line.qty) || 0,
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

  const submitOrder = useSingleSubmit(mutation)
  const fieldErrors = fieldErrorsFromApiError(mutation.error)
  const generalError =
    mutation.error && Object.keys(fieldErrors).length === 0
      ? generalErrorMessage(mutation.error)
      : null

  function addProduct(product: ProductLite) {
    setLines((prev) => [...prev, { product, qty: '1' }])
  }

  function updateLineQty(productId: number, qty: string) {
    setLines((prev) =>
      prev.map((line) => (line.product.id === productId ? { ...line, qty } : line)),
    )
  }

  function removeLine(productId: number) {
    setLines((prev) => prev.filter((line) => line.product.id !== productId))
  }

  // Lines belong to one supplier, so switching supplier with lines present clears them.
  function changeSupplier(nextSupplierId: string) {
    if (lines.length === 0) {
      setSupplierId(nextSupplierId)
      return
    }
    setPendingSupplierId(nextSupplierId)
  }

  function confirmSupplierChange() {
    if (pendingSupplierId === null) return
    setSupplierId(pendingSupplierId)
    setLines([])
    setPendingSupplierId(null)
  }

  function requestMenuLoad() {
    if (lines.length === 0) {
      loadFromMenu.mutate()
      return
    }
    setConfirmingMenuLoad(true)
  }

  function confirmMenuLoad() {
    setConfirmingMenuLoad(false)
    loadFromMenu.mutate()
  }

  const hasSupplier = supplierId !== ''
  const hasValidLines = lines.length > 0 && lines.every((line) => isWholePositive(line.qty))
  const canSubmit = hasSupplier && orderDate !== '' && expectedDate !== '' && hasValidLines

  return (
    <Dialog
      open
      onClose={requestClose}
      title="New purchase order"
      description="Pick a supplier, add product lines, and totals compute live."
      widthClassName="max-w-3xl"
      footer={
        <>
          <Button variant="outline" onClick={requestClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button onClick={() => submitOrder()} disabled={mutation.isPending || !canSubmit}>
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
            <Select value={supplierId} onValueChange={changeSupplier}>
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
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h4 className="text-sm font-semibold">Order lines</h4>
            <div className="flex flex-wrap items-center gap-2">
              <WeekDayPicker value={weekKey} onChange={setWeekKey} compact />
              <Button
                variant="outline"
                onClick={requestMenuLoad}
                disabled={!hasSupplier || loadFromMenu.isPending}
                title={hasSupplier ? LOAD_FROM_MENU_HELP : 'Pick a supplier first'}
              >
                {loadFromMenu.isPending ? 'Loading…' : 'Load from menu'}
              </Button>
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            Load from menu: {LOAD_FROM_MENU_HELP} Unit price and VAT always come from the product
            catalogue.
          </p>
          <ProductPicker
            onSelect={addProduct}
            disabledIds={chosenIds}
            supplierId={hasSupplier ? Number(supplierId) : undefined}
            disabled={!hasSupplier}
            placeholder={
              hasSupplier ? "Search this supplier's products…" : 'Pick a supplier first'
            }
          />
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
                    <th className="px-3 py-2 text-right font-medium">VAT</th>
                    <th className="px-3 py-2 text-right font-medium">Line incl.</th>
                    <th className="px-2 py-2" />
                  </tr>
                </thead>
                <tbody>
                  {lines.map((line) => (
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
                          step={1}
                          value={line.qty}
                          onChange={(event) => updateLineQty(line.product.id, event.target.value)}
                          className="ml-auto h-8 w-20 text-right"
                        />
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">
                        {formatEuro(line.product.purchase_price)}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">
                        {formatFraction(line.product.vat_rate)}
                      </td>
                      <td className="px-3 py-2 text-right font-medium tabular-nums">
                        {formatEuro(lineExVat(line) + lineVat(line))}
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
                  ))}
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

      <ConfirmDialog
        open={pendingSupplierId !== null}
        onClose={() => setPendingSupplierId(null)}
        onConfirm={confirmSupplierChange}
        title="Change supplier?"
        description="The order lines belong to the current supplier and will be removed."
        confirmLabel="Change and clear lines"
        destructive
      />
      <ConfirmDialog
        open={confirmingMenuLoad}
        onClose={() => setConfirmingMenuLoad(false)}
        onConfirm={confirmMenuLoad}
        title="Replace order lines?"
        description="Loading from the menu replaces all current lines with the saved menu quantities."
        confirmLabel="Replace lines"
        destructive
      />
      <UnsavedChangesDialog guard={guard} />
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

  const submitReceipt = useSingleSubmit(receiveMutation)
  const submitCancel = useSingleSubmit(cancelMutation)
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
            <PoStatusChip po={po} className="mr-auto" />
            {isPending ? (
              <Button
                onClick={() => submitReceipt(false)}
                disabled={receiveMutation.isPending || receivingTotal <= 0}
              >
                {receiveMutation.isPending ? 'Receiving…' : 'Receive goods'}
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
          description={CANCEL_PO_DESCRIPTION}
          footer={
            <>
              <Button variant="outline" onClick={() => setConfirmingCancel(false)} disabled={cancelMutation.isPending}>
                Keep PO
              </Button>
              <Button
                variant="destructive"
                onClick={() => submitCancel()}
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
              <Button onClick={() => submitReceipt(true)} disabled={receiveMutation.isPending}>
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
