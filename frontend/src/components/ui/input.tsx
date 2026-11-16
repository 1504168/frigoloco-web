import * as React from 'react'
import { cn } from '@/lib/utils'

export type InputProps = React.InputHTMLAttributes<HTMLInputElement>

const DECIMAL_TEXT = /^\d*\.?\d*$/
const SIGNED_DECIMAL_TEXT = /^-?\d*\.?\d*$/
const WHOLE_NUMBER_TEXT = /^\d*$/
const SIGNED_WHOLE_NUMBER_TEXT = /^-?\d*$/

/**
 * App policy: no number spinners. `type="number"` renders a plain text field
 * (no arrows, no mouse-wheel changes) that only accepts numeric typing.
 * A comma is read as a decimal point; a minus sign is allowed only when `min` is unset or negative;
 * a whole-number `step` (e.g. step={1}) allows whole numbers only.
 */
const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, ...props }, ref) => {
    const isNumber = type === 'number'
    const { min, max, step, onChange, inputMode, ...rest } = props
    const allowsNegative = min === undefined || Number(min) < 0
    const allowsDecimals = step === undefined || step === 'any' || !Number.isInteger(Number(step))
    const decimalPattern = allowsNegative ? SIGNED_DECIMAL_TEXT : DECIMAL_TEXT
    const wholeNumberPattern = allowsNegative ? SIGNED_WHOLE_NUMBER_TEXT : WHOLE_NUMBER_TEXT
    const numericPattern = allowsDecimals ? decimalPattern : wholeNumberPattern
    const numberInputMode = allowsDecimals ? 'decimal' : 'numeric'

    function handleNumberChange(event: React.ChangeEvent<HTMLInputElement>) {
      const field = event.target
      const typed = field.value.replace(',', '.')
      if (!numericPattern.test(typed)) {
        // Dropping the key silently turns "5.5" into "55"; say why the key was refused.
        field.setCustomValidity(rejectedKeyMessage(typed, allowsDecimals, allowsNegative))
        field.reportValidity()
        return
      }
      field.setCustomValidity('')
      field.value = typed
      onChange?.(event)
    }

    return (
      <input
        type={isNumber ? 'text' : type}
        inputMode={isNumber ? (inputMode ?? numberInputMode) : inputMode}
        min={isNumber ? undefined : min}
        max={isNumber ? undefined : max}
        step={isNumber ? undefined : step}
        onChange={isNumber ? handleNumberChange : onChange}
        ref={ref}
        className={cn(
          'flex h-9 w-full rounded-md border border-input bg-card px-3 py-1 text-sm text-foreground shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50',
          className,
        )}
        {...rest}
      />
    )
  },
)
Input.displayName = 'Input'

function rejectedKeyMessage(typed: string, allowsDecimals: boolean, allowsNegative: boolean): string {
  if (!allowsDecimals && typed.includes('.')) return 'Whole numbers only'
  if (!allowsNegative && typed.includes('-')) return 'Negative numbers are not allowed'
  return 'Numbers only'
}

export { Input }
