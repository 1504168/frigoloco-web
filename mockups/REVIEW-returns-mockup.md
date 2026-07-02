# Verification: frigoloco-returns-app-mockup.html vs Weekly & Monthly Return V2.xlsx

Reviewed 2026-07-03 (verifier session). Ground truth = actual formulas read from the workbook (`Weekly Data` table + `Settings` sheet + workbook LAMBDAs). The three monthly P&L views are **correct** (by-fridge net margin verified numerically to the cent; by-supplier/by-category RFID math verified). Issues are on the weekly side.

## Must fix (business-logic errors)

1. **Weekly fridge food cost uses the wrong basis** — line 365 says "fridge food cost (**dispatch import**)". The workbook's weekly `Fridge Food Cost` = **ADDED (restock) value** (`Added Food Cost` column, FILTER over `ByCategoryWeeklyAddedDataTable`), not dispatched value. The mockup's own `added_facts` table and "Added data" import tile already exist — wire the weekly food cost to those.
2. **POS & Software 9% base is wrong** — mockup computes 9% × ex-VAT turnover (verified: ABB 70.54 = 9% × 783.73). Workbook formula is `=[Total Sales] * Settings!$C$3` where `Total Sales` is **VAT-inclusive** Wix gross. Mockup understates the fee ~6%.
3. **Weekly-vs-monthly cost-basis difference is erased** — weekly P&L uses ADDED value; monthly by-fridge uses DISPATCHED value. This is a deliberate legacy inconsistency; the UI should state each view's basis explicitly (a one-line caption per view suffices).

## Should fix

4. **`# Of Fridge` manual input missing** from the weekly entry form and the `weekly_returns` model — but the history table renders a "Fridges" column. It's a manual weekly input in the workbook (column J).
5. **Weekly net margin formula never shown** — add a callout like the monthly ones: `(Sales Turnover + Catering + TGTG) − (Fridge Food Cost + Catering Food Cost + Logistics) − POS − RFID` (verified against column AC).
6. **VAT wording** — Settings says "Deducted to get turnover ex VAT"; actual operation is **÷ 1.06** (`=(Sales + Credit − Refund)/1.06`), not "minus 6% of gross". Different numbers.

## Confirm with Ismail (deviation, possibly intentional)

7. Mockup reclassifies Total Sales / Refund / FrigoLoco Discount / Customer Credit from **manual weekly inputs** (as in Excel) to **auto-pulled from a Wix sales import**. Fine as a target-state re-architecture, but needs explicit sign-off since it changes the weekly workflow.

## Verified OK (no action)

- Settings fees: 9% POS ("Husky fee on sales"), €0.10 RFID/item, 6% VAT — values, labels, effective-dating all correct.
- Monthly by-fridge net margin = client fee (yearly÷12) + food margin + service additionals − fraction logistics − POS. Numerically exact.
- Monthly by-supplier/category net margin = food margin − 0.10 × items sold. Numerically exact.
- FrigoLoco Discount correctly excluded from net-sale numerator; Customer Credit correctly added.
