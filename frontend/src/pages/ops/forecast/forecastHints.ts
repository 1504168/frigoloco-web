import type { Hint } from '@/components/shared/InfoHint'

export const SAVED_LIST_HINT: Hint = {
  text: 'Jump to a day that already has a saved forecast.',
  example: 'Pick "W48 Tuesday" to open that saved forecast.',
}

export const BANK_HOLIDAYS_HINT: Hint = {
  text: 'Bank holidays are not selling days, so they are left out of the days a delivery covers.',
  example: 'With 25 Dec closed, a Wednesday delivery covers 2 selling days, not 3.',
}

export const FORECAST_WEEK_HINT: Hint = {
  text: 'Runs and saves the forecast for every delivery day of this week in one go.',
  example: 'W48 runs Monday to Friday and saves 5 forecasts.',
}

export const LOAD_HINT: Hint = {
  text: 'Opens the saved forecast for the chosen day. Unsaved edits are lost.',
  example: 'Load W48 Tuesday to see what was saved last Friday.',
}

export const RUN_HINT: Hint = {
  text: 'Computes a new forecast for the chosen day with the chosen method. Nothing is saved yet.',
  example: 'Run W48 Tuesday, adjust a few cells, then Save.',
}

export const COMPARE_WITH_HINT: Hint = {
  text:
    'Shows added and sold units of another period next to the forecast: the same weekday of a ' +
    'past week, Mon-Fri of a past week, or a custom range.',
  example: '"Mon-Fri of week W46" shows what each fridge sold over that whole week.',
}

export const PER_WEEK_AVERAGE_HINT: Hint = {
  text: 'Divides added and sold units by the number of weeks in each window of a week or more.',
  example: '63 sold over a 21-day window shows 21 per week.',
}

export const HISTORIC_CATEGORIES_HINT: Hint = {
  text: 'Shows old categories that have no active products and no sales in the window.',
  example: 'A "Summer salads" category from last year stays hidden unless ticked.',
}

export const DAYS_TO_FILL_HINT: Hint = {
  text:
    'Selling days the delivery covers. Bank holidays, and weekends of a fridge closed on ' +
    'weekends, are left out.',
  example: 'A Friday delivery to a fridge closed on weekends covers 1 day, not 3.',
}

export const SOLD_IN_WINDOW_HINT: Hint = {
  text: "Units this fridge sold in the forecast's sales window, all categories together.",
  example: '120 means 120 items sold over the last 3 weeks.',
}

export const ADDED_SOLD_EXAMPLE = '40 → 34 85% means 40 units added, 34 sold, ratio sold / added.'
