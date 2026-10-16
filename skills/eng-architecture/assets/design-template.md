# Design: {feature}

- Owner: eng-architecture
- Language: {the tag this file is written in. On an update: the tag on its Language line (with none, the language the file is written in), unless the request sets another. For a new file: the project language (the `language` key of docs/workbench/runtime.json, or the task's language line; English when absent)}
- Status: draft
- Date: {YYYY-MM-DD, from `date +%F`}
- Specification: docs/product/specs/{feature}.md
- Frameworks and versions relied on: {name version (docs URL, accessed date) | name version (from package.json or the lockfile; documentation not opened)}

## Summary

{five to eight lines: what is built, from what parts, how a change flows from a file edit to the published site or the running system}

## Sources

- {specification, codebase map, decisions, framework documentation pages with URLs and access dates, files read}

## Decisions

| # | Decision | Chosen | Class | ADR or source |
|---|----------|--------|-------|---------------|
| 1 | ... | ... | decided \| engineering \| user | ADR-NNNN \| brief decision n \| user answer date |

## Components

| Component | Responsibility | Location | Inputs | Outputs | Satisfies |
|-----------|----------------|----------|--------|---------|-----------|
| ... | one sentence | folder or file | ... | ... | REQ-n, NFR-n |

## Data or content model

{schemas, folders, files, with validation rules and the EDGE they come from; show the framework's own form and cite the API}

## Contracts

### Routes
| Route | Params | Resolves to | Serves |
|-------|--------|-------------|--------|

### Files and generated artifacts
| Path | Produced by | Shape (example) | Consumed by | Serves |
|------|-------------|-----------------|-------------|--------|

### Component interfaces
| Component | Props / inputs | Slots / events | Serves |
|-----------|----------------|----------------|--------|

## Flows

### Build
1. {component} — {what happens}
### {Runtime flow}
1. ...
### Failure paths
| EDGE | Where it is caught | What happens | Message names |
|------|--------------------|--------------|---------------|

## Removals

| Removed | Replaced by | Must keep working | Checked by |
|---------|-------------|-------------------|------------|

## Verification plan

| AC | Check | Type | Command or location |
|----|-------|------|---------------------|

## Traceability

| Id | Where in this design |
|----|----------------------|

## Assumptions to verify before implementation

- {API or behaviour not cited, named in code}. Verify: {how, one concrete check}

## Open questions

- {only items the user must answer, with the component they block and a recommendation}
