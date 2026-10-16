# Backlog: {project}

- Owner: product-backlog
- Language: {the tag this file is written in: on an update, the one already here unless the request sets another; else the project language}
- Status: draft
- Updated: {YYYY-MM-DD}

## Feature: {feature} (`T-{abbr}`)

- Specification: docs/product/specs/{feature}.md
- Design: docs/engineering/designs/{feature}.md
- Sources: {decisions, verification plan, assumptions}

### Tasks

- T-{abbr}-1: Spike: {the design assumption verified}
  Does: {what is done, in one or two lines}
  Delivers: REQ-n
  Touches: {design components or files}
  Depends on: none
  Check: {the design's "Verify by ..." sentence} (design assumption 1)
  Size: L, because {reason}
  Milestone: M1
- T-{abbr}-2: {title}
  Does: {what is done, in one or two lines}
  Delivers: REQ-n, AC-n
  Touches: {design components or files}
  Depends on: T-{abbr}-1
  Check: `{command of the verification-plan row}`; {observable result} (verification plan: AC-n)
  Size: S, because {reason}
  Milestone: M1
- T-{abbr}-9: Remove {what is removed}
  Does: {what is deleted, after its replacement works}
  Delivers: REQ-n, AC-n
  Touches: {removed files}
  Depends on: T-{abbr}-7, T-{abbr}-8
  Check: `{the "Checked by" command of the Removals table}`; {what must keep working} (verification plan: AC-n)
  Size: S, because {reason}
  Milestone: M3

Without a design, a task's Check is the `Then` of an acceptance criterion it delivers:

  Check: {the Then of AC-n} (acceptance criterion: AC-n)

and, when the user chose to plan before the design, `Touches:` names only what the specification names and the origin reads `(acceptance criterion: AC-n; design pending)`. After its tickets are created, each task gains one line: `Ticket: {key or link}`.

### Order

- Spikes: T-{abbr}-1 (assumption 1) gates T-{abbr}-2
- Critical path: T-{abbr}-… → T-{abbr}-… → … (the `critical_path` of the lint output)
- Parallel tracks: {T-x-2 alongside T-x-3}

### Milestones

- M1 {name}: T-…, T-… → usable state: {one line the checks prove}
- M2 {name}: … → usable state: …

### Coverage

| Id | Delivered by |
|----|--------------|
| REQ-1 | T-{abbr}-2 |

### Assumptions

- Assumption: {a dependency or a fact the design does not state, and the task it affects}; else "none"

### Open questions

- OPEN-1: {question only the user can answer}. Blocks: {T-id}. Recommended: {answer and why}; else "none"
