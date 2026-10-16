# Handoff: {screen}

- Owner: design-handoff
- Language: {the tag this file is written in: on an update, the one already here unless the request sets another; else the project language}
- Status: draft
- Date: {YYYY-MM-DD, from `date +%F`}
- Screen: {SCREEN-n of the flows}
- Approved design: {results document and run}
- Export: {file}, unpacked to {folder}
- Lint: {ok (YYYY-MM-DD) | failed | not run}

## Summary

{two sentences: what is built and the few decisions that matter most}

## Sources

- {results, brief, design system, flows, specs, library version}

## Reference and shipping

- Reference only, never shipped: {tool runtime and its URL, inlined library copy, font CDN}
- Preview-only switches and placeholders: {each flag or data constant of the scripts by name: what it does in the preview, what the product does instead; or "none"}
- Shipped: {library version and how it is loaded, fonts, icons}

## Tokens

| Value | Where | Maps to | Action |
|-------|-------|---------|--------|
| {custom property or colour} | {regions} | {library token, site token or none} | {use token, add site token, fix in code} |

## Components

| Region | Unit | Props and data | Content source | States |
|--------|------|----------------|----------------|--------|
| {region of the SCREEN, in priority order} | {library markup or site component name} | {…} | {messaging, Markdown, config, build data} | {…} |

## Layout

| Width | Columns and order | Sticky | Collapsed or hidden |
|-------|-------------------|--------|---------------------|
| {1280} | {…} | {…} | {…} |
| {768, not designed} | {the rule the flows give} | {…} | {…} |

## Behaviour

| Interaction | Requirement | Rule |
|-------------|-------------|------|
| {copy, mode, theme, tabs, search, keyboard} | {spec REQ} | {what happens, persistence, fallback without JavaScript} |

## Motion

| Animation | Trigger | Timing | Final state | Reduced motion |
|-----------|---------|--------|-------------|----------------|
| {…} | {load, scroll into view, interaction} | {duration in ms, easing, stagger in ms, from the export} | {…} | {…} |

## Assets

- {logo files, icon set and names, fonts and weights, where each goes}

## Deviations

- DEV-1: {what the export does} against {what the source says, with its id: REQ-n, C-n, the design system, SCREEN-n}. Action: {fix in code | back to design | accepted (user, date)}

## Acceptance

- Reference: {screenshot paths, or the unpacked source.html when no screenshot was delivered}
- Compare at: {widths} × {modes} × {states}
- Tolerances: {layout, colour, type}

## Assumptions

- {Assumption: … | none}

## Open questions

- OPEN-1: {question}. Blocks: {…}. Recommended: {answer and why}

## Readiness

- Ready for eng-architecture: {yes | no, because …}
