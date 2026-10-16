# Design results: {artifact}

- Owner: design-execute
- Language: {the tag this file is written in. On an update: the tag on its Language line (with none, the language the file is written in), unless the request sets another. For a new file: the project language (the `language` key of docs/workbench/runtime.json, or the task's language line; English when absent)}
- Status: {in progress | waiting on user | approved}
- Date: {YYYY-MM-DD, from `date +%F`}
- Brief: docs/design/briefs/{artifact}.md
- Tool: {tool}
- Mode: {automatic | assisted}, because {reason}

## Runs

| Run | Round | Direction | Status | Pack | Outputs |
|-----|-------|-----------|--------|------|---------|
| R1 | 1 | {A name} | {planned | waiting on user | done | approved} | docs/design/results/{artifact}/round-1/{a-name}/prompt.md | {paths or links, or -} |

## Critique

| Criterion | R1 | R2 | R3 |
|-----------|----|----|----|
| CRIT-1 | {pass / partial / fail: evidence} | | |

Findings outside the criteria:

- {what would block implementation, or "none"}

## Decision

- Recommendation: {direction or round-2 changes, and why}
- Decision: {the user's answer, with the date | pending}

## Assumptions

- {Assumption: … | none}

## Next

- {round 2 | design-handoff | the questions}
