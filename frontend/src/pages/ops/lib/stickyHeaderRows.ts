import * as React from 'react'

/** Height of the grid box: the screen minus the page toolbar and summary above it. */
export const STICKY_GRID_BOX_CLASS = 'max-h-[calc(100vh-13rem)] overflow-auto'

/** Zebra-striped fridge row of the planning and forecast grids. */
export const FRIDGE_ROW_CLASS = 'group even:bg-muted hover:bg-accent'
/** Sticky cells are opaque so scrolled cells do not show through; they repeat the row shade. */
export const FRIDGE_ROW_STICKY_CELL_CLASS = 'group-even:bg-muted group-hover:bg-accent'
/** Marks a fridge name that carries a site-preferences hover note. */
export const FRIDGE_PREFERENCES_HINT_CLASS = 'cursor-help underline decoration-dotted'

/**
 * Keeps several table header rows stuck to the top of the grid's scroll box.
 * Each row sticks just below the rows above it, so it needs their live heights
 * (product names wrap, so the heights change with the data).
 */
export function useStickyHeaderRows(rowCount: number) {
  const rowsByIndex = React.useRef(new Map<number, HTMLTableRowElement>())
  const observerRef = React.useRef<ResizeObserver | null>(null)
  const [rowHeights, setRowHeights] = React.useState<number[]>([])

  React.useLayoutEffect(() => {
    function measureRows() {
      const heights = Array.from(
        { length: rowCount },
        (_, index) => rowsByIndex.current.get(index)?.offsetHeight ?? 0,
      )
      setRowHeights(heights)
    }
    const observer = new ResizeObserver(measureRows)
    for (const row of rowsByIndex.current.values()) observer.observe(row)
    observerRef.current = observer
    return () => {
      observer.disconnect()
      observerRef.current = null
    }
  }, [rowCount])

  function rowRef(index: number) {
    return (row: HTMLTableRowElement | null) => {
      if (row === null) {
        rowsByIndex.current.delete(index)
        return
      }
      rowsByIndex.current.set(index, row)
      // Rows that mount after the effect (e.g. once data loads) are observed here.
      observerRef.current?.observe(row)
    }
  }

  function stickyTop(index: number): React.CSSProperties {
    const heightsAbove = rowHeights.slice(0, index)
    const top = heightsAbove.reduce((sum, height) => sum + height, 0)
    return { top }
  }

  return { rowRef, stickyTop }
}
