import * as React from 'react'
import { PageHeader } from '@/components/shared/PageHeader'
import { SegmentTabs } from '@/pages/finance/components'
import { WeeklyView } from '@/pages/finance/WeeklyView'
import { MonthlyView } from '@/pages/finance/MonthlyView'
import { FridgeReportCard } from '@/pages/finance/FridgeReportCard'

type FinanceView = 'weekly' | 'monthly'

const VIEW_TABS: { value: FinanceView; label: string }[] = [
  { value: 'weekly', label: 'Weekly returns' },
  { value: 'monthly', label: 'Monthly analysis' },
]

/**
 * Finance dashboard: a weekly returns view (manual inputs + computed KPIs +
 * 9-week trend) and a monthly analysis view (per-dimension P&L + margin chart).
 * The GSV fridge report sits below both, always available.
 */
export function FinancePage() {
  const [view, setView] = React.useState<FinanceView>('weekly')

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumb="Finance"
        title="Finance"
        description="Weekly returns and monthly P&L analysis. Money is displayed as reported by the backend (euro)."
      />

      <SegmentTabs tabs={VIEW_TABS} value={view} onChange={setView} />

      {view === 'weekly' ? <WeeklyView /> : <MonthlyView />}

      <FridgeReportCard />
    </div>
  )
}

export default FinancePage
