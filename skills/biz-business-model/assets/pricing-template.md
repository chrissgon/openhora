Template of `docs/business/pricing.md`. Translate the headings and labels into the artifact language; keep the order. Replace every `<...>` and delete every line in parentheses that is only guidance.

```markdown
# Pricing: <offer>

- Owner: biz-business-model
- Language: <same rule>
- Status: hypothesis | validated (<n> paying customers, <date>) | limited
- Date: <YYYY-MM-DD>
- Decision: OPEN-1: <the price question to the user> | decided by the user on <date>: "<their words>"
- OPEN-2: <a plan-limit question: free plan period, whether one item counts against a paid limit, the margin rule with free users>; recommended: <answer>, because <reason> (one line per open item; `decided by the owner on <date>: "<their words>"` once decided)
- Ready: no | yes

## Anchors
| Alternative | Price (currency, unit, term, date) | What the buyer gets | Source |
|---|---|---|---|
(a price cell holds a price with its currency, a unit with `per` or `/`, and a date; an introductory offer also its term and renewal price; or `price not found`)

## Price pressure
- <a floor bid, a free alternative, a bundled feature, another buyer's price such as a school's>: <what it does to the price> [n]; `none found`

## Proposed price
- <amount> <currency> per <unit> (<billing>): above the cost floor of <floor> [M1]; against <anchor> [n] and <anchor> [n]; goal within capacity: <yes | no> [M1]
- Not chosen: <other candidate>: <why, from the script or an anchor> [M1]

## Price test
- How: <paid pilot | pre-sale | spend questions>; with: <profile, where to find them>; how many: <n>
- Questions (past behaviour and current spend only): 1. ...
- Validated if: <criteria, written before the test>
- Rejected if: <criteria>
- Results: <empty until the test; one line per prospect, no names>

## Assumptions
## Sources
```
