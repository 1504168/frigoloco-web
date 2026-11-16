import type * as React from 'react'
import { Info } from 'lucide-react'

/** Short explanation of a control plus one worked example, shown by InfoHint. */
export interface Hint {
  text: string
  example?: string
}

/** Small "i" icon that explains the control next to it on hover (and to screen readers). */
export function InfoHint({ text, example }: Hint) {
  const hint = example ? `${text}\nExample: ${example}` : text
  return (
    <span title={hint} aria-label={hint} role="img" className="inline-flex cursor-help">
      <Info className="h-3.5 w-3.5 opacity-70" />
    </span>
  )
}

interface WithInfoHintProps {
  hint: Hint
  children: React.ReactNode
}

/**
 * Puts the "i" icon right after a button. It sits outside the button so the hint still
 * shows while the button is disabled.
 */
export function WithInfoHint({ hint, children }: WithInfoHintProps) {
  return (
    <span className="inline-flex items-center gap-1">
      {children}
      <InfoHint {...hint} />
    </span>
  )
}
