import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
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
import { api, ApiError } from '@/lib/api'
import { localIsoDate } from '@/lib/dates'
import { formatEuro } from '@/lib/format'
import { cn } from '@/lib/utils'
import {
  DAY_NAMES,
  currentWeekDayKey,
  deliveryDateFromKey,
  type DayName,
} from '@/pages/ops/lib/pipelineKey'
import { STOCK_BALANCES_QUERY_KEY } from '@/pages/ops/menu/menuApi'
import type {
  MenuOrderPlan,
  MenuOrderPlanLine,
  PurchaseOrder,
  PurchaseOrderCreate,
} from '../types'
import { Dialog } from './Dialog'

const ISO_WEEK_COUNT = 53
const WEEK_OPTIONS = Array.from({ length: ISO_WEEK_COUNT }, (_, index) => index + 1)
const YEARS_AROUND_CURRENT = [-1, 0, 1]
const DAY_SHORT_LABEL_LENGTH = 3

const PLAN_HELP =
  'Need = units in the saved menus of the chosen days. To order = need minus warehouse stock ' +
  'minus units already on order, never below 0. Edit any quantity before creating.'

type MenuSupplierPlan = MenuOrderPlan['suppliers'][number]

interface GeneratePosFromMenuDialogProps {
  onClose: () => void
}

/** Whole units typed in a text box; NaN when the text is not a whole number >= 0. */
function parseUnits(text: string): number {
  const trimmed = text.trim()
  if (!/^\d+$/.test(trimmed)) return Number.NaN
  return Number(trimmed)
}

export function GeneratePosFromMenuDialog({ onClose }: GeneratePosFromMenuDialogProps) {
  const queryClient = useQueryClient()
  const [initialKey] = React.useState(() => currentWeekDayKey())
  const [year, setYear] = React.useState(initialKey.year)
  const [week, setWeek] = React.useState(initialKey.week)
  const [selectedDays, setSelectedDays] = React.useState<DayName[]>([initialKey.dayName])
  const [qtyOverrides, setQtyOverrides] = React.useState<Record<number, string>>({})
  const [expectedDateOverride, setExpectedDateOverride] = React.useState<string | null>(null)
  const [createdOrderNoBySupplier, setCreatedOrderNoBySupplier] = React.useState<
    Record<number, string>
  >({})
  const [creatingSupplierId, setCreatingSupplierId] = React.useState<number | null>(null)

  const orderedDays = DAY_NAMES.filter((dayName) => selectedDays.includes(dayName))
  const planQuery = useQuery({
    queryKey: ['supply', 'menu-order-plan', year, week, orderedDays],
    queryFn: ({ signal }) => {
      const search = new URLSearchParams({ year: String(year), week: String(week) })
      for (const dayName of orderedDays) search.append('day_names', dayName)
      return api.get<MenuOrderPlan>(`/api/v1/purchase-orders/menu-order-plan?${search}`, {
        signal,
      })
    },
    enabled: orderedDays.length > 0,
  })
  const plan = orderedDays.length > 0 ? planQuery.data : undefined
  const expectedDate = expectedDateOverride ?? plan?.expected_delivery_date ?? ''

  function resetPlanEdits() {
    setQtyOverrides({})
    setExpectedDateOverride(null)
    setCreatedOrderNoBySupplier({})
  }

  function changeWeek(nextYear: number, nextWeek: number) {
    setYear(nextYear)
    setWeek(nextWeek)
    resetPlanEdits()
  }

  function toggleDay(dayName: DayName) {
    setSelectedDays((previous) =>
      previous.includes(dayName)
        ? previous.filter((selected) => selected !== dayName)
        : [...previous, dayName],
    )
    resetPlanEdits()
  }

  function qtyTextFor(line: MenuOrderPlanLine): string {
    return qtyOverrides[line.product_id] ?? String(line.to_order_qty)
  }

  const createMutation = useMutation({
    mutationFn: (body: PurchaseOrderCreate) =>
      api.post<PurchaseOrder>('/api/v1/purchase-orders', body),
  })

  function buildOrderBody(supplier: MenuSupplierPlan): PurchaseOrderCreate {
    const orderLines = supplier.lines
      .map((line) => ({ product_id: line.product_id, qty: parseUnits(qtyTextFor(line)) }))
      .filter((line) => line.qty > 0)
    return {
      supplier_id: supplier.supplier_id,
      order_date: localIsoDate(),
      expected_delivery_date: expectedDate,
      comment: `Generated from menu ${year}-W${week} (${orderedDays.join(', ')})`,
      lines: orderLines,
    }
  }

  function isCardReady(supplier: MenuSupplierPlan): boolean {
    const quantities = supplier.lines.map((line) => parseUnits(qtyTextFor(line)))
    const allValid = quantities.every((qty) => !Number.isNaN(qty))
    const anyToOrder = quantities.some((qty) => qty > 0)
    const notCreatedYet = createdOrderNoBySupplier[supplier.supplier_id] === undefined
    return allValid && anyToOrder && notCreatedYet && expectedDate !== ''
  }

  async function createOrder(supplier: MenuSupplierPlan): Promise<boolean> {
    setCreatingSupplierId(supplier.supplier_id)
    try {
      const po = await createMutation.mutateAsync(buildOrderBody(supplier))
      setCreatedOrderNoBySupplier((previous) => ({
        ...previous,
        [supplier.supplier_id]: po.order_no,
      }))
      toast.success(`PO ${po.order_no} created for ${supplier.supplier_name}`)
      return true
    } catch (error) {
      const message = error instanceof ApiError ? error.message : 'Failed to create PO'
      toast.error(`${supplier.supplier_name}: ${message}`)
      return false
    } finally {
      setCreatingSupplierId(null)
      queryClient.invalidateQueries({ queryKey: ['supply', 'purchase-orders'] })
      queryClient.invalidateQueries({ queryKey: ['supply', 'stock-balances'] })
      queryClient.invalidateQueries({ queryKey: STOCK_BALANCES_QUERY_KEY })
    }
  }

  const readySuppliers = (plan?.suppliers ?? []).filter(isCardReady)

  async function createAllOrders() {
    for (const supplier of readySuppliers) {
      const created = await createOrder(supplier)
      if (!created) return
    }
  }

  const isCreating = creatingSupplierId !== null

  return (
    <Dialog
      open
      onClose={onClose}
      title="Generate POs from menu"
      description={PLAN_HELP}
      widthClassName="max-w-5xl"
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={isCreating}>
            Close
          </Button>
          <Button onClick={createAllOrders} disabled={isCreating || readySuppliers.length === 0}>
            Create all ({readySuppliers.length})
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <Select value={String(year)} onValueChange={(next) => changeWeek(Number(next), week)}>
            <SelectTrigger className="w-24" aria-label="Year">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {YEARS_AROUND_CURRENT.map((offset) => {
                const optionYear = initialKey.year + offset
                return (
                  <SelectItem key={optionYear} value={String(optionYear)}>
                    {optionYear}
                  </SelectItem>
                )
              })}
            </SelectContent>
          </Select>
          <Select value={String(week)} onValueChange={(next) => changeWeek(year, Number(next))}>
            <SelectTrigger className="w-24" aria-label="ISO week">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {WEEK_OPTIONS.map((option) => (
                <SelectItem key={option} value={String(option)}>
                  W{String(option).padStart(2, '0')}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="flex flex-wrap gap-1">
            {DAY_NAMES.map((dayName) => (
              <DayToggle
                key={dayName}
                dayName={dayName}
                deliveryDate={deliveryDateFromKey({ year, week, dayName })}
                selected={selectedDays.includes(dayName)}
                onToggle={() => toggleDay(dayName)}
              />
            ))}
          </div>
          <label className="ml-auto flex items-center gap-2 text-sm text-muted-foreground">
            Expected delivery
            <Input
              type="date"
              value={expectedDate}
              onChange={(event) => setExpectedDateOverride(event.target.value)}
              className="w-40"
              disabled={!plan}
            />
          </label>
        </div>

        <PlanBody
          plan={plan}
          hasDays={orderedDays.length > 0}
          isLoading={planQuery.isFetching}
          error={planQuery.error}
          renderCard={(supplier) => (
            <SupplierOrderCard
              key={supplier.supplier_id}
              supplier={supplier}
              qtyTextFor={qtyTextFor}
              onQtyChange={(productId, text) =>
                setQtyOverrides((previous) => ({ ...previous, [productId]: text }))
              }
              createdOrderNo={createdOrderNoBySupplier[supplier.supplier_id]}
              canCreate={isCardReady(supplier) && !isCreating}
              isCreating={creatingSupplierId === supplier.supplier_id}
              onCreate={() => createOrder(supplier)}
            />
          )}
        />
      </div>
    </Dialog>
  )
}

interface DayToggleProps {
  dayName: DayName
  deliveryDate: string
  selected: boolean
  onToggle: () => void
}

function DayToggle({ dayName, deliveryDate, selected, onToggle }: DayToggleProps) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onToggle}
      title={`Delivery ${deliveryDate}`}
      className={cn(
        'rounded-md border px-2 py-1 text-xs',
        selected
          ? 'border-primary bg-primary text-primary-foreground'
          : 'border-border text-muted-foreground hover:bg-muted',
      )}
    >
      {dayName.slice(0, DAY_SHORT_LABEL_LENGTH)} {deliveryDate.slice(5)}
    </button>
  )
}

interface PlanBodyProps {
  plan: MenuOrderPlan | undefined
  hasDays: boolean
  isLoading: boolean
  error: Error | null
  renderCard: (supplier: MenuSupplierPlan) => React.ReactNode
}

function PlanBody({ plan, hasDays, isLoading, error, renderCard }: PlanBodyProps) {
  if (!hasDays) return <PlanMessage text="Pick at least one delivery day." />
  if (error) {
    const message = error instanceof ApiError ? error.message : 'Failed to load the menu plan'
    return <p className="text-sm text-critical">{message}</p>
  }
  if (!plan) return <PlanMessage text={isLoading ? 'Loading menu plan…' : ''} />

  return (
    <div className="space-y-3">
      {plan.days_without_menu.length > 0 ? (
        <p className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-xs">
          No saved menu for {plan.days_without_menu.join(', ')}: those days add nothing.
        </p>
      ) : null}
      {plan.lines_without_supplier.length > 0 ? (
        <p className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-xs">
          Products without a supplier cannot be ordered:{' '}
          {plan.lines_without_supplier.map((line) => line.product_name).join(', ')}
        </p>
      ) : null}
      {plan.suppliers.length === 0 ? (
        <PlanMessage text="The saved menus of these days have no products to order." />
      ) : (
        plan.suppliers.map(renderCard)
      )}
    </div>
  )
}

function PlanMessage({ text }: { text: string }) {
  return (
    <p className="rounded-md border border-dashed border-border px-3 py-6 text-center text-sm text-muted-foreground">
      {text}
    </p>
  )
}

interface SupplierOrderCardProps {
  supplier: MenuSupplierPlan
  qtyTextFor: (line: MenuOrderPlanLine) => string
  onQtyChange: (productId: number, text: string) => void
  createdOrderNo: string | undefined
  canCreate: boolean
  isCreating: boolean
  onCreate: () => void
}

function SupplierOrderCard({
  supplier,
  qtyTextFor,
  onQtyChange,
  createdOrderNo,
  canCreate,
  isCreating,
  onCreate,
}: SupplierOrderCardProps) {
  const totalExVat = supplier.lines.reduce((sum, line) => {
    const units = parseUnits(qtyTextFor(line))
    return Number.isNaN(units) ? sum : sum + units * Number(line.unit_price)
  }, 0)
  const isCreated = createdOrderNo !== undefined

  return (
    <section className="rounded-lg border border-border">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-2">
        <h3 className="text-sm font-semibold">{supplier.supplier_name}</h3>
        <div className="flex items-center gap-3">
          <span className="text-sm">
            <span className="font-semibold tabular-nums">{formatEuro(totalExVat)}</span>{' '}
            <span className="text-xs text-muted-foreground">ex VAT</span>
          </span>
          {isCreated ? (
            <span className="text-xs font-medium text-success">Created PO {createdOrderNo}</span>
          ) : (
            <Button size="sm" onClick={onCreate} disabled={!canCreate}>
              {isCreating ? 'Creating…' : 'Create PO'}
            </Button>
          )}
        </div>
      </header>
      <table className="w-full text-sm">
        <thead className="text-xs text-muted-foreground">
          <tr>
            <th className="px-3 py-1.5 text-left font-medium">Product</th>
            <th className="px-3 py-1.5 text-right font-medium">Need</th>
            <th className="px-3 py-1.5 text-right font-medium">In stock</th>
            <th className="px-3 py-1.5 text-right font-medium">On order</th>
            <th className="px-3 py-1.5 text-right font-medium">To order</th>
          </tr>
        </thead>
        <tbody>
          {supplier.lines.map((line) => {
            const qtyText = qtyTextFor(line)
            const isInvalid = Number.isNaN(parseUnits(qtyText))
            return (
              <tr key={line.product_id} className="border-t border-border">
                <td className="px-3 py-1" title={`Code ${line.product_code}`}>
                  {line.product_name}
                </td>
                <td className="px-3 py-1 text-right tabular-nums">{line.need_qty}</td>
                <td className="px-3 py-1 text-right tabular-nums text-muted-foreground">
                  {line.in_stock_qty}
                </td>
                <td className="px-3 py-1 text-right tabular-nums text-muted-foreground">
                  {line.on_order_qty}
                </td>
                <td className="px-3 py-1 text-right">
                  <Input
                    inputMode="numeric"
                    value={qtyText}
                    onChange={(event) => onQtyChange(line.product_id, event.target.value)}
                    disabled={isCreated}
                    aria-invalid={isInvalid}
                    className={cn('ml-auto h-7 w-20 text-right', isInvalid && 'border-critical')}
                  />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </section>
  )
}
