# Delegation platform plan: data in, one execution model, a score per model

Version 1, of 2026-10-14. Checked on `main` at `9bc9b863`, `origin/feature/parallel-agents` at `39600a0b` and `origin/feature/short-video` at `6794905e`. A proposal: nothing in it is built. It comes from an analysis of the three branches and a two-round debate with an independent reviewer agent on another model, whose claims were checked against the code.

After the check, `origin/main` moved to `d3e60770` (the release merge #393 of 2026-10-14, which carries the `feature/parallel-agents` work), and `origin/feature/parallel-agents` moved to `d9d3f069`. Section 5 says what that changes. Every `file:line` below is read at the commit its heading or its text names; a line number on `feature/*` is at the commit in this status line. The document was committed on a branch cut from `origin/main` at `d3e60770`; the main-side line numbers were read at `9bc9b863` and were not re-numbered.

How to read it: a path with a line number was opened and read for this plan. A claim with no line number was found by a search or comes from a command, and the text says which. What could not be verified is in section 10.

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

The rest of this plan answers three questions: what exists for each pillar and mode, which order of work reaches the target at the least risk, and which decisions are still the maintainer's.

## 2. Where we are

State is one of `exists`, `partial`, `missing`. The evidence column is a path, and a line number where one was read. Paths on `main` are at `9bc9b863`.

### Pillar 1: data sources and persistence

| Capability | State | Evidence |
|---|---|---|
| One SQLite store per project | exists | `providers/store/sqlite.py` |
| Documents mirrored outward to Notion | exists | `runtime/documents.py` (`push`, line 440) |
| The person's edits pulled back from Notion | exists | `runtime/documents.py` `pull`, line 410 |
| A Notion page read by id | exists | `providers/documents/notion.py` `cmd_read`, line 584, verb `read` in `VERBS`, line 699; the contract row is `providers/CONTRACT.md`, line 116 |
| A Notion page read by URL | missing | `doc_id`, `providers/documents/notion.py`, line 522, accepts only the 32-character page id |
| Gmail read, GitHub, LinkedIn, a Notion issue tracker | exists | `providers/mailbox/gmail.py`, `providers/vcs/github.py`, `providers/publisher/linkedin.py`, `providers/issue-tracker/notion.py` |
| Jira | missing | The word is only in `contracts/environment.md`, line 10, as an example of the `integration:issue-tracker` class; no provider and no runtime code names it |
| Google Docs and Drive | missing | No provider folder |
| PDF, XLSX, CSV, HTML parsing | missing | The only PDF reader is `skills/brand-profile/scripts/profile_export.py` (lines 185 to 191, `pypdf`), for one LinkedIn export |
| Taking a file in | partial | The file drop copies the raw file, 25 MB at most (`runtime/drop.py`, `MAX_BYTES`, line 49; `hand_over`, line 76) |
| Indexing, RAG | missing | Nothing in `runtime/` or `providers/` |

The Notion read is mostly built. The provider reads a page by id and prints its Markdown, its version and its open comments. What is missing is the entry point that starts a read as a data source, and the step that places the result where a task can see it.

### Pillar 2: the brain

| Capability | State | Evidence |
|---|---|---|
| Router, then a plan approved by hash, then one skill per task, run in the eval container | exists | `runtime/router.py`; `runtime/plan.py` (`plan_hash`, line 315); `runtime/ops.py` (`approve`, line 2021); `runtime/lab.py` |
| Model choice | partial | Two fixed tiers: `runtime/proof.py` (`TIERS`, line 41; `route`, line 118; the refusal "only the reference model can be asked for", line 133) and `evals/eval-gate.json` (`strong_model`, line 2; `floor_model`, line 4) |
| A band, a gate and a score for every model that has evidence | exists | `evals/eval_status.py` (`as_reference`, line 1095; `skill_band`, line 1965; the per-model loop, line 2074). Computed on 2026-10-14 with `python3 evals/eval_status.py status`: 48 skills; the reference model is `reliable` on 48; the floor model is `reliable` on 43, in `watch` on 2 and in `needs a test` on 3 |
| A baseline on a second model | exists | `evals/eval_run.py`, option `--baseline-on <model>` (line 36). Counted in the committed `lab-*.jsonl` files on 2026-10-14: 192 baseline run lines on the reference model and 181 on the floor model |
| Flows | partial | JSON files of skill tasks in `flows/` (five), loaded from the workbench checkout only: `runtime/flow_files.py` `ROOT` (line 44), called with `core.ROOT` at `runtime/ops.py`, lines 393, 1540 and 1616. A task with `"writer": "user"` is reserved and not read (`runtime/flow_files.py`, line 23; `TASK_KEYS`, line 48, has no `writer`) |
| Tasks in parallel | exists on `feature/parallel-agents` | `runtime/parallel.py` `admit` (line 87); slots per agent up to `MAX_PARALLEL_CEILING = 4` (`runtime/autonomy.py`, line 77); per project `max_running`, default 3 (`runtime/project_config.py`, lines 166 to 172) |
| A task with no skill | exists on `feature/short-video` | `providers/store/sqlite.py` `is_code_task` (line 1487), `code_task_add` (line 1498), `code_task_move` (line 1528) |
| A resumable step engine | exists on `feature/short-video`, for one pipeline | `runtime/pipeline.py`: `ORDER` (line 71), `STOPS` (line 75), `run` (line 747), `prepare_again` (line 808) |
| Agent memory | missing | `docs/backlog.md` R2 lists it and says it is not built (line 149 on `feature/parallel-agents`) |

### Pillar 3: tools

| Capability | State | Evidence |
|---|---|---|
| Schedulers | exists | `providers/scheduler/launchd.py`, `providers/scheduler/systemd.py` |
| MCP as a server | exists | `runtime/mcp.py`: the operations layer served as tools |
| MCP as a client, inside a run | missing, on purpose | The run script of the reference model's adapter (the `strong_harness` of the gate file) passes `--strict-mcp-config` at line 99 and says at line 18 that no MCP server or connector is loaded |
| Five messenger providers and a channel policy | exists on `feature/parallel-agents` | `providers/messenger/` holds `telegram.py`, `discord.py`, `whatsapp.py`, `whatsapp-cloud.py`, `whatsapp-twilio.py`; the page is `docs/architecture/platform/messaging.md` there |
| Prices of models | partial | `adapters/api/prices.json` (six models, with source and access date) and the project's `model_prices` (`runtime/project_config.py`, lines 53 and 158; `runtime/costs.py`, line 7) |

### Run modes

| Mode | State | Evidence |
|---|---|---|
| (a) A simple agent | works for the example | `biz-market-analysis` and `core-research` have web cases (`evals/eval-gate.json`, `web_cases`, line 24), and `biz-market-analysis` is `reliable` on both models (`docs/inventory.md`, lines 222, 276 and 277) |
| (b) A workflow | partial | Flows of skill tasks exist; a step that is plain code does not fit a flow (`runtime/flow_files.py`, `TASK_KEYS`, line 48) |
| (c) A routine | missing as a concept | The pieces exist: the scheduler providers; the dispatcher's jobs `poll` and `work` (`runtime/dispatcher.py`, `JOBS`, line 133); handlers ticked each round (`runtime/ops.py`, `_ticks`, line 2448); `runtime/handlers/published_posts.py` with `due` (line 206) and `tick` (line 392) |

## 3. Decisions taken by the maintainer on 2026-10-14

1. **The reference and floor tiers leave. A skill has a status per model.** Approved on one model says nothing of another. Every pair of skill, model and adapter has its own band, gate and score. Consequence: principle 9 of `AGENTS.md` is rewritten without the tiers, and the code that reads `TIERS` changes (section 6, package 4).
2. **Anyone may test a skill on any model.** The maintainer's own lab runs stay on `claude-sonnet-5-5` and `openrouter/deepseek/deepseek-v4.1-flash`. The grader stays fixed (`grader` in `evals/eval-gate.json`, line 8), so scores compare across models.
3. **The person chooses the model for a run.** An `auto` mode chooses by the skill's score on each model against its cost.
4. **The baseline (runs without the skill) is kept per model,** to measure the difference the skill makes on that model. Consequence: the second-model baseline option already exists (`--baseline-on`), so this costs runs only for a model that has none.
5. **Auto ranks by the providers' list prices:** measured tokens per run times the provider's price, not by subscription.
6. **A new skill enters the repository after a full test on the two lab models.** Its result is published whether it passed or not (principle 10). It runs unattended only where it is `reliable`.
7. **Community lab evidence is set aside for now.** Today lab evidence is trusted because the maintainer runs it (`evals/README.md`, "Who runs the lab tests", line 119); field evidence is counted per contributor (`evals/eval_status.py`, `FIELD_CAP`, line 1729). The topic is parked, not rejected. One idea not yet discussed is in section 9.
8. **Proof keeps deciding autonomy (principle 9) and no longer decides access.** A model the person picks without `reliable` evidence runs `supervised` and is marked unproven. The hold already exists: `runtime/autonomy.py` `review_action`, rule 5, "the skill is not proven: hold" (docstring line 316, code line 330).

## 4. Three paths and the one chosen

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

Rejected for this phase.

- Wiring MCP into a run touches fingerprinted files: everything in `evals/container/` and each eval adapter's `run-prompt.sh` and `eval.json` (`evals/eval_status.py`, `FINGERPRINT_FILES`, line 557, and the text at lines 200 to 204). That is an execution-side measurement change, which opens an epoch for every skill it reaches (`AGENTS.md`, "The measurement has a version, a fingerprint and a floor").
- A read tool can carry data out through its query arguments. That is a side effect the approval gate does not see by structure (principle 11).

### Chosen: B on A's spine

Data comes in first. It is built as the second kind of step task, and that second consumer is what justifies making the step engine generic (package 5). Routines reuse the handler tick. MCP servers may be adopted only on the host side, as provider implementations with read verbs, never inside a run.

### What the debate corrected

Each item was checked against the code.

- **Notion read already exists.** The first draft listed it as missing. `providers/documents/notion.py` has the `read` verb (line 584) and `runtime/documents.py` `pull` (line 410) uses the provider to bring the person's edits back. What is new is reading a page that is not a mirrored document, and reading by URL.
- **The handler tick is already a routine mechanism.** `runtime/ops.py` `_ticks` (line 2448) calls each enabled handler's `tick` every round. A routine does not need a second scheduler.
- **"Code task" means two things.**
  - On `feature/parallel-agents`, `ops.code_task(meta)` (`runtime/ops.py`, line 854) is true when a skill belongs to a code area (`workcopy.CODE_AREAS`). `runtime/parallel.py` `admit` (line 87) lets one such task of a request run at a time (the held reason `CODE_IN_REQUEST`).
  - On `feature/short-video`, `store.is_code_task` (`providers/store/sqlite.py`, line 1487) is true for a task with a parent and no skill. Both meanings are on that branch (`runtime/ops.py`, line 865, and the store function). A task with no skill has an empty footprint, so `admit` never serialises it against a skill task: `runtime/ops_runs.py` `skill_facts` returns an empty footprint and no code flag for a task with no skill (lines 74 to 87).
- **The step engine is not generic yet.** `runtime/pipeline.py` on `feature/short-video` imports `captions`, `media` and `theme` (lines 67 to 69), and its stops are a constant, `STOPS = ("review", "approval")` (line 75).
- **Nobody starts a task with no skill.** It is never `ready`: the store's `NEXT_READY_TASK` has `skill IS NOT NULL` (`providers/store/sqlite.py`, line 1086, on `feature/short-video`). A task with no enabled agent is held (`runtime/dispatcher.py`, `NO_AGENT`, line 65). The only code that moves one is `code_task_move`, called from `runtime/ops_pipeline.py`, line 138.
- **Scanning a raw PDF or XLSX does not find credentials.** The run copy scans with `data.decode("utf-8", errors="replace")` (`runtime/workcopy.py`, line 232). Compressed text inside a PDF or an XLSX is not visible to that scan. The drop does not scan a file that is not UTF-8 at all (`runtime/drop.py`, lines 102 to 108). The size limits do not match either: `SCAN_MAX` is 5 MB (`runtime/workcopy.py`, line 71) and the drop takes 25 MB, so a file between 5 and 25 MB is accepted by the drop and refused at the run's entry as "too large to scan" (line 230). Converting to text before a run closes both gaps.

## 5. Consolidating the branches

### What changed since the check

The first step of the plan, merging `feature/parallel-agents` into `main`, was done by the maintainer on 2026-10-14 as the release #393 (`d3e60770`). On that commit `runtime/autonomy.py` has `MAX_PARALLEL_CEILING = 4` at line 77 and `providers/messenger/` has the five providers (read with `git grep` and `git ls-tree` on `origin/main`). Local `main` is still at `9bc9b863`. So the first action is `git pull` on `main`; no merge is left to plan.

The check the plan was written against: `git merge-tree --write-tree 9bc9b863 39600a0b` reported no conflict (exit 0).

### What stays on `feature/short-video`

A trial merge of `feature/short-video` (`6794905e`) with `feature/parallel-agents` (`39600a0b`) reported conflicts in seven files: `.github/workflows/checks.yml`, `docs/architecture/platform/README.md`, `docs/architecture/platform/shells.md`, `providers/CONTRACT.md`, `runtime/service.py`, `scripts/tests/test_provider_resolve.py` and `scripts/tests/test_runtime_python39.py`. The same trial against `origin/main` (`d3e60770`) reported conflicts in 44 files (both read from `git merge-tree --write-tree --name-only`, run on 2026-10-14). That is the reason to extract, not to merge.

Keep only the generic pieces, extracted:

| Piece | Where it is on `feature/short-video` | Goes into |
|---|---|---|
| The task with no skill, renamed "step task" | `providers/store/sqlite.py`, lines 1486 to 1560 | Package 1 |
| The step engine | `runtime/pipeline.py` | Package 5 |
| The streaming intake and the content-addressed store | `runtime/media.py` `receive` (line 714), `sniff` (line 472) | Package 3, generalised |
| The sandboxed container provider pattern | `providers/renderer/_docker.py` (`container_argv`, line 311) and `providers/transcriber/whispercpp.py` (`container_argv`, line 568), the same limits written twice | Package 2 |
| Exact-artifact approval | `runtime/ops_video.py` `video_approve` (line 184) | Not in this plan; kept for the first publisher of files |
| Secure byte serving | `runtime/video.py` (`open_render`, `open_cover`) | Package 3, if the page shows a converted file |
| The minimal provider environment | `runtime/ops_pipeline.py` `ENV_KEEP` (line 70) | Package 3 |
| Runtime-only provider classes | the transcriber and the renderer (`docs/architecture/platform/short-video.md`, line 293) | Package 3 (`converter:document` is one) |

The video-specific pieces stay on their branch and rebase onto the extracted kernel later.

### A known bug on `feature/short-video`

The reviewer reported that approving the video does not close the second stop, so the task stays `waiting`. The code was read, not run, and does not contradict the report.

- `video_approve` (`runtime/ops_video.py`, line 184) writes the approval into the recording's record (line 224) and logs the event.
- `store.code_task_move` is called from one place only, `runtime/ops_pipeline.py`, line 138 (found with `git grep -n code_task_move`).
- The second stop opens a pending decision on the task (`runtime/pipeline.py`, `approval_decision`, line 683).

Fix it when the step engine is extracted (package 5), with a test that approves and asserts the task is `done`.

## 6. The work packages

Sizes are S, M or L and are judgments, not measurements (section 10). "Measurement impact" says whether the package touches a file in `FINGERPRINT_FILES` or in `evals/container/` (`evals/eval_status.py`, line 557) and, if it does, which kind of measurement change it is.

### Package 1. Merge hygiene (S)

**Goal.** Remove two correctness hazards before anything is built on them.

**Reuses.** `providers/store/sqlite.py` lines 1486 to 1560 on `feature/short-video` (the task with no skill); `runtime/parallel.py` `admit`; `runtime/proof.py`; `runtime/lab.py` `standing`.

**Builds.**

- Rename the task with no skill to "step task" (`code_task_add` becomes `step_task_add`, `is_code_task` becomes `is_step_task`, and the same in the tests and the pipeline). The word "code task" then means only the code-area task of `parallel.py`.
- Give a step task a declared footprint, from its kind. `admit` then holds a step task against a skill task that writes the same path.
- Fix `web_measured`. Today `proof.row` sets it to `bool(standing["web_cases"])` (`runtime/proof.py`, line 97), and `lab.standing` copies the gate file's list for the skill (`runtime/lab.py`, line 280). So a case listed in `web_cases` turns the web on before that case has any evidence. The event line already records the web cases a test ran (`evals/eval_status.py`, the event fields, line 39). Require lab lines of a listed case in the current set.

**Done when** tests show:

- a step task writing path X is held against a skill task writing X;
- the existing one-code-task-per-request tests pass;
- a case listed in `web_cases` with no evidence does not turn the web on.

**Size.** S. The port is about 75 lines of store code and its tests.

**Measurement impact.** None. `runtime/proof.py`, `runtime/lab.py` and the store are not in the fingerprint.

**Depends on.** `git pull` of `main` (section 5).

### Package 2. Shared container helper (S/M)

**Goal.** One place for the limits of a sandboxed container, so a third provider (the converter) does not copy them a third time.

**Reuses.** `providers/renderer/_docker.py` and `providers/transcriber/whispercpp.py`. Both write the same limits: no network, read-only root, all capabilities dropped, no new privileges, a limit on processes, memory, swap and CPUs, memory-backed `/tmp` and `/scratch`, an image that is never pulled at run time (`providers/renderer/_docker.py`, header; `providers/transcriber/whispercpp.py`, `container_argv`, lines 568 to 580).

**Builds.** One helper module that both providers call. Its tests keep the name of each limit.

**Done when** both providers' container-limit tests (`providers/renderer/tests/test_renderer_docker.py`, `providers/transcriber/tests/test_whispercpp.py`) pass unchanged.

**Size.** S/M. Two files of 633 and 1153 lines are touched.

**Measurement impact.** None. Providers are not in the fingerprint.

**Depends on.** The two providers exist only on `feature/short-video`. The package is done on a branch cut from it, and its helper is then one of the extracted pieces. If that is slow, package 3 may write the helper inside the converter and extract it later (section 7, order).

### Package 3. Converter and ingestion (M/L)

**Goal.** A person points the platform at a Notion page or a file, and a task receives clean text.

**Reuses.**

- `runtime/drop.py` (the destination and the per-task folder);
- `runtime/media.py` `receive` (streaming, bounded, hashed as written) for the intake;
- the documents provider's `read` verb;
- the container helper of package 2;
- `ENV_KEEP` (`runtime/ops_pipeline.py`, line 70);
- `providers/resolve.py`, which finds a class by its folder (`converter:document` resolves to `providers/converter/`).

**Builds.**

- A `converter:document` provider class, in a pinned image with no network, adopting existing tools (principle 14): poppler for PDF, pandoc for HTML, an XLSX reader, and a CSV pass. Output is Markdown or CSV. A runtime-only class, like the transcriber: not a class a skill may require.
- The intake generalised from `receive`. Magic bytes extended from video and image to PDF, OOXML and text (`sniff`, `runtime/media.py`, line 472, knows only MP4, MOV, HEIF brands, PNG, JPEG and WebP).
- A Notion page by id, through the existing `read` verb. Reading by URL needs a small function that extracts the 32-character id, since `doc_id` takes only the id (`providers/documents/notion.py`, line 522).
- The output goes to the task's drop through `runtime/drop.py`. It is handed to each task in the step's `depends_on` closure. A request-scoped drop would rewrite limit L2 ("of no other task", `runtime/drop.py`, header and `runtime/workcopy.py`, line 16), which is an M on its own, so it is not part of this package.
- It runs as an operation the person starts from the terminal or the page. The steps are plain functions (fetch, convert, scan, place) that do not import the operations layer, so package 5 can move them onto the engine without a rewrite.

**Done when.**

- Offline fixtures pass for each format.
- A PDF with a planted fake key is refused after conversion. (Raw, it is not found: section 4.)
- The measurement fingerprint is unchanged.
- No skill is bumped.
- One case with converted input is added to each of two target skills. An added case needs no bump (`AGENTS.md`, "Changing an existing skill"). Run it with `--cases <id> --baseline` before closing the package.

**Size.** M/L.

**Measurement impact.** None. Added cases are `pending` until they have run; they move no band.

**Depends on.** Package 2 (the helper), or the helper written inside this package.

### Package 4. A score per model, the choice of model and the auto mode (M/L)

This is the revised package. It is smaller than the first draft, because the status script already computes a band, a gate and a score for every model that has evidence.

**Goal.** The tiers leave. A person names a model, or asks for `auto`; every model has a published band.

**Reuses.** `evals/eval_status.py` `as_reference` (line 1095) and `skill_band` (line 1965), which already give each model its band, cause, gate and score by the same rules on that model's lines (`evals/eval_status.py`, the text at lines 118 to 128); `evals/measure.py` `gate_passes` (line 383); `--baseline-on`; `runtime/costs.py` `usage_of` (line 48) and `recompute` (line 133).

**Builds.**

- **Gate file.** `strong_model`, `floor_model`, `strong_harness`, `floor_harness`, `strong_pass_env`, `floor_pass_env`, `strong_tolerance` and `web_jobs` (keyed by tier, `evals/eval-gate.json`, lines 2 to 10 and 20 to 23; validated by `GATE_FIELDS`, `evals/eval_status.py`, line 250) become a list of models. Each has its adapter, its key variables and its price source. "The lab models" becomes a default list holding the two models of decision 2. `grader`, `threshold`, `runs` and `baseline_runs` stay. The tolerance keeps its value, 0.05.
- **Runner.** `evals/eval_run.py --model <id>`. The adapter is resolved from the id: `claude-*` to the adapter that `strong_harness` names today; `openrouter/...` and `ollama/...` to `agents-dir` (`adapters/agents-dir/run-prompt.sh`, line 29, already reads an `ollama/<name>` id). The rule "never pass a model by hand" (`AGENTS.md`) changes: the lab models are the default and any model may be named.
- **Evidence.** The test header names a list of models instead of `{"strong", "floor"}`. Today every one of the 86 test lines in `skills/*/evals/evidence/lab-*.jsonl` carries `"models": {"strong": ..., "floor": ...}` (counted on 2026-10-14). The reader accepts both shapes. Committed evidence files are never edited. Run lines already carry `model`, `adapter`, `score` and, on 1,596 of 2,005 lines, `cost_usd`.
- **Tokens in the run line.** This is new. The runner measures tokens per run (`evals/eval_run.py`, line 2314) but writes only `cost_usd` into the evidence line (line 2474; `RUN_OPTIONAL`, `evals/eval_status.py`, line 734). Auto ranks by tokens times price, so the line gains an optional usage field with the four kinds `runtime/costs.py` already reads (input, output, cache read, cache write; lines 33 and 34). The recorded cost of the reference model is not usable, since the pinned tool does not recognise the model (`docs/architecture/platform-plan-2026-10-05.md`, line 20). Neither `eval_run.py` nor `eval_status.py` is in `FINGERPRINT_FILES`, so this is infrastructure and asks for no new measurement version.
- **Status.** `evals/eval_status.py` computes the gate per model with that model's own baseline lines. This already holds for the two models. What changes: `known_models` (line 532) reads the gate file's list, and the reference model's special place (`reference_model`, `configured_reference`, lines 1083 to 1093) becomes "the model that decides the repository's gate", as the maintainer's lab default. The comparison itself stays `measure.gate_passes(with_mean, baseline_mean, threshold, tolerance)`, unchanged, so the computation for the existing evidence is byte-identical.
- **Key proxy.** `evals/container/keyproxy/keyproxy.json` pins every OpenRouter call to one upstream provider: `"provider_only": "deepinfra"` (line 6). It becomes a pin per model, with the DeepSeek line unchanged. It is the one fingerprinted file the package touches (everything under `evals/container/` is). Commit it with `python3 evals/eval_status.py measurement --kind execution --models <ids>` (`evals/eval_status.py`, lines 169 to 171 and 676 to 685), naming only models with no evidence yet, so no epoch reaches a model already measured and no evidence is lost. `--models` accepts only models the gate file lists (line 685), so the gate file's new list lands first.
- **Prices.** One table with source and access date replaces `adapters/api/prices.json` and the project's `model_prices`. OpenRouter prices are adopted from its models API (principle 14); the repository already records that URL as the source of three entries, accessed 2026-09-30.
- **Runtime.** `runtime/proof.py` `route(model=<id>)` and `route(auto)` replace the tiers. The tier word is read in `runtime/autonomy.py`, `cli.py`, `dispatcher.py`, `lab.py`, `operations.py`, `ops_reads.py`, `ops_core.py`, `ops.py` and `proof.py`, and in three files of `interface/js` (found with `grep -w tier`). The auto rule:
  1. The candidates are the models where the skill is `reliable`, a key is found and a price is known.
  2. Among them, keep those whose pessimistic score is at least the project's minimum (default the gate threshold, 0.8).
  3. Pick the lowest expected cost per run: the mean usage of that model's with-skill runs times its list price.
  4. A tie goes to the higher pessimistic score.
  5. No candidate: the project's default model, `supervised`, with the reason shown.
  6. A model the person names without `reliable` evidence runs `supervised`, marked unproven.
- **Interface and docs.** A model picker per request and per agent, with a default per project. The per-model table on the proof page (the Control room's skills tab shows two tier columns today, `interface/js/views/control-skills.js`, lines 13 to 23). Principle 9 in `AGENTS.md`, `docs/architecture/reliability-model-2026-10-02.md` and `evals/README.md` are rewritten without the tiers. The backlog item R15 (a setting that keeps an area agent on the reference model, `docs/backlog.md`, line 195 on `feature/parallel-agents`) is replaced by the picker.

**Cost in runs.** No model run for the existing evidence. A model with no baseline needs one baseline run per case (`--baseline-on`); the floor model already has them. The usage field is empty for existing lines. Until a skill has lines with usage on a model, that model is not a candidate for `auto` (it can still be named). The numbers can come from new runs, from the battery's run archive if it holds them (section 10), or from the project's own runs (`runtime/costs.py`).

**Done when.**

- `python3 evals/eval_status.py status` prints a band per skill and model, with a gate from that model's baseline.
- `python3 scripts/validate.py` passes with the new fingerprint committed.
- A test shows `auto` picking the cheaper `reliable` model, and falling back to `supervised` when none qualifies.
- The existing gates and bands on the reference model are unchanged: the same `status` output before and after, compared as text.

**Size.** M/L.

**Measurement impact.** One fingerprinted file, `evals/container/keyproxy/keyproxy.json`. The proposed class is an execution-side measurement change whose epoch names models with no evidence. The maintainer decides the class; the reviewer of this package checks that `keyproxy.json` is the only fingerprinted file in the diff and that the DeepSeek pin is unchanged.

**Depends on.** Package 1 (the `web_measured` fix touches the same files). Nothing else.

### Package 5. Step engine and step tasks in the dispatcher (M)

**Goal.** One engine runs the steps of a media pipeline and of an ingestion, resumably, with stops.

**Reuses.** `runtime/pipeline.py` on `feature/short-video` (`run`, `STOPS`, `prepare_again`, the failure records); `runtime/ops_runs.py` on `feature/parallel-agents` (a task run is its own process, `run-task --project <dir> --task <id>`, line 14; `dispatch`, line 581); `stop-runs` (`runtime/cli.py`, line 48, on `feature/parallel-agents`).

**Builds.**

- `runtime/steps.py`, extracted from `runtime/pipeline.py` and parameterised by a registry of kinds. A kind declares its `ORDER`, its stops and its executors. The engine no longer imports `captions`, `media` or `theme`.
- Step tasks become `planned` and `ready` under `depends_on`, like skill tasks.
- An owner rule, or a runtime pseudo-agent with its own cap, so that a step task is not held with "no enabled agent owns the task" (`runtime/dispatcher.py`, line 65).
- `ops_runs.dispatch` starts `cli.py run-step` as a child process, as it starts `run-task`, with lock-file liveness; `stop-runs` covers it.
- The short-video pipeline rebases onto it, so the engine has two consumers: ingest and media. The bug of section 5 is fixed here.

**Done when.**

- Both consumers run on the engine with their existing tests.
- A step task becomes `ready` only when the tasks it depends on are `done`.
- A killed child is detected by its lock and the task is `failed`, not `running`.
- `stop-runs` ends a running step.

**Size.** M.

**Measurement impact.** None.

**Depends on.** Packages 1 and 3 (the second consumer exists).

### Package 6. Step tasks in flows, and routines (S + M)

**Goal.** A workflow can mix steps and skills, and a schedule can start a request, a flow or a step.

**Reuses.** `runtime/flow_files.py` (the schema, the plan hash at `runtime/plan.py`, line 315); `runtime/handlers/published_posts.py` as the pattern (`due`, line 206; `tick`, line 392); `_ticks` (`runtime/ops.py`, line 2448); the scheduler providers; the store.

**Builds.**

- **The flow schema.** `{"key", "step": "<kind>", "args", "depends_on"}` beside the skill tasks. The args are covered by the plan hash. Flows per project, besides the workbench's.
- **Routines.** A handler, `runtime/handlers/routines.py`, reads routine records from the store. A record is created from the terminal or the page, and approved by the sha256 of its exact content. It carries no mode, cap, policy or standing approval. It is not creatable from MCP or from messaging. Its fires count against the agent's daily caps. A plan made by a routine is still approved by hash, unless a standing policy covers it. Its targets are a request text, a flow or a step.

**Done when.**

- A flow "ingest, then `biz-market-analysis`" passes the flow check and its plan test.
- A routine fires a request on schedule in a test with a fake clock.
- A routine created through a channel that is not the terminal or the page is refused.

**Size.** S for the flow schema, M for routines.

**Measurement impact.** None.

**Depends on.** Package 5.

### Order and funding

The order is 1, 2, 3, 4, 5, 6.

If only three can be funded before the next real project uses the platform, fund 1, 3 and 4. That is the reviewer's choice: correctness hazards first, the data pillar, the chosen model.

**The supervising session's dissent, recorded.** Routines are one of the three run modes the maintainer named, and a real case with a schedule already exists (scheduled posting). So packages 5 and 6 should follow 4, anchored on that case, which gives the engine two real consumers. Both orders are defensible; the choice is the maintainer's (OPEN-6 in section 7).

**Parallel work (principle 7).** Packages 1, 2 and 3 can run at the same time where their files do not overlap.

| Pair | Files in common | Verdict |
|---|---|---|
| 1 and 2 | None expected: 1 edits the store, `proof.py` and `lab.py`; 2 edits two provider folders | In parallel |
| 1 and 3 | `runtime/drop.py` and the store may both be touched | Start 3 after 1 has merged the rename, or keep 3 out of the store |
| 2 and 3 | 3 uses 2's helper | 3 depends on it, or builds the helper inside and extracts it later |
| 1 and 4 | `runtime/proof.py` and `runtime/lab.py` | Serial: 4 after 1 |

## 7. Decisions still open (the maintainer's)

Each has the recommendation. None is decided.

- **OPEN-1. Where ingested data lives.** Recommendation: in the task's drop (`.workbench-local`, `runtime/drop.py`), promoted to `docs/` only by the person. A tracked snapshot enters every run (section 4, path B).
- **OPEN-2. The first source and the real case.** Recommendation: Notion and local files. Jira and Google wait for a real project that needs them. The platform plan already parks Jira until a real project uses the platform (`docs/architecture/platform-plan-2026-10-05.md`, section 8, line 366).
- **OPEN-3. Live tools inside runs in this phase.** Recommendation: no. MCP servers only as host-side provider implementations with read verbs.
- **OPEN-4. Routine records in the store,** created from the terminal or the page and approved by hash (package 6). Recommendation: yes.
- **OPEN-5. The auto mode's minimum score per project.** Recommendation: the gate threshold, 0.8, adjustable per project.
- **OPEN-6. The order after package 4.** Recommendation: the reviewer's (1, 3, 4 first) unless a real project with a schedule starts before the next stage; the supervising session's order (5 and 6 right after 4) is the alternative.

## 8. Risks and how to see them early

| Risk | How to see it early |
|---|---|
| Skills do worse on large converted documents. The proof covers inputs in the form of the cases. | The converted-input cases of package 3 run with `--baseline`; field evidence from the first real use; a size cap per task. |
| A measurement change is classified wrongly, and the battery is paid for. A grader-side change raises the floor and asks every skill for a full test. | Package 4's review checks that only `keyproxy.json` changes among the fingerprinted files and that the DeepSeek pin is unchanged. |
| Most work of one floor stays serial, because a placeholder in a skill's declared path counts as an overlap. | Backlog R17 (`docs/backlog.md`, line 214 on `feature/parallel-agents`) says this and keeps the conservative rule. Count held tasks with the held reason `artifact in use` (`IN_USE`, `runtime/parallel.py`, line 40 on `origin/main`) in the first real runs. |
| The two meanings of "code task" collide at the merge. | Package 1 renames one of them before anything else is built on it. |
| The renderer image has been built on one machine only. | `docs/architecture/platform/short-video.md` says the amd64 renderer image "has not been built or run" (line 390) and that the amd64 browser archive has no pin (line 331). Package 2 does not depend on the images; the video features do. |
| A model that runs on the person's machine (`ollama/...`) cannot be reached from the eval container. | The archived backlog records that the container's network reaches only the hosted providers (`docs/backlog-archive.md`, line 163). `ollama/<name>` is parsed by the adapter, but a lab run on it is not supported until a route is built. Leave it out of package 4's "done when". |
| `auto` ranks by a price that changed. | The price table carries an access date; `auto` shows the date beside the price, and a price older than a limit the project sets is shown as stale. |
| A model the person names without evidence produces a poor result and nothing marks it. | Decision 8: it runs `supervised`, and the run and the card say "unproven". |

## 9. Not in this plan

- **Community lab evidence** (decision 7). One idea for later, not discussed with the maintainer: runs in the contributor's own fork CI, with an artifact attestation proving that the workflow and the code were the workbench's, unmodified.
- An Instagram or TikTok publisher.
- Indexing or RAG.
- Agent memory (listed in backlog R2, not built).
- A persona per agent.

## 10. Assumptions and what was not verified

**Assumptions.**

- Assumption: poppler (`pdftotext`), pandoc and an XLSX reader convert the formats named in package 3. No converter was run in this check.
- Assumption: the size labels S, M and L are the author's judgments from the size of the files named, not measurements.
- Assumption: the battery's run archive, which the 2026-10-05 plan says is kept outside the repository (`docs/architecture/platform-plan-2026-10-05.md`, line 23), holds each run's timing file with its token counts. It was not opened. If it does not, usage for existing evidence comes from new runs.
- Assumption: a Notion page that is not a mirrored document can be read with the existing credential if the integration is shared with it. The provider calls the Notion API for any page id (`providers/documents/notion.py`, `retrieve`, line 530), but no live call was made.
- Assumption: OpenRouter's models API lists a price per model. The repository records the URL `https://openrouter.ai/api/v1/models` as the source of three entries in `adapters/api/prices.json`; the API was not called in this check.
- Assumption: the epoch of the measurement change in package 4 can name only models with no evidence. `--models` accepts a model the gate file lists (`evals/eval_status.py`, line 685); no command was run to commit such a change.

**Not verified.**

- The approve-video bug (section 5) was read in the code and not run.
- A trial merge was run only between the commits named in section 5. A trial merge of `origin/feature/short-video` (`6794905e`) with `origin/main` (`d3e60770`) reported conflicts in 44 files, as in section 5; the trial of `39600a0b` with `6794905e` reported seven.
- The per-model band counts of section 2 were computed once, on 2026-10-14, at `9bc9b863`.
- The line numbers on `feature/*` are at `39600a0b` and `6794905e`; `origin/feature/parallel-agents` has since moved to `d9d3f069` (documentation commits, per `git log`).
