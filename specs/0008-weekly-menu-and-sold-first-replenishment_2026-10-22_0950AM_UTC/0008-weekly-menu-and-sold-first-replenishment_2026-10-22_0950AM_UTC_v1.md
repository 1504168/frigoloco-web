# 0008 - Weekly menu and sold-first replenishment

## Modification History

| Date (UTC)              | Description                                                        |
|-------------------------|--------------------------------------------------------------------|
| 2026-10-22 09:50 AM UTC | Initial design note from Mathieu's review call (22 Oct 2026, L4-L7) |

## Why

On the 22 Oct call Mathieu showed that the Menu page cannot hold "the menu of a week":

- The menu is chosen **per ISO week** (cold and warm dishes change every week; snacks and
  drinks mostly stay). Today a menu exists only per delivery day, so the week's product
  choice must be rebuilt on every day, and there is no way to pre-build week 45.
- **Import from Forecast recomputes the product list from ratings.** A product added by
  hand (the GSPUD potato-salmon salad) disappears on the next import. The forecast is per
  category, so the import must only split the category total over the products the week
  menu already holds.
- There is no **clone** of a week's menu into the next week.
- Replenishment ignores real sales. During the week Mathieu wants products **sold since
  the last delivery** to be replenished first, then the rest split by rating (with an
  on/off switch, off for a "fresh Monday").

Step 2 of the smarter replenishment (adjusting by stock still in the fridge / slow sales)
is out of scope.

## Data model

**Choice: the week menu is the existing week-level `weekly_menus` row (`day_name = ''`)
and its product list is the existing `menu_products` table.**

| Concept | Storage | Key |
|---|---|---|
| Week menu (product list per category) | `weekly_menus` row with `day_name = ''` + `menu_products(menu_id, product_id)` | (year, iso_week) |
| Day menu (quantities per fridge x product) | `weekly_menus` row with a weekday `day_name` + `menu_lines` | (year, iso_week, day_name) |

Options considered:

| Option | Pros | Cons |
|---|---|---|
| A. Reuse the `day_name = ''` row + `menu_products` (chosen) | Both tables already exist and were designed for exactly this ("which products are on a given week's menu"); the unique key `(year, iso_week, day_name)` already allows one week row per week; no new DDL; the legacy allocation path (`compute_allocation`) already reads `menu_products` | Week and day menus share one table, told apart by `day_name = ''` (a named constant in code) |
| B. New `week_menus` + `week_menu_products` tables | Separate names | A second "week menu" concept next to the unused legacy one; more DDL, ORM and schema surface for the same data |

The category of a week-menu product is read from `products.category_id` (not
denormalised: the list is small and always joined to products anyway).

### Migration 0022 (backfill, idempotent)

For every (year, iso_week) that has day menus:

1. Create the week row (`day_name = ''`, status `active`) when missing.
2. When that week row has **no products yet**, fill `menu_products` with the distinct
   products of all that week's saved day menus (`menu_lines`).

Rule 2 keeps the migration safe to re-run: a week list the user has since edited is never
touched again. Existing day menus are not changed and keep loading as before. The two
legacy empty week rows (2026-W51, W52) are left as they are.

No 0023 migration is needed.

## Behaviour

### Day grid shows the week menu

`GET /menus/saved` and `GET /menus/blank` show the products of the week menu plus any
product that has saved lines on that day. Whether Monday, Wednesday or Thursday of week 44
is opened, the same week product list appears (quantities are per day).

### Save keeps the week menu in sync

`POST /menus/save` stores the day quantities (unchanged) **and** sets the week product list
to the products on the saved grid, in the same transaction:

- whole-menu save: the week list becomes exactly the saved grid's products;
- category-scoped save: only that category's part of the week list is replaced.

So adding or removing a product on any day and saving changes the menu of the whole week.
A product removed from the week stays visible on another day only while that day still has
saved lines for it.

`GET /menus/week?year&week` returns the week list (empty, `menu_id = null`, when none is
saved). It powers "Clone from week".

### Clone a week

The Menu page "Clone week" dialog loads another week's product list
(`GET /menus/week`) and replaces the grid's product columns with it (quantities of
products that stay are kept, removed products' quantities are dropped). The user adjusts
and presses Save, which stores it as this week's menu. Clone is a draft, never a silent
write.

### Import from Forecast keeps the chosen products

`POST /menus/import-from-forecast` gains an optional JSON body:

```json
{ "product_ids": [ ... ], "sold_first": true }
```

- **Product list used:** `product_ids` when sent (the page sends the products on screen,
  so an unsaved manual addition is kept too), else the saved week menu.
- Every forecast (fridge, category) quantity is split only over the list's products of
  that category. All list products of the imported scope appear in the result, with 0 when
  they receive nothing, so a manual product never vanishes.
- **Fallback (nothing chosen yet):** when the list has no product in the imported scope at
  all (a brand new week, or a category-scoped import of a category with no chosen products),
  the products are suggested from ratings exactly as before (every active product of the
  category, split by score). The response flags `used_rating_suggestion = true` and the page
  says so ("starting point - remove what is not on the menu").
- On a whole-menu import where some categories have chosen products and others have none,
  the empty categories get nothing and are listed in `categories_without_products`; the page
  warns. Rationale: a category left empty on purpose (no soup this week) must not be refilled
  by a suggestion; importing that category alone gives the suggestion.

### Sold-first replenishment (`sold_first`)

Applies to every category except Snacks and Drinks (they keep their existing logic).

For each fridge x category with forecast quantity `F`:

1. **Last delivery** of that category to that fridge = the newest Husky restock event
   (`restock_events.action = 'added'`) for any product of the category in that fridge,
   before the delivery day (Europe/Brussels midnight), looked back at most
   `SOLD_FIRST_LOOKBACK` (14 days). No delivery found -> no sold-first for that pair
   (pure rating split).
2. **Sold since** = non-refunded `sales_events` of each **list** product in that fridge after
   the last delivery and before the delivery day.
3. If total sold `S <= F`: each product first gets its sold count; the remaining `F - S` is
   split by rating over the list products that **sold nothing** ("then split among the other
   products"); when every product sold something, over all list products.
4. If `S > F` (cap rule): the forecast stays the ceiling. `F` is split over the sold products
   in proportion to their sold counts (largest remainder), nothing goes to the rest.
   Rationale: the forecast is the agreed volume; proportional keeps every sold product
   represented instead of letting the best seller take everything.

Mathieu's example: `F = 15` desserts, product 2 sold 11, ratings 66 / 70 / 75 % ->
product 2 gets 11, the remaining 4 split over products 1 and 3 by rating -> 2 and 2.

Why restock events and not the app's dispatches: restock events are what the fridge really
received (the app only recorded one dispatched delivery so far; most deliveries are still
made from Excel), and they carry a timestamp, so "since last delivery" is exact. Per
category, because snack top-ups on other days must not reset the dessert window.

Default of the switch on the page: **off on Monday, on for other days**, matching
"fresh Monday" in the call; the user can flip it before every import.

## API changes

| Endpoint | Change |
|---|---|
| `GET /api/v1/menus/week` | New: `WeekMenuOut {menu_id, year, week, categories[{category_id, category_name, product_ids}]}` |
| `POST /api/v1/menus/import-from-forecast` | Optional body `{product_ids?, sold_first}`; response adds `used_rating_suggestion`, `categories_without_products`, `sold_first` |
| `POST /api/v1/menus/save` | Also writes the week product list (no request change) |
| `GET /api/v1/menus/saved`, `/blank` | Products = week list plus the day's own lines |

## UI flow

1. Open Menu, pick week 45 Monday. Columns show week 45's menu (empty for a new week).
2. "Clone week" -> pick week 44 -> its products fill the columns. Add (Product) or remove
   (x on a product header) products. Save -> week 45 menu saved (Monday quantities too).
3. "Sold first" switch (off on Monday) -> "Forecast" imports quantities into the chosen
   products only.
4. Open week 45 Wednesday: the same products show. Switch "Sold first" on, import: products
   sold since each fridge's last delivery are refilled first.

## Open questions for Mathieu

1. Cap rule when sales since the last delivery exceed the forecast: proportional to sales
   (built) or best sellers first?
2. After sold-first, should the remainder go only to products that sold nothing (built,
   from "split among the other products") or to all products by rating?
3. Default of the "Sold first" switch: off on Monday, on otherwise (built). Right?
4. Should sold-first also apply to Snacks and Drinks? (Not built: they keep their logic.)
5. His Excel example: check the tests against it when it arrives.
