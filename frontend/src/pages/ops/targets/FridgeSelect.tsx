import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

export interface FridgeOption {
  fridgeId: number
  name: string
}

interface FridgeSelectProps {
  options: FridgeOption[]
  value: number | null
  onChange: (fridgeId: number) => void
  placeholder: string
}

export function FridgeSelect({ options, value, onChange, placeholder }: FridgeSelectProps) {
  return (
    <Select
      value={value === null ? undefined : String(value)}
      onValueChange={(next) => onChange(Number(next))}
    >
      <SelectTrigger className="h-9 w-64">
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        {options.map((option) => (
          <SelectItem
            key={option.fridgeId}
            value={String(option.fridgeId)}
          >
            {option.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
