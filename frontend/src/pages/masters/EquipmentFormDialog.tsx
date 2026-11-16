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
import { Switch } from '@/components/ui/switch'
import { useSupplierOptions } from '@/hooks/useSupplierOptions'
import { api } from '@/lib/api'
import { formatFridgeName } from '@/lib/format'
import type { Equipment, EquipmentCategory, EquipmentOwnership } from '@/lib/types'
import { Dialog } from '@/pages/supply/components/Dialog'
import {
  Field,
  Textarea,
  fieldErrorsFromApiError,
  generalErrorMessage,
} from '@/pages/supply/components/form'
import { useAllClients, useAllFridges } from '@/pages/supply/components/masterLookups'
import {
  EQUIPMENT_CATEGORIES,
  EQUIPMENT_CATEGORY_LABELS,
  OWNERSHIPS,
  OWNERSHIP_LABELS,
} from './equipmentOptions'

const NONE_VALUE = 'none'
const PERCENT = 100
const RATE_FRACTION_DIGITS = 4
const PERCENT_FRACTION_DIGITS = 2
const DECIMAL_PATTERN = /^\d+([.,]\d{1,2})?$/
const WHOLE_NUMBER_PATTERN = /^\d+$/
const INVALID_AMOUNT_MESSAGE = 'Enter an amount like 365 or 365.50, or leave empty.'
const INVALID_WHOLE_NUMBER_MESSAGE = 'Enter a whole number, or leave empty.'

interface EquipmentForm {
  machine_type: string
  machine_code: string
  equipment_category: EquipmentCategory
  ownership: EquipmentOwnership
  supplier: string
  client: string
  fridge: string
  cost: string
  monthly_fee: string
  purchase_date: string
  financing_years: string
  financing_rate_pct: string
  financed_by: string
  is_active: boolean
  notes: string
}

const EMPTY_FORM: EquipmentForm = {
  machine_type: '',
  machine_code: '',
  equipment_category: 'coffee',
  ownership: 'bought',
  supplier: NONE_VALUE,
  client: NONE_VALUE,
  fridge: NONE_VALUE,
  cost: '',
  monthly_fee: '',
  purchase_date: '',
  financing_years: '',
  financing_rate_pct: '',
  financed_by: '',
  is_active: true,
  notes: '',
}

interface EquipmentFormDialogProps {
  /** Null = create a new machine. */
  equipment: Equipment | null
  onClose: () => void
  onSuccess: (equipment: Equipment) => void
}

/** Create or edit one machine of the equipment register. */
export function EquipmentFormDialog({ equipment, onClose, onSuccess }: EquipmentFormDialogProps) {
  const [form, setForm] = React.useState<EquipmentForm>(
    equipment === null ? EMPTY_FORM : toEquipmentForm(equipment),
  )
  const suppliers = useSupplierOptions().data ?? []
  const clients = useAllClients().data ?? []
  const fridges = useAllFridges().data ?? []
  const fridgesOfClient =
    form.client === NONE_VALUE
      ? fridges
      : fridges.filter((fridge) => String(fridge.client_id) === form.client)

  const mutation = useMutation({
    mutationFn: () => {
      const payload = toPayload(form)
      if (equipment === null) return api.post<Equipment>('/api/v1/equipment', payload)
      return api.put<Equipment>(`/api/v1/equipment/${equipment.id}`, payload)
    },
    onSuccess,
  })

  const setField = <Key extends keyof EquipmentForm>(key: Key, value: EquipmentForm[Key]) =>
    setForm((previous) => ({ ...previous, [key]: value }))

  const invalidCost = !isOptionalAmount(form.cost)
  const invalidMonthlyFee = !isOptionalAmount(form.monthly_fee)
  const invalidFinancingYears = !isOptionalWholeNumber(form.financing_years)
  const invalidFinancingRate = !isOptionalAmount(form.financing_rate_pct)
  const hasRequiredFields = form.machine_type.trim() !== '' && form.machine_code.trim() !== ''
  const hasInvalidInput =
    invalidCost || invalidMonthlyFee || invalidFinancingYears || invalidFinancingRate
  const fieldErrors = fieldErrorsFromApiError(mutation.error)
  const generalError =
    mutation.error && Object.keys(fieldErrors).length === 0
      ? generalErrorMessage(mutation.error)
      : null
  const costLabel = form.ownership === 'rent' ? 'Monthly rent we pay (€)' : 'Purchase price (€)'

  return (
    <Dialog
      open
      onClose={onClose}
      title={equipment === null ? 'New equipment' : `Edit ${equipment.machine_code}`}
      description="Reference data: these amounts are not added to the finance reports."
      widthClassName="max-w-2xl"
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending || !hasRequiredFields || hasInvalidInput}
          >
            {mutation.isPending ? 'Saving…' : 'Save'}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {generalError ? (
          <div className="rounded-md border border-critical/40 bg-critical/5 px-3 py-2 text-sm text-critical">
            {generalError}
          </div>
        ) : null}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Machine type" required error={fieldErrors.machine_type}>
            <Input
              value={form.machine_type}
              autoFocus
              placeholder="Technicup 2"
              onChange={(event) => setField('machine_type', event.target.value)}
            />
          </Field>
          <Field label="Machine code" required error={fieldErrors.machine_code}>
            <Input
              value={form.machine_code}
              placeholder="C.TC2-001"
              onChange={(event) => setField('machine_code', event.target.value)}
            />
          </Field>
          <Field label="Category" error={fieldErrors.equipment_category}>
            <Select
              value={form.equipment_category}
              onValueChange={(value) => setField('equipment_category', value as EquipmentCategory)}
            >
              <SelectTrigger aria-label="Category">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {EQUIPMENT_CATEGORIES.map((category) => (
                  <SelectItem key={category} value={category}>
                    {EQUIPMENT_CATEGORY_LABELS[category]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Bought or rented" error={fieldErrors.ownership}>
            <Select
              value={form.ownership}
              onValueChange={(value) => setField('ownership', value as EquipmentOwnership)}
            >
              <SelectTrigger aria-label="Bought or rented">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {OWNERSHIPS.map((ownership) => (
                  <SelectItem key={ownership} value={ownership}>
                    {OWNERSHIP_LABELS[ownership]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Supplier" error={fieldErrors.supplier_id}>
            <Select value={form.supplier} onValueChange={(value) => setField('supplier', value)}>
              <SelectTrigger aria-label="Supplier">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NONE_VALUE}>No supplier</SelectItem>
                {suppliers.map((supplier) => (
                  <SelectItem key={supplier.id} value={String(supplier.id)}>
                    {supplier.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Client" error={fieldErrors.client_id}>
            <Select
              value={form.client}
              onValueChange={(value) => setForm((previous) => ({ ...previous, client: value, fridge: NONE_VALUE }))}
            >
              <SelectTrigger aria-label="Client">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NONE_VALUE}>No client (in stock)</SelectItem>
                {clients.map((client) => (
                  <SelectItem key={client.id} value={String(client.id)}>
                    {client.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Fridge / site" hint="Optional: the fridge this machine stands next to." error={fieldErrors.fridge_id}>
            <Select value={form.fridge} onValueChange={(value) => setField('fridge', value)}>
              <SelectTrigger aria-label="Fridge">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NONE_VALUE}>No fridge</SelectItem>
                {fridgesOfClient.map((fridge) => (
                  <SelectItem key={fridge.id} value={String(fridge.id)}>
                    {formatFridgeName(fridge)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Purchase / start date" error={fieldErrors.purchase_date}>
            <Input
              type="date"
              value={form.purchase_date}
              onChange={(event) => setField('purchase_date', event.target.value)}
            />
          </Field>
          <Field label={costLabel} error={invalidCost ? INVALID_AMOUNT_MESSAGE : null}>
            <Input
              inputMode="decimal"
              value={form.cost}
              onChange={(event) => setField('cost', event.target.value)}
            />
          </Field>
          <Field
            label="Monthly fee charged to client (€)"
            error={invalidMonthlyFee ? INVALID_AMOUNT_MESSAGE : fieldErrors.monthly_fee}
          >
            <Input
              inputMode="decimal"
              value={form.monthly_fee}
              onChange={(event) => setField('monthly_fee', event.target.value)}
            />
          </Field>
          <Field
            label="Financing (years)"
            error={invalidFinancingYears ? INVALID_WHOLE_NUMBER_MESSAGE : fieldErrors.financing_years}
          >
            <Input
              inputMode="numeric"
              value={form.financing_years}
              onChange={(event) => setField('financing_years', event.target.value)}
            />
          </Field>
          <Field
            label="Financing rate (%)"
            error={invalidFinancingRate ? INVALID_AMOUNT_MESSAGE : fieldErrors.financing_rate}
          >
            <Input
              inputMode="decimal"
              value={form.financing_rate_pct}
              placeholder="4"
              onChange={(event) => setField('financing_rate_pct', event.target.value)}
            />
          </Field>
          <Field label="Financed by" error={fieldErrors.financed_by}>
            <Input
              value={form.financed_by}
              placeholder="BNP Bank"
              onChange={(event) => setField('financed_by', event.target.value)}
            />
          </Field>
        </div>
        <Field label="Notes" error={fieldErrors.notes}>
          <Textarea value={form.notes} onChange={(event) => setField('notes', event.target.value)} />
        </Field>
        <label className="flex items-center justify-between gap-3">
          <span className="text-sm font-medium text-foreground">In use</span>
          <Switch
            checked={form.is_active}
            onCheckedChange={(checked) => setField('is_active', checked)}
          />
        </label>
      </div>
    </Dialog>
  )
}

function toEquipmentForm(equipment: Equipment): EquipmentForm {
  const cost =
    equipment.ownership === 'rent' ? equipment.monthly_rent_cost : equipment.purchase_price
  return {
    machine_type: equipment.machine_type,
    machine_code: equipment.machine_code,
    equipment_category: equipment.equipment_category,
    ownership: equipment.ownership,
    supplier: optionalIdToValue(equipment.supplier_id),
    client: optionalIdToValue(equipment.client_id),
    fridge: optionalIdToValue(equipment.fridge_id),
    cost: cost ?? '',
    monthly_fee: equipment.monthly_fee ?? '',
    purchase_date: equipment.purchase_date ?? '',
    financing_years: equipment.financing_years === null ? '' : String(equipment.financing_years),
    financing_rate_pct: fractionToPercentText(equipment.financing_rate),
    financed_by: equipment.financed_by ?? '',
    is_active: equipment.is_active,
    notes: equipment.notes ?? '',
  }
}

/** The cost box holds the purchase price when bought and the monthly rent when rented. */
function toPayload(form: EquipmentForm) {
  const cost = optionalAmount(form.cost)
  const isRented = form.ownership === 'rent'
  const financingYears = form.financing_years.trim()
  return {
    machine_type: form.machine_type.trim(),
    machine_code: form.machine_code.trim(),
    equipment_category: form.equipment_category,
    ownership: form.ownership,
    supplier_id: valueToOptionalId(form.supplier),
    client_id: valueToOptionalId(form.client),
    fridge_id: valueToOptionalId(form.fridge),
    purchase_price: isRented ? null : cost,
    monthly_rent_cost: isRented ? cost : null,
    monthly_fee: optionalAmount(form.monthly_fee),
    purchase_date: form.purchase_date || null,
    financing_years: financingYears === '' ? null : Number(financingYears),
    financing_rate: percentTextToFraction(form.financing_rate_pct),
    financed_by: form.financed_by.trim() || null,
    is_active: form.is_active,
    notes: form.notes.trim() || null,
  }
}

function optionalIdToValue(id: number | null): string {
  return id === null ? NONE_VALUE : String(id)
}

function valueToOptionalId(value: string): number | null {
  return value === NONE_VALUE ? null : Number(value)
}

function isOptionalAmount(text: string): boolean {
  const trimmed = text.trim()
  return trimmed === '' || DECIMAL_PATTERN.test(trimmed)
}

function isOptionalWholeNumber(text: string): boolean {
  const trimmed = text.trim()
  return trimmed === '' || WHOLE_NUMBER_PATTERN.test(trimmed)
}

/** "365,50" -> "365.50"; empty -> null. The API reads euro strings. */
function optionalAmount(text: string): string | null {
  const trimmed = text.trim()
  if (trimmed === '') return null
  return trimmed.replace(',', '.')
}

/** "4.6" (%) -> "0.0460" (fraction), so no float rounding reaches the API. */
function percentTextToFraction(text: string): string | null {
  const amount = optionalAmount(text)
  if (amount === null) return null
  return (Number(amount) / PERCENT).toFixed(RATE_FRACTION_DIGITS)
}

function fractionToPercentText(fraction: string | null): string {
  if (fraction === null) return ''
  const percent = (Number(fraction) * PERCENT).toFixed(PERCENT_FRACTION_DIGITS)
  return String(Number(percent))
}
