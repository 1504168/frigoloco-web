import * as React from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Copy, Target } from 'lucide-react'
import { EmptyState } from '@/components/shared/EmptyState'
import { WithInfoHint, type Hint } from '@/components/shared/InfoHint'
import { ErrorState } from '@/components/shared/ErrorState'
import { LoadingSkeleton } from '@/components/shared/LoadingSkeleton'
import { Modal } from '@/components/shared/Modal'
import { SaveIconButton } from '@/components/shared/SaveIconButton'
import { Toolbar } from '@/components/shared/Toolbar'
import { UnsavedChangesDialog } from '@/components/shared/UnsavedChangesDialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { toast } from '@/components/ui/toast'
import { useUnsavedChangesGuard } from '@/hooks/useUnsavedChangesGuard'
import { ApiError } from '@/lib/api'
import { useFridgeMap } from '@/pages/ops/lib/reference'
import { FridgeSelect, type FridgeOption } from '@/pages/ops/targets/FridgeSelect'
import {
  copyFridgeTargets,
  saveFridgeTargets,
  TARGETS_QUERY_KEY,
  useFridgeTargets,
  useTargetCategories,
  type ProductTarget,
  type TargetItem,
} from '@/pages/ops/targets/targetsApi'

// Typed target text per product id; a blank (or 0) box means "no target".
type TargetDraft = Map<number, string>

const COPY_FROM_FRIDGE_HINT: Hint = {
  text:
    "Replaces this fridge's targets with a copy of another fridge's targets. The copy is saved " +
    "right away.",
  example:
    'Copy from "Thermofisher" to start a new fridge with the same 30 snack and drink targets.',
}
const NO_TARGET_HINT =
  'Snacks and Drinks of this fridge are refilled up to their target on Menu import ' +
  '(target minus the units in the fridge). Leave a box empty for no target.'

/** Per-fridge refill targets for Snacks and Drinks, with a copy from another fridge. */
export function TargetsPage() {
  const queryClient = useQueryClient()
  const fridgeMapQuery = useFridgeMap()
  const categoriesQuery = useTargetCategories()
  const [fridgeId, setFridgeId] = React.useState<number | null>(null)
  // null = nothing typed yet for this fridge: the saved targets are shown.
  const [editedDraft, setEditedDraft] = React.useState<TargetDraft | null>(null)
  const [copyOpen, setCopyOpen] = React.useState(false)
  const [copySourceId, setCopySourceId] = React.useState<number | null>(null)
  const targetsQuery = useFridgeTargets(fridgeId)

  const savedDraft = draftFromTargets(targetsQuery.data ?? [])
  const shownDraft = editedDraft ?? savedDraft
  const isDirty = editedDraft !== null && draftSignature(editedDraft) !== draftSignature(savedDraft)
  const guard = useUnsavedChangesGuard(isDirty)

  const fridgeOptions = sortedFridgeOptions(fridgeMapQuery.data ?? new Map())
  const copySourceOptions = fridgeOptions.filter((option) => option.fridgeId !== fridgeId)
  const fridgeName = (id: number) => fridgeMapQuery.data?.get(id) ?? `Fridge #${id}`

  function showSavedTargets(targetFridgeId: number, targets: ProductTarget[]) {
    queryClient.setQueryData([...TARGETS_QUERY_KEY, 'fridge', targetFridgeId], targets)
    setEditedDraft(null)
  }

  const saveMutation = useMutation({
    mutationFn: (targetFridgeId: number) =>
      saveFridgeTargets(targetFridgeId, targetItemsOf(shownDraft)),
    onSuccess: (targets, targetFridgeId) => {
      showSavedTargets(targetFridgeId, targets)
      toast.success(`Saved ${targets.length} targets for ${fridgeName(targetFridgeId)}`)
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Failed to save the targets'),
  })

  const copyMutation = useMutation({
    mutationFn: ({ fromId, toId }: { fromId: number; toId: number }) =>
      copyFridgeTargets(fromId, toId),
    onSuccess: (targets, { fromId, toId }) => {
      showSavedTargets(toId, targets)
      setCopyOpen(false)
      toast.success(`Copied ${targets.length} targets from ${fridgeName(fromId)}`)
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Failed to copy the targets'),
  })

  function handleFridgeChange(nextFridgeId: number) {
    guard.confirmDiscard(() => {
      setFridgeId(nextFridgeId)
      setEditedDraft(null)
    })
  }

  function handleTargetChange(productId: number, typedText: string) {
    const digitsOnly = typedText.replace(/\D/g, '')
    setEditedDraft(new Map(shownDraft).set(productId, digitsOnly))
  }

  function handleSave() {
    if (fridgeId === null) return
    saveMutation.mutate(fridgeId)
  }

  function handleCopy() {
    if (fridgeId === null || copySourceId === null) return
    copyMutation.mutate({ fromId: copySourceId, toId: fridgeId })
  }

  function renderTargets() {
    if (categoriesQuery.isError) {
      return (
        <ErrorState
          title="Failed to load the Snacks and Drinks products"
          error={categoriesQuery.error}
          onRetry={() => categoriesQuery.refetch()}
        />
      )
    }
    if (targetsQuery.isError) {
      return (
        <ErrorState
          title="Failed to load this fridge's targets"
          error={targetsQuery.error}
          onRetry={() => targetsQuery.refetch()}
        />
      )
    }
    if (fridgeId === null) {
      return (
        <EmptyState
          icon={<Target className="h-8 w-8" />}
          title="Pick a fridge"
          description={NO_TARGET_HINT}
        />
      )
    }
    if (!categoriesQuery.data || !targetsQuery.data) return <LoadingSkeleton rows={8} columns={3} />
    return (
      <div className="grid gap-3 lg:grid-cols-2">
        {categoriesQuery.data.map((category) => (
          <section
            key={category.category_id}
            className="rounded-xl border border-border bg-card p-3"
          >
            <h2 className="mb-2 text-sm font-semibold text-foreground">{category.category_name}</h2>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Code</TableHead>
                  <TableHead>Product</TableHead>
                  <TableHead className="w-28 text-right">Target qty</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {category.products.map((product) => (
                  <TableRow key={product.product_id}>
                    <TableCell className="text-muted-foreground">{product.product_code}</TableCell>
                    <TableCell>{product.product_name}</TableCell>
                    <TableCell className="text-right">
                      <Input
                        inputMode="numeric"
                        aria-label={`Target for ${product.product_name}`}
                        className="h-8 w-20 text-right tabular-nums"
                        value={shownDraft.get(product.product_id) ?? ''}
                        onChange={(event) =>
                          handleTargetChange(product.product_id, event.target.value)
                        }
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </section>
        ))}
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <Toolbar
        left={
          <FridgeSelect
            options={fridgeOptions}
            value={fridgeId}
            onChange={handleFridgeChange}
            placeholder="Choose a fridge"
          />
        }
        right={
          <>
            <WithInfoHint hint={COPY_FROM_FRIDGE_HINT}>
              <Button
                variant="outline"
                size="sm"
                className="h-9"
                onClick={() => guard.confirmDiscard(() => setCopyOpen(true))}
                disabled={fridgeId === null}
              >
                <Copy className="h-4 w-4" />
                Copy from fridge
              </Button>
            </WithInfoHint>
            <SaveIconButton
              label="Save targets"
              onClick={handleSave}
              disabled={fridgeId === null || !isDirty}
              isSaving={saveMutation.isPending}
            />
          </>
        }
      />

      {fridgeId !== null ? <p className="text-xs text-muted-foreground">{NO_TARGET_HINT}</p> : null}
      {renderTargets()}

      <Modal
        open={copyOpen}
        onClose={() => setCopyOpen(false)}
        title="Copy targets from another fridge"
        description={
          fridgeId !== null
            ? `Every target of ${fridgeName(fridgeId)} is replaced by the copied ones.`
            : undefined
        }
        footer={
          <>
            <Button
              variant="outline"
              onClick={() => setCopyOpen(false)}
            >
              Cancel
            </Button>
            <Button
              onClick={handleCopy}
              disabled={copySourceId === null || copyMutation.isPending}
            >
              {copyMutation.isPending ? 'Copying…' : 'Copy targets'}
            </Button>
          </>
        }
      >
        <FridgeSelect
          options={copySourceOptions}
          value={copySourceId}
          onChange={setCopySourceId}
          placeholder="Copy from…"
        />
      </Modal>

      <UnsavedChangesDialog guard={guard} />
    </div>
  )
}

export default TargetsPage

function draftFromTargets(targets: ProductTarget[]): TargetDraft {
  return new Map(targets.map((target) => [target.product_id, String(target.target_qty)]))
}

function targetItemsOf(draft: TargetDraft): TargetItem[] {
  const items: TargetItem[] = []
  for (const [productId, typedText] of draft) {
    const targetQty = Number(typedText)
    if (targetQty > 0) items.push({ product_id: productId, target_qty: targetQty })
  }
  return items
}

/** Order-independent fingerprint of the targets that would be saved. */
function draftSignature(draft: TargetDraft): string {
  const targetKeys = targetItemsOf(draft).map((item) => `${item.product_id}:${item.target_qty}`)
  return targetKeys.sort().join('|')
}

function sortedFridgeOptions(fridgeNames: Map<number, string>): FridgeOption[] {
  const options = [...fridgeNames].map(([fridgeId, name]) => ({ fridgeId, name }))
  return options.sort((first, second) => first.name.localeCompare(second.name))
}
