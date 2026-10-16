# Design brief: {artifact}

- Owner: design-brief
- Language: {the tag this file is written in. On an update: the tag on its Language line (with none, the language the file is written in), unless the request sets another. For a new file: the language the request sets for this deliverable, else the task's language line, else the `language` key of docs/workbench/runtime.json, else English}
- Status: draft
- Date: {YYYY-MM-DD, from `date +%F`}
- Type: {screen | mockup | logo | presentation | animation | image}
- For: {where the artifact is used; for a screen, the SCREEN id in the flows}
- Values: {inline | loaded: <design system as named in the tool>}
- Direction: {open: three directions | chosen: <name>, round 2}
- Lint: {ok (YYYY-MM-DD), written after the lint passes}

## Summary

{two sentences: what to explore, at which sizes and modes, and what is fixed versus open}

## Sources

- {design system, flows, copy source, specs, user review that triggered the brief}

## Subject

{what the product is, in two paragraphs a stranger can act on, with one concrete example}

## Audience and voice

- {who looks at the artifact and what they fear or want, one line per audience}
- Voice: {rules}
- Words to use: {list}
- Words to avoid: {list}

## Creative direction

{what the previous version got wrong, quoting the review, or "No previous version."}

{references as attitudes: scale, depth, motion, illustration; never layouts or copy}

- Direction A, "{name}": {the idea in two or three sentences}
- Direction B, "{name}": {…}
- Direction C, "{name}": {…}

{identity hooks every direction keeps; allowed; not allowed}

## Visual language

{inline: colour table in light and dark, type table, space, radii, borders, elevation, focus, motion, breakpoints, all written out.
loaded: the design system's name in the tool, its rules, and the values the direction depends on}

## Content

{the labelled parts the type profile requires, for example Regions / States / Breakpoints / Motion for a screen}

## Constraints

- {values only from Visual language; copy verbatim; accessibility; what the artifact must not contain; production or performance limits}

## Deliverables

- Round 1: {directions, one run each, at which size and mode}
- Round 2: {the complete set of the chosen direction}

## Evaluation criteria

- CRIT-1: {checkable by looking at the result}
- {at least five}

## Attachments

- Send: {the brief, reference images, the product's own assets}
- Do not send in round 1: {an existing design of this artifact}

## Prompt

```text
{the prompt, with a "Direction:" slot filled per run}
```

## Assumptions

- {Assumption: … (one line each, every fact that has no source) | none}

## Open questions

- OPEN-1: {question}. Blocks: {…}. Recommended: {answer and why}

## Readiness

- Ready for design-execute: {yes | no, because …}
