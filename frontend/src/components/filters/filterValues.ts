/** Select value meaning "no filter"; Radix Select does not accept an empty string. */
export const ALL_OPTION_VALUE = 'all'

export function toSelectValue(id: number | null): string {
  return id === null ? ALL_OPTION_VALUE : String(id)
}

export function fromSelectValue(value: string): number | null {
  return value === ALL_OPTION_VALUE ? null : Number(value)
}
