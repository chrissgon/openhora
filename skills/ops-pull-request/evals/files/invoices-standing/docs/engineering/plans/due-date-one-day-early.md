# Plan: due-date-one-day-early

- Task: "the due date on invoices shows one day early for customers in Brazil" (support ticket, 2037-09-24)
- Date: 2037-09-25

## Root cause

- Evidence: confirmed. `new Date("2037-09-25")` parses a date-only string as UTC midnight; `toLocaleDateString` then prints the previous day in time zones behind UTC (`src/due.js:3`).

## Change

- `src/due.js`: parse the date-only string into a local date (year, month, day) before formatting.
- `test/due.test.js`: the label for a date in time zones behind UTC.
- Checks run on the branch, 2037-09-25:
  - `npm run lint`: exit 0
  - `TZ=America/Sao_Paulo npm test`: 2 passed, 0 failed
  - `TZ=Asia/Tokyo npm test`: 2 passed, 0 failed
