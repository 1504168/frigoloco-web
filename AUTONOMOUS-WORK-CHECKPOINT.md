# Autonomous Work Checkpoint

Running log of everything I (Claude) implement, assume, and decide while the user
is away. The user reviews this at the end. Newest entries at the top of each section.

Started: 2026-07-28. Model: Opus 4.8.

## How to read this
- **DECISION** = a design/behaviour choice I made without being able to ask. Please confirm.
- **ASSUMPTION** = something I inferred from code/spec/Excel; correct me if wrong.
- **DONE** = implemented + validated (tests/browser). Commit hash noted where pushed.
- **OPEN** = known gap / follow-up I did not do (with why).

## Scope the user gave me (2026-07-28)
1. Category-scoped Menu/Dispatch: in the legacy Excel you could pull/save Menu (and
   Dispatch) for ONE category only, or for ALL categories. Add that. Test, commit, push.
2. Drive Purchase Order modifications too (warehouse-first PO redesign per slide 9).
3. Read `FrigoLoco_Dev_Presentation_V5_Final.pptx`, find ALL missing features vs the
   current app, implement them via subagents (I act as validator), commit + push +
   validate, logging assumptions/decisions here.
- cmux remote-control socket is NOT enabled, so I cannot reach the user's other two
  Claude sessions. Coordinating via git + this doc instead.

---

## Workstream 1 - Category-scoped Menu/Dispatch save & pull

### API contract (DECISION)
Scoping is controlled by an optional `category_id`:
- **Menu** `POST /api/v1/menus/import-from-forecast?...&category_id=<id>` - preview only
  that category's allocation (omit -> all categories, unchanged).
- **Menu** `POST /api/v1/menus/save` body gains `category_id?: int`. When set, only that
  category's `menu_lines` are replaced; other categories' saved lines are untouched.
  The overwrite-confirm 409 `{code:"exists"}` fires only if THAT category already has
  saved lines. `category_id=null` keeps the whole-menu behaviour.
- **Dispatch** `POST /api/v1/dispatches/import-from-menu?...&category_id=<id>` - preview
  filtered to that category.
- **Dispatch** `POST /api/v1/dispatches/save` body gains `category_id?: int`, same
  category-scoped replace + category-aware `exists` check. `_replace_lines` already
  supported `category_id`; save_planned now threads it through.
- Backend validates that every line in a category-scoped save actually belongs to that
  category (422 otherwise), so a client can't smuggle other categories in.

### Frontend (DECISION)
- Menu + Dispatch toolbars get a category `<Select>`: "All categories" (default) or one
  category. "From Forecast"/"From Menu" and "Save" respect the selection.
- Scoped import MERGES into the current grid (keeps other categories) instead of
  replacing it; scoped save sends only the selected category's lines.
- New shared component `frontend/src/pages/ops/components/CategoryScopeSelect.tsx`
  ("All categories" + each category in display order). New grid-state method
  `mergeCategoryFromGrid` + `categoryProductIds` in `grid.ts`.

Status: DONE. Validated: 7/7 backend workflow tests pass (incl. 2 new scope tests
`test_category_scoped_menu_save`, `test_category_scoped_dispatch_save_and_import`);
frontend `tsc -b` clean; browser confirms the selector renders on Menu (lists all
10 categories) and Dispatch. Committed + pushed (see git log). NOT browser-round-
tripped to avoid mutating the user's working date (2026-W31-Tuesday) - backend
tests already prove other categories are preserved on a scoped save.
ASSUMPTION: the category options are the full reference category list (from
GET /categories), not only categories currently on the grid - so you can pull a
category that isn't yet present. Tell me if you want it limited to on-grid ones.

---

## Workstream 2 - Purchase Order modifications
Status: PENDING audit (slide 9 = view-by-date, stock page, in-stock vs on-order,
warehouse receiving view, scan & attach delivery note, later Peppol link).

## Workstream 3 - Presentation feature-gap implementation
Status: PENDING - three background audit agents mapping current backend, frontend, and
PO/Stock against the 24-slide deck. Gap list + prioritisation will be appended here.
