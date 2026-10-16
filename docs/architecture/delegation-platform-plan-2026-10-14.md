# Delegation platform plan: data in, one execution model, a score per model

Version 3, of 2026-10-14. On `origin/main` at `d3e60770`. A proposal, written before any of it was built; what has been built since is in the "Status (2026-10-15)" section below, and the rest of the document is unchanged, except the answers added to the items of section 7's "To verify". Version 1 came from an analysis of three branches and a two-round debate with an independent reviewer agent on another model, whose claims were checked against the code. Version 2 recorded the maintainer's decisions taken the same day while walking the open questions of version 1, and the contrast with the architecture document (`docs/architecture/delegation-platform-architecture-2026-10-14.md`, section 6, findings F1 to F16). Version 3 answers two further independent review rounds of the same day (section "Review rounds of 2026-10-14") and the maintainer's decisions D30 to D37 taken after them.

Version 1 was checked on `main` at `9bc9b863`, `origin/feature/parallel-agents` at `39600a0b` and `origin/feature/short-video` at `6794905e`; the release #393 (`d3e60770`) has since carried the `feature/parallel-agents` work into `main`, and `origin/feature/parallel-agents` has moved to `d9d3f069` (documentation commits). Every `file:line` below on `main` was read at `d3e60770` for version 2, and each one new in version 3 was read again on the branch this document sits on, which differs from `d3e60770` only in documents (the changes in `evals/` and `scripts/` since that commit are comment pointers, no line moved); a line number on `origin/feature/short-video` is at `6794905e`, except where a commit is named. The document was committed on a branch cut from `origin/main` at `d3e60770`.

How to read it: a path with a line number was opened and read for this plan. A claim with no line number was found by a search or comes from a command, and the text says which. A `new` element is never written as existing. A fact about a third-party service that was not confirmed is in the "To verify" list of section 7, never stated as fact. What was not verified is in section 10.

## Status (2026-10-15)

Added on 2026-10-15; nothing above or below it was rewritten except the answers added to section 7's "To verify" (items 2, 3, 4, 5, 9, 10, 11 and 13, each with its date and check, the original question kept), so a package's text still says what was planned. This section says what has been built, where, and what differed. The merges are on `feature/delegation-platform` (cut from `cd161411`, the commit that carries this plan); none is on `main` yet. Every PR number and commit was read from `git log origin/feature/delegation-platform` at `f51f41c3`. One package is not merged yet (P9) and is in review; it is not described as built anywhere. The log was read again at `f9d26ad1`, which merged P6c.

| Package | PR | Merge commit | What differed from the plan |
|---|---|---|---|
| P-1. Test speed | [#399](https://github.com/chrissgon/openhora/pull/399) | `997c38da` | pytest-xdist in the hook and in CI; the PB17 wording of the backlog |
| P2a. T24, evidence reader | [#395](https://github.com/chrissgon/openhora/pull/395) | `d9f5a5a2` | `evals/evidence_lines.py` reads both gate-file shapes; a committed evidence file is judged by its own event line, not by the gate file as it is now (backlog T24, done) |
| SEC. Keys against egress | [#396](https://github.com/chrissgon/openhora/pull/396) | `5e417ca9` | a held run reaches only its own key proxy; credential headers are dropped. It opened measurement version 9, which P2b closed |
| Fix, not a package: the security scan's allow entries | [#398](https://github.com/chrissgon/openhora/pull/398) | `66c2cfd1` | restored two `.security-scan-allow` entries that the removal of the old documents (`312c4e48`) had dropped and the history scan still needs |
| P0. Generic intake and container helper | [#397](https://github.com/chrissgon/openhora/pull/397) | `1ae61de4` | as planned (`runtime/intake.py`, `providers/_container.py`) |
| P1. `web_measured` | [#394](https://github.com/chrissgon/openhora/pull/394) | `d0e8e0a0` | as planned |
| P2b. Key proxy per run, routes, metering | [#401](https://github.com/chrissgon/openhora/pull/401) | `dfc9336c` | closed measurement version 9 (`docs/decisions.md`). Its review fixes came as a second pull request, [#405](https://github.com/chrissgon/openhora/pull/405) (`8f5acb3a`), one infrastructure measurement change |
| P2c. Gate, usage and local evidence per model | [#402](https://github.com/chrissgon/openhora/pull/402) | `84c53425` | as planned |
| P2d. The published eval image | [#400](https://github.com/chrissgon/openhora/pull/400) | `f4ce7294` | the workflow, the verified lock file (`scripts/image_lock.py`), the doctor's setup step and the runtime's identity by repo digest are built; the first publication (a manual dispatch on `main`, then making the package public) is a maintainer step still to do |
| P3. Model choice and `auto` | [#404](https://github.com/chrissgon/openhora/pull/404) | `54f08b5f` | store migration 10; the tiers left; one price table (`runtime/prices.json`). A follow-up, P3b ([#406](https://github.com/chrissgon/openhora/pull/406), `24aea736`), gave consent its own policy group, fixed the warning's text and took the tiers off the public site |
| P4. Sources I | [#407](https://github.com/chrissgon/openhora/pull/407) | `b4084a08` | store migration 11; limits L21 to L27. Its converter was extended by P4b ([#411](https://github.com/chrissgon/openhora/pull/411), `d39ebd11`): Microsoft's MarkItDown was measured against the converter's tools and not adopted (it won only on presentations, and only against having no tool for them), and presentations are converted with python-pptx (`docs/decisions.md`, 2026-10-15) |
| P5. The step task and the step engine | [#408](https://github.com/chrissgon/openhora/pull/408) | `93a6fe26` | store migration 12. The stop word `approval` was removed from `STOPS` (`runtime/steps.py`: only `review` remains) because nothing yet gave it a meaning; P8 then built the gate as a separate `Gate` of a kind, not a stop word. A follow-up, P5c ([#412](https://github.com/chrissgon/openhora/pull/412), `04238c93`), moved the dispatcher's flag under the lock and showed the brake on the page |
| P-OPS. Running unattended | [#410](https://github.com/chrissgon/openhora/pull/410) | `af6341f3` | no migration. The lease of a synced sources folder is limit L28 and the retention of runs and source versions is L29 |
| P6a. Workflows with steps, parameters and dates | [#413](https://github.com/chrissgon/openhora/pull/413) | `f51f41c3` | P6 was split in two: P6a (this) and P6b (routines). Store migration 13 (`tasks.web_off`) |
| P7. Sources II: Google Drive | [#409](https://github.com/chrissgon/openhora/pull/409) | `0e401ecb` | files only, scope `drive.file` (the spike refuted item 1 of "To verify" and confirmed item 8). A Drive file was stored as a `file` row with the origin `drive:<file id>` until migration 14 (P6b) let the registry say `drive` |
| P10. Community evidence | [#403](https://github.com/chrissgon/openhora/pull/403) | `9c813685` | as planned; the grader has its own entry in the gate file (P3), so a community run of any listed model writes evidence |
| P8. Outputs | [#414](https://github.com/chrissgon/openhora/pull/414) | `7132f769` | no migration. A second container image and class, `exporter:document` (`providers/exporter/`, image `openhora-exporter`), makes the CSV, workbook, Word and PDF files; the step kinds `export-csv`, `export-xlsx`, `export-docx`, `export-pdf` and `write-back` register in the engine; the new side-effect word `write` and its effect kind (`runtime/effect_write.py`) carry the write to a Notion page, approved only from the terminal or the page by the hash of the exact content; the engine's `Gate` replaces the `approval` stop P5 removed; the converter flags hidden text in HTML and PDF. Limits L30 to L32 |
| P6b. Routines | [#415](https://github.com/chrissgon/openhora/pull/415) | `370d9dfa` | store migration 14: tables `routines` and `routine_fires`, and the `drive` source type (it rewrote P7's rows). A routine is approved by the hash of its exact content (schedule, workflow template, the skills' `X.Y`, the eval image digest, the model with the routine's own consent, the providers for `auto`), fires once for each slot with a catch-up rule, and stops and asks when anything it hashed changed. Limit L33: a routine whose workflow holds a networked step or a standing-policy effect is created and changed only from the terminal or the page |
| P6c. Routine follow-up | [#418](https://github.com/chrissgon/openhora/pull/418) | `f9d26ad1` | a default model that the gate file no longer lists is now the problem of the one routine that follows it, not of the list of routines; the contract's sentence on counting slots says the later of the last fire, the approval and the last resume |
| P9. Project script | [#416](https://github.com/chrissgon/openhora/pull/416) | in review | limits L34 to L38 are planned numbers; the script it runs, once changed, asks for a new plan |

Migration numbers as built: P3 10, P4 11, P5 12, P6a 13 (`tasks.web_off`), P8 none; P6b 14 (routines, routine fires, the `drive` source type). Limit numbers as built: L21 to L27 (P4), L28 (lease) and L29 (retention) from P-OPS, L30 to L32 (P8), L33 (P6b); L34 to L38 (P9) are in review. Files and code still say "flow" (`flows/`, `runtime/flow_files.py`, the operations `flows` and `flow-save`); the pages and the operations' help say "workflow".

## What changed from version 2

Two independent review rounds of the same day (round 1: S1 to S10 and I1 to I6; round 2: Q1 to Q6 and M1 to M6) checked version 2 against the code, and the maintainer decided the open points after them. The findings are listed with the place that resolves each in the section "Review rounds of 2026-10-14".

- **Decisions D30 to D39 are new,** and the decisions they change are marked "changed by D3x" in section 3. D30 renames the folder of D9 the **sources folder** (`sources_dir`) and extends D10's guardrails. D31 makes a routine always target an existing workflow, which supersedes D16's planner split, the plan-time part of D27 and rule 2 of D24. D32 and D33 add "Save this plan as a workflow" and date variables. D34 lets scores inform and rank but not gate a model the person chose, with an explicit per-routine consent for unattended work. D35 widens what a routine's approved hash covers. D36 says community evidence never grants unattended release. D37 leaves free-text requests in manual use as they are. D38 and D39, taken when the maintainer accepted two points left pending, complete D34 and change D21: D38 makes the setting of an agent's model, with the agent `autonomous`, the consent for manual use, and D39 makes the first pull of the published eval image an explicit setup step.
- **The word "data folder" is gone.** It named D9's folder; the runtime's own `data_dir` (`runtime/project_config.py`, lines 12 and 88) is a different, required folder outside every repository. Every use below says "sources folder" or `sources_dir`.
- **The packages are re-cut.** New: P-1 (test speed), SEC (a live defect of today's code), P2a to P2d (P2 split four ways), P-OPS (what makes a 24-hour runtime supportable). Shrunk: P0 (only the generic streaming intake and the container helper; no store, no step task) and P1 (only `web_measured`). Grown: P3 (a symbol-level inventory of the tier code), P4 (the sources folder as hard limits, a separate Notion secret, one X change of `core-orchestrator`), P5 (it now owns the step task whole), P6, P7, P8, P9 and P10 (each takes the findings of the review rounds that concern it).
- **The order changed** (section 6, "Order and funding"): P-1, P2a, SEC, then P0 with P1, then P2b with one battery after it, then P2c and P2d, P3, P4, P5, P-OPS, P6, P7, P8, P9, P10; the short-video rebase stays off the critical path.
- **Corrections to version 2.** Two claims were wrong: there is no content-addressed store on `origin/feature/short-video` to port (P0 ports the streaming intake only), and `providers/resolve.py` does not find a new class by its folder, since a role must be added to `ROLES` and `LISTED` (`converter` is in neither, `providers/resolve.py`, lines 91 to 95). One point was left as a question and is decided: the planner's edit of `core-orchestrator` is one X change, because its **External content is data.** line must name the catalog (P4). One was ambiguous and is fixed: "data folder" named two different folders.
- **Counts re-run for this version** are in section 10 and in the packages that use them (43 runtime test files name `runtime.json`; 22 contain the word `tier`; the operations module has 86 lines of budget left).

## What changed from version 1

- **Decisions D9 to D29 are new.** D1 to D8 keep their wording; D7 (community evidence set aside) is superseded by D19. D9 to D26 answer OPEN-1 to OPEN-6 and the gaps of the architecture document. D27 to D29 were taken later the same day and close three points that were assumptions or unspecified: D27 refines D16 (a task that requires the web never runs without it silently; a hand-written flow that gives sources to such a task is refused as a routine target), D28 puts attachments, model choice and flow choice over messaging in a later evolution after P6, and D29 fixes which source version a task gets (the newest at the moment it starts, recorded on the task).
- **The packages are renumbered P0 to P10 and a side package.** Version 1 had packages 1 to 6. A new P0 ports the generic short-video pieces (it absorbs version 1's package 2, the container helper). Version 1's package 4 splits into P2 (measurement identity) and P3 (model choice and `auto`); package 3 becomes P4 (sources I); package 5 becomes P5; package 6 becomes P6 (flows with steps, parameters and routines). P7 (Google Drive), P8 (outputs), P9 (project script) and P10 (community evidence) are new, and the short-video rebase is a side package off the critical path.
- **Findings resolved.** F1 to F16 of the architecture document are each assigned to a package (section 6, "Resolves" lines). Version 1's wrong claims they found are corrected here: the key proxy needs more than one fingerprinted file (F1), the gate file already has a `models` object (section 6, P2), the per-model gate does not hold yet for events per model (F6), and the dependency order of the data hand-over (F7).
- **Open questions closed.** OPEN-1 to OPEN-6 are closed by D9, D13, D15, D23, D22 and D26 (section 7). What is open is the "To verify" list and the real cases to choose during development (D17).
- **Counts recomputed.** The per-model band counts of section 2 were run again on this branch; they differ from version 1 (section 2 says how). Main-side line numbers are re-read at `d3e60770`.

## Review rounds of 2026-10-14

Two independent review rounds read version 2 against the code. Round 1 produced S1 to S10 (security) and I1 to I6 (installation and operation); round 2 produced Q1 to Q6 (code quality) and M1 to M6 (maintenance). The severity words are the reviewers': BLOCKER (the plan cannot be built, or is unsafe, as written), MAJOR, MINOR. The finding is the reviewers' own one line, shortened where needed; the last column is the author's, and names the decision or the package of section 6 that resolves it.

| ID | Severity | Finding | Resolved in version 3 by |
|---|---|---|---|
| S1 | BLOCKER | Live today: held-key runs reach the provider hosts through the egress proxy, and the key proxy forwards `x-api-key` | SEC; item 9 of "To verify" |
| S2 | MAJOR | The key proxy checks no model and no spend; P2 would let the request body choose the pin; cost comes from the run's own output | P2b |
| S3 | MAJOR | A routine's approved hash does not cover skill content, model and adapter, image or script | D35; P6 |
| S4 | MAJOR | Community-only evidence would grant unattended release to everyone | D34, D36; P3 (principle 9 reworded) |
| S5 | MAJOR | Attestation hardening: split the id-token job, bind the signer digest, no self-hosted runners, no cache, verifier from the base commit | P10 |
| S6 | MAJOR | Gaps in the data-folder guardrails: disjoint paths, container outputs, edits from outside, catalog built from converted output | D30; P0 (the container lifecycle); P4 (limits L21 and up) |
| S7 | MAJOR | Credential scope: the read-write Notion token is reused, `drive.file` reads and writes, and the Picker in the page breaks the page's rules | P4 (a separate read-only Notion secret); P7 (a one-shot loopback page; the scope stated) |
| S8 | MAJOR | A script's declared destinations cannot be enforced, and dependency installs need network | P9 |
| S9 | MINOR | Formula injection in outputs, hidden text, and the write-back target outside the hash | P8 |
| S10 | MINOR | Routines with networked scripts or standing effect policies only from the terminal or the page | P6 |
| I1 | MAJOR | Image identity by the local `.Id` does not travel; digests are per platform | P2d; item 10 of "To verify" |
| I2 | MAJOR | The supply chain of the published image is unspecified, the proxies' packages are unpinned, and the first pull happens in the middle of a dispatch | P2d (and SEC and P2b for the proxy pins, made before the battery) |
| I3 | MAJOR | 24-hour running on a headless server is not designed: a locked keyring reads as "not found", macOS file permissions, disk, logs, remote access | P-OPS |
| I4 | MINOR | Two runtimes on one synced folder | P-OPS (lease file with the host id) |
| I5 | MINOR | Routine fires must be idempotent per routine and slot, with a catch-up rule | P6 |
| I6 | MINOR | Orphan containers after a crash | P2b (labels and log limits) and P-OPS (the check and the removal) |
| Q1 | BLOCKER | The step task is designed three incompatible times (P0, P1, P5) | P5 owns it; P0 ports no store code; P1 keeps only `web_measured` |
| Q2 | MAJOR | "Data folder" already means `data_dir` | D30 (the sources folder, `sources_dir`) |
| Q3 | MAJOR | Concepts without one owner: the registry, the catalog, prices in four places, the container lifecycle written twice, the Drive class | Rules for every package, rule 3 (`runtime/sources.py`, `providers/_container.py`, one price table); P3; P7 (Drive as `integration:documents`) |
| Q4 | MINOR | P0's intake "port" is a rewrite, no content-addressed store exists, and `ENV_KEEP` is hard-coded | P0 (the intake core; the environment from `resolve.variables`) |
| Q5 | MINOR | Loose naming: planner against router run, three meanings of "kind" | Rules for every package, rule 5 (the glossary) |
| Q6 | MINOR | Test cost (about ten minutes serially in the hook) and 43 test files that write `runtime.json` | P-1; P4 (the fixture helper) |
| M1 | MAJOR | New code would land in oversized modules (`runtime/ops.py` has 86 lines of budget left) | Rules for every package, rules 2 and 3 (siblings, fixed homes) |
| M2 | MAJOR | Store migrations spread over five packages with no owner | Rules for every package, rule 1 (numbers 10 to 13; `architecture_tables.py --check`); P5 |
| M3 | MAJOR | Tier removal under-scoped: no symbol-level inventory, the site builder missed | P3 |
| M4 | MAJOR | The `core-orchestrator` lab cost is underpriced and split | P4 (one X change, one full test, 54 to 72 runs) |
| M5 | MAJOR | P2 is too big, and the image identity rule is missing | P2a to P2d |
| M6 | MAJOR | Documents and contracts out of sync, and new hard limits without a home | Rules for every package, rule 4 (limits L21 and up); each package's "Done when" |

## 1. The target

The maintainer's goal, stated on 2026-10-14, translated: a multi-AI platform for delegating tasks to agents, working with different tools and data sources.

It has three pillars.

1. **Data sources and persistence.** Notion, Jira, Google Docs and others. Files: HTML, PDF, XLS, CSV.
2. **The brain.** The runtime, the skills and the models.
3. **Tools.** The adapters and the connections.

It runs in three modes.

| Mode | What it is | Example |
|---|---|---|
| (a) A simple agent | One request, approved skills, the model the person chose | "Do a market research on this idea." |
| (b) A workflow | Stages, several agents, several skills | Research, then positioning, then a landing page |
| (c) A routine | A scheduled start of an existing workflow (a workflow of one step when the work is plain code, D31) | Every Monday, refresh the sources and start the weekly report |

The rest of this plan answers three questions: what exists for each pillar and mode, which order of work reaches the target at the least risk, and which decisions the maintainer took.

## 2. Where we are

State is one of `exists`, `partial`, `missing`. The evidence column is a path, and a line number where one was read. Paths on `main` are at `d3e60770`.

### Pillar 1: data sources and persistence

| Capability | State | Evidence |
|---|---|---|
| One SQLite store per project | exists | `providers/store/sqlite.py` (`SCHEMA_VERSION = 9`, line 53) |
| Documents mirrored outward to Notion | exists | `runtime/documents.py` (`push`, line 533) |
| The person's edits pulled back from Notion | exists | `runtime/documents.py` `pull`, line 503 |
| A Notion page read by id | exists | `providers/documents/notion.py` `cmd_read`, line 589, verb `read` in `VERBS`, line 707; the contract row is `providers/CONTRACT.md`, line 116 |
| A Notion page read by URL | missing | `doc_id`, `providers/documents/notion.py`, line 527, accepts only the 32-character page id |
| Gmail read, GitHub, LinkedIn, a Notion issue tracker | exists | `providers/mailbox/gmail.py`, `providers/vcs/github.py`, `providers/publisher/linkedin.py`, `providers/issue-tracker/notion.py` |
| Jira | missing | The word is only in `contracts/environment.md`, line 10, as an example of the `integration:issue-tracker` class; no provider and no runtime code names it |
| Google Docs and Drive | missing | No provider folder |
| PDF, XLSX, CSV, HTML parsing | missing | The only PDF reader is `skills/brand-profile/scripts/profile_export.py` (lines 185 to 191, `pypdf`), for one LinkedIn export |
| Taking a file in | partial | The file drop copies the raw file, 25 MB at most (`runtime/drop.py`, `MAX_BYTES`, line 49; `hand_over`, line 76) |
| Indexing, RAG | missing | Nothing in `runtime/` or `providers/` |
| File outputs (PDF, XLSX, DOCX, CSV) | missing | No code produces them for the person |

The Notion read is mostly built. The provider reads a page by id and prints its Markdown, its version and its open comments. What is missing is the entry point that starts a read as a data source, and the step that places the result where a task can see it.

### Pillar 2: the brain

| Capability | State | Evidence |
|---|---|---|
| Router, then a plan approved by hash, then one skill per task, run in the eval container | exists | `runtime/router.py`; `runtime/plan.py` (`plan_hash`, line 316, the sha256 of the plan's tasks as JSON); `runtime/ops.py` (`approve`, line 2051); `runtime/lab.py` |
| Model choice | partial | Two fixed tiers: `runtime/proof.py` (`TIERS`, line 41; `route`, line 118; the refusal "only the reference model can be asked for", line 133; called at `runtime/ops.py`, line 355) and `evals/eval-gate.json` (`strong_model`, line 2; `floor_model`, line 4; a `models` object of ids and aliases, line 33) |
| A band, a gate and a score for every model that has evidence | exists | `evals/eval_status.py` (`as_reference`, line 1095; `skill_band`, line 1965; the per-model loop, line 2074). Computed again on 2026-10-14 with `python3 evals/eval_status.py status` on this branch: 48 skills; the band that decides the standing is `reliable` on 45 and `needs a test` on 3 (`core-orchestrator` and `mkt-vote-round`, whose guard assertions have no run in the current set, and `mkt-social-copy`, which has no full test of version 2.x); the floor model is `reliable` on 41, in `watch` on 2 and in `needs a test` on 4, with no entry for one skill |
| A baseline on a second model | exists | `evals/eval_run.py`, option `--baseline-on <model>` (line 36). Counted in the committed `lab-*.jsonl` files on 2026-10-14: 192 baseline run lines on the reference model and 181 on the floor model |
| Flows | partial | JSON files of skill tasks in `flows/` (six, `short-video.json` among them), loaded from the workbench checkout only: `runtime/flow_files.py` `ROOT` (line 44), called with `core.ROOT` at `runtime/ops.py`, lines 402, 1568 and 1642 (and 1777 and 1967). A task with `"writer": "user"` is reserved and not read (`runtime/flow_files.py`, line 23; `TASK_KEYS`, line 47, has no `writer`) |
| Tasks in parallel | exists on `main` (release #393) | `runtime/parallel.py` `admit` (line 87); slots per agent up to `MAX_PARALLEL_CEILING = 4` (`runtime/autonomy.py`, line 77); per project `max_running`, default 3 (`runtime/project_config.py`, lines 166 to 172) |
| A task with no skill | exists on `feature/short-video` only | `providers/store/sqlite.py` `is_code_task` (line 1487), `code_task_add` (line 1498), `code_task_move` (line 1528) |
| A resumable step engine | exists on `feature/short-video` only, for one pipeline | `runtime/pipeline.py`: `ORDER` (line 71), `STOPS` (line 75), `run` (line 747), `prepare_again` (line 808) |
| Agent memory | replaced by the standing instructions (SPEC-INSTRUCTIONS, 2026-10-16) | `docs/backlog.md` R2; `contracts/runtime.md`, "Standing instructions" |

### Pillar 3: tools

| Capability | State | Evidence |
|---|---|---|
| Schedulers | exists | `providers/scheduler/launchd.py`, `providers/scheduler/systemd.py` |
| MCP as a server | exists | `runtime/mcp.py`: the operations layer served as tools |
| MCP as a client, inside a run | missing, on purpose (D15) | The run script of the reference model's adapter (the `strong_harness` of the gate file) passes `--strict-mcp-config` at line 99 and says at line 18 that no MCP server or connector is loaded |
| Five messenger providers and a channel policy | exists on `main` (release #393) | `providers/messenger/` holds `telegram.py`, `discord.py`, `whatsapp.py`, `whatsapp-cloud.py`, `whatsapp-twilio.py`; the page is `docs/architecture/platform/messaging.md`; the policy key is `channels` in `runtime.json` (`runtime/project_config.py`, `_channels`, line 182) |
| Prices of models | partial | `adapters/api/prices.json` (six models, with source and access date) and the project's `model_prices` (`runtime/project_config.py`, lines 53 and 159; `runtime/costs.py`, line 7) |

### Run modes

| Mode | State | Evidence |
|---|---|---|
| (a) A simple agent | works for the example | `biz-market-analysis` and `core-research` have web cases (`evals/eval-gate.json`, `web_cases`, line 24), and `biz-market-analysis` is `reliable` on both models (`docs/inventory.md`, lines 222, 276 and 277) |
| (b) A workflow | partial | Flows of skill tasks exist; a step that is plain code does not fit a flow (`runtime/flow_files.py`, `TASK_KEYS`, line 47) |
| (c) A routine | missing as a concept | The pieces exist: the scheduler providers; the dispatcher's jobs `poll` and `work` (`runtime/dispatcher.py`, `JOBS`, line 163); handlers ticked each round (`runtime/ops.py`, `_ticks`, line 2444); `runtime/handlers/published_posts.py` with `due` (line 206) and `tick` (line 392) |

## 3. Decisions taken by the maintainer on 2026-10-14

D1 to D8 were taken in version 1. D9 to D26 were taken the same day while walking the open questions, and D27 to D29 later the same day. D30 to D37 were taken after the two review rounds (version 3), and D38 and D39 when the maintainer accepted the two points left pending (they complete version 3). The bracket after a decision names the question it closes or the finding it answers. A decision that a later one changes carries the mark "changed by D3x" at its start and keeps its original text, so the history stays readable; where the two differ, the later decision holds.

1. **D1. The reference and floor tiers leave. A skill has a status per model.** Approved on one model says nothing of another. Every pair of skill, model and adapter has its own band, gate and score. Consequence: principle 9 of `AGENTS.md` is rewritten without the tiers, and the code that reads `TIERS` changes (P3).
2. **D2. Anyone may test a skill on any model.** The maintainer's own lab runs stay on `claude-sonnet-5-5` and `openrouter/deepseek/deepseek-v4.1-flash`. The grader stays fixed (`grader` in `evals/eval-gate.json`, line 8), so scores compare across models.
3. **D3. The person chooses the model for a run,** or `auto`. An `auto` mode chooses by the skill's score on each model against its cost.
4. **D4. The baseline (runs without the skill) is kept per model,** to measure the difference the skill makes on that model. Consequence: the second-model baseline option already exists (`--baseline-on`), so this costs runs only for a model that has none.
5. **D5. Auto ranks by the providers' list prices:** measured tokens per run times the provider's price, not by subscription.
6. **D6. A new skill enters the repository after a full test on the two lab models.** Its result is published whether it passed or not (principle 10). It runs unattended only where it is `reliable`.
7. **D7. Community lab evidence was set aside. Superseded by D19.** Today lab evidence is trusted because the maintainer runs it (`evals/README.md`, "Who runs the lab tests", line 119); field evidence is counted per contributor (`evals/eval_status.py`, `FIELD_CAP`, line 1729).
8. **D8. (changed by D34 and D38) Proof keeps deciding autonomy (principle 9) and no longer decides access.** A model the person picks without `reliable` evidence runs `supervised` and is marked unproven. The hold already exists: `runtime/autonomy.py` `review_action`, rule 5, "the skill is not proven: hold" (docstring, line 322; code, line 336).
9. **D9. (changed by D30: the folder is the "sources folder", key `sources_dir`) Data is not centralized (OPEN-1).** Each project declares its sources in a registry; no credentials in it, credentials stay in the OS secret store. Imported data lives in a **sources folder the user defines per project, mandatory**: no default, and a project without one does not run. It is outside the workbench's git; the user may keep it in a repository or drive they already use and version it as they like. Each import is an immutable version: the original, the converted text (Markdown or CSV) and a manifest (origin, date, sha256).
10. **D10. (changed by D30, which extends the guardrails) Guardrails of the sources folder.** Its path is set in the project's accepted configuration (`runtime.json`, accepted only in the terminal: `runtime/project_config.py`, lines 98 and 232). The runtime writes only inside it, never follows a symbolic link out, and refuses dangerous paths (the home folder, the filesystem root, a folder that contains the project). The work copy always excludes it, even when it sits inside a tracked tree. A file changed after import is detected by its hash and treated as a new version made by the person, never handed over as the recorded one.
11. **D11. A task sees only the sources chosen for it.** The **planner chooses** them from a **rich catalog built by code at import, with no model**: name, type, size, date, sheets and columns with sample values, first headings, and the person's optional description. The choice is shown in the plan the person already approves by hash; the planner asks when in doubt; an optional `@mention` in the request forces a source; flows and routines pin the source **id**, not the version. Teaching the planner to choose is a change of `core-orchestrator` (version 2 said a Y change with a partial test; corrected in version 3 by M4: one X change with a full test, because the catalog must be named in the skill's external-content line, P4). The catalog is third-party text: data, never instruction. **Option B** (a non-web task gets the whole sources folder read-only and reads on demand, like a hosted assistant's project retrieval mode) is a future per-project opt-in, off by default, considered only after evidence that the planner misses files, with eval cases that measure folder exploration (principle 13). A source too large for a run gets a size cap with a warning; indexing or RAG waits for a real case.
12. **D12. Integration sources are refreshed on demand or by a routine.** Each refresh is a new version; a task records which version it read.
13. **D13. First sources (OPEN-2):** uploaded files and Notion, then **Google Drive in general** (Docs, Sheets, Slides, PDFs and any file, not only Sheets). OneDrive and Jira wait for a real project. Google OAuth follows the Gmail provider's pattern (`providers/mailbox/README.md`, lines 17, 18 and 26: the person's own Desktop OAuth client, the app published "In production" for personal use, the refresh token in the OS secret store). Native Google files are exported by the Drive API and then converted; other files are downloaded and converted.
14. **D14. Drive permission.** Scope `drive.file` with the Google Picker (only what the person picks), not `drive.readonly`. A source may be a folder or a single file. Google documents a desktop and mobile Picker flow that returns through a callback URL (to verify, section 7).
15. **D15. No MCP inside runs (OPEN-3).** MCP servers may be adopted only on the host, as provider implementations with read verbs; the agent receives files, never the tool.
16. **D16. (the planner split is superseded by D31) Ingested content and the web (R1, F10; refined by D27).** In manual use, the plan card highlights a web task that receives sources; approving the plan is the person's choice. In a routine, a task that receives sources runs **without the web**; work that needs both is split by the planner into a web task without sources and an analysis task with sources and no web.
17. **D17. Both output directions are in the plan (G6, F14).** (1) File outputs (PDF, XLSX, DOCX, CSV) generated by a code step, no model, with adopted tools, into the sources folder or `docs/`. (2) Writing back to Drive or Notion as an external effect: preview of the exact content, one approval, execution, record, with a check that nobody edited the target since it was read. The real case is chosen during development.
18. **D18. Each person's own tests of any model stay local** (outside the workbench checkout, so `git pull` never conflicts) and feed only that person's `auto`. Adding a model must not change a fingerprinted file.
19. **D19. (clarified by D36: community evidence never grants unattended release; the text is unchanged) Community evidence, approved (supersedes D7).** The contributor runs the official reusable workflow, referenced by commit, in their fork's CI with their own keys. The workflow checks out the official code at that commit; GitHub attests the evidence file; the pull request carries the evidence and its attestation. The workbench's CI verifies without a model call (the signature, `--signer-workflow` of the official workflow, that the commit is in the history of `main`, and that the digest matches) and records the result as "community verified": its own column per model, a per-contributor cap, and it counts for everyone's `auto`. Mitigations: every completed run of the fork's workflow must be submitted and gaps in run numbers are flagged (against cherry-picking); the pessimistic score and the cap; field evidence demotes a pair after three `failed` verdicts. The provider host and the per-model pin live in the attested code, so a fake server is impossible. Residual risks: cherry-picking and provider honesty. Later evolution: the maintainer's own score tests (lab runs of `eval_run.py`) move to the same attested CI.
20. **D20. Platforms.** Evidence from `linux/amd64` is accepted beside `linux/arm64`, the platform recorded on each line, both summed (split only if results diverge). Testing only on amd64 was rejected: the maintainer's machine would emulate, switching platform is an execution epoch for every skill, and arm64 users exist.
21. **D21. (changed by D39: the first pull is an explicit setup step, not automatic on first use) The eval image is published (G2, F3).** To a registry, by digest per platform, from a pinned definition. The repository records the digests in a lock file. The runtime pulls the image automatically on first use, with a message. Evidence records the published digest; the proof check compares the local image with the published digest; a locally built image yields local-only evidence. A person only checks out `main`.
22. **D22. (extended by D34, D35 and D36) `auto` picks the cheapest `reliable` pair (OPEN-5),** with no extra minimum score and no per-project setting. A critical project selects a strong model by hand.
23. **D23. (changed by D31: a routine targets a workflow only; by D34 and D35: consent and the approved hash) Routines (OPEN-4).** Created and changed from the terminal or the page, approved by the sha256 of their exact content (schedule, target, arguments). They carry no mode, cap, policy or standing approval of their own, and each fire counts against the agent's daily caps. Messaging's routine permissions are configurable through the existing channel policy (`channels.messaging` groups, accepted in the terminal): by default only the brakes (list, pause, cancel); the person may grant creating and changing. MCP stays outside the ceiling of creating and changing routines (it may list them).
24. **D24. (rule 2 superseded by D31; rule 3 changed by D34; rule 1's hash widened by D35) Three rules for an unattended routine (E2, F4; R2, F12).** (1) Creating a routine generates its plan and the person approves that plan's hash with it; at each fire the plan is regenerated and tasks are created without asking only if the hash is identical, else it stops and asks (a new version of a source does not change the plan, which pins the source id). (2) A free-text routine never runs unattended: each fire becomes a plan to approve; only fixed targets (a flow or a step) run alone. (3) Tasks proceed without review only on `reliable` pairs with the agent in `autonomous` mode; otherwise the routine waits at the first review and messaging notifies. Effects still need approval of their exact content unless a standing policy accepted in the terminal covers them.
25. **D25. (the content of the hash restated by D35; the enforcement of the network by P9, S8) A "project script" step kind (G5, F11).** Approved by its exact hash (a changed file stops and asks). It runs in the shared sandboxed container without credentials and with a read-only root; the network is off by default, and declared destinations enter the approved hash; it writes only into the sources folder, as a new versioned source; no direct effects. Python and shell first, with dependencies declared and pinned.
26. **D26. (the order is replaced by the one of version 3, section 6 "Order and funding") The order of section 6 (OPEN-6).**
27. **D27. (its plan-time part is superseded by D31) A task that requires the web never runs without it silently (refines D16).** For a plan the planner makes, D16's split applies: a web task without sources and an analysis task with sources and no web. For a fixed flow written by hand, the flow check refuses a flow in which a task that requires the web receives sources, when the flow is a routine's target: at routine creation and again at the plan of each fire. Its message tells the person to split the flow into a web task without sources and a task with sources and no web. So no routine runs a web-requiring skill without the web. In manual use D16 stands: the plan card highlights the web task that receives sources and the person decides.
28. **D28. Attachments, model choice and flow choice over messaging are a later evolution of the messaging channel, after P6.** Until then they are done on the page or in the terminal (section 9).
29. **D29. A task receives the newest version of each chosen source at the moment it starts,** and that version (id, version, sha256) is recorded on the task.
30. **D30. The sources folder (changes the wording of D9 and D10; S6, Q2).** The folder of D9 is called the **sources folder** and its key in `runtime.json` is `sources_dir`; it is never called the "data folder", because the runtime's `data_dir` (`runtime/project_config.py`, lines 12 and 88) is a different required folder, for run folders and locks, that must stay outside every repository. D10's guardrails are extended: the sources folder must be dedicated (empty, or marked as the runtime's at acceptance), have mode 0700, and be disjoint from `data_dir`, from `store_db`, from the workbench checkout and from the local evidence folder of D18. A container's outputs go to a size-capped memory-backed folder, and the host copies back only regular files, checked with `lstat` and opened with `O_NOFOLLOW`, under a byte cap and naming rules. A file changed outside the runtime is sniffed, converted and scanned again, labelled as changed by the person, and never used unattended. The catalog is built only from converted output, never by parsing a raw file on the host.
31. **D31. A routine always targets an existing workflow (supersedes D16's planner split, the plan-time part of D27 and rule 2 of D24).** There are no free-text routines. A single step or a project script is a workflow of one step. The mix of web work and sources is settled when the workflow is created: the flow check refuses a task that requires the web and receives sources and, when the skill accepts a research brief as an input, offers a split made by code: `core-research` with the web and without the sources, then the skill without the web, with the sources and the brief. Today two skills that require the web list the brief among their `inputs`: `biz-market-analysis` and `biz-icp-positioning`. For any other skill the check asks the person. A plan made from a free-text request in manual use keeps D16's highlight on the plan card. The router's grammar does not change.
32. **D32. "Save this plan as a workflow."** A free-text request is planned once by the router, adjusted and approved by the person, saved as a project workflow, and then scheduled on the same screen. This is how a request that was first free text becomes a routine's target.
33. **D33. Date variables in workflows.** A workflow may use `{today}` and `{week}`, filled at fire time. A routine's approved hash covers the workflow's template and its fixed arguments, not the values the dates take.
34. **D34. (completed by D38 for manual use) Scores inform and rank; they do not gate a model the person chose (amends D8 and principle 9; S4).** In `auto`, unattended release (a review released in `autonomous` mode, a routine's tasks) happens only for a pair proven by lab evidence or by the person's own local tests; a pair that is `reliable` only through community evidence may be chosen and used, with its output reviewed. With a model the person fixed, an `autonomous` routine runs without review by **explicit consent**, even with no evidence: the screen warns, the consent enters the routine's approved hash (so changing the model asks again), and every run is recorded as "autonomy by consent", never as "proven". The product may recommend a model from the scores. Principle 9 of `AGENTS.md` is reworded in P3 to say that proof decides autonomy by default and that an explicit consent, per routine (D34) or per agent (D38), can grant it. External effects keep the hard limit: the approval of their exact content, or a standing policy the person accepted in the terminal. Manual use is settled by D38.
35. **D35. What a routine's approved hash covers (S3).** Besides the schedule, the workflow template and its fixed arguments: the `X.Y` of each skill the workflow names (a Z change does not stop the routine), the digest of the eval image, the sha256 of a project script and its declared destinations, the model and the consent of D34, and, for `auto`, the **approved provider set**. `auto` picks the cheapest `reliable` pair inside that set; a better candidate from another provider stops the routine and asks.
36. **D36. Community evidence and unattended release (S4; clarifies D19).** Community evidence counts fully for `auto`'s ranking and for manual use, as D19 says. It never by itself grants unattended release (D34).
37. **D37. Free-text requests in manual use are unchanged.** The router plans them and the person approves the plan by its hash, as before. D31 removes free-text routines only.
38. **D38. Consent also in manual use (changes D8, completes D34).** When the person fixes an agent's model and the agent is in `autonomous` mode, that setting is the consent, given once, with the same warning as D34 (this model has no `reliable` evidence for the skills the agent runs, and its reviews will be released by the mode). From then on the reviews of that agent's tasks on an unproven pair are released by the mode, and each run is recorded as "autonomy by consent", never as "proven". Changing the agent's model, or raising its mode to `autonomous` while a model is fixed, asks again. The consent is given on the page or in the terminal, not from a messaging channel (section 10). In `auto`, manual use keeps D34's rule: unattended release only for pairs proven by lab evidence or by the person's own local tests. D8's hold (an unproven pair runs `supervised`) therefore remains for a model named on a single request that no agent has fixed, and for an agent below `autonomous`. External effects keep the hard limit as in D34.
39. **D39. The first pull of the published eval image is an explicit setup step (changes D21).** The doctor or a setup command pulls the image by digest, with the provenance check of P2d; it is never automatic on first use and never happens in the middle of a dispatch. A run that finds no image refuses and prints the command to run. The refusal already exists for a missing local image (`runtime/lab.py`, lines 406 to 409, which says the runtime never builds it); P2d changes its message to name the setup command.

## 4. Three paths and the one chosen

The chosen path holds. Version 2 refined it and version 3 keeps it: the sources folder of D9 settles where ingested data lives (outside the workbench's git, so path B's problem with snapshots under `docs/` does not arise), and the step engine (P5) still waits for its second consumer, ingestion.

### Path A: engine first

Generalise the task with no skill and the step engine first, then build everything else on them.

Rejected as written. It builds a generic engine with one consumer, which today is the short-video pipeline. A reference is added when a second consumer needs it (the rule `AGENTS.md` states for shared references applies here by analogy). Data arrives last.

### Path B: data first

Ingestion providers and converters; agent runs stay closed.

It is the right priority. Two steps are mispriced.

- **Skills declaring snapshot paths as `inputs`.** Each such change bumps and retests the skill (`AGENTS.md`, "Changing an existing skill": an addition to `inputs` is a Y change). The file drop already hands a file to one task (`runtime/drop.py`, header), so the skills need not change.
- **Versioned snapshots under `docs/`.** A run without the web copies every file git tracks, and every file under `docs/` that the path rule classes as a document (`runtime/workcopy.py`, lines 257 to 266 and limit L2, lines 14 to 17). A snapshot written there would enter every run and widen the prompt-injection surface.

### Path C: tools in the run

Adopt MCP servers and many models quickly, with the tools available inside the agent's run.

Rejected for this phase (D15).

- Wiring MCP into a run touches fingerprinted files: everything in `evals/container/` and each eval adapter's `run-prompt.sh` and `eval.json` (`evals/eval_status.py`, `FINGERPRINT_FILES`, line 557, and the text at lines 200 to 204). That is an execution-side measurement change, which opens an epoch for every skill it reaches (`AGENTS.md`, "The measurement has a version, a fingerprint and a floor").
- A read tool can carry data out through its query arguments. That is a side effect the approval gate does not see by structure (principle 11).

### Chosen: B on A's spine

Data comes in first. It is built as the second kind of step task, and that second consumer is what justifies making the step engine generic (P5). Routines reuse the handler tick. MCP servers may be adopted only on the host side, as provider implementations with read verbs, never inside a run.

### What the debate corrected

Each item was checked against the code.

- **Notion read already exists.** The first draft listed it as missing. `providers/documents/notion.py` has the `read` verb (line 589) and `runtime/documents.py` `pull` (line 503) uses the provider to bring the person's edits back. What is new is reading a page that is not a mirrored document, and reading by URL.
- **The handler tick is already a routine mechanism.** `runtime/ops.py` `_ticks` (line 2444) calls each enabled handler's `tick` every round. A routine does not need a second scheduler.
- **"Code task" means two things.**
  - On `main`, `ops.code_task(meta)` (`runtime/ops.py`, line 854) is true when a skill belongs to a code area (`workcopy.CODE_AREAS`). `runtime/parallel.py` `admit` (line 87) lets one such task of a request run at a time (the held reason `CODE_IN_REQUEST`, line 39).
  - On `feature/short-video`, `store.is_code_task` (`providers/store/sqlite.py`, line 1487) is true for a task with a parent and no skill. Both meanings are on that branch (`runtime/ops.py`, line 865, and the store function). A task with no skill has an empty footprint, so `admit` never serialises it against a skill task: `runtime/ops_runs.py` `skill_facts` returns an empty footprint and no code flag for a task with no skill (lines 74 to 87). P5 ports the store functions and renames them, so the clash never reaches `main`.
- **The step engine is not generic yet.** `runtime/pipeline.py` on `feature/short-video` imports `captions`, `media` and `theme` (lines 67 to 69), and its stops are a constant, `STOPS = ("review", "approval")` (line 75).
- **Nobody starts a task with no skill.** It is never `ready`: the store's `NEXT_READY_TASK` has `skill IS NOT NULL` (`providers/store/sqlite.py`, line 1086, on `feature/short-video`; on `main` the same line has no such test and no task with no skill exists). A task with no enabled agent is held (`runtime/dispatcher.py`, `NO_AGENT`, line 70). The only code that moves one is `code_task_move`, called from `runtime/ops_pipeline.py`, line 138 (on `feature/short-video`).
- **Scanning a raw PDF or XLSX does not find credentials.** The run copy scans with `data.decode("utf-8", errors="replace")` (`runtime/workcopy.py`, line 232). Compressed text inside a PDF or an XLSX is not visible to that scan. The drop does not scan a file that is not UTF-8 at all (`runtime/drop.py`, lines 102 to 108). The size limits do not match either: `SCAN_MAX` is 5 MB (`runtime/workcopy.py`, line 71) and the drop takes 25 MB, so a file between 5 and 25 MB is accepted by the drop and refused at the run's entry as "too large to scan" (line 230). Converting to text before a run closes both gaps.

## 5. Consolidating the branches

### What changed since version 1's check

The first step of version 1, merging `feature/parallel-agents` into `main`, was done by the maintainer on 2026-10-14 as the release #393 (`d3e60770`). On that commit `runtime/autonomy.py` has `MAX_PARALLEL_CEILING = 4` at line 77 and `providers/messenger/` has the five providers. No merge is left to plan; the packages below start from `origin/main`.

### What stays on `feature/short-video`

A trial merge of `feature/short-video` (`6794905e`) with `feature/parallel-agents` (`39600a0b`) reported conflicts in seven files: `.github/workflows/checks.yml`, `docs/architecture/platform/README.md`, `docs/architecture/platform/shells.md`, `providers/CONTRACT.md`, `runtime/service.py`, `scripts/tests/test_provider_resolve.py` and `scripts/tests/test_runtime_python39.py`. The same trial against `origin/main` (`d3e60770`) reported conflicts in 44 files (both read from `git merge-tree --write-tree --name-only`, run again on 2026-10-14 for this version). That is the reason to extract, not to merge.

Keep only the generic pieces, extracted:

| Piece | Where it is on `feature/short-video` | Goes into |
|---|---|---|
| The task with no skill, renamed "step task" and designed once | `providers/store/sqlite.py`, lines 1486 to 1560 | P5 |
| The generic streaming intake (about 130 lines by the line ranges of `_Lock`, `sniff`, `_pull`, `_read_head`, `_bound_length` and `_stream_to`; `receive`, line 714, is bound to a recording and a slot and stays). There is no content-addressed store on the branch: a file is kept under its recording's folder | `runtime/media.py` (`sniff`, line 472; `_pull`, line 669; `_stream_to`, line 827) | P0, into the sources module or `runtime/intake.py`; generalised in P4 |
| The minimal provider environment, but derived from `resolve.variables(cls)` instead of the hard-coded names `ENV_KEEP` lists | `runtime/ops_pipeline.py` `ENV_KEEP` (line 70) | P0 |
| The sandboxed container provider pattern | `providers/renderer/_docker.py` (`container_argv`, line 311) and `providers/transcriber/whispercpp.py` (`container_argv`, line 568), the same limits written twice | P0 (`providers/_container.py`, the whole container lifecycle) |
| The step engine | `runtime/pipeline.py` | P5 |
| Runtime-only provider classes | the transcriber and the renderer (`docs/architecture/platform/short-video.md`, line 293; decision D11 of that page, line 40) | P4 (`converter:document` is one) |
| Secure byte serving | `runtime/video.py` (`open_render`, line 205; `open_cover`, line 223) | P4, if the page shows a converted file |
| Exact-artifact approval | `runtime/ops_video.py` `video_approve` (line 184) | P8, as the pattern for approving the exact content of a written file |

The video-specific pieces stay on their branch and rebase onto the extracted kernel in the side package.

### A known bug on `feature/short-video`

The reviewer reported that approving the video does not close the second stop, so the task stays `waiting`. The code was read, not run, and does not contradict the report.

- `video_approve` (`runtime/ops_video.py`, line 184) writes the approval into the recording's record (line 224) and logs the event.
- `store.code_task_move` is called from one place only, `runtime/ops_pipeline.py`, line 138 (found with `git grep -n code_task_move`).
- The second stop opens a pending decision on the task (`runtime/pipeline.py`, `approval_decision`, line 683).

Fix it in the side package (the short-video rebase), with a test that approves and asserts the task is `done`.

## 6. The work packages

Sizes are S, M or L and are judgments, not measurements (section 10). "Measurement impact" says whether the package touches a file in `FINGERPRINT_FILES` (`evals/eval_status.py`, line 557: the grading template, `evals/measure.py`, `evals/measurement.json`, `evals/executor.py`, `scripts/stage_skills.py`) or in `evals/container/`, or an eval adapter's `run-prompt.sh` and `eval.json` (lines 200 to 204), and, if it does, which kind of measurement change it is. "Resolves" names the findings of version 1 (F1 to F16, `docs/architecture/delegation-platform-architecture-2026-10-14.md`, section 6; the E, G or R letter in brackets), the findings of the review rounds (S, I, Q and M, section "Review rounds of 2026-10-14") and the decisions the package carries out. An element marked `new` does not exist on `main`; where a package says it creates a file, the file name is the plan's proposal unless the rules below fix it.

### Rules for every package

These came from the second review round (M1, M2, M6, Q3, Q5). Each package's "Done when" includes them, and the package's report says how each was met.

1. **Migrations are numbered here.** `SCHEMA_VERSION` is 9 (`providers/store/sqlite.py`, line 53; `MIGRATIONS`, line 90). P3 takes 10, P4 takes 11, P5 takes 12 and P6 takes 13, in the order the packages merge. A package that finds it needs no migration says so, and the next takes the next number. A package that adds a table or a column ends with `python3 scripts/architecture_tables.py --check` clean (`python3 scripts/architecture_tables.py --write` rewrites the generated blocks of `docs/architecture/platform/`).
2. **New code never goes in `runtime/ops.py`.** It has 2,690 lines and a budget of 2,776 (`runtime/tests/test_runtime_rules.py`, line 242), so 86 lines are left; a sibling of the layer is capped at 1,200 lines (`SIBLING_BUDGET`, line 243). A new operation lives in a sibling module and is registered in `runtime/operations.py`; the number is never raised to make room.
3. **Three homes are fixed.** `runtime/sources.py` (`new`: the registry, versions, catalog, guardrails and `import_version`; it imports nothing from `ops`); `providers/_container.py` (`new`: P0); and **one price table** (P3 decides its home; `adapters/api/prices.json` and the project's `model_prices` are retired or derived from it). Every other module name in this document (`runtime/steps.py`, `runtime/handlers/routines.py`, `providers/converter/`, `providers/documents/gdrive.py`) is a proposal that the package's executor may change; the executor records the name it used in the package's report.
4. **A package's "Done when" also updates what it touches in the shared documents:** the limits table of `contracts/runtime.md` (a new hard limit gets the next number from L21 and a test named `test_limit_<nn>_...` under `runtime/tests/`, which `scripts/architecture_tables.py` finds); for a new provider class, `providers/resolve.py` (`ROLES`, line 95, and, when a skill may require the class, `LISTED`, line 91, and `contracts/environment.md`) and the class row of `providers/CONTRACT.md`; the generated tables; and the pages of `docs/architecture/platform/` that describe what it changes. Version 2 said that the resolver "finds a class by its folder"; that is false for a new role. `folder()` (line 155) returns the role for any class that is not an `integration`, but `split_class` (line 126) refuses a role that is not in `ROLES` (line 134), and `converter` is not (a runtime-only role such as `messenger` is in `ROLES` and in neither `LISTED` nor `contracts/environment.md`; `providers/CONTRACT.md` says why).
5. **Words.** The **planner** is the router run (`runtime/router.py` with the skill `core-orchestrator`), the only thing in this document that chooses sources or builds a plan from free text. A **step kind** is a kind of step task in P5's registry (`ingest`, a file output, a project script). An **effect kind** is a key of `KINDS` in `runtime/effects.py` (line 149), a word of the side-effect vocabulary. A **pending-decision kind** is the `kind` of a row in `pending_decisions` (`plan`, `effect`, ...; `runtime/ops_waits.py`, line 291). The three are different and a sentence says which it means. A **workflow** is a flow file (`flows/<name>.json`, or a project's own; the interface and the backlog still say "flow" until backlog T30 renames it).
6. **Every package ends with** `python3 scripts/validate.py` at zero errors and the tests of the folders it touched, which the commit hook runs.

### P-1. Test speed (S)

**Goal.** The tests that run before every commit and in CI run across workers, so that the packages below, which add many tests, do not each wait for a serial run.

**Reuses.** Commit `e1202879` on `origin/feature/short-video` (message: "ci: pytest-xdist in the python39 and tests jobs, JS-only interface tests off 3.9, 25-minute limits (#388)"). Of the eleven files it changes, these exist on `main`: `.github/workflows/checks.yml`, `runtime/messaging.py`, `runtime/tests/test_messaging.py`, `runtime/tests/test_messaging_listen.py`, `runtime/tests/test_messaging_shell.py`, `runtime/tests/test_interface_r4_p2.py` and `providers/scheduler/tests/test_scheduler_one_shot.py`. `runtime/tests/conftest.py` is created by the commit (`main` has none); it clears the two `STOPPING` flags after each test (`runtime/ops_runs.py`, line 59, and the execution kit, `evals/execution.py`, line 472), because a flag left set by one test made another `run_group` answer as a timeout. The three renderer tests of the commit (`providers/renderer/tests/`) have no counterpart on `main`. `.githooks/pre-commit`, line 76, runs `uv run --quiet --with pytest==9.1.1 pytest -q "${dirs[@]}"` in one process, after `env -u GIT_DIR -u GIT_INDEX_FILE -u GIT_WORK_TREE -u GIT_PREFIX`.

**Builds.**

- Cherry-pick those parts of the commit that apply to `main`, leaving out the renderer tests, and keep the commit's authorship in the message.
- Add `--with pytest-xdist==3.8.0` (the version the commit pins) and `-n auto` to the hook's `pytest` call. The `env -u GIT_*` prefix stays before it: the tests that create their own repositories would otherwise read this one.
- Record, in the pull request, the wall time of the same test folders before and after, run on one machine. The figure of about ten minutes serially for `runtime/` and `evals/` is the maintainer's; it was not re-timed for this plan.

**Done when.**

- The hook's `pytest` line contains `-n auto` and still starts with the `env -u GIT_DIR ...` prefix (a test over the hook's text).
- A test sets both `STOPPING` flags and the next test finds them clear.
- The test folders the hook and the `tests` job run pass three times in a row under `-n auto`, with no test sharing a port or the per-user state folder with another; every collision found is fixed in the test, as the commit did.
- The `tests` and `python39` jobs of `.github/workflows/checks.yml` run under `-n auto` with the 25-minute limit of the commit.

**Size.** S.

**Measurement impact.** None. The hook, the workflow, the tests and `runtime/messaging.py` are not in the fingerprint.

**Depends on.** Nothing. It is first in the order, so that the later packages run their tests in parallel; the side package will find the commit already applied when it rebases.

**Resolves.** Q6.

### SEC. Keys never next to an egress path (S to M)

**Goal.** A run whose key a key proxy holds reaches only its own key proxy, and the key proxy forwards a credential header or an endpoint of no model. This is a live defect of today's code (S1), so it is built before P4 and does not wait for the rest of P2.

**Reuses.**

- `evals/executor.py`: `held_route` (line 141) and `places` (line 157); the `network == "proxy"` branch of `command`, lines 347 to 353, which gives a held run the four proxy variables `HTTPS_PROXY`, `HTTP_PROXY`, `https_proxy` and `http_proxy` on the route's internal network; the key proxy's own start with `HTTPS_PROXY` toward the egress proxy (line 246), which is right and stays.
- `evals/container/proxy/allow.txt` (two anchored lines, `^api\.anthropic\.com$` and `^openrouter\.ai$`: any account on either host is reachable through the egress proxy) and `evals/container/proxy/tinyproxy.conf` (`LogLevel Connect`, so the connections are logged).
- `evals/container/keyproxy/keyproxy.py`: `NOT_FORWARDED` (line 47) lists `authorization`, `host`, `content-length`, `expect` and the hop-by-hop headers and not `x-api-key`; `allowed` (line 88) accepts every path under the route's prefix, `/api/v1/` in `keyproxy.json` and `/v1/` in `keyproxy-strong.json`; the header loop (line 200).
- `evals/tests/test_executor_routes.py`, `test_keyproxy.py`, `test_keyproxy_pin.py` and the two docker tests the `WB_EVAL_DOCKER_TESTS=1` job runs (`test_executor_docker.py`, `test_keyproxy_docker.py`).

**Builds.**

- **First, a read.** Before any change, read the egress proxy's `Connect` log of a recent battery for a host other than the two or a request that did not come from a key proxy. The log may not have been kept; say so in the report if it was not.
- A held run's network holds the run and its key proxy only: no proxy variables for the run and no egress proxy on its network. The key proxy reaches the egress proxy through a second internal network that the run is not on.
- The key proxy strips every header that carries a credential, `x-api-key` first, in addition to `authorization`, and forwards only the paths of the model endpoints the two adapters call. The list of those paths is read from a recorded run's request log, not guessed (section 10). The `provider_only` pin of the floor route (lines 79 and 187) stays.

**Done when.**

- An argv test: a held run's container arguments carry none of the four proxy variables and name no network the egress proxy is on.
- A test in the docker job: from a held run's container a connection to the egress proxy and to a provider host fails and one to its key proxy succeeds.
- A key proxy test: a request carrying `x-api-key` reaches the stand-in upstream without it, and a path outside the endpoint list is answered 403 with the stated reason.
- The report states what the connection log showed, or that it was not available.

**Size.** S to M.

**Measurement impact.** An execution-side measurement change (`python3 evals/eval_status.py measurement --kind execution`): it edits `evals/executor.py` and files under `evals/container/`, which the definition hash covers. One epoch entry covers SEC and P2b together; no lab run is made between them, so the two cost one battery, which runs after P2b. The class is the maintainer's call: the change alters how the two measured models' runs reach the network and which headers leave, so this plan assumes it reaches them.

**Depends on.** Nothing in code. The order of the plan puts it after P2a; they touch different files (`evals/eval_status.py` and a new module against `evals/executor.py` and `evals/container/`) and can run at the same time.

**Resolves.** S1; item 9 of "To verify" (what the provider does when it receives both an `x-api-key` and a bearer token decides how strict the header rule must be).

### P0. Port the generic short-video pieces (S to M)

**Goal.** Put on `main`, without any video feature, the two pieces the sources pillar needs, so that no later package depends on a branch that is not merged. Version 2 also ported the store's task with no skill and a content-addressed store; the first moves to P5 and the second does not exist (Q1).

**Reuses.**

- On `origin/feature/short-video` at `6794905e`, `runtime/media.py`: `_Lock` (line 221), `sniff` (line 472), `_pull` (line 669), `_read_head` (line 688), `_bound_length` (line 702) and `_stream_to` (line 827), about 130 lines by their line ranges, with their tests. The rest of the file is bound to a recording and a slot: `receive` (line 714) takes `recording` and `slot`, and a file is kept as `raw.<ext>` or `<slot>-<sha256>.<ext>` in the recording's folder (`_finish`, line 873). There is no content-addressed store on the branch.
- `providers/renderer/_docker.py` (`container_argv`, line 311) and `providers/transcriber/whispercpp.py` (`container_argv`, line 568), which write the same limits twice: no network, read-only root, all capabilities dropped, no new privileges, a limit on processes, memory, swap and CPUs, memory-backed `/tmp` and `/scratch`, an image that never pulls at run time (`providers/transcriber/whispercpp.py`, lines 568 to 580). Their tests: `providers/renderer/tests/test_renderer_docker.py` and `providers/transcriber/tests/test_whispercpp.py`.
- `runtime/ops_pipeline.py`, `ENV_KEEP` (line 70): the names a provider's process keeps. It hard-codes four provider variables (`TRANSCRIBER_SPEECH_PROVIDER`, `TRANSCRIBER_PROVIDER`, `RENDERER_VIDEO_PROVIDER`, `RENDERER_PROVIDER`); P0 does not copy the constant.
- `providers/resolve.py`: `variables(cls)` (line 163) returns the variables that select a class's implementation.

**Builds.** All of it is copied from the branch into a branch cut from `origin/main`, not merged (section 5).

- The generic streaming intake, into `runtime/sources.py` (`new`) or `runtime/intake.py` (`new`), whichever the executor prefers: bounded reads under a deadline, a hash computed as the bytes are written, never the whole body in memory, a type sniff that the sources module extends in P4. No store code, no recording, no slot, no `captions`, `theme` or `video`.
- `providers/_container.py` (`new`), which owns the **whole** lifecycle of a sandboxed container job: the arguments (the limits written once), the docker binary and its environment, the run, the stop, the removal and the reaping of a container that outlived its job. The environment a provider's process gets is a fixed minimum (what finds a program, a home and a docker daemon) plus the variables `resolve.variables(cls)` returns for the class, never a list of provider names. `evals/executor.py` does not import it, so the fingerprint is untouched.
- The two providers stay on their branch; the side package makes them call the helper.

**Done when.**

- The ported intake passes its tests; the module imports none of `captions`, `theme`, `video` or a recording type, and no function of it takes a recording or a slot.
- A test compares the helper's arguments, limit by limit, with those the two providers write today (the golden is each provider's `container_argv` at `6794905e`), and each limit keeps its name.
- Tests with a fake container tool show that a stop removes the container by name, that a job past its time is reaped, and that a start that fails leaves none.
- A test shows the provider environment holds the variables `resolve.variables` returns for a listed class and no other provider variable.
- The diff holds no video file, and `scripts/tests/test_layer_map.py` passes.

**Size.** S to M. About 130 lines of intake, a helper of about the size of the two `container_argv` functions plus the lifecycle, and the tests.

**Measurement impact.** None. `runtime/` and `providers/` are not in the fingerprint, and `evals/executor.py` does not import the helper.

**Depends on.** A branch cut from `origin/main`. Nothing else.

**Resolves.** F15 (E7), Q1, Q3, Q4, and S6 for the container lifecycle. Absorbs version 1's package 2 (the shared container helper).

### P1. Hygiene (S)

**Goal.** Make `web_measured` true.

**Reuses.** `runtime/proof.py` `row` (line 97); `runtime/lab.py` `standing` (line 280); the gate file's `web_cases` (`evals/eval-gate.json`, line 24); the web cases a test event records (`evals/eval_status.py`, the event fields, line 39).

**Builds.** Fix `web_measured`. Today `proof.row` sets it to `bool(standing["web_cases"])` (`runtime/proof.py`, line 97), and `lab.standing` copies the gate file's list for the skill (`runtime/lab.py`, line 280). So a case listed in `web_cases` turns the web on before that case has any evidence, and the flag is the same for every model. Require lab lines of a listed case in the current set, on that model. Until P3 removes the tiers, "that model" is the model of each of the two tiers. The step-task rename and its footprint, which version 2 put here, are P5's.

**Done when.** A case listed in `web_cases` with no evidence does not turn the web on, and a case with evidence on model A and none on model B turns it on for A only.

**Size.** S.

**Measurement impact.** None. `runtime/proof.py` and `runtime/lab.py` are not in the fingerprint.

**Depends on.** Nothing.

**Resolves.** Part of F13 (E6): `web_measured` per model, from evidence.

### P2a. T24 and a reader for both gate-file shapes (S)

**Goal.** Reshaping the gate file invalidates no committed evidence, and the code that reads an evidence line is a module of its own, so the next parts change the gate file and the test header without touching the reader again.

**Reuses.** `docs/backlog.md`, T24 (line 89); `evals/eval_status.py`: `known_models` (line 532), `model_id` (line 540), `_model` (line 760), `event_line_problems` (line 773, and the `strong` requirement near line 795), the stored-gate fallback (lines 1180 to 1186), `GATE_FIELDS` (line 250). The evidence on this branch is 86 test lines, all with the old header `{"strong": ..., "floor": ...}` (counted on 2026-10-14 over `skills/*/evals/evidence/lab-*.jsonl`).

**Builds.**

- The validator reads an old evidence line against the gate file as it was at that event, or accepts the old shape (T24), so that a change of `runs` or of the models in the gate file makes no committed file invalid. Committed evidence files are never edited.
- The reader accepts both test-header shapes: the old `{"strong", "floor"}` and a list of models.
- The reading of an evidence line (header, run lines, the checks of `event_line_problems`) moves from `evals/eval_status.py` (2,319 lines) into a module of its own under `evals/`; `eval_status.py` imports it and its behaviour does not change.

**Done when.**

- `python3 evals/eval_status.py status` prints the same text before and after, compared as text, for the committed evidence.
- A fixture changes the gate file's `runs` and removes a model, and the validator still accepts the old evidence file.
- A fixture with the new header shape is read.
- `measurement_sha256` is unchanged (no file of `FINGERPRINT_FILES` is edited), and `python3 scripts/validate.py` passes.

**Size.** S.

**Measurement impact.** None to the fingerprint: `evals/eval_status.py` and the new module are not in `FINGERPRINT_FILES`, so no `measurement` command is run.

**Depends on.** Nothing in code. It is early in the order because P2b and P2c reshape the gate file and the test header.

**Resolves.** F16 (R3), M5 (the first of the four parts of P2).

### P2b. A model-keyed key proxy, routes and metering (L)

**Goal.** A model is a line in a list: adding one changes no fingerprinted file. A run's tokens and its budget are counted where the run cannot change them.

**Reuses.** `evals/eval-gate.json` (the `models` object of ids and aliases, line 33, which `known_models` reads, `evals/eval_status.py`, line 532); `evals/executor.py` (`ROUTE_FILES`, line 73; `IMAGE_PLATFORM`, line 81; `routes`, line 136; the key proxy's start and label, lines 236 to 250; the run container's name, line 321); `evals/container/keyproxy/keyproxy.py` (the single `provider_only`, lines 79 and 187) and `keyproxy.json` (line 6), `keyproxy-strong.json`; `evals/eval_run.py` (the event line's `upstream`, lines 2492 to 2496; the run line, lines 2314 and 2474); `evals/eval_status.py` (`RUN_OPTIONAL`, line 734, where `platform` is already an optional run field); `runtime/costs.py` (`usage_of`, line 48; `recompute`, line 133).

**Builds.**

1. **The gate file's model list.** The `models` object (line 33) gains, for each model, its adapter, its key variables, its price source and its provider pin. The old keys (`strong_model`, `floor_model`, `strong_harness`, `floor_harness`, `strong_pass_env`, `floor_pass_env`, `strong_tolerance`, `web_jobs`; lines 2 to 10 and 20 to 23, validated by `GATE_FIELDS`, line 250) stay until P3, and P2a's reader accepts both shapes. "The lab models" becomes a default list holding the two models of D2. `grader`, `threshold`, `runs`, `baseline_runs` and the tolerance (0.05) stay.
2. **One key proxy per run,** started with exactly one model id and that model's pin, read from the gate file's list (which is outside the fingerprint), and refusing any request that names another model. `keyproxy.py` reads the model from the request body and the pin from the route chosen by model; `executor.py` keys its routes by model, not by tier.
3. **Metering (S2).** The proxy counts the tokens of each response (input, output, cache read, cache write) for its run, writes the count where only the runner reads it, and stops answering the run, with a stated error, when a per-run budget is reached. The runtime's cost of a run is taken from this count and the configuration's prices, not from what the run's output reports.
4. **The event line's `upstream`** is written for every model that ran through a proxy, not for the floor tier only. The same change accepts `linux/amd64` beside `linux/arm64` and records the platform on each run line (D20).
5. **Container hygiene set where the containers start.** The proxy containers start with a log size limit, and the run containers carry a label, so that P-OPS can remove orphans by label. Both are arguments of `docker run` in `evals/executor.py`, which is fingerprinted, so they are made here, before the battery, and not in P-OPS (I6).

After it, a new model never changes a fingerprinted file (D18).

**Done when.**

- A test adds a model to the gate file's list and to a route, and the measurement fingerprint (`measurement_sha256`) is unchanged.
- A test: a request that names another model is refused by the proxy; a run past its budget gets the stated error; the count equals the sum of the usage in a recorded response fixture, streaming included.
- The review compares the upstream request of the two measured models before and after SEC and P2b with a golden recording, and finds it identical except the credential headers SEC removes.
- The event line carries `upstream` for each model that ran through a proxy, and a run line carries the platform; the same test run on `amd64` and `arm64` writes lines with the platform and both count.
- The docker tests of the `WB_EVAL_DOCKER_TESTS=1` job pass.

**Size.** L.

**Measurement impact.** One execution-side measurement change (`python3 evals/eval_status.py measurement --kind execution`) touching `evals/executor.py`, `evals/container/keyproxy/keyproxy.py` and the route files, with SEC. Proposed: the epoch entry covers both packages and names the two measured models, since SEC changes how their runs reach the network; the review's golden recording shows whether the request that leaves the proxy changed, and if it did not and the maintainer judges the network change harmless to results, the entry can name only models with no evidence (`--models` accepts only models the gate file lists, `evals/eval_status.py`, line 685, so the gate file's list lands first). The maintainer decides the class; if he judges that it reaches the measured models, the cost is an epoch for every skill with evidence on them, which principle 12 makes the last resort, and which the plan pays once: **the battery runs once, after P2b**, and nothing is measured between SEC and it.

**Depends on.** SEC (the same files and the same epoch entry) and P2a (the reader of both shapes).

**Resolves.** F1 (E1), the key-proxy half of F2 (G1), S2, the container half of I6. Carries out D18, D20.

### P2c. Gate, completion, Y count, stored gate and usage per model (M)

**Goal.** The gate is read per model: a full test of one model moves nothing of another, the usage of a run is on its line, and a person's tests of any model stay on their machine.

**Reuses.** `evals/eval_status.py` (the newest full test, lines 1133 to 1136; `baseline_lines`, line 1107; `y_changes_since`, line 1888; the stored-gate fallback, lines 1180 to 1186; `as_reference`, line 1095; `skill_band`, line 1965); `evals/eval_run.py` (`scratch_reason`, line 1826, and its checks at lines 1837 to 1863; `complete`, line 2507); `measure.gate_passes`, unchanged; `runtime/costs.py` (the four kinds of usage, lines 33 and 34); `docs/backlog.md` (line 84: `modelUsage` of a run's raw output).

**Builds.**

1. **The test header** names a list of models instead of `{"strong", "floor"}` (P2a reads both shapes).
2. **Gate, completion, Y count and stored gate per model.** The gate takes the newest full test whose header lists that model, and `complete`, `y_changes_since` and the stored gate follow the same selection, so that a full test on model Z resets no other model's Y count and moves no other model's `X.Y`. The comparison stays `measure.gate_passes(with_mean, baseline_mean, threshold, tolerance)`.
3. **A usage field on run lines,** optional, with the four kinds `runtime/costs.py` reads, taken from P2b's proxy count where the run went through a proxy, and otherwise from the full model usage that counts the subagents, `modelUsage` of the run's raw output, not from the `usage` total of `timing.json`. The recorded `cost_usd` of the reference model is not usable (`docs/architecture/platform-plan-2026-10-05.md`, line 20). Neither `eval_run.py` nor `eval_status.py` is in `FINGERPRINT_FILES`.
4. **Local evidence outside the checkout (D18).** A person's runs of any model write to a folder outside the workbench checkout and feed only that person's `auto`. `scratch_reason` stops refusing a named model; what it refuses is writing into the repository's evidence folder.
5. **No model is special.** The text and code that say "the model that decides the repository's gate" go; no model is special in the gate or in `done`.

**Done when.**

- `python3 evals/eval_status.py status` prints the same text before and after for the existing evidence (a golden).
- A fixture with full tests on two models shows each model's gate, `complete`, Y count and `X.Y` independent of the other's.
- The evidence validator accepts an old evidence file against a changed gate file, and a run line with and without the usage field.
- A run of any model by a person leaves `git status` of the checkout clean.
- `python3 scripts/validate.py` passes.

**Size.** M.

**Measurement impact.** None to the fingerprint (infrastructure: `evals/eval_run.py` and `evals/eval_status.py` are not in it).

**Depends on.** P2a (the reader) and P2b (the list of models and the proxy's count).

**Resolves.** F6 (E4), the usage part of F13 (E6) and, with P3, F5 (E3). Carries out D18.

### P2d. The published image (M)

**Goal.** The eval image the evidence was measured in is the image anyone pulls. A rebuilt image would have another digest and would make all the evidence unproven on every other machine.

**Reuses.** `evals/executor.py` (`definition_hash`, line 96, the sha256 over the files of `evals/container/`; the local build, lines 192 and 193; the image id read at line 213); `runtime/lab.py` (the image id read at line 228, the check at line 406); `runtime/proof.py` `checks` (lines 104 to 115, which compares the local image with the evidence's `evidence_images`); the event line's `image_digest` and `image_platform` fields (`evals/eval_status.py`, lines 37 to 41); `.github/workflows/checks.yml`; `scripts/doctor.py`.

**Builds.**

- **A lock file** (`new`, outside `evals/container/` and outside the fingerprint) that maps the definition hash to the config digest and the manifest digest of the image, per platform (`linux/arm64`, `linux/amd64`).
- **The image the evidence was measured in is the one published.** The image is built only by a protected workflow on `main`, from the pinned definition, with short-lived registry credentials and build provenance. The provenance is verified before a lock-file change and before the first pull. The key proxy and egress proxy images are built locally, or from pinned package versions, so that only the run image travels through the registry.
- **Identity is the repo digest, never `.Id` (I1).** The code reads `{{.Id}}` today (`evals/executor.py`, line 213; `runtime/lab.py`, line 228); whether `.Id` differs between image stores is item 10 of "To verify".
- **The first pull is an explicit setup step (I2),** reported by `scripts/doctor.py` and run by a command it names, not a silent pull in the middle of a task. This is D39, which changed D21 (it said the runtime pulls the image automatically on first use): a run on a machine without the image refuses and prints the command to run (`runtime/lab.py`, lines 406 to 409, refuses today and names the maintainer's `docker load` or `evals/executor.py ensure`; the message changes). `proof.checks` compares the local digest with the published one and answers the same on every machine that holds the published image; a locally built image yields local-only evidence (D21).

**Timing.** The battery's evidence records the image it ran in. So that it names a published digest, the workflow, the lock file and the pull path are ready before the battery and the battery pulls the published image; the rest of the package (the doctor step, the messages, `proof.checks`) runs during the battery, in parallel with P2c. If the battery runs on a locally built image, its evidence is local-only until the same image is published.

**Done when.**

- A test with a fake container tool shows a machine without the image refused with the setup command named, the setup command pulling the published digest, and `proof.checks` answering `image: None` when the local digest equals the published one.
- An offline test of the lock-file check: a digest that does not match the definition hash is rejected, and a missing provenance is rejected.
- A test with fake `docker inspect` outputs in which `.Id` differs and the repo digest is equal shows the image accepted.
- No file of `FINGERPRINT_FILES` or of `evals/container/` is edited by this package. If pinning the proxies' packages needs an edit of their Dockerfiles, that edit is made with SEC and P2b, before the battery.

**Size.** M.

**Measurement impact.** None, by design: the lock file, the workflow, `runtime/lab.py`, `runtime/proof.py` and the doctor are not fingerprinted. Publishing the unchanged definition changes nothing. Any edit of `evals/container/` or `evals/executor.py` here would be a measurement change; see the rule above.

**Depends on.** P2b (the definition must be final before it is published).

**Resolves.** F3 (G2), I1, I2. Carries out D20, D21 as changed by D39, and D39.

### P3. Model choice and `auto` (L)

**Goal.** The tiers leave. A person names a model, or asks for `auto`; every pair has a published band; scores inform the choice and are the basis of `auto`, and do not gate a model the person chose (D34).

**Reuses.** The per-model gate, the list of models and the usage field of P2; the tier code, found by reading each symbol (not by a blind search, because "floor" also names interface floors and the measurement floor, `measurement_floor` in the gate file):

- `runtime/proof.py`: `TIERS` (line 41), `route` (line 118), `checks` (line 104), `row` (line 97); its call site at `runtime/ops.py`, line 355.
- `runtime/lab.py`: `TIERS` (line 61, a table of the gate-file keys of each tier), `reference` (line 138), `credential_missing` (line 154), `run_skill(..., tier=)` (line 500), and the `tiers` fields of the facade's results (lines 263 and 278).
- `runtime/ops_core.py`: the runtime's own key for the floor model, `FLOOR_KEY = "WB_RUNTIME_FLOOR_KEY"` (line 71), `_floor_key` (line 197), and the tier's billing, `_tier_billing` (line 232).
- `runtime/autonomy.py`: the billing history of runs that predate the column, `history_billing` (line 220) and `with_billing` (line 229), whose rule is "a run on the floor model is metered, any other's subscription"; and `review_action` (line 316; rule 5 at line 336).
- `runtime/dispatcher.py`: the snapshot's `tier` map (line 14).
- `site/tools/build_proof_json.py` (lines 63 to 65 read `strong_model`, `strong_harness`, `floor_model`, `floor_harness` and `strong_tolerance`) and `site/assets/js/proof.js` (lines 16 to 32).
- `interface/js`: `format.js`, `views/control-model.js` and `views/control-skills.js` (the two tier columns, lines 13 to 23).
- The word `tier` is also in 22 runtime test files, 12 of them with `tier=` (found on 2026-10-14 with `grep -lw tier runtime/tests/*.py` and `grep -l "tier=" runtime/tests/*.py`).

Also: `evals/eval_status.py` `as_reference` (line 1095) and `skill_band` (line 1965), which already give each model its band, cause, gate and score by the same rules on that model's lines (the text at lines 118 to 128); `runtime/costs.py` `usage_of` (line 48) and `recompute` (line 133); `adapters/api/prices.json` (six models, with source and access date) and `model_prices` (`runtime/project_config.py`, lines 53, 91 and 159).

**Builds.**

- **The runtime.** `route(model=<id>)` and `route(auto)` replace the tiers, and the inventory above is done symbol by symbol: `TIERS` deleted from both files; the lab facade keyed by model (`reference`, `credential_missing`, `run_skill`); the runtime's own key for the floor model generalised to a key name per model, and the billing of a model read per model; the billing history rule per model; the snapshot's tier map per task model; the site's proof data and script; the interface's two tier columns replaced by one row per model; the 22 test files updated. The `strong_*` and `floor_*` keys leave the gate file only when no reader is left (P2a made the reader of the old evidence shape, which stays in `evals/`). The auto rule (D22, D34, D35, D36):
  1. The candidates are the pairs where the skill is `reliable`, a key is found, a price is known and the provider is inside the routine's approved provider set (for a routine, D35).
  2. Pick the lowest expected cost per run: the mean usage of that model's with-skill runs times its list price (D5).
  3. A tie goes to the higher pessimistic score.
  4. No candidate: the project's default model, `supervised`, with the reason shown.
  5. **Unattended release in `auto`** (a review released in `autonomous` mode, a routine's tasks) only for a pair proven by lab evidence or by the person's own local tests; a pair that is `reliable` only through community evidence is chosen and used, with its output reviewed (D34, D36).
  6. A model the person names without `reliable` evidence is marked unproven. It runs `supervised` (D8) when it is named on a single request or the agent is below `autonomous`; when it is the agent's fixed model and the agent is `autonomous`, the person's consent (D38) releases the reviews and each run is recorded as "autonomy by consent".
  There is no extra minimum score and no per-project setting; a critical project selects a model by hand.
- **Where the choice is stored.** A column on the request and the task in the store, which is migration 10 (rule 1), and a project default model in `runtime.json`. The router's run uses the project default.
- **One price table** with source and access date, in a home this package decides, replaces `adapters/api/prices.json` and the project's `model_prices` (retired, or derived from it). OpenRouter prices are adopted from its models API (principle 14); the repository already records that URL as the source of three entries, accessed 2026-09-30.
- **Interface.** A model picker per request and per agent, with a default per project. It shows each model's band and cost, recommends a model from the scores (D34), and shows the date beside a price. **Consent per agent (D38):** fixing an agent's model while the agent is `autonomous`, or raising the agent to `autonomous` with a model fixed, shows the D34 warning and stores the consent with the agent's settings; changing the model asks again; the rule in `runtime/autonomy.py` `review_action` (rule 5, line 336) releases the review of an unproven pair for an agent that has the consent and records the run as "autonomy by consent". The consent of D34 for an unattended routine on a fixed model is stored by P6; the warning text is written here.
- **Documents.** `AGENTS.md` principle 9 (line 15) is reworded: proof decides autonomy by default, and an explicit consent, per routine (D34) or per agent (D38), can grant it; external effects keep the hard limit of principle 11. The band rules of the same file, `docs/architecture/reliability-model-2026-10-02.md`, `evals/README.md` (line 119) and the "Adding a skill" step 5 (a new skill is done when its first full test has passed on the two lab models, D6) are rewritten without the tiers. Principle 12's trigger ("the next change of reference model", `AGENTS.md`, line 18) and backlog T23 (`docs/backlog.md`, lines 83 to 88) get a new trigger: a change of the lab default list or of the grader. The inventory's band table, which is on the reference model, becomes per model (`docs/inventory.md`, line 214, and the model table beside it). Backlog R15 (`docs/backlog.md`, line 195) is replaced by the picker.

**Done when.**

- A test shows `auto` picking the cheaper `reliable` pair, breaking a tie by the pessimistic score, falling back to the project default, `supervised`, when none qualifies, and holding a pair that is reliable only through community evidence for review.
- A test shows a model named on one request, without evidence, running `supervised` and marked unproven; and the same model fixed on an `autonomous` agent, after the warning, having its reviews released and its runs recorded as "autonomy by consent", with a change of model or of mode asking again.
- `git grep -nw TIERS -- runtime site` finds none; `grep -lw tier` over the source files of `runtime/` and `interface/js` finds none, except the reader of the old evidence shape in `evals/`; `evals/eval-gate.json` holds no `strong_*` or `floor_*` key.
- A test shows the cost estimate of `auto`, the run's cost and the proof page reading one price table.
- `python3 evals/eval_status.py status` gives the same bands and gates on the existing evidence as before, compared as text.
- No sentence of `AGENTS.md` or of the reliability-model document says one model decides a skill's standing, and principle 9 says what D34 says.

**Size.** L.

**Measurement impact.** None. `runtime/`, `interface/`, `site/`, the documents and `evals/eval_status.py` are not in the fingerprint.

**Depends on.** P2c (the per-model gate and the usage field), P2b (the models in the gate file) and P1 (`web_measured` touches the same files).

**Resolves.** F5 (E3), M3, Q3 (the one price table). Carries out D1, D3, D4, D5, D6, D8 as changed by D34 and D38, D22 as extended, D38, and the rewording of principle 9.

### P4. Sources I (L)

**Goal.** A person gives a project a source (an uploaded file or a Notion page), and a task receives clean text of the versions the planner chose for it.

**Reuses.**

- `runtime/drop.py` (the destination and the per-task folder; the web-task note, lines 25 to 29; `hand_over`, line 76) and `runtime/workcopy.py` (limit L2, lines 14 to 17; the walk of tracked files and `docs/`, lines 257 to 266; the scan, lines 228 to 232);
- the intake and the container helper of P0;
- the documents provider's `read` verb (`providers/documents/notion.py`, line 589; `doc_id`, line 527, accepts only the 32-character id) and the secret registry (`providers/secrets/resolver.py`: `NOTION_TOKEN`, lines 128 to 133, is described as "read and write the task board and the documents");
- `providers/resolve.py` (`ROLES`, line 95; `LISTED`, line 91; `folder`, line 155; `variables`, line 163), `providers/CONTRACT.md` and `contracts/environment.md`, for the new class `converter:document`;
- `runtime/project_config.py` (the accepted configuration, lines 98 and 232; `REQUIRED`, line 88; `TASK_RUNTIME_KEYS`, line 90) for the sources folder's key;
- `contracts/runtime.md` (limits L1 to L20) and the tests named `test_limit_<nn>_...`;
- `runtime/plan.py` `plan_hash` (line 316), which hashes the plan's tasks as JSON, so a field added to a task is covered;
- `skills/core-orchestrator/SKILL.md` and its `references/routing.md`.

**Builds.**

- **The ingest operation.** A synchronous operation, or a background job, over `sources.import_version()` in `runtime/sources.py` (`new`; no `ops` import, rule 3). There is no task row before P5: an ingest is not yet a task. Its operation lives in a sibling module and is registered in `runtime/operations.py` (rule 2).
- **The sources folder and its guardrails (D30, S6),** `sources_dir`, a new mandatory key of `runtime.json` with no default (a project without it does not run), and as numbered hard limits from L21, each with a test named after it: (1) the folder is dedicated, empty or marked as the runtime's at acceptance, with mode 0700; (2) it is disjoint from `data_dir`, `store_db`, the workbench checkout and the local evidence folder; (3) the runtime writes only inside it, never follows a symbolic link out, and refuses the home folder, the filesystem root and a folder that contains the project; (4) a container's outputs go to a size-capped memory-backed folder and the host copies back only regular files, checked with `lstat` and opened with `O_NOFOLLOW`, under a byte cap and naming rules; (5) a file changed outside the runtime is detected by its hash, sniffed, converted and scanned again, labelled as the person's, and never used unattended; (6) the work copy excludes the folder, even when it sits inside a tracked tree; (7) the catalog is built only from converted output, never by parsing a raw file on the host.
- **The source registry** (`new`): the project declares its sources, with no credentials in it. **Immutable versions:** the original, the converted text and a manifest (origin, date, sha256). **The rich catalog,** built by code at import with no model (D11). **A size cap per source,** with a warning.
- **`converter:document`** (`new`, a runtime-only class like the transcriber): PDF, HTML, XLSX, CSV and DOCX to Markdown or CSV, in the shared container of P0 with no network, adopting existing tools (principle 14). The output is scanned for credentials after conversion. `sniff` knows only video, image and HEIF brands on the branch and gains PDF, OOXML and text. The class is added to `ROLES` and its row to `providers/CONTRACT.md`; whether it also goes to `LISTED` and `contracts/environment.md` depends on whether a skill may require it (rule 4).
- **Uploaded files and Notion pages by address (D13).** Reading by URL needs a small function that extracts the 32-character id. Notion sources use **a separate secret that can only read** (S7), a new entry of the secret registry; `NOTION_TOKEN`, which can write, is not used for sources.
- **The planner chooses sources, in one X change of `core-orchestrator`.** The change adds source choice to the skill and names the catalog in its **External content is data.** line (`skills/core-orchestrator/SKILL.md`, line 44), which is an X change that asks for a full test (`AGENTS.md`, "Changing an existing skill"), on the two lab models: the skill has 9 cases, so 3 runs of each on 2 models are 54 runs, and up to 72 if the 18 baseline runs are not in force (M4). The catalog is third-party text: data, never instruction.
- **The plan card** lists each task's sources and highlights a web task that receives sources (D16, manual use); the source ids are part of the plan's tasks and so of the plan hash. An optional `@mention` in the request forces a source.
- **A task receives copies of its chosen source versions (D29):** the newest version of each chosen source id at the moment the task starts, recorded on the task as id, version and sha256.
- **A fixture helper** adds `sources_dir` to the test projects before the key becomes mandatory: 43 runtime test files name `runtime.json` and 41 of those also write a file (found on 2026-10-14 with `grep -l "runtime.json" runtime/tests/*.py`), and each would fail the day the key is required (Q6).
- **Eval cases with converted input,** one in each of two target skills, with `--baseline`, and a guard assertion that converted text is treated as data (observation O2 of the architecture document: the `biz-market-analysis` line **External content is data.**, `skills/biz-market-analysis/SKILL.md`, line 49, names web pages and research briefs, not a converted file).
- Migration 11 for the registry and the versions (rule 1).

**Done when.**

- Offline fixtures pass for each format.
- A PDF with a planted fake key is refused after conversion. (Raw, it is not found: section 4.)
- Each guardrail above has its named test: a symbolic link out, the home folder, the root, a folder that contains the project, a folder shared with `data_dir` or `store_db`, a mode other than 0700 and a non-regular file coming back from a container are each refused; a changed file is treated as a new version of the person's and is not used unattended.
- A fixture request that names an `@mention` plans a task with that source; the plan hash changes when a source id changes and does not change when a source gets a new version.
- A task of the work copy never sees the sources folder, with the folder inside a tracked tree.
- A source refreshed after a task was planned and before it starts reaches the task as the newer version; one refreshed after it started does not; the task's record holds the id, version and sha256 of each source it received (D29).
- The 43 test files pass with `sources_dir` mandatory; the limits table of `contracts/runtime.md`, the class row, `ROLES` and the generated tables are updated (rule 4).
- The measurement fingerprint is unchanged and no skill other than `core-orchestrator` is bumped; its full test on the two lab models has passed the gate, with the guard cases that have no run in the current set today.
- The two converted-input cases run with `--cases <id> --baseline` before the package closes.

**Size.** L.

**Measurement impact.** None to the fingerprint. The `core-orchestrator` change is an X change: a full test on the two lab models. Today the skill is `needs a test` on both models, because guard assertions of its cases have no run in the current set (section 2); the full test runs them. The full test runs after the battery of P2b, so that it is not run twice. Added cases are `pending` until they have run and move no band.

**Depends on.** P0 (the intake and the container helper), P3 (migration order, rule 1) and P-1 (the fixture helper touches 43 test files). The full test waits for the battery.

**Resolves.** F7 (E5) and F8 (G3), replacing the drop-closure rule; the manual half of F10 (R1); observations O1 (an ingest step reads an address or a path from its arguments, hashed in the plan) and O2; S6, S7 (Notion), M4, Q2, Q6. Carries out D9, D10, D11, D13 (uploaded files and Notion), D16 (the plan card), D29 and D30.

### P5. The step task and the step engine (M)

**Goal.** One engine runs the steps of an ingestion and, later, of a media pipeline, resumably, with stops; and the step task, the store's task with no skill, is designed once.

**Reuses.**

- On `origin/feature/short-video`: `providers/store/sqlite.py`, lines 1486 to 1560 (`is_code_task`, line 1487; `code_task_add`, line 1498; `code_task_move`, line 1528); `runtime/pipeline.py` (`run`, line 747; `STOPS`, line 75; `prepare_again`, line 808; the failure records); `runtime/ops_pipeline.py`, line 138, the one caller of `code_task_move`.
- On `main`: `runtime/ops_runs.py` (`skill_facts`, lines 74 to 87; a task run is its own process, `run-task --project <dir> --task <id>`, line 14; `dispatch`, line 581); `stop-runs` (`runtime/cli.py`, line 48); `runtime/parallel.py` `admit` (line 87); `runtime/dispatcher.py` (`NO_AGENT`, line 70); `runtime/plan.py` `combine` (line 575, which calls `agent_of` for every task at line 595; `agent_of`, line 163).

**Builds.**

- **The step task, once (Q1, M2).** The branch's three store functions are ported and renamed `step_task_add`, `is_step_task` and `step_task_move`, so that "code task" means only the code-area task of `parallel.py`. The task gets its columns (migration 12): its kind, its arguments (hashed in the plan), its footprint (derived from the kind, so that `admit` holds a step task against a skill task that writes the same path), and its states.
- **`planned` and `ready` under `depends_on`,** like skill tasks. On the branch, `NEXT_READY_TASK` (`providers/store/sqlite.py`, line 1086) requires `skill IS NOT NULL`, so a task with no skill is never ready; this package changes that for step tasks.
- **One owner rule** so that a step task is not held with "no enabled agent owns the task" (`runtime/dispatcher.py`, line 70) and does not fail planning (`runtime/plan.py`, `agent_of`, lines 163 and 595). The executor decides between a runtime pseudo-agent with its own cap and a rule in the planner, and records the choice in `docs/decisions.md`.
- **`runtime/steps.py`** (`new`), extracted from `runtime/pipeline.py` and parameterised by a registry of kinds. A kind declares its order, its stops and its executors. The engine no longer imports `captions`, `media` or `theme` (lines 67 to 69 of the branch's file).
- `ops_runs.dispatch` starts `cli.py run-step` as a child process, as it starts `run-task`, with lock-file liveness; `stop-runs` covers it. The new operations live in a sibling module (rule 2).
- The kinds `ingest` and the file-output kinds of P8 are registered. `ingest` wraps `sources.import_version`, so ingest is the engine's second consumer and the engine does not wait for the short-video rebase.

**Done when.**

- The ingest kind runs on the engine with its tests, and the engine imports no module of the video features.
- `git grep -n "code_task_add\|is_code_task\|code_task_move" -- providers runtime` finds none.
- A step task writing path X is held against a skill task writing X; the existing one-code-task-per-request tests pass.
- A step task becomes `ready` only when the tasks it depends on are `done`.
- A killed child is detected by its lock and the task is `failed`, not `running`; `stop-runs` ends a running step.
- A plan with a step task passes `plan.combine`.

**Size.** M.

**Measurement impact.** None.

**Depends on.** P4 (the second consumer, `sources.import_version`, and migration 11 before migration 12).

**Resolves.** Part of F9 (G4): the owner rule in the planner and the dispatcher; Q1, M2.

### P-OPS. Running unattended (M)

**Goal.** A runtime that is meant to run for weeks, with routines firing at night, fails in a way the person can see and fix, and does not fill the disk or depend on a desktop session. It comes before P6, so that a routine can be called 24-hour.

**Reuses.**

- `providers/secrets/resolver.py`: `store_available` (line 262), `_ask` (line 269), whose `except Exception` (line 272) turns any failure of the store, a locked one included, into an empty string, which every caller reads as "not found".
- `scripts/doctor.py` (`check_class`, line 108) for the doctor's checks.
- `providers/scheduler/systemd.py` (the linger notes, lines 44 and 45) and `providers/scheduler/launchd.py`.
- `evals/executor.py`: the run containers' names (`wb-eval-run-<id>`, line 321) and the labels P2b adds.
- `runtime/service.py`: `--lan` (lines 23 and 50) opens the page on the local network over plain HTTP with the bearer token.

**Builds.**

- **A distinct error for a secret store that is locked or unavailable,** instead of "not found" (`providers/secrets/resolver.py`, line 272), shown by the runtime, by messaging and by the doctor; and **one supported headless secret backend** for a machine with no desktop session, chosen by the executor and recorded in `docs/decisions.md` (I3).
- **Doctor checks:** the user manager's linger on Linux, the macOS file-access permission of the scheduler's jobs on the sources folder (item 12 of "To verify"), the eval image present (P2d), with the setup command named when it is not (D39), and free disk (I3).
- **Retention:** run folders under `data_dir` are removed after an age the project sets, and the number of kept source versions per source is stated and enforced (I6).
- **Orphan containers are removed by label on recovery** (the label of P2b; containers started before it are found by the name prefix), and the log size limits of the proxy containers, set in P2b, are checked by the doctor (I6).
- **A lease file with the host id** when a sources folder is in a synced drive: a second machine that finds a live lease of another host refuses to write and names it. No SQLite file and no lock lives inside a synced folder; `data_dir` and `store_db` are already required to be outside it (D30) (I4).
- **Documentation,** in `docs/architecture/platform/`: the SSH tunnel as the way to reach the page from another machine, never `--lan`; OAuth consent on a machine with a browser, and where the resulting token is stored; the retention of source versions.

**Done when.**

- A test with a fake keyring shows a locked store reported as such and an absent secret reported as missing, in the runtime's message and in the doctor.
- Doctor tests with fakes for each check.
- A test shows run folders past their age removed and a younger one kept; a test with a fake container tool shows orphans removed by label and by name prefix.
- A test shows a second host refused while another host's lease is live, and the refusal naming that host.
- The pages named above exist and `python3 scripts/validate.py` passes.

**Size.** M.

**Measurement impact.** None, provided the label and the log limits are made in P2b. A container argument added later in `evals/executor.py` would be a measurement change.

**Depends on.** P2b (the label and the log limits), P2d (the doctor's image check) and P4 (the sources folder). It is ordered after P5 so that recovery covers step tasks.

**Resolves.** I3, I4, I6.

### P6. Workflows with steps, parameters and dates, and routines (M + M)

**Goal.** A workflow can mix steps and skills, take parameters from the request and dates at fire time, be saved from a plan, and be started by a schedule unattended under D31 to D35.

**Reuses.** `runtime/flow_files.py` (the schema; `TASK_KEYS`, line 47); `runtime/plan.py` `plan_hash` (line 316); `runtime/handlers/published_posts.py` as the pattern (`due`, line 206; `tick`, line 392); `_ticks` (`runtime/ops.py`, line 2444); the scheduler providers; the store; the claim lock (`runtime/ops_core.py`, `_claim_lock`, line 371, used at `runtime/ops.py`, lines 742 and 1691); the channel policy (`runtime/operations.py`: `GROUPS`, line 259, `DEFAULT_POLICY`, line 281, `BRAKES`, line 287, `EFFECT_CHANNELS`, line 286; `runtime/project_config.py`, `_channels`, line 182); the effect gate (`runtime/autonomy.py`, `covers`, line 358).

**Builds.**

- **The flow schema.** `{"key", "step": "<kind>", "args", "depends_on"}` beside the skill tasks. Flow parameters are bound from the request and covered by the plan hash. **Date variables** `{today}` and `{week}` are filled at fire time (D33). Project flows live in the project, besides the workbench's; making the router choose among them would be a further change of `core-orchestrator`, which this package does not do: the person names a project flow on the page or in the terminal.
- **The flow check (D31).** It refuses a task that requires the web and receives sources, when the workflow is created or changed. When the skill accepts a research brief as an input (today `biz-market-analysis` and `biz-icp-positioning`, which list `docs/workbench/research/<topic>.md` in `inputs` and require `search:web`), it offers a split made by code: `core-research` with the web and without the sources, then the skill without the web, with the sources and the brief. For any other skill it asks the person.
- **"Save this plan as a workflow" (D32):** a free-text request is planned by the router, adjusted and approved, saved as a project workflow and scheduled on the same screen.
- **Routines.** A handler, `runtime/handlers/routines.py` (`new`), reads routine records from the store (migration 13): created and changed from the terminal or the page, approved by the sha256 of their exact content. A routine **always targets an existing workflow** (D31); a single step or a project script is a workflow of one step. The approved hash covers the schedule, the workflow template with its fixed arguments (not the date values), the `X.Y` of each skill, the image digest, a script's sha256 and declared destinations, the model with the consent of D34, and, for `auto`, the approved provider set (D35). A routine carries no mode, cap, policy or standing approval of its own, and each fire counts against the agent's daily caps.
- **At each fire** the workflow's dates are filled, the hash is recomputed, and tasks are created only if it equals the approved one; else the routine stops and asks. A new version of a source does not change the hash, since the workflow pins the source id (D24 rule 1).
- **Idempotent fires (I5).** A fire is keyed by the routine and the slot, under the claim lock, so that one slot never creates tasks twice. After an outage the record states what happens to a missed slot. Proposed default, to confirm with the maintainer: a missed slot is run once on recovery if it is younger than a window the record holds, and is otherwise skipped and noted; never once per missed slot.
- **Tasks proceed without review** only for pairs proven by lab evidence or the person's own tests, with the agent in `autonomous` mode; or, on a model the person fixed, by the routine's own explicit consent of D34 (distinct from the agent-level consent of D38, which covers manual use and is not read for a routine), the record then reading "autonomy by consent". Otherwise the routine waits at the first review and messaging notifies (D24 rule 3 as changed by D34). Effects still need the approval of their exact content unless a standing policy accepted in the terminal covers them.
- **Messaging.** The routine verbs are new rows of `runtime/operations.py` in a group of their own, and their code lives in a sibling module, not in `runtime/ops.py` (rule 2). By default only the brakes (list, pause, cancel) reach messaging, and the person may grant creating and changing through `channels.messaging`. MCP lists routines and cannot create or change them. **A routine whose workflow holds a networked script, or that a standing effect policy covers, is creatable only from the terminal or the page,** whatever `channels.messaging` grants: a hard limit with its own number and test, like `EFFECT_CHANNELS` (S10). Attachments, model choice and flow choice over messaging are not part of P6 (D28, section 9).

**Done when.**

- A workflow "ingest, then `biz-market-analysis`" is refused when created, with the split offered; with the brief as an input it is offered the code-made split, and the split workflow passes the flow check and its plan test as a manual request, with a parameter bound from the request. A free-text plan keeps the highlight on the plan card.
- A routine fires a workflow on schedule in a test with a fake clock; with the same hash it creates tasks, with a changed workflow template, skill `X.Y`, image digest, script sha256 or provider set it stops and asks, and a Z change of a skill does not stop it.
- Two fires for one slot create tasks once; a test shows the catch-up rule on a fake outage.
- "Save this plan as a workflow" saves the approved plan as a project workflow and schedules it.
- A routine created through MCP, or through messaging under the default policy, is refused; one that holds a networked script is refused through messaging even when the policy grants creating.
- On an unproven pair, a routine waits at its first review; with the consent of D34 it does not, its record reads "autonomy by consent", and changing the model asks for consent again.
- The limit of S10 is in the limits table of `contracts/runtime.md` with a test named after it, and `runtime/ops.py` has not grown past its budget.

**Size.** M for the flow schema, parameters and the save, M for routines.

**Measurement impact.** None.

**Depends on.** P5 (the step task and engine), P-OPS (so a routine can be 24-hour) and P3 (the picker the consent sits beside).

**Resolves.** F4 (E2), F12 (R2), the rest of F9 (G4) (flow parameters; the owner rule is P5's); S3, S10, I5. Carries out D23, D24, D27, D31, D32, D33, D34, D35 and the routine half of D16, and uses D12 (a refresh is a routine target).

### P7. Sources II: Google Drive (L)

**Goal.** A person picks Drive files, and each becomes a source like any other (a folder, after the spike of 2026-10-15, is not).

**Reuses.** `providers/mailbox/README.md` and `providers/mailbox/auth.py` (the Desktop OAuth client, the app "In production", the refresh token in the OS secret store, lines 17, 18 and 26 of the README; the loopback host, line 67; `pkce_pair`, line 144; `authorize_url`, line 151, with PKCE S256 and a state checked on the callback); `providers/secrets/resolver.py`; the source registry, versions and converter of P4; the documents class (`integration:documents`, whose folder is `providers/documents/`, `providers/CONTRACT.md`, line 116; the Notion provider's verbs, `providers/documents/notion.py`, `VERBS`, line 707).

**Builds.**

- **First step, in parallel with earlier packages: a spike** that answers "does picking a folder under `drive.file` give access to the files inside it?" If not, multi-select of files, and a new question to the maintainer about `drive.readonly` for folder sources. **Done 2026-10-15: it does not (item 1 of "To verify"); the maintainer decided files only, so P7 builds multi-select of files, one scope and no folder source.**
- **Drive as an implementation of `integration:documents`** (`providers/documents/gdrive.py`, `new`) under the existing verbs, which P8's write-back reuses; OAuth like Gmail with the scope `drive.file` (D14); files only, several at once (folders were dropped after the spike, item 1 of "To verify"); export of native Google files by the Drive API and conversion; download and conversion of other files. The documentation states that `drive.file` lets the app read and write every file the person picks, so the scope is not read-only; the provider uses its read verbs for sources.
- **The Picker runs on a one-shot loopback page** served by the authorization script, with state and PKCE as `auth.py` already does, and closed after the callback. It never runs inside the interface: the interface's rule is "nothing from another host" (`interface/README.md`, line 112), and the page's policy is `default-src 'self'` (`runtime/service.py`, line 228), which the Picker's script from Google's host would break (S7). Whether the Picker's desktop flow works with a loopback page is item 8 of "To verify".
- **Change detection for refresh (D12):** each refresh is a new version, and a task records which version it read.

**Done when.**

- The spike's answer is written in this document's "To verify" list as confirmed or refuted, with the date and how it was checked.
- With a recorded or fake Drive, a multi-select of file sources imports, converts, versions and refreshes; a refresh with no change creates no version.
- The provider holds no scope beyond `drive.file`, and a credential never enters a run (a test on the environment passed to the provider).
- A test shows the one-shot page refusing a callback with a wrong state, and no file of `interface/` naming a host other than its own.
- The class and provider rows of `providers/CONTRACT.md` and the generated tables are updated (rule 4).

**Size.** L.

**Measurement impact.** None.

**Depends on.** P4. The spike depends on nothing.

**Resolves.** S7 (the Picker half), Q3 (Drive as `integration:documents`). Carries out D13 (Drive), D14 and D12 for Drive.

### P8. Outputs (M)

**Goal.** A task's result can leave as a file, or as a write to Drive or Notion, under the gates of principle 11, and nothing the source text says reaches the person disguised.

**Reuses.** The step engine of P5; the container helper of P0; `runtime/documents.py` (`push`, line 533, which mirrors manifest documents only); `providers/documents/notion.py` (the `write` verb, `VERBS`, line 707); the Drive provider of P7; the effect gate (`runtime/autonomy.py`, `covers`, line 358; `runtime/ops.py`, line 1456) and the registry of effect kinds (`runtime/effects.py`, `KINDS`, line 149: "a new kind is a module and a row of KINDS"); the exact-content approval of `runtime/ops_video.py` `video_approve` (line 184, on `feature/short-video`) as the pattern. HTML to PDF may reuse the short-video renderer's headless browser in a container (`providers/renderer/_docker.py`, on `feature/short-video`).

**Builds.**

- **The file-output step kinds** (D17 direction 1): PDF, XLSX, DOCX and CSV generated by a code step with no model, using adopted tools, written into the sources folder or `docs/` as a new version. **Spreadsheet formula injection is guarded (S9):** in XLSX and CSV outputs a cell whose text starts with `=`, `+`, `-` or `@` is written as text, with a test for each.
- **Hidden text is flagged (S9)** in converted HTML and PDF (text that is invisible to the person, such as off-page, zero-size or colour-matched text): the conversion records it in the version's manifest and the catalog shows it, so that the person sees what a model will read.
- **Write-back to Drive and Notion as an external effect** (D17 direction 2), as a new effect kind (a module and a row of `KINDS`, with its word added to the side-effect vocabulary of `contracts/environment.md`): preview of the exact content, one approval, execution, record. **The write-back target's id is inside the approved payload hash (S9).** Before the write, a check that the target was not edited since it was read (its version or hash against the version the task read); a target changed since stops and asks.
- The real case for each direction is chosen during development.

**Done when.**

- Each output kind produces a file from a fixture, offline, and a cell starting with each of the four characters is written as text.
- A converted fixture with hidden text is flagged in its manifest.
- A write-back without the approval of its exact content is refused by structure (a test); one with it runs once and records; a changed target id changes the hash and the approval no longer covers it.
- A target edited since it was read stops the write and asks (a test with a changed fixture).

**Size.** M.

**Measurement impact.** None.

**Depends on.** P5 (the engine) and P4 (the converter that flags hidden text); write-back to Drive also needs P7.

**Resolves.** F14 (G6), S9. Carries out D17.

### P9. Project script (M)

**Goal.** A project can run its own code as a step of a workflow or a routine, under limits that satisfy principle 11.

**Reuses.** The step engine and its registry of kinds (P5); the container helper of P0; the sources folder and versions of P4; the plan hash; the credential scan (`runtime/workcopy.py`, lines 228 to 232, and `scripts/redact.py`).

**Builds.** The "project script" step kind (D25): approved by the sha256 of its exact content (a changed file stops and asks); runs in the shared sandboxed container without credentials and with a read-only root; writes only into the sources folder, as a new versioned source; no direct effects (an effect goes through the effect gate); Python and shell first. Network and dependencies (S8):

- **Declared destinations are enforced** by a per-step egress proxy built from the hashed declaration, on an internal network without external DNS (item 11 of "To verify"), so that an undeclared host cannot be reached by name or by address. The proxy's definition lives outside `evals/container/`.
- **Dependencies are installed in a separate build container** from hashed lock files, with no mounts, and only the result reaches the run, read-only.
- **The script is scanned for credentials before approval.**

**Done when.**

- A script runs from a fixture and its output appears as a new source version.
- A changed script file stops the step and asks.
- A script cannot read an environment credential, cannot write outside the sources folder, reaches no network unless the destination is declared and in the approved hash, and cannot resolve an undeclared name (a test for each).
- The build container's arguments carry no mount (an argv test); a script with a planted fake key is refused before approval.

**Size.** M.

**Measurement impact.** None, as long as the per-step proxy's definition is kept outside `evals/container/`.

**Depends on.** P5, and P-OPS for the container hygiene the new containers inherit.

**Resolves.** F11 (G5), S8. Carries out D25.

### P10. Community evidence (L)

**Goal.** A contributor's lab tests of any model count for everyone's `auto`, without the maintainer running them, and the maintainer's own score tests move to the same attested CI. Community evidence ranks and never by itself releases unattended work (D36).

**Reuses.** The per-model gate, local evidence and published image of P2; the keys rule of SEC; `evals/eval_status.py` (`FIELD_CAP`, line 1729, the per-contributor cap pattern; the evidence validators); `.github/workflows/checks.yml`; the "first attested battery on GitHub" already listed as waiting in `docs/backlog.md`, line 84.

**Builds.** D19: an official reusable workflow, referenced by commit, that checks out the official code at that commit, runs the lab test with the contributor's keys in their fork's CI and has GitHub attest the evidence file; a check in the workbench's CI that verifies with no model call and records the evidence as "community verified" in its own column per model, with a per-contributor cap; a rule that every completed run of the fork's workflow is submitted and that gaps in run numbers are flagged; field evidence demotes a pair after three `failed` verdicts. Later: the maintainer's lab runs move to the same attested CI. Hardening (S5):

- **`id-token: write` only in a separate attestation job** that receives the evidence file's digest, never in the job that runs the model.
- **Verification** with `--signer-workflow` and `--signer-digest` bound to the checked-out commit, and refusal of self-hosted runners (item 13 of "To verify").
- **No actions cache** in the reusable workflow.
- **The verifier runs from the base commit's code** under `pull_request`, never under `pull_request_target`.

**Done when.**

- A fixture evidence file with a valid attestation is accepted and shown in the community column; a file with a wrong signer workflow, a signer digest not equal to the checked-out commit, a self-hosted runner, a commit not in `main` or a digest mismatch is rejected (a test for each, offline).
- A text test over the workflow file: `id-token: write` appears only in the attestation job, no cache step appears, and the verifier's trigger is `pull_request`.
- A set of runs with a gap in the run numbers is flagged.
- The per-contributor cap holds, and a pair `reliable` only through community evidence is not released unattended (P3's rule).
- `python3 scripts/validate.py` passes.

**Size.** L.

**Measurement impact.** None for the verification. Running the maintainer's tests in a CI on another platform later is an execution-side change for the skills it reaches (D20 accepts both platforms; the maintainer decides when to move).

**Depends on.** P2c, P2d and SEC.

**Resolves.** The community half of F2 (G1), S5. Carries out D19 (supersedes D7), D36 and the later evolution of D19.

### Side package. The short-video rebase (L)

**Goal.** Put the video features on the extracted kernel, off the critical path.

**Reuses.** Everything P0 and P5 extracted; the branch `origin/feature/short-video`, which already carries commit `e1202879` (P-1), so a rebase finds its changes applied.

**Builds.** The pipeline, the renderer and transcriber providers, `runtime/media.py` and `runtime/video.py` rebased onto the step engine (`runtime/steps.py`), the store functions with the new names and the container helper (`providers/_container.py`, which the two providers call instead of writing their limits twice). The approve-video bug of section 5 is fixed here, with a test that approves and asserts the task is `done`.

**Done when.** The short-video pipeline runs on the engine with its existing tests; the bug test passes; the 44-file conflict of section 5 is gone because the branch is rebased on the kernel.

**Size.** L.

**Measurement impact.** None.

**Depends on.** P0 and P5.

**Resolves.** The bug of section 5. Nothing else.

### Order and funding

D26 fixes the order of version 2; version 3 replaces it with this one, which follows from the decisions D30 to D39 and the review rounds. The packages are P-1, SEC, P0 to P10 with P2 in four parts (P2a to P2d), P-OPS and the side package.

**The order:** P-1, then P2a, then SEC, then P0 and P1 (in parallel), then P2b (**one battery after it**), then P2c and P2d (in parallel with the battery, except P2d's publication part, which comes before it), then P3, P4, P5, P-OPS, P6, P7 (its folder-access spike at any time), P8, P9, P10. The short-video rebase stays off the critical path.

| Package | Starts after |
|---|---|
| P-1 | Nothing |
| P2a | Nothing in code; after P-1 so its tests run in parallel |
| SEC | Nothing in code; after P2a in the order, in parallel with it if two people work |
| P0, P1 | Nothing; together |
| P2b | SEC and P2a; the battery runs after it |
| P2c | P2a and P2b |
| P2d | P2b (the definition must be final); its publication part before the battery |
| P3 | P2c, P2b and P1 |
| P4 | P0, P3 (migration order) and P-1; its `core-orchestrator` full test after the battery |
| P5 | P4 |
| P-OPS | P2b, P2d, P4; ordered after P5 |
| P6 | P5, P-OPS and P3 |
| P7 | P4 (the spike: any time) |
| P8 | P5 and P4 (write-back to Drive also P7) |
| P9 | P5 |
| P10 | P2c, P2d and SEC |
| Side package | P0 and P5 |

If only three can be funded first: **P-1 with P2a and SEC; then P2b to P2d; then P4.** They give fast tests and the fix of a live defect, one model-independent measurement paid with one battery, and the sources pillar. P3 follows, since it is the choice of model that the maintainer asked for.

**Parallel work (principle 7).** The packages that can run at the same time, by the files they own:

| Pair | Files in common | Verdict |
|---|---|---|
| P-1 and anything | `.githooks/pre-commit`, `.github/workflows/checks.yml`, `runtime/tests/conftest.py` | Others may start meanwhile; their tests run serially until P-1 merges |
| P2a and SEC | P2a: `evals/eval_status.py` and a new module; SEC: `evals/executor.py`, `evals/container/` | In parallel; the order of the plan is not a dependency |
| P0, P1 and P2a | P0: new files; P1: `runtime/proof.py` (`row`), `runtime/lab.py` (`standing`) | In parallel |
| SEC and P2b | The same files and one epoch entry | Serial: SEC, then P2b |
| P2b, then P2c and P2d | P2c: `evals/eval_status.py`, `evals/eval_run.py`; P2d: the lock file, a workflow, `runtime/lab.py`, `runtime/proof.py`, the doctor | In parallel with each other and with the battery; the battery needs P2d's publication part |
| P3 and P4 | The store schema (`SCHEMA_VERSION`, line 53, migrations 10 and 11), `runtime/project_config.py` (a key each), `runtime/proof.py` | Serial: P3 then P4 |
| P4 and P7 | P7 uses P4's registry and converter | P7 after P4; its spike any time |
| P5 and P-OPS | `runtime/dispatcher.py`, `runtime/ops_runs.py` against `providers/secrets/resolver.py`, `scripts/doctor.py` | In parallel after P4, with P-OPS's recovery check after P5 |
| P8 and P9 | Both register kinds in P5's registry | In parallel; each adds its own kinds |
| P10 and anything but P2c, P2d and SEC | `.github/` and the evidence validators | In parallel after those three |

## 7. Open questions closed, and what is still to verify

OPEN-1 to OPEN-6 of version 1 are closed. Each is a decision of section 3.

| Question of version 1 | Closed by | What was decided |
|---|---|---|
| OPEN-1. Where ingested data lives | D9, D10, D11, D30 | A mandatory sources folder per project, outside the workbench's git and apart from `data_dir`; immutable versions; the planner chooses the sources a task sees. (Version 1 recommended the task's drop.) |
| OPEN-2. The first source and the real case | D13, D14 | Uploaded files and Notion, then Google Drive in general with `drive.file` and the Picker; OneDrive and Jira wait for a real project |
| OPEN-3. Live tools inside runs | D15 | No; MCP only on the host, as provider implementations with read verbs |
| OPEN-4. Routine records | D23, D24, D31, D35 | Records in the store, approved by hash; a routine targets a workflow; the unattended rules of D24 as changed |
| OPEN-5. The auto mode's minimum score | D22 | The cheapest `reliable` pair; no extra minimum and no per-project setting. (Version 1 recommended the gate threshold, adjustable.) |
| OPEN-6. The order after package 4 | D26, replaced in version 3 | The order of section 6 |

**Nothing from OPEN-1 to OPEN-6 remains open.** What is open is the list below, the proposed catch-up rule of P6 (a default to confirm), and the real cases to choose during development (D17: one for file outputs, one for write-back).

### To verify

Third-party facts that were not confirmed. None is stated as fact anywhere in this document; each decision that rests on one says so.

1. Whether picking a folder under `drive.file` grants access to the files inside it (P7's spike). **Refuted, 2026-10-15.** Checked by the maintainer with the supervisor's one-shot spike: a page on 127.0.0.1 serving the Picker with folders selectable (`setIncludeFolders(true)`, `setSelectFolderEnabled(true)`), the scope `drive.file` alone, a real folder that held files. `files.get` on the picked folder answered and `files.list` with `'<folderId>' in parents` listed 0 children. Picking a folder does not give access to the files inside it. Decision (maintainer, 2026-10-15): files only; the scope stays `drive.file`, the person picks one or more files (multi-select, folders not selectable), a Drive folder as a source is deferred (section 9), and `drive.readonly` is not requested.
2. Whether the Drive API exports Google Docs directly to Markdown, and the export size limit (recalled as 10 MB). **Answered from the documentation, 2026-10-15, not tested on the live service:** Google Docs have a Markdown export format (`text/markdown`) and the content of `files.export` is limited to 10 MB; `drive.file` is accepted for it (the Drive API's export-formats guide and the reference of `files.export`). Still open: P7 asks for `text/markdown` first and falls back to the Word format on a 400, and reports a 403 `exportSizeLimitExceeded` as the 10 MB limit; the first real import of a Doc records which format served it. Risk to watch: the Markdown export may embed pasted pictures as base64 `data:` URIs, which would push a Doc with screenshots past the converted cap; P7 replaces them with placeholders before the cap (`strip_embedded_images`), tested on a fixture, not on the live service.
3. Whether GitHub offers free arm64 hosted runners to public repositories. **Confirmed, 2026-10-15,** from GitHub's documentation and changelog: the labels `ubuntu-24.04-arm` and `ubuntu-22.04-arm` are free and unlimited on public repositories (generally available since 2025-08-07).
4. Whether the identity signed for a reusable workflow called from a fork is the official repository's workflow, so that `--signer-workflow` pins it. **Partly confirmed, 2026-10-15:** from the documentation of the certificate fields and the CLI's source, the Build Signer URI and Signer Digest name the called reusable workflow and its commit (`job_workflow_ref`, `job_workflow_sha`), and the Source Repository is the fork, so `--signer-workflow` pins the official workflow and `--repo` must name the fork. The case of a fork was inferred from that mapping, not run.
5. Whether artifact attestations require a public repository (the workbench is public, so it does not block). **Partly confirmed, 2026-10-15:** on a public repository they are available on every plan; on a private one only with GitHub Enterprise Cloud. The wording of the plan requirement was read from a search summary, not from the page.
6. Whether the subscription OAuth token of the reference model works in CI, for the later move of the maintainer's tests.
7. The size of the published eval image (estimated 1 to 2 GB, not measured).
8. Whether the Picker's desktop flow works with the loopback page. **Confirmed, 2026-10-15.** Checked by the maintainer with the same spike: the Picker's desktop flow worked on the one-shot page on 127.0.0.1 (the pick came back to the local server, which then called the Drive API with the token it held).
9. Whether the provider API prefers a client's `x-api-key` over the proxy's bearer token when both are present (SEC: how strict the header rule must be). **Answered, 2026-10-15,** by 13 requests with invented keys: Anthropic's API evaluates `x-api-key` before the bearer token (both invented: "invalid x-api-key"; its documentation calls the bearer a fallback). OpenRouter accepts `x-api-key` as a live credential path that its documentation does not mention, and which of the two wins could not be told without two real accounts. SEC drops the header on both routes; a list of the headers that may be forwarded is safer than a list of those dropped.
10. Whether the `.Id` of a pulled image differs between the classic and the containerd image stores (P2d: why the repo digest is the identity). **Confirmed, 2026-10-15:** observed on the classic store and read from Docker's source for the containerd store. Classic: `.Id` is the digest of the local platform's image configuration. Containerd: `.Id` is the top-level digest, the index digest for a multi-platform pull. `RepoDigests` (the index digest) is the same on both and `.Id` is not.
11. How DNS behaves on Docker `--internal` networks (P9: whether an undeclared name cannot be resolved). **Confirmed, 2026-10-15,** by observation: a container on an internal network alone gets an error answer (SERVFAIL) for an external name at once, and its IP traffic out fails with "network unreachable" (no default route); names on the same network resolve. A container on an internal network and an ordinary bridge has both egress and DNS. So a per-step proxy must be on both networks and the step's container on the internal one only.
12. Which macOS file-access permissions launchd jobs need on synced folders (P-OPS).
13. Whether `gh attestation verify`, in the version of the CLI that CI pins, can refuse self-hosted runners (P10). **Confirmed, 2026-10-15:** `--deny-self-hosted-runners` exists in the CLI's version 2.101.0 (it checks the runner environment field of the certificate) and combines with `--signer-workflow`.

## 8. Risks and how to see them early

| Risk | How to see it early |
|---|---|
| Skills do worse on large converted documents. The proof covers inputs in the form of the cases. | The converted-input cases of P4 run with `--baseline`; field evidence from the first real use; a size cap per source. |
| A measurement change is classified wrongly, and the battery is paid for. A grader-side change raises the floor and asks every skill for a full test. | SEC and P2b are one epoch entry and one battery, and nothing is measured between them; the review of P2b compares the upstream request of the two measured models with a golden recording; P-OPS, P2d and P9 are kept out of fingerprinted files on purpose (a container argument added later in `evals/executor.py` would be a second epoch). |
| SEC changes how the measured runs reach the network, and the change is less harmless than judged. | The golden recording of the upstream request; the connection log of a recent battery read first; the maintainer's decision on the class of the change. |
| The `core-orchestrator` X change is run before the battery and again after it. | P4 waits for the battery; the full test is run once, on the two lab models (54 to 72 runs). |
| Most work of one floor stays serial, because a placeholder in a skill's declared path counts as an overlap. | Backlog R17 (`docs/backlog.md`, line 214) says this and keeps the conservative rule. Count held tasks with the held reason `artifact in use` (`IN_USE`, `runtime/parallel.py`, line 40) in the first real runs. |
| The renderer image has been built on one machine only. | On `feature/short-video`, `docs/architecture/platform/short-video.md` says the amd64 renderer image "has not been built or run" (line 390) and that the amd64 browser archive has no pinned sha256 (lines 437 and 466). P0 does not depend on the images; the video features and HTML to PDF through the renderer (P8) do. |
| A model that runs on the person's machine (`ollama/...`) cannot be reached from the eval container. | The archived backlog records that the container's network reaches only the hosted providers (`docs/backlog-archive.md` (removed on 2026-10-14; `git show d3e60770:docs/backlog-archive.md`), line 163). `ollama/<name>` is parsed by the adapter (`adapters/agents-dir/run-prompt.sh`, line 99), but a lab run on it is not supported until a route is built. Leave it out of P2 and P3's "done when". |
| `auto` ranks by a price that changed. | The one price table carries an access date; `auto` shows the date beside the price, and a price older than a limit the project sets is shown as stale. |
| A model the person names without evidence produces a poor result and nothing marks it; or a routine on such a model runs unattended by consent and does damage. | D8: a model named on one request runs `supervised`, and the run and the card say "unproven". D34 and D38: the consent is explicit (per routine, in its hash; per agent, when its model is fixed and it is `autonomous`), warned on the screen, and each run reads "autonomy by consent"; external effects keep the approval of their exact content. |
| The Picker's folder access is unknown: `drive.file` may not reach the files inside a picked folder. | P7's spike, first, in parallel with the earlier packages; if refuted, multi-select of files and a new question to the maintainer. |
| The published image is a dependency on a registry: availability, cost, size (not measured) and the pin; and a rebuilt image would make all the evidence unproven. | The lock file records digests per platform; only the protected workflow publishes; the first pull is an explicit setup step (D39) and a run without the image refuses with the command; a person with no network keeps working on a local image, whose evidence is local-only (D21). Measure the size in P2d. |
| Community cherry-picking and provider honesty remain after the mitigations of D19. | Every completed run must be submitted and gaps in run numbers are flagged; the pessimistic score and the per-contributor cap; field evidence demotes a pair after three `failed` verdicts; D36 keeps community evidence from releasing unattended work. Provider honesty is not checkable and is published as such (principle 10). |
| Dependence on GitHub: the attestation, the reusable workflow, the runners (free arm64 runners are unconfirmed). | The verification in the workbench's CI is offline apart from the signature check; the maintainer's own tests keep running on his machine until the move is confirmed (items 3 to 6 and 13 of "To verify"). |
| The planner misses a source a task needs, or a catalog's text carries an instruction. | The plan shows the chosen sources and the person approves it; the planner asks when in doubt; the `@mention` forces a source; the catalog is data (D11), named in the skill's external-content line, and a guard assertion measures that. Option B is considered only after evidence that the planner misses files. |
| The sources folder is attacked or damaged: a link out, a shared folder, a file changed behind the runtime's back, a container writing something odd. | The hard limits L21 and up with a named test each (P4); a changed file is never used unattended (D30). |
| A secret store that is locked reads as a missing key and a routine fails silently at night. | P-OPS: a distinct error, a headless backend, the doctor, and messaging notice of a routine that did not run. |
| A sources folder in a synced drive is written from two machines. | P-OPS: the lease file with the host id; no database or lock in a synced folder. |
| The test suite is slow enough to be skipped. | P-1 first; the wall time before and after is recorded in its pull request. |

## 9. Not in this plan

- An Instagram or TikTok publisher.
- Indexing or RAG. It waits for a real case (D11).
- Agent memory: replaced by the standing instructions (SPEC-INSTRUCTIONS, 2026-10-16; `docs/workbench/instructions.md`, written only by the person).
- A persona per agent.
- OneDrive and Jira. They wait for a real project that needs them (D13). The platform plan of 2026-10-05 already parks Jira (`docs/architecture/platform-plan-2026-10-05.md`, section 8, line 366).
- Attachments, model choice and flow choice over messaging (D28). Messaging carries none of them today (`runtime/messaging_inbound.py`, header, lines 7 to 19); until the later evolution of the messaging channel, a file, a model or a flow is chosen on the page or in the terminal. The trigger is the completion of P6, after which the maintainer decides when to open the work.
- Option B of D11 (the whole sources folder read on demand by non-web tasks), as a future per-project opt-in, off by default, only after evidence that the planner misses files and with eval cases that measure folder exploration.
- MCP inside runs (D15).
- Free-text routines (D31). A request that should repeat is saved as a workflow first (D32).
- Remote access to the page other than an SSH tunnel: `--lan` (plain HTTP with the bearer token) is a risk the person accepts for a phone on the same network, and this plan adds no other way (P-OPS).
- Releasing unattended work on community evidence alone (D36).
- A Drive folder as a source (decided 2026-10-15, after the spike in item 1 of "To verify"): `drive.file` does not reach the files inside a picked folder, so P7 reads picked files only. A folder source would need `drive.readonly`, a wider and sensitive scope (Google's review of the app), and the maintainer's decision; it waits for a real case.

## 10. Assumptions and what was not verified

**Assumptions.**

- Assumption: poppler (`pdftotext`), pandoc and an XLSX reader convert the formats named in P4 (pandoc also reads DOCX). No converter was run in this check.
- Assumption: the size labels S, M and L are the author's judgments from the size of the files named, not measurements.
- Assumption: the battery's run archive, which the 2026-10-05 plan says is kept outside the repository (`docs/architecture/platform-plan-2026-10-05.md`, line 23), holds each run's raw output with `modelUsage` (`docs/backlog.md`, line 84). It was not opened. If it does not, usage for existing evidence comes from new runs.
- Assumption: a Notion page that is not a mirrored document can be read with a read-only integration token if the integration is shared with it. The provider calls the Notion API for any page id (`providers/documents/notion.py`, `retrieve`, line 535), but no live call was made.
- Assumption: OpenRouter's models API lists a price per model. The repository records the URL `https://openrouter.ai/api/v1/models` as the source of three entries in `adapters/api/prices.json`; the API was not called in this check.
- Assumption: the epoch of the measurement change of SEC and P2b can name only models with no evidence. `--models` accepts a model the gate file lists (`evals/eval_status.py`, line 685); no command was run to commit such a change. The plan proposes the conservative reading (the two measured models are reached).
- Assumption: the paths of the model endpoints SEC lets through are the ones a recorded run's request log shows. The log was not read for this plan; the prefixes (`/api/v1/` and `/v1/`) are those of the route files.
- Assumption: a step task's footprint and kind can be stored with the task by migration 12; the row was not inspected for a field that would hold them without one.
- Assumption: the file names given here to new elements are proposals, except the three homes of rule 3 (`runtime/sources.py`, `providers/_container.py`, the one price table, whose home is P3's to decide).
- Assumption: the routine verbs and the group that holds them (P6) are new rows of `runtime/operations.py`. The existing messaging default is `read`, `talk`, `answer` (`runtime/operations.py`, `DEFAULT_POLICY`, line 281) and the brakes are `cancel` and `set-mode` (`BRAKES`, line 287); the routine brakes (list, pause, cancel) are new and are not those.
- Assumption: a routine's schedule is a weekday and a time of day in the project's time zone; no format is fixed here. The catch-up default of P6 (run a missed slot once if it is younger than a window) is proposed, not decided.
- Assumption: D38's consent is the agent-level setting (the agent's fixed model with the agent `autonomous`), given on the page or in the terminal and not from a messaging channel, which the maintainer's wording does not say; and a model named on a single request that no agent has fixed keeps D8's hold, since no agent-level setting exists to carry a consent. Both readings can be changed by the maintainer.
- Assumption: the one-line findings and severities of the review table are the reviewers' own, as the coordinator gave them; the reports are not in the repository. The "resolved by" column is the author's.
- Assumption: the 54 to 72 runs of the `core-orchestrator` full test are 9 cases times 3 runs times 2 models, plus 18 baseline runs (one per case and model, `baseline_runs` in the gate file) when no baseline is in force.

**Not verified.**

- The third-party facts of the "To verify" list in section 7.
- The approve-video bug (section 5) was read in the code and not run.
- That a held run can reach the egress proxy and send data to another account on an allowed host (S1) was read in the code (`evals/executor.py`, lines 347 to 353; `evals/container/proxy/allow.txt`) and not run.
- The figure of about ten minutes for a serial run of the `runtime/` and `evals/` tests is the maintainer's (P-1) and was not re-timed.
- The counts of the test files (43 name `runtime.json`, 41 of them write a file, 22 contain the word `tier`, 12 contain `tier=`) were found by plain word search on 2026-10-14: the first agrees with the figure the review gave (43), the second does not (the review gave 16 test files for the tier code; the search finds 22 that contain the word, some of them in other senses). The package executors recount them symbol by symbol.
- A trial merge was run only between the commits named in section 5, and re-run for version 2 with the same counts: 44 files for `d3e60770` with `6794905e`, seven for `39600a0b` with `6794905e`.
- The per-model band counts of section 2 were computed on 2026-10-14 at `d3e60770` on this branch. They differ from version 1 (reference model `reliable` on 45 of 48, not 48; floor model `reliable` on 41, not 43), because the release #393 carried changes to skills (`core-orchestrator`, `mkt-social-copy`, `mkt-vote-round`) that version 1's check did not include. The cause of each skill's band is the one printed by `python3 evals/eval_status.py status`.
- The line numbers on `feature/short-video` are at `6794905e`, except where commit `e1202879` is named; `origin/feature/parallel-agents` has moved to `d9d3f069` and is no longer used for line numbers, since its work is on `main`.
- Whether P2b and P2d can publish and pull the eval image on both platforms, and its size, were not tested.
