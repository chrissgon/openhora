# Feature specification: {feature}

- Owner: product-feature-spec
- Language: {the tag this file is written in. On an update: the tag on its Language line (with none, the language the file is written in), unless the request sets another. For a new file: the language the request sets for this deliverable, else the task's language line, else the `language` key of docs/workbench/runtime.json, else English}
- Status: draft
- Date: {YYYY-MM-DD}
- Feature of: {brief, PRD or phase this belongs to}

## Summary

{one or two sentences: what ships and for whom}

## Goal and users

- Problem: {from the brief or the user, with source}
- Users: {who, from the brief}
- Success: {what is observed when it works, measurable}

## Scope

- In: ...
- Out: ...

## Sources

- {document, decision id, file path, user answer date}

## Functional requirements

- REQ-1: {action} {object} {condition}. Source: {…}
- REQ-2: ...

## Non-functional requirements

- NFR-1: {quality} {number and unit} {condition}. Source: {…}

## Constraints

- {technical | business | operational}: {constraint}. Source: {…}

## Edge cases

- EDGE-1: {scenario} → {expected behaviour}
- Categories skipped: {which and why}

## Acceptance criteria

- AC-1:
  Given {precondition}
  When {action}
  Then {observable result}
  Covers: REQ-1

## Assumptions

- ASSUMPTION-1: {statement}. Safe because: {reason}

## Open questions

- OPEN-1: {question}. Blocks: {REQ-n | AC-n | nothing}. Recommended: {answer and why}

## Readiness

- Ready for architecture: {yes | no, because OPEN-n blocks REQ-n}
