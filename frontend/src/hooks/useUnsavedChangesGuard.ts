/**
 * Guards a page that holds unsaved edits.
 *
 * Usage:
 *   const guard = useUnsavedChangesGuard(isDirty)
 *   // replace in-page state only after the user agrees:
 *   guard.confirmDiscard(() => setKey(nextKey))
 *   // render the prompt once per page:
 *   <UnsavedChangesDialog guard={guard} />
 *
 * While `isDirty` is true:
 * - any react-router navigation that changes the path or query string (sidebar
 *   links, back/forward, navigate()) is held and the prompt asks Stay / Leave;
 * - closing the tab, reloading or typing a new URL triggers the browser's own
 *   leave-page prompt.
 * `confirmDiscard(onProceed)` runs `onProceed` at once when not dirty, otherwise
 * after the user picks Leave. A navigation `onProceed` starts synchronously
 * (e.g. setSearchParams) is let through without a second prompt.
 * Only one page may use this hook at a time (react-router allows one blocker).
 */
import * as React from 'react'
import { useBlocker, type BlockerFunction } from 'react-router-dom'

export interface UnsavedChangesGuard {
  isPromptOpen: boolean
  confirmDiscard: (onProceed: () => void) => void
  stay: () => void
  leave: () => void
}

export function useUnsavedChangesGuard(isDirty: boolean): UnsavedChangesGuard {
  const [pendingDiscard, setPendingDiscard] = React.useState<(() => void) | null>(null)
  const isDiscardRunningRef = React.useRef(false)

  const shouldBlockNavigation = React.useCallback<BlockerFunction>(
    ({ currentLocation, nextLocation }) => {
      const pageChanged =
        currentLocation.pathname !== nextLocation.pathname ||
        currentLocation.search !== nextLocation.search
      return isDirty && pageChanged && !isDiscardRunningRef.current
    },
    [isDirty],
  )
  const blocker = useBlocker(shouldBlockNavigation)

  React.useEffect(() => {
    if (!isDirty) return
    const warnBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      // Older Chrome/Edge show the prompt only when returnValue is set.
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', warnBeforeUnload)
    return () => window.removeEventListener('beforeunload', warnBeforeUnload)
  }, [isDirty])

  const confirmDiscard = React.useCallback(
    (onProceed: () => void) => {
      if (isDirty) {
        setPendingDiscard(() => onProceed)
        return
      }
      onProceed()
    },
    [isDirty],
  )

  function stay() {
    if (blocker.state === 'blocked') blocker.reset()
    setPendingDiscard(null)
  }

  function leave() {
    if (blocker.state === 'blocked') blocker.proceed()
    if (pendingDiscard === null) return
    setPendingDiscard(null)
    isDiscardRunningRef.current = true
    try {
      pendingDiscard()
    } finally {
      isDiscardRunningRef.current = false
    }
  }

  return {
    isPromptOpen: blocker.state === 'blocked' || pendingDiscard !== null,
    confirmDiscard,
    stay,
    leave,
  }
}
