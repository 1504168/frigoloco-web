# FrigoLoco Frontend

React frontend for the FrigoLoco forecasting & operations platform. This is the
**foundation**: app shell, design system, typed API client, shared components,
the routing registry, and two real end-to-end pages (Products, Alerts). Domain
page-agents build their screens on top of it.

## Stack

- **Vite** + **React 18** + **TypeScript**
- **Tailwind CSS** + **shadcn/ui**-style primitives (Radix + CVA)
- **react-router-dom** (v6) — route registry pattern
- **@tanstack/react-query** (v5) — server state
- **d3** — charts (available for domain pages)
- **sonner** — toasts

Design tokens (colors, dark mode, sidebar, chips, tables) are mapped verbatim
from `../mockups/frigoloco-forecasting-app-mockup.html` into CSS variables in
`src/index.css` and consumed through `tailwind.config.js`.

## Run

```bash
npm install
npm run dev        # http://localhost:5173
```

The app talks to the backend at `VITE_API_BASE_URL` (default
`http://localhost:8100`). Copy `.env.example` to `.env.local` to override.

```bash
npm run build      # tsc -b + vite build (must be clean)
npm run preview    # serve the production build
```

The FastAPI backend must be running for data pages (Products, Alerts) to load.

## Project layout

```
src/
  lib/
    api.ts            # typed fetch client: get/post/put/patch/del, Page<T>, ApiError, API_BASE_URL
    query-client.ts   # shared react-query QueryClient
    format.ts         # formatEuro, formatDateTime
    types.ts          # shared backend entity types (Product, Alert)
    utils.ts          # cn() classnames helper
  components/
    ui/               # shadcn-style primitives (button, input, card, table, select, switch, skeleton, sonner)
    shared/           # DataTable, PageHeader, StatusChip, MoneyCell, EmptyState, ErrorState, LoadingSkeleton
    layout/           # AppLayout, Sidebar, ThemeToggle
    theme-provider.tsx
  config/nav.ts       # canonical sidebar IA (single source of nav truth)
  hooks/              # useDebouncedValue, useAlertsCount
  pages/
    _shared/          # PlaceholderPage
    masters/          # ProductsPage (real)
    alerts/           # AlertsPage (real)
    ops/routes.tsx    # domain route registry (owned by ops page-agent)
    supply/routes.tsx # domain route registry (owned by supply page-agent)
    finance/routes.tsx# domain route registry (owned by finance page-agent)
  routes.tsx          # composes AppLayout + all route arrays
  App.tsx             # providers + RouterProvider
```

## For domain page-agents — contract

You own `src/pages/<domain>/` and its `routes.tsx`. Do not modify shared files.

1. **Register routes** — export a `RouteObject[]` from your `routes.tsx` (paths
   are absolute, e.g. `/stock`). It is spread into `AppLayout`'s children by
   `src/routes.tsx`. When you implement a route that currently has a temporary
   placeholder in `src/routes.tsx` (`placeholderRoutes`), remove that entry to
   avoid a duplicate-path conflict.
2. **Fetch data** — use `api.get/post/put/patch/del` from `@/lib/api` with
   `@tanstack/react-query`. List endpoints return `Page<T>`; errors throw
   `ApiError`.
3. **Reuse shared components** — `DataTable`, `PageHeader`, `StatusChip`,
   `MoneyCell`, `EmptyState`, `ErrorState`, `LoadingSkeleton`, and `toast`
   (from `@/components/ui/sonner`). Add nav links in `src/config/nav.ts` only if
   a route is missing there.

See `ProductsPage.tsx` (list + search + filter + pagination) and `AlertsPage.tsx`
(list + mutation with toast) as reference implementations.
