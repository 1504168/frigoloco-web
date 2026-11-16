import { cn } from '@/lib/utils'

export interface DialogTab<TabId extends string> {
  id: TabId
  label: string
}

interface DialogTabsProps<TabId extends string> {
  tabs: DialogTab<TabId>[]
  activeTab: TabId
  onChange: (tab: TabId) => void
}

/** Underlined tab bar used at the top of the master-data dialogs. */
export function DialogTabs<TabId extends string>({
  tabs,
  activeTab,
  onChange,
}: DialogTabsProps<TabId>) {
  return (
    <div className="mb-4 flex gap-1 border-b border-border">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          onClick={() => onChange(tab.id)}
          className={cn(
            '-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors',
            tab.id === activeTab
              ? 'border-primary text-foreground'
              : 'border-transparent text-muted-foreground hover:text-foreground',
          )}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
}
