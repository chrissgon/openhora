Template of `docs/business/business-model.md`. Translate the headings and labels into the artifact language; keep the order. Replace every `<...>` and delete every line in parentheses that is only guidance.

```markdown
# Business model: <offer>

- Owner: biz-business-model
- Language: <the tag this file is written in. On an update: the tag on its Language line (with none, the language the file is written in), unless the request sets another. For a new file: the language the request sets for this deliverable, else the task's language line, else the `language` key of docs/workbench/runtime.json, else English>
- Status: hypothesis | validated (<n> paying customers, <date>) | limited
- Date: <YYYY-MM-DD, from `date +%F`>
- Offer: <offer>; who pays: <payer>; who uses: <user>; goal: <goal and horizon> (state file, <date>)

## What stays free
- <what the state file records as free or open, quoted with its date; `nothing recorded`>

## Revenue model
- Unit: <the value metric> because <the three criteria, with the anchors that charge this way> [n]
- Billing: <recurring per <period> | one-off>; payment: <method or `not chosen`>
- Price: see docs/business/pricing.md (<proposed | decided on <date>>)

## Costs
| Cost | Kind (variable per unit, fee %, tax %, fixed per period, hours) | Value | From |
|---|---|---|---|
(every row ends with its origin: a source number, an M label, `user`, `state file`, `Assumption: <...>` or `unknown`)

## Unit economics
<the table as printed by unit_economics.py>
- Reading: <contribution per unit, the cost floor, customers for the goal, hours the goal needs against the hours available> [M1]

## Path to the goal
- Customers needed: <n> [M1]; hours per month at the goal: <h> of <available> [M1]; within capacity: <yes | no | unknown>
- What breaks first: <hours, price pressure, an unknown cost>

## Risks
- <risk>: <evidence> [n]

## Unknowns
- <what is not known and what would establish it>

## Assumptions
- Assumption: <...>; `none` when every fact has a source

## Sources
[n] <Title>, <Publisher>. Published <date | undated>. Accessed <date>. <URL>. Tier <1|2|3>. <fact | estimate | opinion>. Quote: "<...>"

## Method
- Queries: <each query>
- M1: unit_economics.py with the inputs of the Costs table on standard input
- Checks: check_refs.py --file docs/business/business-model.md; lint_model.py --file docs/business/business-model.md --kind model
```
