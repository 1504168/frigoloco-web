# QA Questions & Test Plan — FrigoLoco Web ERP

> QA agent, 2026-07-03. Scope: functional + aesthetic quality of the four mockups and the ported forecasting/returns/data-sync modules, plus an audit of every open question across specs 0002/0003/0004 and the canonical decisions in `architecture/IMPLEMENTATION-BRIEF.md`.
> Sources read: 4 mockups, `REVIEW-returns-mockup.md`, `IMPLEMENTATION-BRIEF.md`, the `<main id="spec-content">` + `open-questions-data` JSON of specs 0002/0003/0004, CLAUDE.md. (`mockups/AUDIT-coverage.md` does not exist.)
> Legend: **[EDGE]** = nasty edge case; **[BLOCKER]** = needs a decision before this can be tested/built.

---

## 1. FUNCTIONAL QA SCENARIOS

End-to-end pipeline under test: **Forecast → Menu → Dispatch → PO → Receive → Verify → Weekly Return**, plus supporting Stock, Scores, Master Data. Each scenario: *Steps → Expected*.

### 1.1 Forecast (Forecast Workbench)
- **F1 Happy path.** Pick fridge + delivery weekday (Tue) + category, run forecast. → `qty = (cat_sold / (valid_days + no_info_days)) × days_to_fill × (1 + pct_adjust)`, 3-week lookback anchored on the delivery weekday (brief §formulas). Numbers match legacy within tolerance.
- **F2 Residual-stock deduction.** Live RFID stock present for a product. → Forecast net of residual (per "Residual stock deduction" panel); items below DLC route to withdrawal list, not re-ordered.
- **F3 [EDGE] Holiday exclusion.** A lookback day where fridge total sold ≤ `min_qty`. → That day is dropped from `valid_days` (counted as holiday), forecast rises accordingly. **Verify:** does "holiday" mean the min-qty heuristic OR a Belgian public-holiday calendar? Both appear in copy — confirm one definition (see gap G14).
- **F4 [EDGE] No-info days.** Product newly added, <3 weeks of data. → `no_info_days` included in denominator; no divide-by-zero; forecast degrades gracefully, flagged as low-confidence.
- **F5 [EDGE] Zero valid days.** All 3 lookback days are holidays / no sales. → No crash; forecast falls back (0 or target-based), UI shows why.
- **F6 Snacks & Drinks branch.** Category ∈ {Snacks, Drinks}. → Uses `target − live_stock`, NOT the sold-rate formula (brief menu-allocation rule). Confirm the Workbench applies the correct branch per category.
- **F7 [EDGE] RFID offline / stale stock.** `stock_snapshots` >2h old for the fridge. → Residual deduction warns "stock stale," forecast still runs on last-known, staleness surfaced (ties to `rfid_offline_detector`).

### 1.2 Menu Planner (allocation)
- **M1 Happy path.** Forecast total N, products scored. → `alloc = round(forecast × score/Σscores)`, capped; totals reconcile to forecast (leftover → top-scored product).
- **M2 [EDGE] Sub-0.5 bump.** A product's raw allocation <0.5 while remainder >0.5. → Bumped to 0.51 per rule; remainder decrements; no product silently dropped to 0 when remainder allows.
- **M3 [EDGE] Score ties / Σscores = 0.** All candidate products score 0 (new, no sales). → No divide-by-zero; even split or target fallback; UI explains.
- **M4 Copy previous week.** "New week" from prior draft. → Slots/products prefilled; requires Excel history import (spec 0002 Q5) — if vendor-only import chosen, this is empty on day 1 (test both).
- **M5 [EDGE] Product deactivated mid-week.** Catalogue sync marks a planned product `is_active=false`. → Planner flags it, blocks dispatch of a dead SKU, offers substitute.

### 1.3 Dispatch Board / Matrix
- **D1 Happy path save.** Edit the fridges×products grid, save. → Versioned save (needs `dispatch_line_versions`, spec 0002 Q12 [BLOCKER]); "Saved" badge; withdrawal list computed (live-stock + DLC).
- **D2 Confirm & generate sheets.** Confirm dispatch. → 42 per-fridge PDFs in **category print order (rule R8)** + In-box/Missing + withdrawal list, + 1 warehouse XLSX → Azure Blob; per-fridge emails to logistics (recipient source unresolved — spec 0002 Q14 [BLOCKER]).
- **D3 [EDGE] Past-date dispatch.** Operator selects/confirms a dispatch for a date already past. → Blocked or hard-warned; must not silently backdate stock movements or corrupt week roll-ups.
- **D4 [EDGE] Cancel after confirm.** Cancel a dispatch that already generated sheets / decremented stock. → Reverses `stock_movements` (compensating entries, append-only), re-issues/void sheets, audit trail shows who/when; verification for that week recomputes.
- **D5 [EDGE] Negative-stock block.** Dispatch qty > available warehouse stock. → DB trigger on `stock_movements` blocks the movement; UI shows a clear, per-line error, not a 500.
- **D6 [EDGE] Concurrent edit.** Two operators edit the same board (see gap G8). → Version conflict detected on save; loser is warned, not silently overwritten.
- **D7 Driver View (mobile).** Open driver preview (dispatch mockup). → Shows per-fridge pick list, In-box/Missing, withdrawal resolution (Loss / Return to WH). **Verify** how the driver authenticates and whether it works offline (gap G6).

### 1.4 Purchase Orders (Order Builder)
- **P1 Happy path.** Build PO for a supplier, add lines. → `line = price × qty × (1+vat)`; order ref `YYYY-NNNNN` from row-locked `order_no_counters`; **parity anchor:** order 2026-00360 → 239.36 / 14.36 / 253.72 (brief).
- **P2 Concurrent PO creation.** Two POs created simultaneously. → No duplicate/skipped order numbers (row-lock proven under contention).
- **P3 [EDGE] Price override / effective-dated price.** `fridgeproductprice` changed after PO drafted. → PO uses price in force at draft time; historical PO totals never mutate (ties to settings-versioning, spec 0003 Q9 [BLOCKER]).
- **P4 [EDGE] Cancel PO after partial receipt.** → Received lines preserved in stock; cancel only voids un-received remainder; totals recompute.
- **P5 PDF + email.** Generate PO PDF (WeasyPrint), send to supplier. → Test-mode gate honored during parallel run (no real supplier email); provider (SMTP vs Graph) unresolved (gap G5).

### 1.5 Receive / Stock Position
- **R1 Happy path receipt.** Receive a PO. → `stock_movements` append (+qty), `v_stock_balances` reflects; "Currently in stock & ordered" updates.
- **R2 [EDGE] Over-receipt.** Receive qty > ordered qty. → Explicit decision required: block, or allow with variance flag? Must not silently accept a mismatch. **Currently unspecified — flag.**
- **R3 [EDGE] Under-receipt / short.** Receive less than ordered. → Backorder/short flagged; PO stays partially open; stock reflects only what arrived.
- **R4 [EDGE] Receive against cancelled PO.** → Blocked with clear message.
- **R5 Manual stock adjustment.** (Supply mockup) Operator adjusts stock. → Append-only movement with reason + `updated_by`; negative resulting balance blocked (D5 trigger).

### 1.6 Restock Verification
- **V1 Happy path.** After a dispatched week, open Verification. → `Δ = added(VALID, ADDED RFID) − dispatched` per category; "Discrepancies" lists only Δ≠0 rows.
- **V2 [EDGE] UNRELIABLE RFID tags.** Tags marked UNRELIABLE. → Counted **separately** (own column/callout), NOT folded into the reliable Δ (brief; mockups already flag "unreliable"). Verify the number reconciles: reliable + unreliable + unrecognised.
- **V3 [EDGE] UNRECOGNISED tags.** → **Excluded** from Δ entirely (brief). Confirm they don't leak into added totals or scores.
- **V4 [EDGE] Refund / is_refunded.** A purchase's `refundStatus` contains "refunded" (case-insensitive). → Treated as refunded in sales, not as a sale (brief husky normalisation).
- **V5 [EDGE] Dispatched-but-zero-added.** Product dispatched, RFID shows 0 added (never scanned in). → Large negative Δ surfaced in "Largest product-level gaps," not hidden.

### 1.7 Weekly & Monthly Return (Returns app)
- **W1 Happy path weekly.** Enter manual inputs, view Computed panel. → Turnover ex-VAT = `(gross + credit − refunds) / 1.06`; POS fee = `0.09 × VAT-INCLUSIVE gross`; RFID = `0.10 × items_sold`; net margin uses **fridge food cost = ADDED (restock) value** (REVIEW must-fix #1/#2). Each view states its cost basis (ADDED weekly vs DISPATCHED monthly) per REVIEW #3.
- **W2 [EDGE] `# Of Fridge` input.** REVIEW #4 / spec 0003 Q10 [BLOCKER]: is it a manual 8th field or `COUNT(DISTINCT fridge)`? History table renders a "Fridges" column but entry form omits it. Test whichever is chosen; ensure history table isn't fed a null.
- **W3 [EDGE] Week 52/53 boundary.** ISO week 53 years (2020, 2026...). → Week picker offers 53; roll-ups don't drop/duplicate; "copy previous week" crosses the year boundary correctly.
- **W4 [EDGE] Week 1 / prior-Dec spillover.** ISO week 1 containing late-Dec days. → Sales dated 29–31 Dec land in the correct ISO week; brief §12 "week_start DATE everywhere" holds.
- **W5 [EDGE] Cross-month week (monthly attribution).** A week spanning two months (spec 0003 Q7 [BLOCKER]). → Exact date attribution vs day-count proration — pick one; monthly totals reconcile to the sum of weeks under that rule.
- **W6 [EDGE] Rate change mid-history.** POS% or RFID fee edited (spec 0003 Q9 [BLOCKER]). → With effective-dating, reported past weeks DON'T change; with current-only, they silently recompute — test the chosen behaviour explicitly.
- **W7 Monthly P&L parity.** By-fridge / by-supplier / by-category net margin. → Numerically exact to the cent (REVIEW confirms formulas OK): by-fridge = `yearly_fee/12 + food_margin[DISPATCHED] + service_additionals − fraction×logistics − pos_pct×sales`; by-supplier/category = `food_margin − 0.10×items`.
- **W8 [EDGE] Missing weekly inputs.** A week with no manual entry. → Completeness report flags it; dashboard shows gap; monthly rollup doesn't treat missing as zero-and-fine.

### 1.8 Name drift / Master Data / Sync
- **N1 [EDGE] Name drift.** Vendor renames a fridge/product (`friendlyName` vs `name` diverge). → Fridge resolved by **BOTH** friendlyName and name (brief); "Name mapping review" (returns mockup) surfaces the new incoming name for operator confirmation; local overrides preserved (Admin: "synced from /facility, local overrides preserved").
- **N2 [EDGE] Catalogue item disappears.** Product absent from `/producttype` sync. → `is_active=false`, not deleted; historical rows intact; "Box n°" fridges auto-excluded as test.
- **N3 Sync health / failure.** A cron job fails. → `sync_run` row records failure; Sync screen shows red; staleness/alert fires. Verify idempotent re-run (trailing overlap upsert produces no dupes).
- **N4 [EDGE] Backfill resume.** Backfill interrupted mid-chunk. → Resumes from `sync_run` bookkeeping at 7-day chunk granularity; raw-first archive intact; no double-count.
- **N5 [EDGE] Duplicate event.** Same sales/restock event pulled twice (overlap window). → UNIQUE constraint / natural key (`tag_id+purchased_at`, session id) dedupes at DB level.

---

## 2. AESTHETIC QA CHECKLIST

### 2.0 Cross-cutting (ALL four mockups — verified by scan)
- [ ] **No empty states.** Zero `empty-state` / "no data" / "no results" markup in any mockup. Every grid/list/chart (Orders, Alert inbox, Scores, Weekly history, Discrepancies, Sync runs) needs a designed empty state.
- [ ] **No loading / skeleton states.** No skeletons/spinners (except 3 stray "loading" strings in supply). Forecast run, sync, PDF gen, grid saves all need loading affordance.
- [ ] **No error states.** Almost no error UI (1–2 keyword hits total). Failed forecast, save conflict, negative-stock block, sync failure, email failure — all need inline error patterns + toasts (no `toast` markup anywhere).
- [ ] **Accessibility near-zero.** No `aria-*`, `role=`, `tabindex`, `alt=`, or `:focus-visible` in any file. Icon-only nav (◧ ▤ ▦ ◎ ✚ …) has no accessible labels. Charts are inline SVG with no title/desc/table fallback. Keyboard nav for the editable grids unverified.
- [ ] **Single breakpoint.** Only `@media (max-width:1100px)` everywhere; nothing for tablet/phone. Dispatch's own "Driver View — mobile preview" is not actually mobile-responsive CSS.
- [ ] **No `prefers-reduced-motion`.** Any transitions/animations lack a reduced-motion guard.
- [ ] **Dark mode auto-only.** All rely on `prefers-color-scheme` with **no manual toggle**; user can't override OS. Verify dark palette contrast on every badge/chart color.
- [ ] **No print styles anywhere.** `@media print` count = 0 in all four. See 2.5.
- [ ] **Currency/locale.** Euro shown as `€498.87` (dot). Belgian/FR locale uses comma decimal + `€` suffix — confirm intended format is consistent app-wide.

### 2.1 `frigoloco-forecasting-app-mockup.html` (the big one — full pipeline)
- [ ] Consistency: it duplicates screens that also live in dispatch/supply/returns mockups (Dispatch Board, PO, Stock, Reports, Admin) — confirm one canonical design per screen so the four don't drift.
- [ ] Hierarchy: 10+ top-level screens under Planning/Operations/Insights/System — verify active-nav state, breadcrumb, and that the icon-only rail is legible with labels.
- [ ] Allocation matrix & Diagnostics tables: need column sort, sticky header, and horizontal-scroll containment (45×90 grid must not break body layout).
- [ ] "Forecast results" and "Sync health" cards need loading + last-run-failed + stale states.
- [ ] Restock Verification: UNRELIABLE / UNRECOGNISED visually distinct from reliable Δ (color + not relying on color alone).
- [ ] Reports & Analytics overlaps returns app — resolve the 0002/0003 boundary (Q10) before polishing.

### 2.2 `frigoloco-dispatch-app-mockup.html`
- [ ] Has `@media print`? No (the 2 "print" hits are the business term "category print order," not CSS). Driver sheets/withdrawal list render on screen but can't be cleanly browser-printed.
- [ ] Dispatch Matrix (fridges×products): sticky first column + header, cell-edit affordance, save/dirty indicator, keyboard fill-down (grid lib undecided, Q2).
- [ ] Driver View "mobile preview" is a desktop-CSS mock — needs true responsive layout + large tap targets + offline/empty state.
- [ ] "Confirm dispatch" is a destructive/irreversible-feeling action — needs confirm modal, in-flight state, and success/failure toast.
- [ ] French copy present ("Vue globale") — bilingual consistency: some labels FR, most EN (see i18n gap).

### 2.3 `frigoloco-supply-app-mockup.html`
- [ ] PO screen has a "PDF preview" panel but **no print styles** and no download/regenerate/void controls' states.
- [ ] Alert inbox: needs empty state, unread/read distinction, and per-alert resolve action states.
- [ ] Manual stock adjustment: needs validation error state (negative balance block), required-reason enforcement, confirm step.
- [ ] Movement history table: needs pagination/virtualization empty + loading states.
- [ ] Only 2 dark-mode media blocks vs 4 in the others — verify dark mode is actually complete here (possible inconsistency).
- [ ] Scoring weights / fees settings: needs save/dirty/validation states and effective-date UI if Q9 → effective-dated.

### 2.4 `frigoloco-returns-app-mockup.html`
- [ ] Weekly entry form: shows 7 fields; `# Of Fridge` missing (REVIEW #4) — if kept manual, add the field; ensure form validation + required markers.
- [ ] Each P&L view must show a one-line **cost-basis caption** (ADDED weekly / DISPATCHED monthly) — REVIEW #3/#5. Add the weekly net-margin formula callout (REVIEW #5).
- [ ] "Name mapping review" screen: the core name-drift UX — needs pending/confirmed/rejected states, empty state, and a clear "this maps to" affordance.
- [ ] Charts (turnover W18–W26, food margin by category/fridge top/bottom 6): inline SVG — need accessible titles, value labels, and a colorblind-safe palette; empty/partial-week state.
- [ ] "Import runs" + "Raw sales sample": need failure state and a "re-run import" affordance.
- [ ] Backend & Data Model screen is developer documentation inside a user app — confirm it's intentional / gated to admins.

### 2.5 Print styles (driver sheets & PDFs) — dedicated check
- [ ] **No `@media print` in any mockup.** Server-side WeasyPrint owns PO/driver/return PDFs (brief), so screen print CSS may be out of scope — **but** the mockups show "PDF preview," "Delivery sheets," and "Withdrawal list — driver pulls these on arrival" that a user may Ctrl-P. Decide: (a) print CSS for these, or (b) explicit "Download PDF" that hides the SPA chrome. Driver withdrawal/pick lists especially — they're printed on-site.

---

## 3. OPEN QUESTIONS AUDIT

Status across the three specs: **34 questions total → 3 answered, 31 open.**
Answered: 0002 Q1 (React+Vite), 0002 Q7 (Railway + Azure Blob), 0004 Q4 (APScheduler).
The IMPLEMENTATION-BRIEF resolves many *contradictions* but explicitly leaves a set of business questions for the user (Appendix E item 19 names 0004 Q3/Q9/Q10, 0003 Q3/Q4/Q9, 0002 Q2/Q6 as still-open).

### 3(a) Questions the USER still MUST answer — ranked by how much they block

| Rank | Q | Question | Why it blocks |
|---|---|---|---|
| 1 | **0002 Q11** | Does 0002/0003/0004 supersede 0001, or is 0001 the parent? | Governance. Nobody knows which doc is authoritative for scope; blocks everything downstream. |
| 2 | **0002 Q10** (+Q9) | Boundary between 0002 Reports module and 0003 Returns app | The two specs port the SAME workbook. Building both as written = duplicated Reports/Analytics. Must scope before any returns/analytics work. |
| 3 | **0002 Q2** | Grid library (AG Grid Community/Enterprise/Handsontable) | The 45×90 Dispatch Board is the daily workflow's heart. Licensing budget (~$900–1000/dev/yr) + Excel-style copy/paste/fill-down capability. Blocks all grid screens. |
| 4 | **0002 Q3 / 0003 Q5** | Auth model (M365 SSO vs local; single-role vs ops/finance/admin) | Brief defers JWT, BUT every write needs `updated_by` (audit non-negotiable, deck slide 23). You still need *identity* now. Ambiguous — resolve minimum viable identity. |
| 5 | **0003 Q3** | RFID-fee history: correct the ×items formula retroactively, from-cutover, or replicate the bug? | Sets Phase-1 parity fixtures; shifts every historical net margin €90–250/wk. Can't lock finance tests without it. |
| 6 | **0003 Q9** | Rate changes (POS%, RFID) — effective-dated vs current-only | Metrics computed live from views. Current-only silently rewrites reported history the moment a rate is edited. Data-integrity blocker for finance. |
| 7 | **0004 Q1** | Backfill depth (auto-probe all vs known go-live ~2021) | Blocks the backfill job design + run time. Cheap to go deep; just needs the go-live date if known. |
| 8 | **0004 Q9** | Which payment statuses to pull (all 15 vs settled-only) | Changes sales row counts + reconciliation semantics. Affects every downstream sales/margin number. |
| 9 | **0003 Q10** | `# Of Fridge`: manual 8th input vs `COUNT(DISTINCT fridge)` | Blocks the weekly entry form + `weekly_summary` model + history "Fridges" column (mockup mismatch). |
| 10 | **0003 Q7** | Cross-month week attribution: exact-date vs day-count proration | Changes monthly totals vs workbook history; sets monthly parity fixtures. |
| 11 | **0002 Q14** | Dispatch-note email recipients + where configured | No fridge/facility email column exists; dispatch confirm "emails logistics" has no recipient source. Blocks D2. |
| 12 | **0002 Q6** | ISO-8601 weeks everywhere (brief already picks ISO) | Direction resolved by brief §12, but historical week-boundary shift needs explicit user sign-off (reports change). |
| 13 | **0004 Q10** | `stock_snapshot` retention (keep-all/downsample/prune) | At the brief's 15-min cadence (!), ~200k rows/day → tens of millions/yr on Railway. Cost/perf. See ambiguity note below. |
| 14 | **0002 Q5 / 0004 Q5** | How much history to migrate (vendor-only vs + Excel history) | Determines whether "copy previous week," day-1 stock position, and PO/dispatch history work at launch. |
| 15 | **0003 Q6 / 0002 Q4** | Parallel-run length (2/4/8 wk) + retire PA flows day-1 vs keep during transition | Cutover risk/scheduling; lower urgency than the above but needed before go-live plan. |
| — | Lower | 0002 Q8 (UI language), Q12 (job_runs/dispatch_line_versions DDL), Q13 (exact PA flow inventory), Q15/Q16 (Phase-5 scope, category mapping); 0003 Q1/Q2/Q4/Q8; 0004 Q2/Q6/Q8/Q11 | Real but deferrable or partly pre-answered by the brief (see 3c). |

### 3(b) Questions NOBODY has asked yet but SHOULD (gaps)

- **G1 Backups & disaster recovery.** No spec addresses Railway Postgres backup cadence, PITR, restore drills, or blob-archive redundancy. Hosting answer (Q7) named Railway but not durability.
- **G2 Data retention & GDPR.** Only stock_snapshots retention is asked (Q10). No policy for sales/restock event partitions, raw payload blobs, product reviews, or **customer personal data / customer_credit** (Belgium → GDPR). Retention + right-to-erasure unaddressed.
- **G3 Dutch (NL) localisation.** 0002 Q8 offers EN or FR+EN only. Belgium is FR **and** NL — Flemish clients/operators may need Dutch. Nobody asked. Decide FR/NL/EN scope before i18n scaffolding.
- **G4 Driver mobile access.** Dispatch mockup has a "Driver View" but nothing specs: how a driver authenticates, whether it's a separate low-privilege login, offline capability in a van, or how Loss/Return-to-WH is captured on device.
- **G5 Email/notification provider & credentials.** Q8 (0003) asks the *channel*, Q14 (0002) asks *recipients*, but the actual **provider (SMTP vs Microsoft Graph)**, mailbox, sender identity, and Test-mode gating for the parallel run are unspecified.
- **G6 TGTG (Too Good To Go) integration mechanics.** "TGTG CA" appears as a returns input. Is it a manual figure, a TGTG API pull, or a CSV? No auth/endpoint/cadence specified.
- **G7 Wix sales integration mechanics.** REVIEW #7 flags the mockup reclassifies Total Sales/Refund/Discount/Customer Credit from manual inputs to auto-pulled Wix. HOW (API? webhook? export?), auth, and reconciliation with Husky sales are entirely unspecified — and it changes the weekly workflow (needs sign-off).
- **G8 Concurrency / multi-user editing.** No spec covers two operators editing the Dispatch Board or Menu Planner at once. Versioned saves are mentioned (Q12) but the conflict-resolution UX isn't.
- **G9 Cron failure alerting.** `sync_run` records failures, but who gets paged/emailed when husky_sync, snapshot, or backfill fails is undefined (the below-target/ops alert recipients are the only mail configured).
- **G10 Husky API rate limits / quota.** Backfill pulls 365+ days in 7-day chunks + 15-min snapshots of 41 fridges. No rate-limit, retry/backoff, or vendor-quota contract documented.
- **G11 Test-fridge / non-production data rules.** "Box n°" fridges auto-excluded as test — but no confirmed authoritative list of which fridges/facilities are test vs live.
- **G12 Timezone display vs operational.** Brief fixes Europe/Brussels for cron. User-facing timestamp display, and DST handling around week boundaries, unspecified.
- **G13 Undo / cancel authority & window.** Who may cancel a dispatch/PO after receipt, within what window, and what audit/approval is required (ties to D4/P4).
- **G14 Holiday definition source.** Forecast "holiday" = min-qty-sold heuristic (brief), but copy also says "Holiday." Is there also a Belgian public-holiday calendar? One definition needed (F3).
- **G15 Monitoring/observability.** No logging, metrics, uptime, or health-check strategy beyond `sync_run` rows.
- **G16 User management.** Even with deferred auth, no spec covers user provisioning/deprovisioning, password reset, or who administers accounts (needed for `updated_by` audit to be trustworthy).

### 3(c) Answers that EXIST but are incomplete / ambiguous — what's missing

- **0002 Q7 (hosting = Railway + Azure Blob).** Answered for *where*, silent on **backups, TLS/cert management, DB region/GDPR residency, and why blobs are on Azure while compute is on Railway** (cross-cloud egress/latency). See G1/G2.
- **0004 Q4 (APScheduler).** Answered, but: **single always-on container = SPOF**; nothing on missed-job catch-up after restart, overlapping-run prevention beyond the advisory lock, or health monitoring (G9/G15).
- **0002 Q1 (React+Vite+TS).** Answered for framework, but leaves **grid library (Q2 still open), component library (shadcn assumed), i18n library, and whether 0003's Returns UI is the same app or separate (0003 Q1 open).**
- **Brief §13 live-stock cadence.** Brief mandates **snapshots every 15 min**, but 0004 Q3's options were only 30min/hourly/4×daily — 15 min is *finer than any option offered* and worsens the unresolved retention problem (Q10). This is a decision the user was never actually shown; confirm 15 min vs the offered cadences.
- **Brief §6 / 0004 Q7 (scoring weights).** Brief seeds legacy **62/33/5** and puts the dual-deck model behind a default-off `DUAL_SCORING` flag — effectively pre-answers Q7, but the user hasn't confirmed they're OK deferring the deck's target-state model. Surface for sign-off.
- **Brief §4 + REVIEW #1–#3 (cost basis).** Resolved (ADDED weekly / DISPATCHED monthly) and marked as a *deliberate* legacy inconsistency — but this hinges on the user accepting that two views intentionally disagree; the per-view caption (REVIEW #3/#5) is required for that to be defensible. Confirm the user wants the inconsistency preserved rather than unified.
- **Brief §5 (money = NUMERIC not integer-cents).** Overrides spec 0004's stated integer-cents preference. Recorded, not user-confirmed — flag as a knowingly-overridden preference.
- **0003 Q3 formula vs history.** Brief fixes the RFID *formula* (`0.10 × items`, calling Excel's rate-only subtraction a bug) but leaves the **historical-restatement** decision (recompute all vs from-cutover) to the user — the two are entangled and must be answered together (see 3a rank 5).
- **0002 Q4 / PA cutover.** Native PDF+email chosen in-spec, but the **exact PA flow inventory to disable (Q13)** is contradicted across sources (6 vs 4 vs Office-Scripts' 4 endpoints) — the answer to "go native" is incomplete without the authoritative flow list.

---

### Highest-priority actions
1. **Governance + scope:** answer 0002 Q11 and Q10 first — they gate what even gets built.
2. **Grid + auth:** 0002 Q2 and the identity question (Q3/0003 Q5) unblock the frontend and the mandatory `updated_by` audit.
3. **Finance parity locks:** 0003 Q3 (+history), Q9 (effective-dating), Q7 (cross-month), Q10 (`# Of Fridge`) — needed before writing parity fixtures.
4. **Ask the un-asked:** backups/DR, GDPR retention, Dutch localisation, Wix/TGTG mechanics, email provider, driver auth (G1–G7) — these will otherwise surface as rework late.
5. **Add the missing UI states everywhere:** empty / loading / error / focus / print — currently absent across all four mockups.
