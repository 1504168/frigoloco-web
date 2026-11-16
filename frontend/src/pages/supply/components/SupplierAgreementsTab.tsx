import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Trash2 } from 'lucide-react'
import { EmptyState } from '@/components/shared/EmptyState'
import { ErrorState } from '@/components/shared/ErrorState'
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
import { EMPTY_PLACEHOLDER, formatDate } from '@/lib/format'
import type { SupplierAgreement, SupplierAgreementBasis } from '@/lib/types'
import { Field, Textarea, fieldErrorsFromApiError } from './form'

const BASIS_LABELS: Record<SupplierAgreementBasis, string> = {
  year_end_rebate: 'Year-end rebate',
  price_discount: 'Price discount',
}
const BASIS_OPTIONS = Object.keys(BASIS_LABELS) as SupplierAgreementBasis[]
const DEFAULT_BASIS: SupplierAgreementBasis = 'year_end_rebate'
const DECIMAL_PATTERN = /^\d+([.,]\d{1,2})?$/
const YEAR_PATTERN = /^\d{4}$/

/** Yearly negotiated discounts with one supplier. Reference only: prices are not changed. */
export function SupplierAgreementsTab({ supplierId }: { supplierId: number }) {
  const queryClient = useQueryClient()
  const agreementsUrl = `/api/v1/suppliers/${supplierId}/agreements`
  const agreementsQueryKey = ['supply', 'supplier-agreements', supplierId]
  const [year, setYear] = React.useState(String(new Date().getFullYear()))
  const [discountPct, setDiscountPct] = React.useState('')
  const [basis, setBasis] = React.useState<SupplierAgreementBasis>(DEFAULT_BASIS)
  const [reviewDate, setReviewDate] = React.useState('')
  const [notes, setNotes] = React.useState('')

  const agreementsQuery = useQuery({
    queryKey: agreementsQueryKey,
    queryFn: ({ signal }) => api.get<SupplierAgreement[]>(agreementsUrl, { signal }),
  })

  const refreshAgreements = () => queryClient.invalidateQueries({ queryKey: agreementsQueryKey })

  const addMutation = useMutation({
    mutationFn: () =>
      api.post<SupplierAgreement>(agreementsUrl, {
        year: Number(year),
        discount_pct: discountPct.replace(',', '.'),
        basis,
        review_date: reviewDate || null,
        notes: notes.trim() || null,
      }),
    onSuccess: () => {
      toast.success('Agreement added')
      setDiscountPct('')
      setReviewDate('')
      setNotes('')
      refreshAgreements()
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Failed to add agreement')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (agreementId: number) => api.del<void>(`${agreementsUrl}/${agreementId}`),
    onSuccess: refreshAgreements,
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Failed to delete agreement')
    },
  })

  const fieldErrors = fieldErrorsFromApiError(addMutation.error)
  const canSubmit = YEAR_PATTERN.test(year.trim()) && DECIMAL_PATTERN.test(discountPct.trim())

  return (
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground">
        Yearly review and negotiated discounts, for reference. They do not change product
        prices or purchase orders.
      </p>
      <AgreementsTable
        agreements={agreementsQuery.data}
        isLoading={agreementsQuery.isLoading}
        error={agreementsQuery.isError ? agreementsQuery.error : null}
        onRetry={() => agreementsQuery.refetch()}
        onDelete={(agreementId) => deleteMutation.mutate(agreementId)}
      />

      <div className="rounded-lg border border-border p-4">
        <h4 className="mb-3 text-sm font-semibold">Add agreement</h4>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
          <Field label="Year" required error={fieldErrors.year}>
            <Input inputMode="numeric" value={year} onChange={(event) => setYear(event.target.value)} />
          </Field>
          <Field label="Discount (%)" required error={fieldErrors.discount_pct}>
            <Input
              inputMode="decimal"
              value={discountPct}
              placeholder="2.5"
              onChange={(event) => setDiscountPct(event.target.value)}
            />
          </Field>
          <Field label="Basis" error={fieldErrors.basis}>
            <Select value={basis} onValueChange={(value) => setBasis(value as SupplierAgreementBasis)}>
              <SelectTrigger aria-label="Basis">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {BASIS_OPTIONS.map((option) => (
                  <SelectItem key={option} value={option}>
                    {BASIS_LABELS[option]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Review date" error={fieldErrors.review_date}>
            <Input type="date" value={reviewDate} onChange={(event) => setReviewDate(event.target.value)} />
          </Field>
        </div>
        <Field label="Notes" className="mt-3" error={fieldErrors.notes}>
          <Textarea value={notes} onChange={(event) => setNotes(event.target.value)} />
        </Field>
        <div className="mt-3 flex justify-end">
          <Button
            size="sm"
            onClick={() => addMutation.mutate()}
            disabled={addMutation.isPending || !canSubmit}
          >
            {addMutation.isPending ? 'Adding…' : 'Add agreement'}
          </Button>
        </div>
      </div>
    </div>
  )
}

interface AgreementsTableProps {
  agreements: SupplierAgreement[] | undefined
  isLoading: boolean
  error: unknown
  onRetry: () => void
  onDelete: (agreementId: number) => void
}

function AgreementsTable({ agreements, isLoading, error, onRetry, onDelete }: AgreementsTableProps) {
  if (isLoading) {
    return <p className="py-4 text-center text-sm text-muted-foreground">Loading agreements…</p>
  }
  if (error) return <ErrorState error={error} onRetry={onRetry} />
  if (!agreements || agreements.length === 0) {
    return <EmptyState title="No agreements" description="No yearly agreement recorded yet." />
  }
  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead className="bg-muted/40 text-xs text-muted-foreground">
          <tr>
            <th className="px-3 py-2 text-left font-medium">Year</th>
            <th className="px-3 py-2 text-right font-medium">Discount</th>
            <th className="px-3 py-2 text-left font-medium">Basis</th>
            <th className="px-3 py-2 text-left font-medium">Review date</th>
            <th className="px-3 py-2 text-left font-medium">Notes</th>
            <th className="px-3 py-2" />
          </tr>
        </thead>
        <tbody>
          {agreements.map((agreement) => (
            <tr key={agreement.id} className="border-t border-border">
              <td className="px-3 py-2 font-medium tabular-nums">{agreement.year}</td>
              <td className="px-3 py-2 text-right tabular-nums">{Number(agreement.discount_pct)}%</td>
              <td className="px-3 py-2">{BASIS_LABELS[agreement.basis]}</td>
              <td className="px-3 py-2">{formatDate(agreement.review_date)}</td>
              <td className="px-3 py-2 text-muted-foreground">{agreement.notes ?? EMPTY_PLACEHOLDER}</td>
              <td className="px-3 py-2 text-right">
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={`Delete ${agreement.year} agreement`}
                  onClick={() => onDelete(agreement.id)}
                >
                  <Trash2 className="h-4 w-4 text-critical" />
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
