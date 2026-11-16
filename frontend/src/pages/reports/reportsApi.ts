import { useMutation, useQuery } from '@tanstack/react-query'
import { api, downloadFile } from '@/lib/api'
import { toast } from '@/components/ui/toast'
import type { ReportScope } from '@/pages/reports/types'

export type ReportKind = 'restock' | 'loss'

function scopeParams(scope: ReportScope): Record<string, string> {
  const params: Record<string, string> = { from: scope.from, to: scope.to }
  if (scope.fridgeId !== null) params.fridge_id = String(scope.fridgeId)
  if (scope.categoryId !== null) params.category_id = String(scope.categoryId)
  return params
}

/** Fetch one report for the scope; waits until both dates are filled in. */
export function useReport<T>(kind: ReportKind, scope: ReportScope) {
  return useQuery({
    queryKey: ['reports', kind, scope],
    queryFn: ({ signal }) =>
      api.get<T>(`/api/v1/reports/${kind}`, { params: scopeParams(scope), signal }),
    enabled: Boolean(scope.from) && Boolean(scope.to),
  })
}

/** Download the report's Excel export through the shared authenticated download helper. */
export function useReportExport(kind: ReportKind, scope: ReportScope) {
  return useMutation({
    mutationFn: () => downloadReportExcel(kind, scope),
    onSuccess: () => toast.success('Report exported'),
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Export failed'),
  })
}

function downloadReportExcel(kind: ReportKind, scope: ReportScope): Promise<void> {
  return downloadFile(
    `/api/v1/reports/${kind}/export.xlsx`,
    `${kind}-report_${scope.from}_${scope.to}.xlsx`,
    scopeParams(scope),
  )
}
