import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { InfoHint, type Hint } from '@/components/shared/InfoHint'

interface ImportOptionSwitchProps {
  id: string
  label: string
  hint: Hint
  checked: boolean
  onCheckedChange: (checked: boolean) => void
}

/** A labelled toolbar switch that changes how Import from Forecast computes quantities. */
export function ImportOptionSwitch({
  id,
  label,
  hint,
  checked,
  onCheckedChange,
}: ImportOptionSwitchProps) {
  return (
    <div className="flex h-9 items-center gap-2 px-1">
      <Switch
        id={id}
        checked={checked}
        onCheckedChange={onCheckedChange}
      />
      <Label
        htmlFor={id}
        className="whitespace-nowrap text-xs"
      >
        {label}
      </Label>
      <InfoHint {...hint} />
    </div>
  )
}
