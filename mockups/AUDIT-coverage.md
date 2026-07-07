# FrigoLoco Mockups — Coverage Audit & Design-System Report

Reviewed 2026-07-03. Scope: the four self-contained HTML mockups in `mockups/` that
collectively replace the Excel/Office-Scripts system. All mockups share one design
system (tokens, sidebar, nav, cards, tables, chips/badges). This document records:

1. **Canonical IA** — which mockup owns which view when views overlap.
2. **Capability → view coverage** vs the Excel system, with what was added/changed.
3. **Design-system tokens & the drift that was fixed** so all four feel identical.
4. **Cross-cutting additions** (d3.js charting decision, empty/loading/error states, print, a11y).
5. **Per-file change log.**

The four files:

| File | App | Domain |
|------|-----|--------|
| `frigoloco-forecasting-app-mockup.html` | Forecasting & Operations | **Canonical shell / full IA** |
| `frigoloco-dispatch-app-mockup.html` | Dispatch | Dispatch matrix + driver field view |
| `frigoloco-supply-app-mockup.html` | Supply & Stock | Purchase orders, stock, products, alerts |
| `frigoloco-returns-app-mockup.html` | Weekly & Monthly Returns | Financial returns/P&L |

---

## 1. Canonical IA (which file is authoritative)

The four mockups **overlap**: the forecasting mockup is a superset that re-implements
several Dispatch / Orders / Stock / Verification views that also exist as standalone
apps. To avoid ambiguity we declare:

> **`frigoloco-forecasting-app-mockup.html` is the canonical application shell and
> information architecture.** It defines the master sidebar, nav taxonomy
> (Planning / Operations / Insights / System) and the authoritative version of every
> shared operational view. The dispatch / supply / returns mockups are **domain detail
> references** — they show a richer, focused treatment of one slice and are the place
> to look for that slice's interaction detail, but they are not separate products.

For every view that appears in more than one file, the authoritative source is:

| View | Appears in | **Authoritative** | Notes |
|------|-----------|-------------------|-------|
| Dispatch grid (fridge × product) | forecasting `#page-dispatch`, dispatch `#page-matrix` | **dispatch `#page-matrix`** | Dispatch mockup has the full sticky category/product/stock matrix + confirm modal; forecasting's Dispatch Board is the canonical shell entry that links to it. |
| Menu planner | forecasting `#page-menu`, dispatch `#page-menu` | **forecasting `#page-menu`** | Forecasting has the category-rail + allocation-matrix canonical layout; dispatch's is the product-picker detail reference. |
| Forecast V2 | forecasting `#page-forecast`, dispatch `#page-forecast` | **dispatch `#page-forecast`** | Dispatch mockup shows the full R1 rule, holiday-exclusion and residual-stock detail; forecasting's Workbench is the canonical shell entry. |
| Restock Verification | forecasting `#page-verification`, dispatch `#page-verify` | **forecasting `#page-verification`** | Both equivalent; forecasting is the shell. |
| Purchase Orders | forecasting `#page-orders`, supply `#page-orders` | **supply `#page-orders`** | Supply owns the PO domain (create/receive/PO doc/history); forecasting's PO view is the canonical shell entry and now includes the receive-with-qty panel. |
| Stock & Ordered | forecasting `#page-stock`, supply `#page-stock` | **supply `#page-stock`** | Supply owns stock domain; forecasting `#page-stock` is the shell view of the same `v_stock_position`. |
| Clients & Fridges | forecasting `#page-clients`, supply `#page-clients`, returns `#page-master` | **forecasting `#page-clients`** | Master data; returns/supply show fee/fraction slices. |
| Weekly / Monthly returns | returns `#page-weekly` / `#page-monthly`, forecasting `#page-reports` | **returns app** | Returns app owns the financial P&L; forecasting Reports is a summary shell view. |
| Alerts | supply `#page-alerts`, forecasting `#page-alerts` (**new**) | **supply `#page-alerts`** for settings/thresholds; **forecasting `#page-alerts`** for the operational inbox | Supply owns alert-threshold config; the operational alert inbox was missing from the canonical shell and was added. |
| Driver dispatch sheet | dispatch `#page-driver` | **dispatch `#page-driver`** | Only home; field/mobile view. |

---

## 2. Capability coverage vs the Excel system

Legend: **✅ covered** · **➕ added this pass** · **⚠️ covered, gap noted**.

| # | Capability (Excel) | Status | Mockup → View |
|---|--------------------|--------|---------------|
| 1 | **Forecast V2** — per-fridge×category weekday forecast; min-qty holiday rule; days-to-fill; per-category % adjust; added/sold/ratio actuals | ✅ | **dispatch `#page-forecast`** (R1 rule, holiday exclusion, days-to-fill, margin %, added/sold/ratio) + forecasting `#page-forecast` (Workbench: % adjust per category, in-grid min-qty/days-to-fill, diagnostics) |
| 2 | **Menu** — weekly; category→supplier→product cascade; scores; quantities; export-to-order | ⚠️➕ | forecasting `#page-menu` (canonical) + dispatch `#page-menu` (picker). **Added "Export to Order →"** button to both. Gap: cascade is category→product with supplier shown per row, not a 3-level drilldown (documented). |
| 3 | **Product Rating** — 16-col scorecard; editable weights | ✅ | forecasting `#page-ratings` (16-col table: Product…Combined+Active; editable weight fields). Supply `#page-alerts` also exposes 3 forecast-scoring weights. Note: forecasting uses a redesigned dual-model (0.55/0.30/0.15 global + fridge) rather than the legacy 0.62/0.33/0.05 single weights — a deliberate target-state redesign, same capability. |
| 4 | **Dispatch View** — week/day/category fridge×product grid; stock-check row; save vs confirm-dispatch; history reload; clear; clone | ✅➕ | dispatch `#page-matrix` (grid + pinned stock/total rows + confirm modal) + forecasting `#page-dispatch`. **Added to dispatch matrix**: Clone previous week, History…, Clear grid controls (save/confirm/clone/history/clear now all present). |
| 5 | **Purchase Orders** — create from menu; manual order; receive w/ qty-received; statuses Pending/Received/Cancelled; PO document; order history | ✅➕ | supply `#page-orders` + forecasting `#page-orders`. **Added a "Receive delivery" panel** (qty-received per line, Δ, line status, Partial/Received/Cancelled, attach delivery note) to forecasting `#page-orders`. |
| 6 | **Stock & Ordered** — pending/received/dispatched/net per product | ✅ | forecasting `#page-stock` (Pending/Received/Dispatched/Stock&ordered columns, `v_stock_position`) + supply `#page-stock` |
| 7 | **Snacks & Drinks target map** — par levels, current, diff | ✅ | forecasting `#page-targets` (Target ✎ / Live stock / Difference; red = restock needed) |
| 8 | **Restock Verification** — dispatched vs ADDED diff per category+product; UNRELIABLE counts | ✅ | forecasting `#page-verification` + dispatch `#page-verify` (Δ = added − dispatched, unreliable counted separately) |
| 9 | **GSV report** — per-fridge added qty / food cost / revenue over date range | ✅ | forecasting `#page-reports` → "Fridge food-cost & revenue report (GSV)" tab (fridge + date range → added qty, unit buy/sell, food cost, revenue) |
| 10 | **Weekly return entry + weekly/monthly analysis** | ✅ | returns `#page-weekly` (manual-input entry + history) + returns `#page-monthly` (by client/supplier/category P&L) + forecasting `#page-reports` |
| 11 | **Driver dispatch sheet** — per-fridge picking doc + delivery instructions | ✅ | dispatch `#page-driver` (mobile sheet: category print order, check-off, delivery instructions, withdrawal list) — now **print-friendly** (one fridge per page) |
| 12 | **Alerts** | ✅➕ | supply `#page-alerts` (thresholds/settings) + **new forecasting `#page-alerts`** operational inbox (stock-negative, PO overdue, verification Δ, below-target, sync failure) |

**Net:** every Excel capability has a home. No capability was entirely missing; the
genuine gaps were sub-features (export-to-order button, dispatch clear/history/clone
controls, PO receive-with-qty flow, and an operational alert inbox in the canonical
shell) — all added this pass. Redesign deviations (dual-model rating, Wix auto-pull
of weekly sales) are noted, not "fixed", because they are intentional target-state
choices.

---

## 3. Design-system tokens & drift fixed

### Shared tokens (identical across all four)
- **Type:** `system-ui, -apple-system, "Segoe UI", sans-serif`; body 14px / 1.45.
- **Palette (`:root`):** `--surface-1 #fcfcfb`, `--page #f9f9f7`, ink `#0b0b0b/#52514e/#898781`,
  `--grid #e1e0d9`, `--baseline #c3c2b7`, series `#2a78d6 / #1baf7a / #eda100`,
  `--good #0ca30c`, `--warning #fab219`, `--critical #d03b3b`, `--teal #0d9488`,
  `--sidebar-bg #14202e`, `--sidebar-ink #c7d2de`, plus a full dark-mode `@media` override.
- **Sidebar:** 218px, `--sidebar-bg`, `.logo`/`.nav-section`/`.nav-item`/`.foot` pattern,
  3px active left-border `#3987e5`, blue-tinted active fill.
- **Cards / tables / tiles / badges / callouts / tabs / forms:** identical rules.

### Drift found and corrected

| Drift | Was | Fixed to | Files touched |
|-------|-----|----------|---------------|
| `--teal` token missing | absent | added (light `#0d9488`, dark `#2dd4bf`) | dispatch, returns, supply |
| Status `.chip.*` family (Draft/Saved/Sent/Dispatched/Partial/Cancelled/Verified) | absent | added the shared family | dispatch, returns |
| `.btn.danger` | supply = red **text only** | filled red `#fff` on `--critical` (matches others) | supply |
| `.btn.sm` | supply = `3px/12px`; dispatch = missing | standardized `4px 10px / 12.5px` | supply, dispatch, returns |
| `.callout.warn` tint | dispatch = `.10` opacity | `.08` (matches others) | dispatch |
| `.callout.warn/.green` | returns = missing `.warn` | added `.warn` + `.green` | returns |
| Sidebar not scrollable | `overflow-y` missing on `.sidebar` | added `overflow-y: auto` | dispatch, returns, supply |
| Dark-mode coverage | supply had **2** `@media dark` blocks vs 4–5 elsewhere | brought supply to 5 (added chip/callout/badge/toast dark refinements) | supply |
| `.nav-item .pill` count badge | only supply defined it | added the shared rule to forecasting (used by new Alerts nav) | forecasting |

### Accepted, documented divergence (not force-changed)
- **`.chip` means different things:** status pill in forecasting/dispatch/returns, but a
  **filter chip** in supply (`.chip.active`, `.chip.amber.active`). Supply renders statuses
  with `.badge.*`. Renaming supply's filter chips would break its markup + JS across many
  views for no visual gain, so it was left as-is and recorded here. The `.badge.*` family
  (the actually-shared status/label component) **is byte-identical across all four**.

---

## 4. Cross-cutting additions

### 4a. Charting — d3.js (production)
Decision (from coordinator): the real React frontend renders charts with **d3.js**.
The mockups must stay self-contained (no CDN), so charts remain **inline SVG / HTML bars**,
and each chart carries a visible caption and an HTML comment noting `production: d3.js`.
Captions/comments added at:
- forecasting: `#dash-cat-chart` (dashboard), `#monthly-chart` (reports).
- returns: `#trend-chart`, `#cat-margin-chart`, and the `renderHBars` render function.
- dispatch: sell-through bar note on `#page-forecast`.
- supply: no charts (all tables + PO paper doc) — nothing to caption.

### 4b. Empty / loading / error states
Previously **no** empty/loading/error states existed anywhere. Added to the **shared
design system** in all four files:
- `.empty-state` (icon + heading + body), `.skeleton` (shimmer loading bar),
  `.toast` / `.toast-wrap` (error/warn/ok toast, fixed bottom-right container).
- A **representative live example** of all three lives in forecasting `#page-alerts`
  ("Empty state — no matching alerts" + skeleton rows + error/warn/ok toasts).
- **Production note:** every list/table/detail view in the React build needs these three
  states wired (loading skeleton, empty, error toast/inline). The mockups show the
  pattern on one representative screen only.

### 4c. Print styles
Previously **no** `@media print` existed. Added a shared print block to all four:
hides sidebar / mock-foot / tooltip / toast / controls / buttons, forces black-on-white,
removes card borders/shadows, and provides a `.print-break` page-break utility.
- dispatch: driver sheet prints **one fridge per page** with a plain (non-phone) header.
- supply: PO `.pdf-paper` prints as a clean document.
- forecasting: PO preview / reports print cleanly.

### 4d. Accessibility (nav)
Icon-only-looking nav rails now: `.ico` glyphs marked `aria-hidden="true"`; a JS pass
gives every `.nav-item` `role="link"`, `tabindex="0"`, `title` + `aria-label` (from its
text), keyboard activation (Enter/Space), and `aria-current="page"` on the active item.
**Production note:** nav items should be real `<a>`/`<button>` elements in React (they are
`<div>`s here); `aria-current` should update on navigation.

---

## 5. Per-file change log

### `frigoloco-forecasting-app-mockup.html` (canonical shell)
- Design system: added `.nav-item .pill`; added shared empty-state / skeleton / toast /
  `@media print` block.
- **New view: `#page-alerts`** (+ sidebar nav item with count pill) — operational alert
  inbox (stock-negative, PO overdue, verification Δ, below-target, sync failure) plus the
  canonical **empty-state + loading + error-toast** demonstration.
- `#page-orders`: **added "Receive delivery" panel** (qty-received per line, Δ, line status,
  Partial/Received/Cancelled, attach delivery note).
- `#page-menu`: added **"Export to Order →"** control.
- d3 captions on dashboard + monthly charts; nav a11y JS; `aria-hidden` icons.

### `frigoloco-dispatch-app-mockup.html`
- Drift: `--teal`, status `.chip.*` family, `.btn.sm`, `.callout.warn` tint `.10→.08`,
  sidebar `overflow-y`.
- `#page-matrix`: **added Clone previous week / History… / Clear grid** controls (completes
  save/confirm/clone/history/clear).
- `#page-menu`: added **"Export to Order →"**.
- `#page-forecast`: d3 sell-through caption. `#page-driver`: print-friendly one-fridge-per-page.
- Shared empty-state / toast / print block; nav a11y JS; `aria-hidden` icons.

### `frigoloco-returns-app-mockup.html`
- Drift: `--teal`, status `.chip.*` family, `.btn.danger` + `.btn.sm`, `.callout.warn/.green`,
  sidebar `overflow-y`.
- **REVIEW-returns-mockup.md fixes applied** (see §6).
- d3 captions on trend + food-margin charts; shared empty-state / toast / print block; nav a11y; `aria-hidden` icons.

### `frigoloco-supply-app-mockup.html`
- Drift: `--teal`, `.btn.danger` (text→filled), `.btn.sm` (`3px/12px`→`4px 10px/12.5px`),
  sidebar `overflow-y`; **dark-mode blocks 2 → 5** (added chip/callout/badge/toast dark refinements).
- Shared empty-state / toast / print block; nav a11y JS; `aria-hidden` icons.
- `.chip` kept as the filter-chip component (documented divergence, §3).

---

## 6. REVIEW-returns-mockup.md — fixes applied

All must-fix and should-fix items from `REVIEW-returns-mockup.md` were applied to
`frigoloco-returns-app-mockup.html`:

| Review item | Fix |
|-------------|-----|
| 1 — Weekly fridge food cost basis | Weekly callout now reads **"fridge food cost = ADDED / restock value (the `Added Food Cost` column) — not dispatched value."** |
| 2 — POS & Software 9% base | Weekly callout now reads **"POS & software fee = 9% × VAT-inclusive gross sales (Total Sales / Wix gross — not ex-VAT)."** |
| 3 — Weekly-vs-monthly cost-basis stated per view | Added a **cost-basis caption on each view**: weekly = **ADDED (restock)**; monthly by-fridge = **DISPATCHED** (deliberate legacy inconsistency, surfaced explicitly). |
| 4 — `# Of Fridge` manual input | Added a **`# of Fridges`** field to the weekly entry form (manual, Weekly Data col J). |
| 5 — Weekly net-margin formula callout | Added: **(Sales Turnover + Catering + TGTG) − (Fridge Food Cost[ADDED] + Catering Food Cost + Logistics) − POS − RFID.** |
| 6 — VAT wording | Settings row now states **"Turnover ex VAT = gross ÷ 1.06"** = (Sales + Credit − Refund) ÷ 1.06, **not** gross − 6%. |
| 7 — Wix auto-pull (confirm with Ismail) | **Left as-is** (target-state re-architecture) and flagged here for sign-off — it changes the weekly workflow from manual inputs to auto-pulled Wix sales. |

---

## 7. Open items for the React build (not mockup gaps)
- Wire loading/empty/error states on **every** view (pattern shown on forecasting `#page-alerts`).
- Nav items → semantic `<a>`/`<button>` with focus states and live `aria-current`.
- Menu cascade: decide whether to add an explicit supplier drill level (item 2).
- Confirm the weekly Wix auto-pull workflow change with Ismail (review item 7).
