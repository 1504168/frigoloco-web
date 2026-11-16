import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { api } from '@/lib/api'
import type { Product } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Dialog } from '@/pages/supply/components/Dialog'
import {
  Field,
  fieldErrorsFromApiError,
  generalErrorMessage,
} from '@/pages/supply/components/form'
import { productTagLabel, useProductTagOptions } from '@/pages/supply/components/masterLookups'

const WHOLE_NUMBER_PATTERN = /^\d+$/
const INVALID_NUMBER_MESSAGE = 'Enter a whole number, or leave empty.'
const MIN_STOCK_HINT =
  'Below this many units in the warehouse, a Low stock alert opens. Empty = no minimum.'
const PRINT_ORDER_HINT =
  'Position on the printed dispatch sheet inside its category (1 first). ' +
  'Empty = after the numbered products.'
const TAGS_HINT =
  'Client rules exclude products by tag, e.g. a client with "no pork" gets a warning ' +
  'for products tagged Contains pork.'
const CUSTOM_TAG_PATTERN = /^[a-z0-9_ -]+$/i

interface ProductSettingsDialogProps {
  product: Product
  onClose: () => void
  onSuccess: (product: Product) => void
}

/** Edit the local-only product settings: warehouse minimum, print order and product tags. */
export function ProductSettingsDialog({ product, onClose, onSuccess }: ProductSettingsDialogProps) {
  const queryClient = useQueryClient()
  const tagsUrl = `/api/v1/products/${product.id}/tags`
  const savedTagsQuery = useQuery({
    queryKey: ['masters', 'product-tags', product.id],
    queryFn: ({ signal }) => api.get<string[]>(tagsUrl, { signal }),
  })
  const tagOptionsQuery = useProductTagOptions()
  const [editedTags, setEditedTags] = React.useState<string[] | null>(null)
  const selectedTags = editedTags ?? savedTagsQuery.data ?? []

  const [minStockInput, setMinStockInput] = React.useState(
    formatOptionalNumber(product.min_stock_qty),
  )
  const [printOrderInput, setPrintOrderInput] = React.useState(
    formatOptionalNumber(product.print_order),
  )

  const minStockQty = parseOptionalWholeNumber(minStockInput)
  const printOrder = parseOptionalWholeNumber(printOrderInput)
  const hasInvalidInput = minStockQty === undefined || printOrder === undefined

  const mutation = useMutation({
    mutationFn: async () => {
      const updatedProduct = await api.put<Product>(`/api/v1/products/${product.id}`, {
        min_stock_qty: minStockQty,
        print_order: printOrder,
      })
      if (editedTags !== null) await api.put<string[]>(tagsUrl, { tags: editedTags })
      return updatedProduct
    },
    onSuccess: (updatedProduct) => {
      queryClient.invalidateQueries({ queryKey: ['masters', 'product-tags', product.id] })
      queryClient.invalidateQueries({ queryKey: ['supply', 'product-tags'] })
      onSuccess(updatedProduct)
    },
  })

  const fieldErrors = fieldErrorsFromApiError(mutation.error)
  const generalError =
    mutation.error && Object.keys(fieldErrors).length === 0
      ? generalErrorMessage(mutation.error)
      : null

  return (
    <Dialog
      open
      onClose={onClose}
      title={product.name}
      description={`Code ${product.code}. These settings are local: the Husky sync never changes them.`}
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending || hasInvalidInput}
          >
            {mutation.isPending ? 'Saving…' : 'Save changes'}
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
        <Field
          label="Minimum warehouse stock"
          error={minStockQty === undefined ? INVALID_NUMBER_MESSAGE : fieldErrors.min_stock_qty}
          hint={MIN_STOCK_HINT}
        >
          <Input
            inputMode="numeric"
            value={minStockInput}
            onChange={(event) => setMinStockInput(event.target.value)}
          />
        </Field>
        <Field
          label="Print order"
          error={printOrder === undefined ? INVALID_NUMBER_MESSAGE : fieldErrors.print_order}
          hint={PRINT_ORDER_HINT}
        >
          <Input
            inputMode="numeric"
            value={printOrderInput}
            onChange={(event) => setPrintOrderInput(event.target.value)}
          />
        </Field>
        <Field label="Product tags" error={fieldErrors.tags} hint={TAGS_HINT}>
          <ProductTagPicker
            tagOptions={tagOptionsQuery.data ?? []}
            selectedTags={selectedTags}
            isLoading={savedTagsQuery.isLoading}
            onChange={setEditedTags}
          />
        </Field>
      </div>
    </Dialog>
  )
}

interface ProductTagPickerProps {
  tagOptions: string[]
  selectedTags: string[]
  isLoading: boolean
  onChange: (tags: string[]) => void
}

/** Toggle chips for the known tags, plus a box to add a new tag. */
function ProductTagPicker({ tagOptions, selectedTags, isLoading, onChange }: ProductTagPickerProps) {
  const [customTag, setCustomTag] = React.useState('')
  if (isLoading) return <p className="text-xs text-muted-foreground">Loading tags…</p>

  const shownTags = [...new Set([...tagOptions, ...selectedTags])].sort()
  const toggleTag = (tag: string) => {
    const isSelected = selectedTags.includes(tag)
    onChange(isSelected ? selectedTags.filter((selected) => selected !== tag) : [...selectedTags, tag])
  }
  const normalizedCustomTag = normalizeTag(customTag)
  const canAddCustomTag = CUSTOM_TAG_PATTERN.test(customTag.trim())
  const addCustomTag = () => {
    if (!selectedTags.includes(normalizedCustomTag)) onChange([...selectedTags, normalizedCustomTag])
    setCustomTag('')
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1.5">
        {shownTags.map((tag) => (
          <button
            key={tag}
            type="button"
            aria-pressed={selectedTags.includes(tag)}
            onClick={() => toggleTag(tag)}
            className={cn(
              'rounded-full border px-2.5 py-1 text-xs font-medium transition-colors',
              selectedTags.includes(tag)
                ? 'border-primary bg-primary text-primary-foreground'
                : 'border-border text-muted-foreground hover:text-foreground',
            )}
          >
            {productTagLabel(tag)}
          </button>
        ))}
      </div>
      <div className="flex gap-2">
        <Input
          value={customTag}
          placeholder="New tag, e.g. contains fish"
          aria-label="New product tag"
          onChange={(event) => setCustomTag(event.target.value)}
        />
        <Button variant="outline" size="sm" onClick={addCustomTag} disabled={!canAddCustomTag}>
          Add tag
        </Button>
      </div>
    </div>
  )
}

/** Mirrors normalize_tag in the backend: "Contains fish" -> "contains_fish". */
function normalizeTag(text: string): string {
  return text.trim().toLowerCase().replace(/[\s-]+/g, '_')
}

function formatOptionalNumber(value: number | null): string {
  return value === null ? '' : String(value)
}

/** Empty -> null (clears the setting); a whole number -> that number; anything else -> undefined. */
function parseOptionalWholeNumber(text: string): number | null | undefined {
  const trimmed = text.trim()
  if (trimmed === '') return null
  if (!WHOLE_NUMBER_PATTERN.test(trimmed)) return undefined
  return Number(trimmed)
}
