# PRD: {product}

- Owner: product-prd
- Language: {the tag this file is written in. On an update: the tag on its Language line (with none, the language the file is written in), unless the request sets another. For a new file: the language the request sets for this deliverable, else the task's language line, else the `language` key of docs/workbench/runtime.json, else English}
- Status: draft
- Date: {YYYY-MM-DD}
- Brief: {path}

## Summary

{two or three sentences: what the product is, for whom, what changes with this PRD}

## Problem and goal

- Problem: {one sentence}. Source: {…}
- Goal: {one sentence, observable when reached}. Source: {…}

## Users

- U-1: {who}. Situation: {…}. Needs: {…}. Source: {…}

## Scope

- In: {…}. Source: {…}
- Out: {…}. Source: {…}
- Later: {…}. Source: {…}

## Sources

- {document, decision id, research citation, file path}
- User answer {YYYY-MM-DD}: "{the user's words}"
- User answer (accepted recommendation, {YYYY-MM-DD}): "{the recommended answer the user accepted with one word}"

## Features

- F-1: {name}. Outcome: the {user} can {…}. Priority: {must | should | later}. Phase: {P-n | OPEN-n}. Source: {…}

## Success metrics

- M-1: {metric}. Target: {number and unit copied from the source} {by when, only with a source}. Baseline: {value | none}. Measured by: {instrument}. Source: {document and decision that sets the target}
- No metric yet for {goal whose source sets no target}: the target is OPEN-{n}.

## Constraints

- {technical | business | operational | positioning}: {constraint}. Source: {…}

## Dependencies and risks

- R-1: {risk}. Trigger: {…}. Impact: {…}. Mitigation: {…}

## Release phases

- P-1: {name}. Includes: F-1, F-2. Exit: {observable state}. Source: {…}

## Assumptions

- ASSUMPTION-1: {statement}. Safe because: {reason}

## Open questions

- OPEN-1: {question}. Blocks: {F-n | M-n | P-n | nothing}. Recommended: {answer and why}

## Readiness

- Ready for feature specs: {yes: which first and why | no, because OPEN-n blocks F-m}
