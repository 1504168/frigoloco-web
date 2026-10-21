import * as React from 'react'
import type { UseMutationResult } from '@tanstack/react-query'

/**
 * Returns a submit function that ignores repeat calls until the mutation settles.
 * TanStack reports `isPending` a tick late, so a double click would otherwise send
 * the request twice before the button disables.
 */
export function useSingleSubmit<TData, TError, TVariables>(
  mutation: UseMutationResult<TData, TError, TVariables>,
): (variables: TVariables) => void {
  const isInFlightRef = React.useRef(false)
  const { mutate } = mutation
  return React.useCallback(
    (variables: TVariables) => {
      if (isInFlightRef.current) return
      isInFlightRef.current = true
      mutate(variables, {
        onSettled: () => {
          isInFlightRef.current = false
        },
      })
    },
    [mutate],
  )
}
