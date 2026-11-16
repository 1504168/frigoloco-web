import * as React from 'react'
import { NavLink } from 'react-router-dom'
import { LogOut } from 'lucide-react'
import { NAV_SECTIONS, type NavItem } from '@/config/nav'
import { useUnacknowledgedAlertsCount } from '@/hooks/useAlertsCount'
import { ROLE_LABELS, useCurrentUser } from '@/hooks/useCurrentUser'
import { ThemeToggle } from '@/components/layout/ThemeToggle'
import { clearToken } from '@/lib/auth'
import { cn } from '@/lib/utils'

/** Clear the stored session and hard-navigate to the public login page. */
function handleLogout() {
  clearToken()
  window.location.href = '/login'
}

/** Renders the count badge on a nav item, if the item declares a badgeKey. */
function NavBadge({ item }: { item: NavItem }) {
  const alerts = useUnacknowledgedAlertsCount()
  if (item.badgeKey !== 'alerts') return null
  const count = alerts.data ?? 0
  if (count <= 0) return null
  return (
    <span className="ml-auto rounded-full bg-critical px-1.5 text-[10px] font-bold text-white">
      {count}
    </span>
  )
}

/**
 * FrigoLoco brand block (D6). Renders the committed wordmark SVG
 * (public/frigoloco-logo.svg - swap the file, keep the path). If the asset
 * fails to load, falls back to the app-name wordmark text so the header is
 * never blank.
 */
function BrandBlock() {
  const [logoFailed, setLogoFailed] = React.useState(false)
  return (
    <div className="px-5 pb-3 pt-5">
      {logoFailed ? (
        <div className="text-[17px] font-bold tracking-tight text-white">
          Frigo<span className="text-[var(--sidebar-accent)]">Loco</span>
        </div>
      ) : (
        <img
          src="/frigoloco-logo.svg"
          alt="FrigoLoco"
          className="h-11 w-auto"
          onError={() => setLogoFailed(true)}
        />
      )}
    </div>
  )
}

/**
 * Fixed dark sidebar: brand block, nav links grouped without section titles,
 * active-item highlight with a left accent bar, and a footer.
 */
export function Sidebar() {
  const currentUser = useCurrentUser()
  const isAdmin = currentUser.data?.role === 'admin'

  // Admin-only links (e.g. Users) stay hidden until we know the user is an admin;
  // dropping them can leave a section with no items, so those sections are hidden too.
  const sections = NAV_SECTIONS.map((section) => ({
    ...section,
    items: section.items.filter((item) => !item.adminOnly || isAdmin),
  })).filter((section) => section.items.length > 0)

  return (
    <aside className="flex h-full w-48 shrink-0 flex-col bg-sidebar text-sidebar-ink">
      <BrandBlock />

      <nav className="flex-1 overflow-y-auto pb-4">
        {sections.map((section) => (
          <div
            key={section.title}
            className="pt-2"
          >
            {section.items.map((item) => (
              <NavLink
                key={item.path}
                to={item.path}
                className={({ isActive }) =>
                  cn(
                    'flex items-center gap-2.5 border-l-[3px] border-transparent px-5 py-2 text-[13px] text-sidebar-ink transition-colors',
                    'hover:bg-white/5 hover:text-white',
                    isActive &&
                      'border-l-[var(--sidebar-accent)] bg-[rgba(69,188,180,0.16)] font-semibold text-white',
                  )
                }
              >
                <item.icon className="h-[18px] w-[18px] shrink-0 opacity-85" aria-hidden="true" />
                <span className="truncate">{item.label}</span>
                <NavBadge item={item} />
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      <div className="mt-auto flex items-center justify-between gap-2 border-t border-white/10 px-5 pb-3 pt-3.5 text-[11px] text-[#647181]">
        <div className="min-w-0">
          {currentUser.data ? (
            <>
              <b className="block truncate text-[#9db0c2]">{currentUser.data.email}</b>
              <span className="block truncate">
                {currentUser.data.full_name || ROLE_LABELS[currentUser.data.role]}
              </span>
            </>
          ) : (
            <b className="block truncate text-[#9db0c2]">
              {currentUser.isLoading ? 'Loading…' : 'Not signed in'}
            </b>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <ThemeToggle
            variant="ghost"
            className="h-8 w-8 shrink-0 text-sidebar-ink hover:bg-white/10 hover:text-white"
          />
          <button
            type="button"
            onClick={handleLogout}
            title="Log out"
            aria-label="Log out"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-sidebar-ink transition-colors hover:bg-white/10 hover:text-white"
          >
            <LogOut className="h-[18px] w-[18px]" aria-hidden="true" />
          </button>
        </div>
      </div>
    </aside>
  )
}
