import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { EmptyState } from '@/components/shared/EmptyState'
import { ErrorState } from '@/components/shared/ErrorState'
import { api, type Page } from '@/lib/api'
import { formatEuro } from '@/lib/format'
import type { Equipment } from '@/lib/types'
import {
  EQUIPMENT_CATEGORY_LABELS,
  OWNERSHIP_LABELS,
  formatEquipmentCost,
} from '@/pages/masters/equipmentOptions'

const CLIENT_EQUIPMENT_LIMIT = 500
const CENTS_PER_EURO = 100

/** Machines placed at one client, with the monthly fees charged for them. Read-only here. */
export function ClientEquipmentTab({ clientId }: { clientId: number }) {
  const equipmentQuery = useQuery({
    queryKey: ['masters', 'equipment', { clientId }],
    queryFn: ({ signal }) =>
      api.get<Page<Equipment>>('/api/v1/equipment', {
        params: { client_id: clientId, limit: CLIENT_EQUIPMENT_LIMIT },
        signal,
      }),
  })

  if (equipmentQuery.isLoading) {
    return <p className="py-4 text-center text-sm text-muted-foreground">Loading equipment…</p>
  }
  if (equipmentQuery.isError) {
    return <ErrorState error={equipmentQuery.error} onRetry={() => equipmentQuery.refetch()} />
  }
  const machines = equipmentQuery.data?.items ?? []
  if (machines.length === 0) {
    return (
      <EmptyState
        title="No equipment"
        description="Link a coffee machine or water filter to this client on the Equipment page."
        action={<EquipmentPageLink />}
      />
    )
  }

  const activeMachines = machines.filter((machine) => machine.is_active)
  const monthlyFeeCents = activeMachines.reduce(
    (total, machine) => total + Math.round(Number(machine.monthly_fee ?? 0) * CENTS_PER_EURO),
    0,
  )

  return (
    <div className="space-y-3">
      <div className="overflow-hidden rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Machine</th>
              <th className="px-3 py-2 text-left font-medium">Code</th>
              <th className="px-3 py-2 text-left font-medium">Bought / rented</th>
              <th className="px-3 py-2 text-right font-medium">Our cost</th>
              <th className="px-3 py-2 text-right font-medium">Monthly fee</th>
            </tr>
          </thead>
          <tbody>
            {machines.map((machine) => (
              <tr key={machine.id} className="border-t border-border">
                <td className="px-3 py-2">
                  <div className="font-medium">{machine.machine_type}</div>
                  <div className="text-xs text-muted-foreground">
                    {EQUIPMENT_CATEGORY_LABELS[machine.equipment_category]}
                    {machine.is_active ? '' : ' (not in use)'}
                  </div>
                </td>
                <td className="px-3 py-2 font-mono text-xs">{machine.machine_code}</td>
                <td className="px-3 py-2">{OWNERSHIP_LABELS[machine.ownership]}</td>
                <td className="px-3 py-2 text-right tabular-nums">{formatEquipmentCost(machine)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{formatEuro(machine.monthly_fee)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between text-sm">
        <EquipmentPageLink />
        <span className="text-muted-foreground">
          Monthly fees of machines in use:{' '}
          <span className="font-medium tabular-nums text-foreground">
            {formatEuro(monthlyFeeCents / CENTS_PER_EURO)}
          </span>
        </span>
      </div>
    </div>
  )
}

function EquipmentPageLink() {
  return (
    <Link to="/masters/equipment" className="text-sm text-primary hover:underline">
      Manage on the Equipment page
    </Link>
  )
}
