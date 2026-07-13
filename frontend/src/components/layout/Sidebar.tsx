import * as React from 'react'
import { NavLink } from 'react-router-dom'
import { NAV_SECTIONS, type NavItem } from '@/config/nav'
import { useUnacknowledgedAlertsCount } from '@/hooks/useAlertsCount'
import { cn } from '@/lib/utils'

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
 * (public/frigoloco-logo.svg — swap the file, keep the path). If the asset
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
      <div className="mt-1 text-[11px] text-[#7d8b9a]">Forecasting &amp; Operations</div>
    </div>
  )
}

/**
 * Fixed dark sidebar matching the canonical mockup: brand block, titled nav
 * sections, active-item highlight with a left accent bar, and a footer.
 */
export function Sidebar() {
  return (
    <aside className="flex h-full w-48 shrink-0 flex-col bg-sidebar text-sidebar-ink">
      <BrandBlock />

      <nav className="flex-1 overflow-y-auto pb-4">
        {NAV_SECTIONS.map((section) => (
          <div key={section.title}>
            <div className="px-5 pb-1.5 pt-3 text-[10.5px] font-medium uppercase tracking-wider text-[#647181]">
              {section.title}
            </div>
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

      <div className="mt-auto border-t border-white/10 px-5 pb-3 pt-3.5 text-[11px] text-[#647181]">
        <b className="block text-[#9db0c2]">ismail@alliedchb.com</b>
        Planner · v0.1
      </div>
    </aside>
  )
}
