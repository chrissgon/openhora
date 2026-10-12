# Artifact contract: `docs/workbench/state.md`

The state file is what lets a flow resume in a new session and lets the orchestrator know where a project stands. Every flow reads it first and updates it at every checkpoint. `core-project-init` owns the file and creates it; every other skill that writes into it lists it in `metadata.updates` (`contracts/project-layout.md`). A capability writes only the row of an artifact it owns, the decisions and open questions of its own work, and the approvals of its own confirmation gate.

Keep it small. It is a table of contents with status, not a journal.

## Template

```markdown
# Workbench state

- Project: <name>
- Current flow: <flow-name or none>
- Current phase: <phase name or none>
- Updated: <YYYY-MM-DD>
- Docs in git: <all | code | none | undecided>

## Autonomy

- Checkpoints: every-phase   # every-phase | milestones | end

## Artifacts

| Artifact | Owner skill | Status | Updated |
|----------|-------------|--------|---------|
| docs/business/idea-validation.md | biz-validate-idea | approved | 2026-09-22 |
| docs/business/business-model.md | biz-business-model | draft | 2026-09-22 |
| docs/engineering/architecture.md (at ARCHITECTURE.md) | existing | approved | 2026-09-22 |

## Decisions

- 2026-09-22: No brand phase; internal tool. (user)
- 2026-09-22: Pricing is usage-based; see docs/business/pricing.md. (biz-pricing, approved by user)

## Open questions

- [ ] Who owns customer support after launch? (raised by flow-fix-bug, phase 9, pull request)

## Approvals

| Scope | What | Payload hash | Approved | Expires | Status |
|-------|------|--------------|----------|---------|--------|
| action | LinkedIn post "Launching X" with image-01.png at 2026-09-23 09:00 | sha256:9f2c…(64 hex) | 2026-09-22 | after execution | pending-execution |
| standing | open pull requests on feature/* branches | — | 2026-09-22 | 2026-12-31 | active |
```

## Rules

- `Status` is `draft`, `approved` or `skipped`. Only the user approves. A skill sets `draft`; a checkpoint sets `approved` or `skipped`.
- Those three words are the only ones a row of the Artifacts table carries. An artifact's own header may carry a finer status that its owner's template defines (a post that is `drafted`, `scheduled` or `published`; a review that is `open`); the row keeps `draft` until the user approves the artifact, whatever the header says.
- **Who registers.** An artifact is registered in the Artifacts table, by its owner, when it is a named slot of the layout that later skills read as the project's current answer to something (a market analysis, a research brief, a critique, a repository baseline). Working records are not registered: plans, reviews, logs, inboxes and a check script's report file. A skill that registers lists the state file in `updates`.
- A pre-existing document is registered as `<slot> (at <real path>)` with owner `existing`. Skills that list the slot as an input read the real path. It is never moved or edited by registration.
- A flow resumes from the first phase whose artifacts are not `approved` or `skipped`.
- Decisions record what was decided, by whom, and where the reasoning lives. One line each.
- Open questions are checkboxes; a flow surfaces unchecked ones at every checkpoint. A draft artifact marks its own open questions `OPEN-<n>` in its text (the writing standard of `AGENTS.md`); in this file the line stays a checkbox, which may carry that mark (`- [ ] OPEN-1 ...`). The task runtime's merge of the state file (`runtime/state_merge.py`) reads a new open question in either form, with or without the checkbox, and writes it as a checkbox.
- `Docs in git` records which workbench folders under `docs/` go into git, a decision the user takes once per project: `all` (every workbench folder is committed), `code` (only `docs/product/`, `docs/design/`, `docs/engineering/`, `docs/ai/` and `docs/delivery/`; `docs/workbench/`, `docs/business/`, `docs/brand/`, `docs/marketing/` and `docs/security/` are work data, listed in `.gitignore`), `none` (no workbench folder is committed) or `undecided` (not taken yet; an open question asks it). `core-project-init` writes the line, and the same value in the workbench section of the project's `AGENTS.md`, at setup and when the user later states the decision. It is read by `ops-pull-request` before any commit under `docs/` (while it is `undecided` or missing, the skill asks and stops), by `ops-branch-sync` before it lets its approval row reach a commit, and by `flow-fix-bug` through `ops-pull-request`. A state file without the line counts as `undecided`.
- `Autonomy.Checkpoints` is set by the user once per project: `every-phase` stops after each phase; `milestones` stops only at phases marked as milestones in the flow's phase table; `end` runs every phase and presents one consolidated summary. Confirmation gates and blocking open questions stop the flow in every mode.
- Approvals follow the scopes and rules in `contracts/environment.md`. A skill checks this table before asking; an `action` or `plan` approval matches only when the approved payload file still hashes to its `Payload hash`, and a `standing` approval (`—`) matches when the action is inside its bounds and before its expiry. The table stores the hash, never the payload. Status moves `pending-execution` → `executed` (with timestamp) or `revoked`, and `active` → `expired` or `revoked`. A row of the task runtime's approvals is a copy code generates from the store's approvals table (`contracts/environment.md`, "Two records of approvals"); the row of a revoked standing approval leaves the file.
- Never store secrets, tokens or personal data here.
