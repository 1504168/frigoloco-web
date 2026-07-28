import { Outlet } from 'react-router-dom'
import { Sidebar } from '@/components/layout/Sidebar'

/**
 * Top-level shell: fixed dark sidebar on the left (the theme toggle lives in its
 * footer) and the routed page content in a scrollable main column.
 */
export function AppLayout() {
  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background text-foreground">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-none px-6 py-6">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
