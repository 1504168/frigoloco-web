import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { BankHoliday } from '@/pages/ops/lib/types'

export const SAVED_LIST_KEY = ['ops', 'forecast', 'saved-list'] as const
export const BANK_HOLIDAYS_URL = '/api/v1/forecasts/bank-holidays'
export const BANK_HOLIDAYS_KEY = ['ops', 'forecast', 'bank-holidays'] as const

/** Bank holidays of one calendar year, oldest first. */
export function useBankHolidays(year: number) {
  return useQuery({
    queryKey: [...BANK_HOLIDAYS_KEY, year],
    queryFn: ({ signal }) => api.get<BankHoliday[]>(BANK_HOLIDAYS_URL, { params: { year }, signal }),
  })
}
