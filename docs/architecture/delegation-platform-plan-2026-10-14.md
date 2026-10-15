# Delegation platform plan: data in, one execution model, a score per model

Version 2, of 2026-10-14. On `origin/main` at `d3e60770`. A proposal: nothing in it is built. Version 1 came from an analysis of three branches and a two-round debate with an independent reviewer agent on another model, whose claims were checked against the code. Version 2 records the maintainer's decisions taken the same day while walking the open questions of version 1, and the contrast with the architecture document (`docs/architecture/delegation-platform-architecture-2026-10-14.md`, section 6, findings F1 to F16).

Version 1 was checked on `main` at `9bc9b863`, `origin/feature/parallel-agents` at `39600a0b` and `origin/feature/short-video` at `6794905e`; the release #393 (`d3e60770`) has since carried the `feature/parallel-agents` work into `main`, and `origin/feature/parallel-agents` has moved to `d9d3f069` (documentation commits). Every `file:line` below on `main` was re-read at `d3e60770` for this version; a line number on `origin/feature/short-video` is at `6794905e`. The document was committed on a branch cut from `origin/main` at `d3e60770`.

How to read it: a path with a line number was opened and read for this plan. A claim with no line number was found by a search or comes from a command, and the text says which. A `new` element is never written as existing. A fact about a third-party service that was not confirmed is in the "To verify" list of section 7, never stated as fact. What was not verified is in section 10.

## What changed from version 1

- **Decisions D9 to D29 are new.** D1 to D8 keep their wording; D7 (community evidence set aside) is superseded by D19. D9 to D26 answer OPEN-1 to OPEN-6 and the gaps of the architecture document. D27 to D29 were taken later the same day and close three points that were assumptions or unspecified: D27 refines D16 (a task that requires the web never runs without it silently; a hand-written flow that gives sources to such a task is refused as a routine target), D28 puts attachments, model choice and flow choice over messaging in a later evolution after P6, and D29 fixes which source version a task gets (the newest at the moment it starts, recorded on the task).
- **The packages are renumbered P0 to P10 and a side package.** Version 1 had packages 1 to 6. A new P0 ports the generic short-video pieces (it absorbs version 1's package 2, the container helper). Version 1's package 4 splits into P2 (measurement identity) and P3 (model choice and `auto`); package 3 becomes P4 (sources I); package 5 becomes P5; package 6 becomes P6 (flows with steps, parameters and routines). P7 (Google Drive), P8 (outputs), P9 (project script) and P10 (community evidence) are new, and the short-video rebase is a side package off the critical path.
- **Findings resolved.** F1 to F16 of the architecture document are each assigned to a package (section 6, "Resolves" lines). Version 1's wrong claims they found are corrected here: the key proxy needs more than one fingerprinted file (F1), the gate file already has a `models` object (section 6, P2), the per-model gate does not hold yet for events per model (F6), and the dependency order of the data hand-over (F7).
- **Open questions closed.** OPEN-1 to OPEN-6 are closed by D9, D13, D15, D23, D22 and D26 (section 7). What is open is the "To verify" list and the real cases to choose during development (D17).
- **Counts recomputed.** The per-model band counts of section 2 were run again on this branch; they differ from version 1 (section 2 says how). Main-side line numbers are re-read at `d3e60770`.

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
| (c) A routine | A scheduled task: plain code, or a process that starts a workflow | Every Monday, refresh the sources and start the weekly report |

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
| Agent memory | missing | `docs/backlog.md` R2 (line 144) lists it, unticked |

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

D1 to D8 were taken in version 1. D9 to D26 were taken the same day while walking the open questions, and D27 to D29 later the same day. The bracket after a decision names the question it closes or the finding it answers.

1. **D1. The reference and floor tiers leave. A skill has a status per model.** Approved on one model says nothing of another. Every pair of skill, model and adapter has its own band, gate and score. Consequence: principle 9 of `AGENTS.md` is rewritten without the tiers, and the code that reads `TIERS` changes (P3).
2. **D2. Anyone may test a skill on any model.** The maintainer's own lab runs stay on `claude-sonnet-5-5` and `openrouter/deepseek/deepseek-v4.1-flash`. The grader stays fixed (`grader` in `evals/eval-gate.json`, line 8), so scores compare across models.
3. **D3. The person chooses the model for a run,** or `auto`. An `auto` mode chooses by the skill's score on each model against its cost.
4. **D4. The baseline (runs without the skill) is kept per model,** to measure the difference the skill makes on that model. Consequence: the second-model baseline option already exists (`--baseline-on`), so this costs runs only for a model that has none.
5. **D5. Auto ranks by the providers' list prices:** measured tokens per run times the provider's price, not by subscription.
6. **D6. A new skill enters the repository after a full test on the two lab models.** Its result is published whether it passed or not (principle 10). It runs unattended only where it is `reliable`.
7. **D7. Community lab evidence was set aside. Superseded by D19.** Today lab evidence is trusted because the maintainer runs it (`evals/README.md`, "Who runs the lab tests", line 119); field evidence is counted per contributor (`evals/eval_status.py`, `FIELD_CAP`, line 1729).
8. **D8. Proof keeps deciding autonomy (principle 9) and no longer decides access.** A model the person picks without `reliable` evidence runs `supervised` and is marked unproven. The hold already exists: `runtime/autonomy.py` `review_action`, rule 5, "the skill is not proven: hold" (docstring, line 322; code, line 336).
9. **D9. Data is not centralized (OPEN-1).** Each project declares its sources in a registry; no credentials in it, credentials stay in the OS secret store. Imported data lives in a **data folder the user defines per project, mandatory**: no default, and a project without one does not run. It is outside the workbench's git; the user may keep it in a repository or drive they already use and version it as they like. Each import is an immutable version: the original, the converted text (Markdown or CSV) and a manifest (origin, date, sha256).
10. **D10. Guardrails of the data folder.** Its path is set in the project's accepted configuration (`runtime.json`, accepted only in the terminal: `runtime/project_config.py`, lines 98 and 232). The runtime writes only inside it, never follows a symbolic link out, and refuses dangerous paths (the home folder, the filesystem root, a folder that contains the project). The work copy always excludes it, even when it sits inside a tracked tree. A file changed after import is detected by its hash and treated as a new version made by the person, never handed over as the recorded one.
11. **D11. A task sees only the sources chosen for it.** The **planner chooses** them from a **rich catalog built by code at import, with no model**: name, type, size, date, sheets and columns with sample values, first headings, and the person's optional description. The choice is shown in the plan the person already approves by hash; the planner asks when in doubt; an optional `@mention` in the request forces a source; flows and routines pin the source **id**, not the version. Teaching the planner to choose is a Y change of `core-orchestrator` (partial test on the two lab models). The catalog is third-party text: data, never instruction. **Option B** (a non-web task gets the whole folder read-only and reads on demand, like a hosted assistant's project retrieval mode) is a future per-project opt-in, off by default, considered only after evidence that the planner misses files, with eval cases that measure folder exploration (principle 13). A source too large for a run gets a size cap with a warning; indexing or RAG waits for a real case.
12. **D12. Integration sources are refreshed on demand or by a routine.** Each refresh is a new version; a task records which version it read.
13. **D13. First sources (OPEN-2):** uploaded files and Notion, then **Google Drive in general** (Docs, Sheets, Slides, PDFs and any file, not only Sheets). OneDrive and Jira wait for a real project. Google OAuth follows the Gmail provider's pattern (`providers/mailbox/README.md`, lines 17, 18 and 26: the person's own Desktop OAuth client, the app published "In production" for personal use, the refresh token in the OS secret store). Native Google files are exported by the Drive API and then converted; other files are downloaded and converted.
14. **D14. Drive permission.** Scope `drive.file` with the Google Picker (only what the person picks), not `drive.readonly`. A source may be a folder or a single file. Google documents a desktop and mobile Picker flow that returns through a callback URL (to verify, section 7).
15. **D15. No MCP inside runs (OPEN-3).** MCP servers may be adopted only on the host, as provider implementations with read verbs; the agent receives files, never the tool.
16. **D16. Ingested content and the web (R1, F10; refined by D27).** In manual use, the plan card highlights a web task that receives sources; approving the plan is the person's choice. In a routine, a task that receives sources runs **without the web**; work that needs both is split by the planner into a web task without sources and an analysis task with sources and no web.
17. **D17. Both output directions are in the plan (G6, F14).** (1) File outputs (PDF, XLSX, DOCX, CSV) generated by a code step, no model, with adopted tools, into the data folder or `docs/`. (2) Writing back to Drive or Notion as an external effect: preview of the exact content, one approval, execution, record, with a check that nobody edited the target since it was read. The real case is chosen during development.
18. **D18. Each person's own tests of any model stay local** (outside the workbench checkout, so `git pull` never conflicts) and feed only that person's `auto`. Adding a model must not change a fingerprinted file.
19. **D19. Community evidence, approved (supersedes D7).** The contributor runs the official reusable workflow, referenced by commit, in their fork's CI with their own keys. The workflow checks out the official code at that commit; GitHub attests the evidence file; the pull request carries the evidence and its attestation. The workbench's CI verifies without a model call (the signature, `--signer-workflow` of the official workflow, that the commit is in the history of `main`, and that the digest matches) and records the result as "community verified": its own column per model, a per-contributor cap, and it counts for everyone's `auto`. Mitigations: every completed run of the fork's workflow must be submitted and gaps in run numbers are flagged (against cherry-picking); the pessimistic score and the cap; field evidence demotes a pair after three `failed` verdicts. The provider host and the per-model pin live in the attested code, so a fake server is impossible. Residual risks: cherry-picking and provider honesty. Later evolution: the maintainer's own score tests (lab runs of `eval_run.py`) move to the same attested CI.
20. **D20. Platforms.** Evidence from `linux/amd64` is accepted beside `linux/arm64`, the platform recorded on each line, both summed (split only if results diverge). Testing only on amd64 was rejected: the maintainer's machine would emulate, switching platform is an execution epoch for every skill, and arm64 users exist.
21. **D21. The eval image is published (G2, F3).** To a registry, by digest per platform, from a pinned definition. The repository records the digests in a lock file. The runtime pulls the image automatically on first use, with a message. Evidence records the published digest; the proof check compares the local image with the published digest; a locally built image yields local-only evidence. A person only checks out `main`.
22. **D22. `auto` picks the cheapest `reliable` pair (OPEN-5),** with no extra minimum score and no per-project setting. A critical project selects a strong model by hand.
23. **D23. Routines (OPEN-4).** Created and changed from the terminal or the page, approved by the sha256 of their exact content (schedule, target, arguments). They carry no mode, cap, policy or standing approval of their own, and each fire counts against the agent's daily caps. Messaging's routine permissions are configurable through the existing channel policy (`channels.messaging` groups, accepted in the terminal): by default only the brakes (list, pause, cancel); the person may grant creating and changing. MCP stays outside the ceiling of creating and changing routines (it may list them).
24. **D24. Three rules for an unattended routine (E2, F4; R2, F12).** (1) Creating a routine generates its plan and the person approves that plan's hash with it; at each fire the plan is regenerated and tasks are created without asking only if the hash is identical, else it stops and asks (a new version of a source does not change the plan, which pins the source id). (2) A free-text routine never runs unattended: each fire becomes a plan to approve; only fixed targets (a flow or a step) run alone. (3) Tasks proceed without review only on `reliable` pairs with the agent in `autonomous` mode; otherwise the routine waits at the first review and messaging notifies. Effects still need approval of their exact content unless a standing policy accepted in the terminal covers them.
25. **D25. A "project script" step kind (G5, F11).** Approved by its exact hash (a changed file stops and asks). It runs in the shared sandboxed container without credentials and with a read-only root; the network is off by default, and declared destinations enter the approved hash; it writes only into the data folder, as a new versioned source; no direct effects. Python and shell first, with dependencies declared and pinned.
26. **D26. The order of section 6 (OPEN-6).**
27. **D27. A task that requires the web never runs without it silently (refines D16).** For a plan the planner makes, D16's split applies: a web task without sources and an analysis task with sources and no web. For a fixed flow written by hand, the flow check refuses a flow in which a task that requires the web receives sources, when the flow is a routine's target: at routine creation and again at the plan of each fire. Its message tells the person to split the flow into a web task without sources and a task with sources and no web. So no routine runs a web-requiring skill without the web. In manual use D16 stands: the plan card highlights the web task that receives sources and the person decides.
28. **D28. Attachments, model choice and flow choice over messaging are a later evolution of the messaging channel, after P6.** Until then they are done on the page or in the terminal (section 9).
29. **D29. A task receives the newest version of each chosen source at the moment it starts,** and that version (id, version, sha256) is recorded on the task.

## 4. Three paths and the one chosen

The chosen path holds. Version 2 refines it: the data folder of D9 settles where ingested data lives (outside the workbench's git, so path B's problem with snapshots under `docs/` does not arise), and the step engine (P5) still waits for its second consumer, ingestion.

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
  - On `feature/short-video`, `store.is_code_task` (`providers/store/sqlite.py`, line 1487) is true for a task with a parent and no skill. Both meanings are on that branch (`runtime/ops.py`, line 865, and the store function). A task with no skill has an empty footprint, so `admit` never serialises it against a skill task: `runtime/ops_runs.py` `skill_facts` returns an empty footprint and no code flag for a task with no skill (lines 74 to 87). P0 renames the store functions at the port, so the clash never reaches `main`.
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
| The task with no skill, renamed "step task" | `providers/store/sqlite.py`, lines 1486 to 1560 | P0 |
| The streaming intake and the content-addressed store | `runtime/media.py` `receive` (line 714), `sniff` (line 472) | P0, then generalised in P4 |
| The minimal provider environment | `runtime/ops_pipeline.py` `ENV_KEEP` (line 70) | P0 |
| The sandboxed container provider pattern | `providers/renderer/_docker.py` (`container_argv`, line 311) and `providers/transcriber/whispercpp.py` (`container_argv`, line 568), the same limits written twice | P0 (one helper module) |
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

Sizes are S, M or L and are judgments, not measurements (section 10). "Measurement impact" says whether the package touches a file in `FINGERPRINT_FILES` (`evals/eval_status.py`, line 557: the grading template, `evals/measure.py`, `evals/measurement.json`, `evals/executor.py`, `scripts/stage_skills.py`) or in `evals/container/`, or an eval adapter's `run-prompt.sh` and `eval.json` (lines 200 to 204), and, if it does, which kind of measurement change it is. "Resolves" names the findings (F1 to F16, `docs/architecture/delegation-platform-architecture-2026-10-14.md`, section 6; the E, G or R letter in brackets) and the decisions the package carries out.

### P0. Port the generic short-video pieces (M)

**Goal.** Put on `main`, without any video feature, the pieces the data pillar needs, so that no later package depends on a branch that is not merged.

**Reuses.** On `origin/feature/short-video` at `6794905e`: `providers/store/sqlite.py`, lines 1486 to 1560 (the task with no skill); `runtime/media.py` `receive` (line 714) and `sniff` (line 472); `runtime/ops_pipeline.py` `ENV_KEEP` (line 70); `providers/renderer/_docker.py` (`container_argv`, line 311) and `providers/transcriber/whispercpp.py` (`container_argv`, line 568), which write the same limits twice: no network, read-only root, all capabilities dropped, no new privileges, a limit on processes, memory, swap and CPUs, memory-backed `/tmp` and `/scratch`, an image that never pulls at run time (`providers/transcriber/whispercpp.py`, lines 568 to 580). Their tests: `providers/renderer/tests/test_renderer_docker.py` and `providers/transcriber/tests/test_whispercpp.py`.

**Builds.** All of it is copied from the branch into a branch cut from `origin/main`, not merged (section 5).

- The store's task with no skill, renamed: `code_task_add` becomes `step_task_add`, `is_code_task` becomes `is_step_task`, `code_task_move` becomes `step_task_move`, in the tests too. The word "code task" then means only the code-area task of `parallel.py`.
- The streaming intake: `receive` (bounded, hashed as written) and the content-addressed item store, with the arguments that belong to a recording or a slot left out; `sniff`, as it is.
- `ENV_KEEP`.
- One helper module for the limits of a sandboxed container, written once. The two providers stay on their branch; the side package makes them call it.
- Nothing of the video features: no `pipeline.py`, no `captions`, no `theme`, no `video.py`, no renderer or transcriber provider.

**Done when** tests show:

- the ported store functions pass the ported tests, and `git grep -n "code_task_add\|is_code_task\|code_task_move" -- providers runtime` finds none;
- the ported intake passes its tests and the module imports none of `captions`, `theme`, `video` or a recording type;
- a test compares the helper's container arguments, limit by limit, with those the two providers write today (the golden is each provider's `container_argv` at `6794905e`), and each limit keeps its name;
- the diff holds no video file.

**Size.** M. About 75 lines of store code and its tests, the intake, the environment constant and the helper.

**Measurement impact.** None. The store, `runtime/` and `providers/` are not in the fingerprint.

**Depends on.** A branch cut from `origin/main`. Nothing else.

**Resolves.** F15 (E7). Absorbs version 1's package 2 (the shared container helper).

### P1. Hygiene (S)

**Goal.** Remove correctness hazards before anything is built on them.

**Reuses.** The ported store functions of P0; `runtime/ops_runs.py` `skill_facts` (lines 74 to 87); `runtime/parallel.py` `admit` (line 87); `runtime/proof.py` `row` (line 97); `runtime/lab.py` `standing` (line 280).

**Builds.**

- A declared footprint for a step task, so that `admit` holds a step task against a skill task that writes the same path. From its kind; until kinds exist (P5), the footprint the creator declares when it adds the task.
- Fix `web_measured`. Today `proof.row` sets it to `bool(standing["web_cases"])` (`runtime/proof.py`, line 97), and `lab.standing` copies the gate file's list for the skill (`runtime/lab.py`, line 280). So a case listed in `web_cases` turns the web on before that case has any evidence, and the flag is the same for every model. Require lab lines of a listed case in the current set, on that model. The event line already records the web cases a test ran (`evals/eval_status.py`, the event fields, line 39).

**Done when** tests show:

- a step task writing path X is held against a skill task writing X;
- the existing one-code-task-per-request tests pass;
- a case listed in `web_cases` with no evidence does not turn the web on, and a case with evidence on model A and none on model B turns it on for A only.

**Size.** S.

**Measurement impact.** None. `runtime/proof.py`, `runtime/lab.py` and the store are not in the fingerprint.

**Depends on.** P0, where they share the store functions.

**Resolves.** Part of F13 (E6): `web_measured` per model, from evidence. The code-task clash of section 4.

### P2. Measurement identity (L)

**Goal.** Make a model a line in a list: adding one changes no fingerprinted file, the gate is read per model, the proof travels between machines, and a person's tests of any model stay on their machine. Done once, in one execution-side measurement change.

**Reuses.** `evals/eval-gate.json` (the `models` object of ids and aliases, line 33, which `known_models` reads, `evals/eval_status.py` line 532); `evals/eval_status.py` (`_model`, line 760; `event_line_problems`, line 773 and the `strong` requirement at line 795; `model_id`, line 540; `y_changes_since`, line 1888; the stored-gate fallback, lines 1180 to 1186; the newest full test, lines 1133 to 1136; `baseline_lines`, line 1107); `evals/eval_run.py` (`scratch_reason`, line 1826, and its checks at lines 1837 to 1863; the event line's `upstream` at lines 2492 to 2496; `complete`, line 2507; the run line at lines 2314 and 2474); `evals/executor.py` (`ROUTE_FILES`, line 73; `IMAGE_PLATFORM`, line 81; the local build, line 193); `evals/container/keyproxy/keyproxy.py` (the single `provider_only`, lines 79 and 187) and `keyproxy.json` (line 6), `keyproxy-strong.json`; `runtime/proof.py` `checks` (lines 104 to 115); `runtime/lab.py`; `runtime/costs.py` `usage_of` (line 48); `docs/backlog.md` T24 (line 89).

**Builds.**

1. **T24 first** (`docs/backlog.md`, line 89). The validator reads an old evidence file against the gate file as it was at that event, or accepts the old shape, so that reshaping the gate file invalidates no committed evidence. Committed evidence files are never edited.
2. **The gate file's model list.** The `models` object (line 33) gains, for each model, its adapter, its key variables, its price source and its provider pin; `strong_model`, `floor_model`, `strong_harness`, `floor_harness`, `strong_pass_env`, `floor_pass_env`, `strong_tolerance` and `web_jobs` (lines 2 to 10 and 20 to 23; validated by `GATE_FIELDS`, `evals/eval_status.py`, line 250) become entries of it. "The lab models" becomes a default list holding the two models of D2. `grader`, `threshold`, `runs`, `baseline_runs` and the tolerance (0.05) stay. The test header names a list of models instead of `{"strong", "floor"}`; the reader accepts both shapes (86 of 86 committed test lines carry the old one, counted on 2026-10-14).
3. **A model-keyed key proxy and routes, in one execution-side measurement change.** `keyproxy.py` reads the model from the request body and the pin from the route chosen by model; `executor.py` keys its routes by model, not by tier; the pin per model is read from the gate file's list, which is outside the fingerprint. The event line's `upstream` is written for every model that ran through the proxy, not for the floor tier only. The same change accepts `linux/amd64` beside `linux/arm64` and records the platform on each line (D20; `platform` is already an optional run field, `RUN_OPTIONAL`, `evals/eval_status.py`, line 734). After it, a new model never changes a fingerprinted file (D18).
4. **Gate, completion, Y count and stored gate per model.** The gate takes the newest full test whose header lists that model, and `complete`, `y_changes_since` and the stored gate follow the same selection, so that a full test on model Z resets no other model's Y count and moves no other model's `X.Y`. The comparison stays `measure.gate_passes(with_mean, baseline_mean, threshold, tolerance)`, unchanged.
5. **A usage field on run lines,** optional, with the four kinds `runtime/costs.py` already reads (input, output, cache read, cache write; lines 33 and 34), taken from the full model usage that counts the subagents, `modelUsage` of each run's raw output (`docs/backlog.md`, line 84), not from the `usage` total of `timing.json`. The recorded `cost_usd` of the reference model is not usable (`docs/architecture/platform-plan-2026-10-05.md`, line 20). Neither `eval_run.py` nor `eval_status.py` is in `FINGERPRINT_FILES`, so this part is infrastructure.
6. **The published image.** The eval image is built from the pinned definition and published to a registry by digest per platform; a lock file in the repository records the digests; the runtime pulls the image on first use with a message; evidence records the published digest; `proof.checks` compares the local image with the published digest and returns the same answer on every machine that holds the published image; a locally built image yields local-only evidence (D20, D21).
7. **Local evidence outside the checkout.** A person's runs of any model write to a folder outside the workbench checkout and feed only that person's `auto` (D18). `scratch_reason` (`evals/eval_run.py`, line 1826) stops refusing a named model; what it refuses is writing into the repository's evidence folder.
8. **Drops** "the model that decides the repository's gate": no model is special in the gate or in `done`.

**Done when.**

- A test adds a model to the gate file's list and to a route, and the measurement fingerprint (`measurement_sha256`) is unchanged.
- `python3 evals/eval_status.py status` prints the same text before and after for the existing evidence.
- A fixture with full tests on two models shows each model's gate, `complete`, Y count and `X.Y` independent of the other's.
- The `evidence` validator accepts an old evidence file against a changed gate file, and accepts a run line with and without the usage field.
- A test with a fake container tool shows the runtime pulling the published digest on a machine without the image, and `proof.checks` answering `image: None` when the local digest equals the published one.
- The same test run on `amd64` and `arm64` writes lines with the platform, and both count.
- A run of any model by a person leaves `git status` of the checkout clean.
- `python3 scripts/validate.py` passes with the new fingerprint committed.

**Size.** L.

**Measurement impact.** One execution-side measurement change (`python3 evals/eval_status.py measurement --kind execution`), touching `evals/executor.py`, `evals/container/keyproxy/keyproxy.py` and the route files. Proposed: an epoch that names only models with no evidence (`--models`; it accepts only models the gate file lists, `evals/eval_status.py`, line 685, so the gate file's new list lands first), because for the two measured models the request that leaves the proxy is unchanged. The review checks that with a test that compares the upstream request of the two measured models before and after. The maintainer decides the class; if he judges the change reaches the measured models, the cost is an epoch for every skill that principle 12 makes the last resort.

**Depends on.** Nothing. It runs in parallel with P0 and P1 (different files: `evals/` against `runtime/` and the store).

**Resolves.** F16 (R3) first, then F1 (E1), F2 (G1), F3 (G2), F6 (E4), the usage part of F13 (E6) and, with P3, F5 (E3). Carries out D18, D20 and D21, and the platform and image halves of D2.

### P3. Model choice and `auto` (M)

**Goal.** The tiers leave. A person names a model, or asks for `auto`; every pair has a published band.

**Reuses.** `runtime/proof.py` (`TIERS`, line 41; `route`, line 118; `checks`, line 104); its call site (`runtime/ops.py`, line 355); `evals/eval_status.py` `as_reference` (line 1095) and `skill_band` (line 1965), which already give each model its band, cause, gate and score by the same rules on that model's lines (the text at lines 118 to 128); `runtime/costs.py` `usage_of` (line 48) and `recompute` (line 133); the usage field and the per-model gate of P2; `runtime/autonomy.py` `review_action` (rule 5 at line 336).

**Builds.**

- **The runtime.** `route(model=<id>)` and `route(auto)` replace the tiers. The tier word is read in ten source files of `runtime/` (`autonomy.py`, `cli.py`, `dispatcher.py`, `lab.py`, `operations.py`, `ops.py`, `ops_core.py`, `ops_reads.py`, `ops_runs.py`, `proof.py`) and three of `interface/js` (`format.js`, `views/control-model.js`, `views/control-skills.js`), found on 2026-10-14 with `grep -lw tier runtime interface/js`. The auto rule (D22):
  1. The candidates are the pairs where the skill is `reliable`, a key is found and a price is known.
  2. Pick the lowest expected cost per run: the mean usage of that model's with-skill runs times its list price (D5).
  3. A tie goes to the higher pessimistic score.
  4. No candidate: the project's default model, `supervised`, with the reason shown.
  5. A model the person names without `reliable` evidence runs `supervised`, marked unproven (D8).
  There is no extra minimum score and no per-project setting; a critical project selects a model by hand.
- **Where the choice is stored.** A column on the request and the task in the store, which is a schema change (`SCHEMA_VERSION`, `providers/store/sqlite.py`, line 53), and a project default model in `runtime.json`. The router's run uses the project default.
- **Prices.** One table with source and access date replaces `adapters/api/prices.json` and the project's `model_prices`. OpenRouter prices are adopted from its models API (principle 14); the repository already records that URL as the source of three entries, accessed 2026-09-30.
- **Interface.** A model picker per request and per agent, with a default per project. The per-model table on the proof page (the Control room's skills tab shows two tier columns today, `interface/js/views/control-skills.js`, lines 13 to 23). `auto` shows the date beside the price.
- **Documents.** `AGENTS.md` principle 9 (line 15), the band rules of the same file, `docs/architecture/reliability-model-2026-10-02.md`, `evals/README.md` (line 119) and the "Adding a skill" step 5 (a new skill is done when its first full test has passed on the two lab models, D6) are rewritten without the tiers. Principle 12's trigger ("the next change of reference model", `AGENTS.md`, line 18) and backlog T23 (`docs/backlog.md`, lines 83 to 88) get a new trigger: a change of the lab default list or of the grader. The inventory's band table, which is on the reference model, becomes per model (`docs/inventory.md`, line 214, and the model table beside it). Backlog R15 (`docs/backlog.md`, line 195) is replaced by the picker.

**Done when.**

- A test shows `auto` picking the cheaper `reliable` pair, breaking a tie by the pessimistic score, and falling back to the project default, `supervised`, when none qualifies.
- A test shows a named model without evidence running `supervised` and marked unproven.
- `grep -lw tier` over the source files of `runtime/` and `interface/js` finds none, except the reader of the old evidence shape in `evals/`.
- `python3 evals/eval_status.py status` gives the same bands and gates on the existing evidence as before, compared as text.
- No sentence of `AGENTS.md` or of the reliability-model document says one model decides a skill's standing.

**Size.** M.

**Measurement impact.** None. `runtime/`, `interface/`, the documents and `evals/eval_status.py` are not in the fingerprint.

**Depends on.** P2 (the per-model gate and the usage field) and P1 (the `web_measured` fix touches the same files).

**Resolves.** F5 (E3). Carries out D1, D3, D4, D5, D6, D8 and D22; the stored choice answers the assumption of the architecture document about the store's schema.

### P4. Sources I (L)

**Goal.** A person gives a project a source (an uploaded file or a Notion page), and a task receives clean text of the versions the planner chose for it.

**Reuses.**

- `runtime/drop.py` (the destination and the per-task folder; the web-task note, lines 25 to 29; `hand_over`, line 76) and `runtime/workcopy.py` (limit L2, lines 14 to 17; the walk of tracked files and `docs/`, lines 257 to 266; the scan, lines 228 to 232);
- the ported intake and `ENV_KEEP` of P0, and the container helper of P0;
- the documents provider's `read` verb (`providers/documents/notion.py`, line 589);
- `providers/resolve.py`, which finds a class by its folder (`converter:document` resolves to `providers/converter/`);
- `runtime/project_config.py` (the accepted configuration, lines 98 and 232) for the data folder's key;
- `runtime/plan.py` `plan_hash` (line 316), which hashes the plan's tasks as JSON, so a field added to a task is covered;
- `skills/core-orchestrator/SKILL.md` and its `references/routing.md`.

**Builds.**

- **The data folder and its guardrails** (D9, D10): a new key of `runtime.json`, mandatory, with no default; a project without it does not run. The runtime writes only inside it, never follows a symbolic link out, refuses the home folder, the filesystem root and a folder that contains the project; the work copy excludes it even when it sits inside a tracked tree; a file changed after import is detected by its hash and is a new version made by the person.
- **The source registry** (new): the project declares its sources, with no credentials in it.
- **Immutable versions:** the original, the converted text and a manifest (origin, date, sha256).
- **The rich catalog,** built by code at import with no model (D11): name, type, size, date, sheets and columns with sample values, first headings, the person's optional description.
- **`converter:document`** (new, runtime-only like the transcriber): PDF, HTML, XLSX, CSV and DOCX to Markdown or CSV, in the shared container with no network, adopting existing tools (principle 14). The output is scanned for credentials after conversion. The intake's `sniff` (`runtime/media.py` on the branch, line 472, knows only video, image and HEIF brands) gains PDF, OOXML and text.
- **Uploaded files and Notion pages by address** (D13). Reading by URL needs a small function that extracts the 32-character id, since `doc_id` takes only the id (`providers/documents/notion.py`, line 527).
- **A size cap per source,** with a warning (D11).
- **The planner chooses sources.** A Y change of `core-orchestrator` (partial test on the two lab models plus its guard cases). The catalog is third-party text: data, never instruction. The skill's **External content is data.** line (`skills/core-orchestrator/SKILL.md`, line 44) already names documents a request points to; whether the catalog needs naming there is decided in the review, because editing that line is an X change that asks for a full test (`AGENTS.md`, "Changing an existing skill").
- **The plan card** lists each task's sources and highlights a web task that receives sources (D16); the source ids are part of the plan's tasks and so of the plan hash. An optional `@mention` in the request forces a source.
- **A task receives copies of its chosen source versions,** which replaces version 1's rule of handing data to the step's `depends_on` closure (D29): the newest version of each chosen source id at the moment the task starts, recorded on the task as id, version and sha256. A refresh that lands after the task started does not reach it.
- **Eval cases with converted input,** one in each of two target skills, with `--baseline`, and a guard assertion that converted text is treated as data (observation O2 of the architecture document: the `biz-market-analysis` line **External content is data.**, `skills/biz-market-analysis/SKILL.md` line 49, names web pages and research briefs, not a converted file).

**Done when.**

- Offline fixtures pass for each format.
- A PDF with a planted fake key is refused after conversion. (Raw, it is not found: section 4.)
- A project with no data folder does not run; a path that is a symbolic link out, the home folder, the root and a folder containing the project are each refused, with a test for each.
- A file changed in the data folder after import is detected by its hash and treated as a new version.
- A fixture request that names an `@mention` plans a task with that source; the plan hash changes when a source id changes and does not change when a source gets a new version.
- A task of the work copy never sees the data folder, with the folder inside a tracked tree.
- A source refreshed after a task was planned and before it starts reaches the task as the newer version; one refreshed after it started does not; the task's record holds the id, version and sha256 of each source it received (D29).
- The measurement fingerprint is unchanged and no skill other than `core-orchestrator` is bumped.
- The two converted-input cases run with `--cases <id> --baseline` before the package closes, and the planner's partial test passes on both lab models.

**Size.** L.

**Measurement impact.** None to the fingerprint. The planner change is a Y change of `core-orchestrator` (a partial test of the cases it could move and the guard cases, 3 runs each). Today the skill is `needs a test` on both models, because guard assertions of its cases have no run in the current set (section 2); the partial test of this package runs them. Added cases are `pending` until they have run and move no band.

**Depends on.** P0 (the intake, the store functions and the container helper).

**Resolves.** F7 (E5) and F8 (G3), replacing the drop-closure rule; the manual half of F10 (R1); observation O1 (an ingest step reads an address or a path from its arguments, hashed in the plan) and O2. Carries out D9, D10, D11, D13 (uploaded files and Notion), D16 (the plan card) and D29.

### P5. Step engine (M)

**Goal.** One engine runs the steps of an ingestion and, later, of a media pipeline, resumably, with stops.

**Reuses.** `runtime/pipeline.py` on `feature/short-video` (`run`, line 747; `STOPS`, line 75; `prepare_again`, line 808; the failure records); `runtime/ops_runs.py` (a task run is its own process, `run-task --project <dir> --task <id>`, line 14; `dispatch`, line 581); `stop-runs` (`runtime/cli.py`, line 48); `runtime/dispatcher.py` (`NO_AGENT`, line 70); `runtime/plan.py` `combine` (line 575, which calls `agent_of` for every task at line 595).

**Builds.**

- `runtime/steps.py` (new), extracted from `runtime/pipeline.py` and parameterised by a registry of kinds. A kind declares its order, its stops and its executors. The engine no longer imports `captions`, `media` or `theme`.
- Step tasks `planned` and `ready` under `depends_on`, like skill tasks.
- An owner rule in the planner and the dispatcher, or a runtime pseudo-agent with its own cap, so that a step task is not held with "no enabled agent owns the task" (`runtime/dispatcher.py`, line 70) and does not fail planning (`runtime/plan.py`, `agent_of`, lines 163 and 595).
- `ops_runs.dispatch` starts `cli.py run-step` as a child process, as it starts `run-task`, with lock-file liveness; `stop-runs` covers it.
- The kinds `ingest` and the file-output kinds of P8 are registered. Its second consumer is ingest, so it does not wait for the short-video rebase.

**Done when.**

- The ingest kind runs on the engine with its tests, and the engine imports no module of the video features.
- A step task becomes `ready` only when the tasks it depends on are `done`.
- A killed child is detected by its lock and the task is `failed`, not `running`.
- `stop-runs` ends a running step.
- A plan with a step task passes `plan.combine`.

**Size.** M.

**Measurement impact.** None.

**Depends on.** P0, P1 and P4 (the second consumer exists).

**Resolves.** Part of F9 (G4): the owner rule in the planner and the dispatcher.

### P6. Flows with steps and parameters, and routines (M + M)

**Goal.** A workflow can mix steps and skills, take parameters from the request, and a schedule can start a flow or a step unattended under D24.

**Reuses.** `runtime/flow_files.py` (the schema; `TASK_KEYS`, line 47); `runtime/plan.py` `plan_hash` (line 316); `runtime/handlers/published_posts.py` as the pattern (`due`, line 206; `tick`, line 392); `_ticks` (`runtime/ops.py`, line 2444); the scheduler providers; the store; the channel policy (`runtime/operations.py`, `GROUPS`, line 259, `DEFAULT_POLICY`, line 281, `BRAKES`, line 287; `runtime/project_config.py`, `_channels`, line 182).

**Builds.**

- **The flow schema.** `{"key", "step": "<kind>", "args", "depends_on"}` beside the skill tasks. Flow parameters are bound from the request and covered by the plan hash. Project flows live in the project, besides the workbench's; making the router choose among them would be a further Y change of `core-orchestrator`, which this package does not do: the person names a project flow on the page or in the terminal.
- **Routines.** A handler, `runtime/handlers/routines.py` (new), reads routine records from the store (D23): created and changed from the terminal or the page, approved by the sha256 of their exact content (schedule, target, arguments); no mode, cap, policy or standing approval of their own; each fire counts against the agent's daily caps. Targets are a flow or a step; a free-text request is never unattended (D24 rule 2).
- **The plan of a routine** is generated at creation and approved by hash with the record; at each fire it is regenerated and tasks are created only if the hash is identical, else the routine stops and asks (D24 rule 1).
- **Tasks proceed without review** only on `reliable` pairs with the agent in `autonomous` mode; otherwise the routine waits at the first review and messaging notifies (D24 rule 3).
- **Routine tasks that receive sources run without the web** (D16), and the planner splits work that needs both. For a hand-written flow the flow check (`runtime/flow_files.py`) refuses, at routine creation and again at the plan of each fire, a task that requires the web and receives sources; its message tells the person to split the flow into a web task without sources and a task with sources and no web (D27). No routine runs a web-requiring skill without the web.
- **Messaging.** The routine verbs are new rows of `runtime/operations.py` in a group of their own; by default only the brakes (list, pause, cancel) reach messaging, and the person may grant creating and changing through `channels.messaging`. MCP lists routines and cannot create or change them. Attachments, model choice and flow choice over messaging are not part of P6 (D28, section 9).

**Done when.**

- A flow "ingest, then `biz-market-analysis`" passes the flow check and its plan test as a manual request, with a parameter bound from the request and the plan card highlighting the web task that receives sources; the same flow as a routine target is refused, at creation and at a fire, with the message of D27 (a test for each).
- A routine fires a flow on schedule in a test with a fake clock; with a regenerated plan of the same hash it creates tasks, with a different hash it stops and asks.
- A free-text routine target is refused as unattended; each fire becomes a plan to approve.
- A routine created through MCP, or through messaging under the default policy, is refused.
- On an unproven pair, a routine waits at its first review.

**Size.** M for the flow schema and parameters, M for routines.

**Measurement impact.** None.

**Depends on.** P5.

**Resolves.** F4 (E2), F12 (R2), the rest of F9 (G4) (flow parameters; the owner rule is P5's). Carries out D23, D24, D27 and the routine half of D16, and uses D12 (a refresh is a routine target).

### P7. Sources II: Google Drive (L)

**Goal.** A person picks a Drive folder or file, and it becomes a source like any other.

**Reuses.** `providers/mailbox/README.md` and `providers/mailbox/auth.py` (the Desktop OAuth client, the app "In production", the refresh token in the OS secret store, lines 17, 18 and 26 of the README); `providers/secrets/resolver.py`; the source registry, versions and converter of P4; the loopback pattern of the existing authorisation script.

**Builds.**

- **First step, in parallel with earlier packages: a spike** that answers "does picking a folder under `drive.file` give access to the files inside it?" If not, multi-select of files, and a new question to the maintainer about `drive.readonly` for folder sources.
- A Drive provider (new) with OAuth like Gmail and the scope `drive.file` with the Picker (D14); folders and single files; export of native Google files by the Drive API and conversion; download and conversion of other files.
- Change detection for refresh (D12): each refresh is a new version, and a task records which version it read.
- The Picker's desktop flow through the local page and a callback URL (to verify, section 7).

**Done when.**

- The spike's answer is written in this document's "To verify" list as confirmed or refuted, with the date and how it was checked.
- With a recorded or fake Drive, a folder and a file source import, convert, version and refresh; a refresh with no change creates no version.
- The provider holds no scope beyond `drive.file`, and a credential never enters a run (a test on the environment passed to the provider).

**Size.** L.

**Measurement impact.** None.

**Depends on.** P4. The spike depends on nothing.

**Resolves.** Carries out D13 (Drive), D14 and D12 for Drive.

### P8. Outputs (M)

**Goal.** A task's result can leave as a file, or as a write to Drive or Notion, under the gates of principle 11.

**Reuses.** The step engine of P5; the container helper of P0; `runtime/documents.py` (`push`, line 533, which mirrors manifest documents only); `providers/documents/notion.py` (the `write` verb, `VERBS`, line 707); the Drive provider of P7; the effect gate (`runtime/autonomy.py`, `covers`, line 358; `runtime/ops.py`, line 1456); the exact-content approval of `runtime/ops_video.py` `video_approve` (line 184, on `feature/short-video`) as the pattern. HTML to PDF may reuse the short-video renderer's headless browser in a container (`providers/renderer/_docker.py`, on `feature/short-video`).

**Builds.**

- **The file-output step kinds** (D17 direction 1): PDF, XLSX, DOCX and CSV generated by a code step with no model, using adopted tools, written into the data folder or `docs/` as a new version.
- **Write-back to Drive and Notion as an external effect** (D17 direction 2): preview of the exact content, one approval, execution, record; before the write, a check that the target was not edited since it was read (its version or hash against the version the task read). A target changed since stops and asks.
- The real case for each direction is chosen during development.

**Done when.**

- Each output kind produces a file from a fixture, offline.
- A write-back without the approval of its exact content is refused by structure (a test); one with it runs once and records.
- A target edited since it was read stops the write and asks (a test with a changed fixture).

**Size.** M.

**Measurement impact.** None.

**Depends on.** P5 (the engine); write-back to Drive also needs P7.

**Resolves.** F14 (G6). Carries out D17.

### P9. Project script (M)

**Goal.** A project can run its own code as a step of a flow or a routine, under limits that satisfy principle 11.

**Reuses.** The step engine and its registry of kinds (P5); the container helper of P0 and the shared sandboxed container; the data folder and versions of P4; the plan hash.

**Builds.** The "project script" step kind (D25): approved by the sha256 of its exact content (a changed file stops and asks); runs in the shared sandboxed container without credentials and with a read-only root; the network is off by default, and declared destinations enter the approved hash; writes only into the data folder, as a new versioned source; no direct effects (an effect goes through the effect gate); Python and shell first, dependencies declared and pinned.

**Done when.**

- A script runs from a fixture and its output appears as a new source version.
- A changed script file stops the step and asks.
- A script cannot read an environment credential, cannot write outside the data folder, and reaches no network unless the destination is declared and in the approved hash (a test for each).

**Size.** M.

**Measurement impact.** None.

**Depends on.** P5.

**Resolves.** F11 (G5). Carries out D25.

### P10. Community evidence (L)

**Goal.** A contributor's lab tests of any model count for everyone's `auto`, without the maintainer running them, and the maintainer's own score tests move to the same attested CI.

**Reuses.** The per-model gate, local evidence and published image of P2; `evals/eval_status.py` (`FIELD_CAP`, line 1729, the per-contributor cap pattern; the evidence validators); `.github/workflows/checks.yml`; the "first attested battery on GitHub" already listed as waiting in `docs/backlog.md`, line 84.

**Builds.** D19: an official reusable workflow, referenced by commit, that checks out the official code at that commit, runs the lab test with the contributor's keys in their fork's CI and has GitHub attest the evidence file; a check in the workbench's CI that verifies with no model call (the signature, `--signer-workflow`, the commit in the history of `main`, the digest) and records the evidence as "community verified" in its own column per model, with a per-contributor cap; a rule that every completed run of the fork's workflow is submitted and that gaps in run numbers are flagged; field evidence demotes a pair after three `failed` verdicts. Later: the maintainer's lab runs move to the same attested CI.

**Done when.**

- A fixture evidence file with a valid attestation is accepted and shown in the community column; a file with a wrong signer workflow, a commit not in `main` or a digest mismatch is rejected (a test for each, offline).
- A set of runs with a gap in the run numbers is flagged.
- The per-contributor cap holds.
- `python3 scripts/validate.py` passes.

**Size.** L.

**Measurement impact.** None for the verification. Running the maintainer's tests in a CI on another platform later is an execution-side change for the skills it reaches (D20 accepts both platforms; the maintainer decides when to move).

**Depends on.** P2.

**Resolves.** The community half of F2 (G1). Carries out D19 (supersedes D7) and the later evolution of D19.

### Side package. The short-video rebase (L)

**Goal.** Put the video features on the extracted kernel, off the critical path.

**Reuses.** Everything P0 and P5 extracted; the branch `origin/feature/short-video`.

**Builds.** The pipeline, the renderer and transcriber providers, `runtime/media.py` and `runtime/video.py` rebased onto the step engine (`runtime/steps.py`), the store functions with the new names and the container helper. The approve-video bug of section 5 is fixed here, with a test that approves and asserts the task is `done`.

**Done when.** The short-video pipeline runs on the engine with its existing tests; the bug test passes; the 44-file conflict of section 5 is gone because the branch is rebased on the kernel.

**Size.** L.

**Measurement impact.** None.

**Depends on.** P0 and P5.

**Resolves.** The bug of section 5. Nothing else.

### Order and funding

D26 fixes the order. The packages are P0 to P10 and the side package.

| Package | Starts after |
|---|---|
| P0, P1, P2 | Nothing; together (P2 touches `evals/`, P0 and P1 touch the runtime and the store; P1 after P0 where they share the store) |
| P3 | P2 and P1 |
| P4 | P0 |
| P5 | P0, P1 and P4 |
| P6 | P5 |
| P7 | P4 (the spike: any time) |
| P8 | P5 (write-back to Drive also P7) |
| P9 | P5 |
| P10 | P2 |
| Side package | P0 and P5 |

If only three can be funded first: **P0 and P1 as one, P2, and P4.** They give correctness, one model-independent measurement, and the data pillar. P3 follows P2 and P1, since it is the choice of model that the maintainer asked for.

**Parallel work (principle 7).** The packages that can run at the same time, by the files they own:

| Pair | Files in common | Verdict |
|---|---|---|
| P0, P1 and P2 | P2 edits `evals/` and, for the published-digest check, `runtime/proof.py` (`checks`) and `runtime/lab.py`; P1 edits the store, `runtime/ops_runs.py` and, for `web_measured`, `runtime/proof.py` (`row`) and `runtime/lab.py` (`standing`) | In parallel; P1 after P0 where they share the store; P1 and P2 touch different functions of `proof.py` and `lab.py`, so the second to merge rebases |
| P3 and P4 | The store schema (`SCHEMA_VERSION`, line 53, a migration each), `runtime/ops.py`, `runtime/project_config.py` (a key each) | In parallel only if one of them owns the schema step; otherwise serial |
| P4 and P7 | P7 uses P4's registry and converter | P7 after P4; its spike any time |
| P5 and P3 | `runtime/dispatcher.py`, `runtime/ops_runs.py` are read by both | In parallel; P5 does not touch `proof.py` |
| P8 and P9 | Both register kinds in P5's registry | In parallel; each adds its own kinds |
| P10 and anything but P2 | `.github/` and the evidence validators | In parallel after P2 |

## 7. Open questions closed, and what is still to verify

OPEN-1 to OPEN-6 of version 1 are closed. Each is a decision of section 3.

| Question of version 1 | Closed by | What was decided |
|---|---|---|
| OPEN-1. Where ingested data lives | D9, D10, D11 | A mandatory data folder per project, outside the workbench's git; immutable versions; the planner chooses the sources a task sees. (Version 1 recommended the task's drop.) |
| OPEN-2. The first source and the real case | D13, D14 | Uploaded files and Notion, then Google Drive in general with `drive.file` and the Picker; OneDrive and Jira wait for a real project |
| OPEN-3. Live tools inside runs | D15 | No; MCP only on the host, as provider implementations with read verbs |
| OPEN-4. Routine records | D23, D24 | Records in the store, approved by hash; the unattended rules of D24 |
| OPEN-5. The auto mode's minimum score | D22 | The cheapest `reliable` pair; no extra minimum and no per-project setting. (Version 1 recommended the gate threshold, adjustable.) |
| OPEN-6. The order after package 4 | D26 | The order of section 6 |

**Nothing from OPEN-1 to OPEN-6 remains open.** What is open is the list below and the real cases to choose during development (D17: one for file outputs, one for write-back).

### To verify

Third-party facts that were not confirmed. None is stated as fact anywhere in this document; each decision that rests on one says so.

1. Whether picking a folder under `drive.file` grants access to the files inside it (P7's spike).
2. Whether the Drive API exports Google Docs directly to Markdown, and the export size limit (recalled as 10 MB).
3. Whether GitHub offers free arm64 hosted runners to public repositories.
4. Whether the identity signed for a reusable workflow called from a fork is the official repository's workflow, so that `--signer-workflow` pins it.
5. Whether artifact attestations require a public repository (the workbench is public, so it does not block).
6. Whether the subscription OAuth token of the reference model works in CI, for the later move of the maintainer's tests.
7. The size of the published eval image (estimated 1 to 2 GB, not measured).
8. Whether the Picker's desktop flow works with the loopback page.

## 8. Risks and how to see them early

| Risk | How to see it early |
|---|---|
| Skills do worse on large converted documents. The proof covers inputs in the form of the cases. | The converted-input cases of P4 run with `--baseline`; field evidence from the first real use; a size cap per source. |
| A measurement change is classified wrongly, and the battery is paid for. A grader-side change raises the floor and asks every skill for a full test. | P2's review checks that the upstream request of the two measured models is unchanged and that the epoch names only models with no evidence. |
| Most work of one floor stays serial, because a placeholder in a skill's declared path counts as an overlap. | Backlog R17 (`docs/backlog.md`, line 214) says this and keeps the conservative rule. Count held tasks with the held reason `artifact in use` (`IN_USE`, `runtime/parallel.py`, line 40) in the first real runs. |
| The renderer image has been built on one machine only. | On `feature/short-video`, `docs/architecture/platform/short-video.md` says the amd64 renderer image "has not been built or run" (line 390) and that the amd64 browser archive has no pinned sha256 (lines 437 and 466). P0 does not depend on the images; the video features and HTML to PDF through the renderer (P8) do. |
| A model that runs on the person's machine (`ollama/...`) cannot be reached from the eval container. | The archived backlog records that the container's network reaches only the hosted providers (`docs/backlog-archive.md`, line 163). `ollama/<name>` is parsed by the adapter (`adapters/agents-dir/run-prompt.sh`, line 99), but a lab run on it is not supported until a route is built. Leave it out of P2 and P3's "done when". |
| `auto` ranks by a price that changed. | The price table carries an access date; `auto` shows the date beside the price, and a price older than a limit the project sets is shown as stale. |
| A model the person names without evidence produces a poor result and nothing marks it. | D8: it runs `supervised`, and the run and the card say "unproven". |
| The Picker's folder access is unknown: `drive.file` may not reach the files inside a picked folder. | P7's spike, first, in parallel with the earlier packages; if refuted, multi-select of files and a new question to the maintainer. |
| The published image is a dependency on a registry: availability, cost, size (not measured) and the pin. | The lock file records digests per platform; the runtime pulls on first use and says so; a person with no network keeps working on a local image, whose evidence is local-only (D21). Measure the size in P2. |
| Community cherry-picking and provider honesty remain after the mitigations of D19. | Every completed run must be submitted and gaps in run numbers are flagged; the pessimistic score and the per-contributor cap; field evidence demotes a pair after three `failed` verdicts. Provider honesty is not checkable and is published as such (principle 10). |
| Dependence on GitHub: the attestation, the reusable workflow, the runners (free arm64 runners are unconfirmed). | The verification in the workbench's CI is offline apart from the signature check; the maintainer's own tests keep running on his machine until the move is confirmed (items 3 to 6 of "To verify"). |
| The planner misses a source a task needs, or a catalog's text carries an instruction. | The plan shows the chosen sources and the person approves it; the planner asks when in doubt; the `@mention` forces a source; the catalog is data (D11) and a guard assertion measures that. Option B is considered only after evidence that the planner misses files. |

## 9. Not in this plan

- An Instagram or TikTok publisher.
- Indexing or RAG. It waits for a real case (D11).
- Agent memory (listed in backlog R2, unticked).
- A persona per agent.
- OneDrive and Jira. They wait for a real project that needs them (D13). The platform plan of 2026-10-05 already parks Jira (`docs/architecture/platform-plan-2026-10-05.md`, section 8, line 366).
- Attachments, model choice and flow choice over messaging (D28). Messaging carries none of them today (`runtime/messaging_inbound.py`, header, lines 7 to 19); until the later evolution of the messaging channel, a file, a model or a flow is chosen on the page or in the terminal. The trigger is the completion of P6, after which the maintainer decides when to open the work.
- Option B of D11 (the whole data folder read on demand by non-web tasks), as a future per-project opt-in, off by default, only after evidence that the planner misses files and with eval cases that measure folder exploration.
- MCP inside runs (D15).

## 10. Assumptions and what was not verified

**Assumptions.**

- Assumption: poppler (`pdftotext`), pandoc and an XLSX reader convert the formats named in P4 (pandoc also reads DOCX). No converter was run in this check.
- Assumption: the size labels S, M and L are the author's judgments from the size of the files named, not measurements.
- Assumption: the battery's run archive, which the 2026-10-05 plan says is kept outside the repository (`docs/architecture/platform-plan-2026-10-05.md`, line 23), holds each run's raw output with `modelUsage` (`docs/backlog.md`, line 84). It was not opened. If it does not, usage for existing evidence comes from new runs.
- Assumption: a Notion page that is not a mirrored document can be read with the existing credential if the integration is shared with it. The provider calls the Notion API for any page id (`providers/documents/notion.py`, `retrieve`, line 535), but no live call was made.
- Assumption: OpenRouter's models API lists a price per model. The repository records the URL `https://openrouter.ai/api/v1/models` as the source of three entries in `adapters/api/prices.json`; the API was not called in this check.
- Assumption: the epoch of the measurement change in P2 can name only models with no evidence. `--models` accepts a model the gate file lists (`evals/eval_status.py`, line 685); no command was run to commit such a change.
- Assumption: a step task's declared footprint (P1) can be stored with the task without a schema change if the task row has a field that holds structured text; if it has none, it is part of the schema migration of P3 or P4. The row was not inspected for this.
- Assumption: the file names given here to new elements (`runtime/steps.py`, `runtime/handlers/routines.py`, `providers/converter/`) are this plan's; the names of the source registry, the data folder's key in `runtime.json` and the Drive provider's folder are not fixed here and are P4's and P7's to fix.
- Assumption: the routine verbs and the group that holds them (P6) are new rows of `runtime/operations.py`. The existing messaging default is `read`, `talk`, `answer` (`runtime/operations.py`, `DEFAULT_POLICY`, line 281) and the brakes are `cancel` and `set-mode` (`BRAKES`, line 287); the routine brakes (list, pause, cancel) are new and are not those.
- Assumption: a routine's schedule is a weekday and a time of day in the project's time zone; no format is fixed here.

**Not verified.**

- The third-party facts of the "To verify" list in section 7.
- The approve-video bug (section 5) was read in the code and not run.
- A trial merge was run only between the commits named in section 5, and re-run for this version with the same counts: 44 files for `d3e60770` with `6794905e`, seven for `39600a0b` with `6794905e`.
- The per-model band counts of section 2 were computed again on 2026-10-14 at `d3e60770` on this branch. They differ from version 1 (reference model `reliable` on 45 of 48, not 48; floor model `reliable` on 41, not 43), because the release #393 carried changes to skills (`core-orchestrator`, `mkt-social-copy`, `mkt-vote-round`) that version 1's check did not include. The cause of each skill's band is the one printed by `python3 evals/eval_status.py status`.
- The line numbers on `feature/short-video` are at `6794905e`; `origin/feature/parallel-agents` has moved to `d9d3f069` and is no longer used for line numbers, since its work is on `main`.
- Whether P2 can publish and pull the eval image on both platforms, and its size, were not tested.
