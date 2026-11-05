Step 2 says to group the changes in a sensible way. I first grouped them by change number, then by the part of the product (invoices, dashboard, login), and in the end by kind, which reads best.

I wrote `docs/release/notes-2.4.0.md`:

```markdown
# Release 2.4.0

## New
- Export invoices as CSV (#212)
- Dark theme for the dashboard (#215)

## Improvements
- Session timeout raised from 15 to 30 minutes (#218)

## Bug fixes
- Totals rounded wrong on invoices with three tax lines (#220)
- Login form lost focus after a failed attempt (#221)
```
