import { Outlet } from 'react-router-dom'
import { Sidebar } from '@/components/layout/Sidebar'
import { cn } from '@/lib/utils'

/**
 * A page that holds a DataTable becomes a growing flex column, so the table's
 * pagination bar (mt-auto) sits at the bottom of the page area.
 */
const FILL_HEIGHT_PAGE_CLASSES = [
  '[&>*:has([data-fills-page])]:flex',
  '[&>*:has([data-fills-page])]:flex-1',
  '[&>*:has([data-fills-page])]:flex-col',
].join(' ')

/**
 * Top-level shell: fixed dark sidebar on the left (the theme toggle lives in its
 * footer) and the routed page content in a scrollable, full-height main column.
 */
export function AppLayout() {
  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background text-foreground">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <main className="flex-1 overflow-y-auto">
          <div className={cn('flex min-h-full flex-col px-6 py-6', FILL_HEIGHT_PAGE_CLASSES)}>
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
