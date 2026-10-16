# UX flows: {product}, phase {P-n}

- Owner: design-ux-flows
- Language: {the tag this file is written in. On an update: the tag on its Language line (with none, the language the file is written in), unless the request sets another. For a new file: the language the request sets for this deliverable, else the task's language line, else the `language` key of docs/workbench/runtime.json, else English}
- Status: draft
- Date: {YYYY-MM-DD, from `date +%F`}
- PRD: docs/product/prd.md
- Phase covered: {P-n}

## Summary

{two sentences: how many nodes, screens and flows, and what the first release must let each user group do}

## Sources

- {document, decision id, user answer date}

## Information architecture

- IA-1: {name}. Parent: {none | IA-n}. URL: {pattern}. Filled by: {content folder | generated | static}. Source: {…}

## Screens

- SCREEN-1: {name}. Purpose: {one sentence}. Regions: {first}, {second}, {…}. States: {default, empty, error, …}. Breakpoints: {what changes on narrow screens}. Source: {…}

## Flows

- FLOW-1: {name}. Actor: U-{n}. Trigger: {…}. Steps: 1. on SCREEN-{x}: {action} → {result}; 2. on SCREEN-{y}: {…}. End: {observable state}. Failures: {step n: what the user sees}. Keyboard: {keys for the same path}. Source: {…}

## Coverage

- F-1: FLOW-1, SCREEN-1
- F-2: no screen: {reason}

## Assumptions

- ASSUMPTION-1: {statement}. Safe because: {reason}

## Open questions

- OPEN-1: {question}. Blocks: {SCREEN-n | FLOW-n | nothing}. Recommended: {answer and why}

## Readiness

- Ready for design-system and design-brief: {yes: SCREEN-n first, because … | no, because OPEN-n blocks SCREEN-m}
