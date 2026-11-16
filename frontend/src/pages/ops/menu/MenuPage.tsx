import * as React from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Copy, Download, LayoutGrid, Plus, Sparkles } from 'lucide-react'
import { SaveIconButton } from '@/components/shared/SaveIconButton'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { EmptyState } from '@/components/shared/EmptyState'
import { WithInfoHint, type Hint } from '@/components/shared/InfoHint'
import { ErrorState } from '@/components/shared/ErrorState'
import { LoadingSkeleton } from '@/components/shared/LoadingSkeleton'
import { Modal } from '@/components/shared/Modal'
import { Toolbar } from '@/components/shared/Toolbar'
import { UnsavedChangesDialog } from '@/components/shared/UnsavedChangesDialog'
import { Button } from '@/components/ui/button'
import { toast } from '@/components/ui/toast'
import { useUnsavedChangesGuard, type DiscardPrompt } from '@/hooks/useUnsavedChangesGuard'
import { api, ApiError } from '@/lib/api'
import { AddProductPicker } from '@/pages/ops/components/AddProductPicker'
import { CategoryScopeSelect } from '@/pages/ops/components/CategoryScopeSelect'
import { PlanningGrid } from '@/pages/ops/components/PlanningGrid'
import { WeekDayPicker } from '@/pages/ops/components/WeekDayPicker'
import { StockFitNotice } from '@/pages/ops/dispatch/StockFitNotice'
import { usePlanningGridState, useProductMeta } from '@/pages/ops/lib/grid'
import { useWeekDayKey, weekKeyLabel, type WeekDayKey } from '@/pages/ops/lib/pipelineKey'
import {
  useCategories,
  useCategoryName,
  useProductCatalogue,
  useSupplierMap,
} from '@/pages/ops/lib/reference'
import { useStockDetailRows } from '@/pages/ops/lib/stockDetailRows'
import type {
  MenuGrid,
  MenuImport,
  MenuImportRequest,
  WeekMenu,
} from '@/pages/ops/lib/types'
import { CloneWeekDialog } from '@/pages/ops/menu/CloneWeekDialog'
import {
  adjustmentsOfImport,
  buildCellHints,
  describeShelfLifeHold,
  describeSpeedAdjustment,
  mergeCategoryAdjustments,
  NO_IMPORT_ADJUSTMENTS,
} from '@/pages/ops/menu/importAdjustments'
import { MenuImportOptions, type MenuImportChoices } from '@/pages/ops/menu/MenuImportOptions'
import { MenuImportNotice } from '@/pages/ops/menu/MenuImportNotice'
import { MenuSummary } from '@/pages/ops/menu/MenuSummary'
import {
  menuKeyParams,
  SAVED_MENU_QUERY_KEY,
  useMenuForKey,
} from '@/pages/ops/menu/menuApi'
import { computeMenuTotals } from '@/pages/ops/menu/menuTotals'
import { ensureSavedForecast, tomorrowKey } from '@/pages/ops/menu/suggestForTomorrow'

const NOT_FOUND_STATUS = 404
const EXISTS_ERROR_CODE = 'exists'
// A fresh Monday restarts every fridge from the forecast, so the import options start off there.
const FRESH_START_DAY = 'Monday'
const FORECAST_IMPORT_PROMPT: DiscardPrompt = {
  description: 'Import from Forecast replaces the quantities you typed. Continue?',
  confirmLabel: 'Import',
  cancelLabel: 'Cancel',
}
const LOAD_SAVED_PROMPT: DiscardPrompt = {
  description: 'Loading the saved menu discards your unsaved edits. Continue?',
  confirmLabel: 'Load',
  cancelLabel: 'Cancel',
}
const SUGGEST_TOMORROW_HINT: Hint = {
  text:
    "Opens tomorrow's menu, runs and saves its forecast if none is saved yet, then imports " +
    'it with the default options. Nothing is saved until you press Save.',
  example: 'On Monday it opens Tuesday, fills every fridge from the forecast, ready to review.',
}
const CLONE_WEEK_HINT: Hint = {
  text: "Copies another week's menu products into this week's menu. Review, then Save.",
  example: 'Clone W46 into W48 to start from the same 40 products.',
}
const NO_FRIDGES_HINT =
  'Set delivery days on the fridges, import from the saved forecast, ' +
  'or add products to start this menu.'

interface ForecastImport {
  request: MenuImportRequest
  // null = whole menu; a category id merges only that category into the grid.
  categoryId: number | null
}

function keyId(key: WeekDayKey): string {
  return `${key.year}-${key.week}-${key.dayName}`
}

/** The import options a day starts with (all off on a fresh Monday). */
function defaultImportChoices(key: WeekDayKey): MenuImportChoices {
  const isFreshStartDay = key.dayName === FRESH_START_DAY
  return {
    soldFirst: !isFreshStartDay,
    useFridgeStock: !isFreshStartDay,
    salesSpeed: !isFreshStartDay,
    fitToStock: false,
  }
}

export function MenuPage() {
  const { key, setKey } = useWeekDayKey()
  const grid = usePlanningGridState()
  const guard = useUnsavedChangesGuard(grid.isDirty)
  const queryClient = useQueryClient()
  const { meta: productMeta, isLoading: metaLoading } = useProductMeta()

  const supplierMapQuery = useSupplierMap()
  const catalogueQuery = useProductCatalogue()
  const categoriesQuery = useCategories()
  const stockDetailRows = useStockDetailRows()
  const keyMenuQuery = useMenuForKey(key)

  // The key whose menu the grid currently holds; null while the next key loads.
  const [loadedKeyId, setLoadedKeyId] = React.useState<string | null>(null)
  const [overwriteOpen, setOverwriteOpen] = React.useState(false)
  const [addOpen, setAddOpen] = React.useState(false)
  const [cloneOpen, setCloneOpen] = React.useState(false)
  // null = the day's default (off on a fresh Monday, on otherwise) until the user flips it.
  const [soldFirstChoice, setSoldFirstChoice] = React.useState<boolean | null>(null)
  const [useFridgeStockChoice, setUseFridgeStockChoice] = React.useState<boolean | null>(null)
  const [salesSpeedChoice, setSalesSpeedChoice] = React.useState<boolean | null>(null)
  const [fitToStock, setFitToStock] = React.useState(false)
  // Set when "Suggest for tomorrow" switched the key: the suggestion runs once it is loaded.
  const [isSuggestionWaitingForKey, setIsSuggestionWaitingForKey] = React.useState(false)
  const [importAdjustments, setImportAdjustments] = React.useState(NO_IMPORT_ADJUSTMENTS)
  // null = whole menu; a category id scopes pull/save to that one category.
  const [scopeCategoryId, setScopeCategoryId] = React.useState<number | null>(null)

  const scopeCategoryName = useCategoryName(scopeCategoryId)
  const dayDefaults = defaultImportChoices(key)
  const importChoices: MenuImportChoices = {
    soldFirst: soldFirstChoice ?? dayDefaults.soldFirst,
    useFridgeStock: useFridgeStockChoice ?? dayDefaults.useFridgeStock,
    salesSpeed: salesSpeedChoice ?? dayDefaults.salesSpeed,
    fitToStock,
  }
  const currentKeyId = keyId(key)
  const isKeyLoaded = loadedKeyId === currentKeyId

  const { loadFromGrid } = grid
  React.useEffect(() => {
    if (isKeyLoaded || keyMenuQuery.isFetching || !keyMenuQuery.data) return
    loadFromGrid(keyMenuQuery.data)
    setLoadedKeyId(currentKeyId)
  }, [isKeyLoaded, keyMenuQuery.isFetching, keyMenuQuery.data, currentKeyId, loadFromGrid])

  const supplierName = React.useCallback(
    (id: number) => supplierMapQuery.data?.get(id) ?? `Supplier #${id}`,
    [supplierMapQuery.data],
  )
  const categoryLabel = React.useCallback(
    (categoryId: number) => categoriesQuery.data?.byId.get(categoryId) ?? `Category #${categoryId}`,
    [categoriesQuery.data],
  )
  const fridgeNameById = new Map(
    grid.fridges.map((fridge) => [fridge.fridge_id, fridge.friendly_name]),
  )
  const fridgeLabel = (fridgeId: number) => fridgeNameById.get(fridgeId) ?? `Fridge #${fridgeId}`

  function buildImportRequest(choices: MenuImportChoices): MenuImportRequest {
    const importRequest: MenuImportRequest = {
      sold_first: choices.soldFirst,
      use_fridge_stock: choices.useFridgeStock,
      sales_speed: choices.salesSpeed,
      fit_to_stock: choices.fitToStock,
    }
    // The products on screen are the week menu, including unsaved additions.
    if (grid.productIds.size > 0) importRequest.product_ids = [...grid.productIds]
    return importRequest
  }

  const importMutation = useMutation({
    mutationFn: ({ request, categoryId }: ForecastImport) =>
      api.post<MenuImport>('/api/v1/menus/import-from-forecast', request, {
        params: {
          ...menuKeyParams(key),
          ...(categoryId !== null ? { category_id: categoryId } : {}),
        },
      }),
    onSuccess: (result, { request, categoryId }) => {
      if (categoryId !== null) {
        const scopedProductIds = grid.categoryProductIds(categoryId)
        setImportAdjustments((previous) =>
          mergeCategoryAdjustments(previous, result, categoryId, scopedProductIds),
        )
        grid.mergeCategoryFromGrid(result.grid, categoryId)
      } else {
        setImportAdjustments(adjustmentsOfImport(result))
        grid.loadFromGrid(result.grid, { isUnsaved: true })
      }
      toast.success(describeImport(result))
      if (result.target_refill_fridge_ids.length > 0) {
        const fridgeCount = result.target_refill_fridge_ids.length
        toast.info(`Snacks and Drinks refilled to their targets in ${fridgeCount} fridges.`)
      }
      if (request.use_fridge_stock && !result.fridge_stock_applied) {
        toast.info('Fridge stock not used: only the next delivery can use the current stock.')
      }
      if (result.categories_without_products.length > 0) {
        const categoryNames = result.categories_without_products.map(categoryLabel)
        toast.warning(
          `No products chosen for ${categoryNames.join(', ')}: nothing imported there. ` +
            'Add products, or import that category alone for a rating suggestion.',
        )
      }
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === NOT_FOUND_STATUS) {
        toast.error('No saved forecast for this key - save a forecast first.')
      } else {
        toast.error(error instanceof ApiError ? error.message : 'Failed to import from forecast')
      }
    },
  })

  const loadSavedMutation = useMutation({
    mutationFn: () =>
      api.get<MenuGrid>('/api/v1/menus/saved', { params: menuKeyParams(key) }),
    onSuccess: (result) => {
      grid.loadFromGrid(result)
      setImportAdjustments(NO_IMPORT_ADJUSTMENTS)
      toast.success(`Loaded saved menu for ${weekKeyLabel(key)}`)
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === NOT_FOUND_STATUS) {
        toast.error('No saved menu for this key yet.')
      } else {
        toast.error(error instanceof ApiError ? error.message : 'Failed to load saved menu')
      }
    },
  })

  const saveMutation = useMutation({
    mutationFn: (overwrite: boolean) => {
      const scopedProductIds =
        scopeCategoryId !== null ? grid.categoryProductIds(scopeCategoryId) : null
      const lines = grid
        .toLines({ keepEmptyProducts: true })
        .filter(({ product_id }) => scopedProductIds === null || scopedProductIds.has(product_id))
        .map(({ fridge_id, product_id, qty }) => ({ fridge_id, product_id, qty }))
      return api.post<MenuGrid>('/api/v1/menus/save', {
        ...menuKeyParams(key),
        lines,
        overwrite,
        ...(scopeCategoryId !== null ? { category_id: scopeCategoryId } : {}),
      })
    },
    onSuccess: (result) => {
      // A category-scoped save keeps the other categories' unsaved edits on screen.
      if (scopeCategoryId !== null) {
        grid.mergeCategoryFromGrid(result, scopeCategoryId, { isSavedGrid: true })
      } else {
        grid.loadFromGrid(result)
      }
      void queryClient.invalidateQueries({ queryKey: SAVED_MENU_QUERY_KEY })
      toast.success(`Menu saved for ${weekKeyLabel(key)}; its products are now the week menu`)
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === EXISTS_ERROR_CODE) {
        setOverwriteOpen(true)
        return
      }
      toast.error(error instanceof ApiError ? error.message : 'Failed to save menu')
    },
  })

  function handleConfirmOverwrite() {
    // Closing first keeps a double click on Overwrite from sending two saves.
    setOverwriteOpen(false)
    saveMutation.mutate(true)
  }

  function handleKeyChange(nextKey: WeekDayKey, afterKeyChange?: () => void) {
    guard.confirmDiscard(() => {
      grid.reset()
      setLoadedKeyId(null)
      setSoldFirstChoice(null)
      setUseFridgeStockChoice(null)
      setSalesSpeedChoice(null)
      setImportAdjustments(NO_IMPORT_ADJUSTMENTS)
      setKey(nextKey)
      afterKeyChange?.()
    })
  }

  const suggestMutation = useMutation({
    mutationFn: () => ensureSavedForecast(key),
    onSuccess: (tomorrowForecast) => {
      if (tomorrowForecast === 'computed_and_saved') {
        toast.info(`No forecast was saved for ${weekKeyLabel(key)}: computed and saved one.`)
      }
      const suggestionImport: ForecastImport = {
        request: buildImportRequest(defaultImportChoices(key)),
        categoryId: null,
      }
      importMutation.mutate(suggestionImport)
    },
    onError: (error) => {
      const isNoDeliveryConfig = error instanceof ApiError && error.code === 'no_delivery_config'
      if (isNoDeliveryConfig) {
        toast.error('No fridge is delivered tomorrow, so there is nothing to suggest.')
        return
      }
      toast.error(error instanceof ApiError ? error.message : 'Failed to suggest a menu')
    },
  })

  const { mutate: suggestMenu } = suggestMutation
  React.useEffect(() => {
    if (!isSuggestionWaitingForKey || !isKeyLoaded) return
    setIsSuggestionWaitingForKey(false)
    suggestMenu()
  }, [isSuggestionWaitingForKey, isKeyLoaded, suggestMenu])

  function handleSuggestForTomorrow() {
    const nextKey = tomorrowKey()
    if (keyId(nextKey) === currentKeyId) {
      guard.confirmDiscard(() => suggestMutation.mutate(), FORECAST_IMPORT_PROMPT)
      return
    }
    handleKeyChange(nextKey, () => setIsSuggestionWaitingForKey(true))
  }

  function handleForecastImport() {
    const forecastImport: ForecastImport = {
      request: buildImportRequest(importChoices),
      categoryId: scopeCategoryId,
    }
    guard.confirmDiscard(() => importMutation.mutate(forecastImport), FORECAST_IMPORT_PROMPT)
  }

  function handleCloneWeek(weekMenu: WeekMenu) {
    grid.replaceProducts(weekMenu.categories)
    const productCount = weekMenu.categories.reduce(
      (count, category) => count + category.product_ids.length,
      0,
    )
    toast.success(`Cloned ${productCount} products from week ${weekMenu.week}. Adjust, then Save.`)
  }

  const gridLines = grid.toLines()
  const menuTotals = computeMenuTotals(gridLines, catalogueQuery.data?.byId ?? new Map())
  const cellHints = buildCellHints(importAdjustments, grid.orderedCategories, categoryLabel)
  const speedLines = importAdjustments.speedAdjustments.map((adjustment) => {
    const speedText = describeSpeedAdjustment(adjustment, categoryLabel(adjustment.category_id))
    return `${fridgeLabel(adjustment.fridge_id)} ${speedText}`
  })
  const staleStockFridgeNames = importAdjustments.staleStockFridgeIds.map(fridgeLabel)
  const productName = (productId: number) =>
    catalogueQuery.data?.byId.get(productId)?.name ?? `Product #${productId}`
  const shelfLifeLines = importAdjustments.shelfLifeHolds.map((hold) => {
    const holdText = describeShelfLifeHold(hold)
    return `${fridgeLabel(hold.fridge_id)} ${productName(hold.product_id)}: ${holdText}`
  })
  const defaultScoreProductNames = importAdjustments.defaultScoreProductIds.map(productName)
  const ruleViolationLines = importAdjustments.ruleViolations.map(
    (violation) =>
      `${fridgeLabel(violation.fridge_id)}: ${productName(violation.product_id)} (${violation.tag})`,
  )

  const isBusy =
    importMutation.isPending || loadSavedMutation.isPending || suggestMutation.isPending
  const isLoadingGrid = isBusy || !isKeyLoaded || metaLoading
  const canSave = grid.fridges.length > 0 && grid.productIds.size > 0

  function renderGridArea() {
    if (catalogueQuery.isError) {
      return (
        <ErrorState
          title="Failed to load the product catalogue"
          error={catalogueQuery.error}
          onRetry={() => catalogueQuery.refetch()}
        />
      )
    }
    if (keyMenuQuery.isError) {
      return (
        <ErrorState
          title="Failed to load the menu for this day"
          error={keyMenuQuery.error}
          onRetry={() => keyMenuQuery.refetch()}
        />
      )
    }
    if (isLoadingGrid) return <LoadingSkeleton rows={8} columns={8} />
    if (!grid.hasData) {
      return (
        <EmptyState
          icon={<LayoutGrid className="h-8 w-8" />}
          title="No fridge is delivered on this day"
          description={NO_FRIDGES_HINT}
        />
      )
    }
    return (
      <>
        <MenuImportNotice
          speedLines={speedLines}
          shelfLifeLines={shelfLifeLines}
          staleStockFridgeNames={staleStockFridgeNames}
          defaultScoreProductNames={defaultScoreProductNames}
          ruleViolationLines={ruleViolationLines}
        />
        <StockFitNotice
          cuts={importAdjustments.warehouseStockCuts}
          productName={productName}
        />
        <MenuSummary totals={menuTotals} />
        <PlanningGrid
          fridges={grid.fridges}
          categories={grid.orderedCategories}
          productMeta={productMeta}
          draft={grid.draft}
          onCellChange={grid.setCell}
          editedKeys={grid.editedKeys}
          extraDetailRows={stockDetailRows}
          onRemoveProduct={grid.removeProduct}
          cellHints={cellHints}
        />
      </>
    )
  }

  return (
    <div className="space-y-3">
      <Toolbar
        left={
          <>
            <WeekDayPicker
              value={key}
              onChange={handleKeyChange}
              compact
            />
            <CategoryScopeSelect
              value={scopeCategoryId}
              onChange={setScopeCategoryId}
            />
          </>
        }
        right={
          <>
            <Button
              variant="outline"
              size="sm"
              className="h-9"
              onClick={() => setAddOpen(true)}
              disabled={!catalogueQuery.data || !isKeyLoaded}
            >
              <Plus className="h-4 w-4" />
              Product
            </Button>
            <WithInfoHint hint={CLONE_WEEK_HINT}>
              <Button
                variant="outline"
                size="sm"
                className="h-9"
                onClick={() => setCloneOpen(true)}
                disabled={!isKeyLoaded}
              >
                <Copy className="h-4 w-4" />
                Clone week
              </Button>
            </WithInfoHint>
            <MenuImportOptions
              choices={importChoices}
              onSoldFirstChange={setSoldFirstChoice}
              onUseFridgeStockChange={setUseFridgeStockChoice}
              onSalesSpeedChange={setSalesSpeedChoice}
              onFitToStockChange={setFitToStock}
            />
            <WithInfoHint hint={SUGGEST_TOMORROW_HINT}>
              <Button
                variant="outline"
                size="sm"
                className="h-9"
                onClick={handleSuggestForTomorrow}
                disabled={suggestMutation.isPending || importMutation.isPending}
              >
                <Sparkles className="h-4 w-4" />
                {suggestMutation.isPending ? 'Suggesting…' : 'Suggest for tomorrow'}
              </Button>
            </WithInfoHint>
            <Button
              variant="outline"
              size="sm"
              className="h-9"
              onClick={handleForecastImport}
              disabled={importMutation.isPending || !isKeyLoaded}
              title="Import the saved forecast for this day"
            >
              <Download className="h-4 w-4" />
              {importMutation.isPending ? 'Importing…' : 'Forecast'}
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="h-9"
              title="Load the saved menu for this day"
              onClick={() =>
                guard.confirmDiscard(() => loadSavedMutation.mutate(), LOAD_SAVED_PROMPT)
              }
              disabled={loadSavedMutation.isPending || !isKeyLoaded}
            >
              <Download className="h-4 w-4" />
              {loadSavedMutation.isPending ? 'Loading…' : 'Load'}
            </Button>
            <SaveIconButton
              label="Save menu"
              onClick={() => saveMutation.mutate(false)}
              disabled={!canSave}
              isSaving={saveMutation.isPending}
            />
          </>
        }
      />

      {renderGridArea()}

      <Modal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        title="Add a product"
        className="max-w-lg"
        footer={
          <Button
            variant="outline"
            onClick={() => setAddOpen(false)}
          >
            Done
          </Button>
        }
      >
        {catalogueQuery.data ? (
          <AddProductPicker
            products={catalogueQuery.data.items}
            supplierName={supplierName}
            existingProductIds={grid.productIds}
            onAdd={(product) => {
              grid.addProduct(product)
              toast.success(`${product.name} added`)
            }}
          />
        ) : (
          <LoadingSkeleton rows={3} columns={2} />
        )}
      </Modal>

      {cloneOpen ? (
        <CloneWeekDialog
          open
          onClose={() => setCloneOpen(false)}
          targetKey={key}
          onClone={handleCloneWeek}
        />
      ) : null}

      <ConfirmDialog
        open={overwriteOpen}
        onClose={() => setOverwriteOpen(false)}
        onConfirm={handleConfirmOverwrite}
        title="Overwrite the saved menu?"
        description={describeMenuOverwrite(weekKeyLabel(key), scopeCategoryName)}
        confirmLabel="Overwrite"
        destructive
      />

      <UnsavedChangesDialog guard={guard} />
    </div>
  )
}

export default MenuPage

function describeMenuOverwrite(keyLabel: string, scopeCategoryName: string | null): string {
  const existing = `A saved menu already exists for ${keyLabel}. `
  if (scopeCategoryName === null) {
    return existing + 'Overwriting replaces its lines with the current grid.'
  }
  return (
    existing +
    `Overwriting replaces only its ${scopeCategoryName} lines with the current grid; ` +
    'the other categories stay as saved.'
  )
}

function describeImport(result: MenuImport): string {
  if (result.used_rating_suggestion) {
    return (
      'No products chosen yet: products suggested from ratings as a starting point. ' +
      'Remove what is not on the menu, then Save.'
    )
  }
  const productCount = result.grid.products.length
  if (result.sold_first) {
    return `Imported ${productCount} products: sold since the last delivery first, then by rating`
  }
  return `Imported ${productCount} products from the saved forecast, split by rating`
}
