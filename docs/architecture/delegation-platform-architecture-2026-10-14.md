# Delegation platform: the architecture after the plan

Version 2, of 2026-10-14, on `origin/main` at `d3e60770`. Describes the system as it would be once packages P0 to P10 of the plan's version 2 are done (the side package, the short-video rebase, is off this path). Nothing new in it is built. Section 6 keeps version 1's findings, with how version 2 resolves each; they were checked against the code by an independent reviewer and by the supervising session.

Companion of [the plan](delegation-platform-plan-2026-10-14.md). The plan says what to build and in which order; this document shows the whole once it is built. Package numbers (P0 to P10) and decision numbers (D1 to D29) are those of the plan's version 2.

**How to read the markers.** Every element carries one state.

- `exists`: on `origin/main` at `d3e60770` today. The path is given, with a line where one was read.
- `extracted (Pn)`: exists on `origin/feature/short-video` at `6794905e`, absent from `main`, and moved to `main` by package `Pn`. Its path and line are on that branch.
- `new (Pn)`: built by package `Pn`. Nothing of it exists. It is written in the present tense because the text describes the target, never because it is built.
- `future`: named by a decision, built by no package of P0 to P10, and only after a stated trigger.
- `deferred`: waits for a real project that needs it.

A sentence marked "After the plan" describes the target. A line that starts `To verify n:` marks a fact about a third-party service that was not confirmed; `n` is its number in section 7. No other open gap remains in the target. Every main-side line number below was read in this checkout, which is `d3e60770` plus the plan's commit. Several of them differ from the plan's, which read main at `9bc9b863` and did not re-number them (section 6, "Corrections to the plan's own citations"), and a few differ from version 1 of this document (same section).

## What changed from version 1

Version 1 described the system after the plan's six packages and listed, as `Gap:` lines, what that plan lacked. The maintainer took twenty-nine decisions on 2026-10-14 (D1 to D29) and the plan became ten packages (P0 to P10). The differences that matter to the architecture:

- **Data is not centralized (D9, D10, D11, D12).** Version 1 proposed a source store inside the workbench's local folder. Version 2 has a mandatory data folder that the user defines per project, outside the workbench's git, with guardrails; each import is an immutable version; a registry names the sources; a rich catalog built by code lets the planner choose the sources for a task. L4 is rewritten around it.
- **More sources and outputs (D13, D14, D17).** Uploaded files and Notion pages, then Google Drive in general with the narrow `drive.file` scope and the Picker. File outputs by a code step, and write-back to Drive and Notion as an approved external effect.
- **No MCP in a run (D15).** MCP may be adopted only on the host as a provider implementation with read verbs.
- **Web and sources (D16, D27).** In manual use the plan card highlights a web task that receives sources; in a routine such a task runs without the web. A task that requires the web never runs without it silently: the planner splits mixed work, and for a flow written by hand the flow check refuses, as a routine target, a web task that receives sources, with a message that tells the person to split it (D27).
- **Sources and messaging (D28, D29).** A task receives the newest version of each chosen source at the moment it starts and records its id, version and sha256 (D29). Attachments, model choice and flow choice over messaging are a later evolution of the messaging channel, after P6 (D28).
- **Models and proof (D18 to D22).** A person's own tests stay local and feed only their `auto`; community evidence is verified by attestation and counted for everyone (D19); evidence from `linux/amd64` is accepted beside `linux/arm64` (D20); the eval image is published by digest and the runtime pulls it (D21); `auto` picks the cheapest `reliable` pair, with no minimum score and no project setting (D22).
- **Routines (D23, D24).** Created from the terminal or the page, approved by the sha256 of their content, with their plan approved by hash at creation and checked at each fire; a free-text routine never runs unattended; messaging's routine permissions are configurable through the existing channel policy.
- **Project scripts (D25).** A step kind that runs the person's own code, approved by its exact hash, in the sandbox, writing only into the data folder.
- **Packages.** P0 ports the generic short-video pieces to main first (version 1's finding F15); P2 does the measurement identity once; P4 to P9 build sources, the step engine, flows and routines, Drive, outputs and project scripts; P10 is community evidence.
- **Findings.** F1 to F16 are kept as history; each now ends with a line "Resolved in version 2 by". Three are only narrowed (F9, F10, F13) and the line says what remains. The "Proposed changes to the plan" of version 1 were adopted and are replaced by a note.
- **Nothing from OPEN-1 to OPEN-6 remains open.** What is open is the list "To verify" (section 7) and the real cases that D17 leaves to be chosen during development.

## 1. Why this document

The plan fixes the target (its section 1: three pillars, three run modes), the order of the work and the decisions. This document does the other half: it lays out the finished system layer by layer and says, for each layer, which pillar and which run mode it makes possible, so that a reader can see where a package lands.

It restates nothing of the plan's section 1. The three pillars are (1) data sources and persistence, (2) the brain, (3) tools; the three run modes are (a) a simple agent, (b) a workflow, (c) a routine.

## 2. The principles that shape every layer

| Principle (`AGENTS.md`) | What it forces in the architecture |
|---|---|
| 11. Hard limits live in code | A credential never enters a run: providers hold credentials on the host (`providers/secrets/resolver.py`), a run sees only its folder and one adapter script (`evals/executor.py`, header), and the model's key sits in a key proxy (`evals/container/keyproxy/keyproxy.py`, header). An external effect is shown, approved by the hash of its exact content, executed by code, recorded (`runtime/effects.py`, header); after the plan this includes writing back to Drive or Notion (D17). Converted and ingested files pass a credential scan before a run (`runtime/workcopy.py`, `scan`, line 227). The data folder is guarded in code (D10): the runtime writes only inside it, never follows a symbolic link out of it, refuses dangerous paths, and the work copy excludes it. A project script runs only by its approved hash, without credentials, with a read-only root and no direct effects (D25). |
| 9. Proof decides | After the plan, proof is kept per model and adapter and decides autonomy, not access (D8): a model the person names without `reliable` evidence runs `supervised`, marked unproven; `auto` picks the cheapest `reliable` pair (D22). Evidence comes from three places: the maintainer's lab, the person's own local tests (their `auto` only, D18) and verified community evidence (everyone's, D19). Today proof decides access too (`runtime/proof.py`, `route`, line 118). |
| 10. A claim says what it rests on | Community evidence is a column of its own, per model, with a per-contributor cap, and never merged into the lab's figures (D19); each line records its platform (D20) and the published image digest it ran in (D21). |
| 4. Artifacts over invocation | Skills never call each other. Tasks exchange files under the artifact contract (`contracts/project-layout.md`); a flow orders tasks by `depends_on` (`runtime/flow_files.py`). A step task, which is not a skill, exchanges files the same way; a source reaches a task as a copy of a recorded version, never as a call. |
| 14. Adopt before building | The converter adopts open document tools behind a provider (P4); Drive is read through its own API and the Picker (D13, D14); Notion through the existing documents provider; file outputs by adopted tools (D17); evidence is attested by the code host's own attestation (D19). An MCP server may be adopted only as a provider implementation on the host (D15). |
| 1 and 2. A harness-agnostic core and open-closed adapters | `runtime/`, `providers/`, `skills/` name no AI tool. What belongs to one tool lives in `adapters/<harness>/`; the runner finds an adapter from the gate file's model list (`evals/eval-gate.json`), and adding a model adds an entry there, not a branch in the core and not a change to a fingerprinted file (D18, P2). |
| 7. Parallel by default | Tasks run at once unless a slot or a file in use forbids it: `runtime/parallel.py` `admit` (line 87) walks the project's slots, the agent's slots and the footprint of the files a task writes. A step task gets a declared footprint too (P1). |
| 8. Shared core, projects outside | A project's data, flows, routines and imported sources live in that project: `docs/` for artifacts, `.workbench-local/` (untracked) for the drop (`runtime/path_rule.py`, `DROP_DIR`, line 41), and the data folder the user defines for the sources (D9), outside the workbench's git. A person's own lab evidence lives outside the checkout, so a pull never conflicts (D18). The workbench checkout holds none of it. |
| 12. A change pays for what it can reach | Adding a model changes no fingerprinted file (D18); publishing the image is one execution-side measurement change made once (P2); teaching the planner to choose sources is a Y change of one skill with a partial test (D11). |
| 13. A saving must exceed its loss of safety | Accepting `linux/amd64` evidence beside `linux/arm64` (D20) is accepted because the alternative (amd64 only) costs the maintainer an emulated machine and an epoch for every skill. Giving every non-web task the whole folder (option B) is left `future`: it saves the planner's choice and loses the property that a task sees only what was chosen. |
| 5. Never assume; ask | The planner asks when in doubt about a source; a step task can stop and ask the person (a pending decision); a plan and an effect always reach the person, and a review does unless an autonomy mode releases it (`runtime/autonomy.py`, `review_action`, line 316). A free-text routine turns every fire into a plan to approve (D24). |

## 3. The layers

```
L1 CHANNELS: five shells over one table of operations and one operations layer
+------------+ +---------+ +---------------+ +---------------+ +----------------+
| terminal   | | chat    | | page          | | MCP           | | messaging      |
| cli.py     | | chat.py | | service.py    | | mcp.py        | | messaging.py   |
| all verbs  | |         | | + interface/  | | read verbs;   | | policy groups  |
| routines   | |         | | model picker  | | lists         | | for routines   |
| (create)   | |         | | routines      | | routines only | | (D23)          |
+------------+ +---------+ +---------------+ +---------------+ +----------------+
      |            |              |                 |                  |
      +------------+--------------+-----------------+------------------+
                                  |  operations.py (the table), ops.py (the layer)
                                  v
+-----------------------------------------------------+  +------------------------------+
| L2 ORCHESTRATION                                    |  | L5 PROVIDERS (host side only)|
| router + planning run: skill or flow, and the       |  | documents  issue-tracker     |
|   sources, chosen from the catalog (P4)             |  | mailbox    messenger         |
| plan (sha256, sources inside) -> approval by hash   |  | publisher  scheduler         |
| flows: workbench + project, parameters (P6)         |  | vcs        store             |
| routines: records + handler, D23 and D24 (P6)       |  | converter:document (P4)      |
| area agents = configuration in runtime.json         |  | Notion by address (P4)       |
+-----------------------------------------------------+  | Google Drive (P7)            |
                          |  tasks: skill, step         | | write-back effects (P8)      |
                          v                             | | secrets: OS keyring          |
+-----------------------------------------------------+  +------------------------------+
| L3 EXECUTION                                        |     Providers are called by host
| dispatcher + admission (slots, footprints, caps)    |     code only (messaging bridge,
| skill task: lab -> eval container, on a copy that   |     effects, mirrors, handlers,
|   holds copies of its chosen source versions        |     ingest). A run never calls one
| step task: its own process; kinds: ingest, file     |     and holds no credential. MCP
|   output, project script (P5, P8, P9)               |     only here, never in a run.
| effects: preview -> approval -> execute -> record   |
| route(model | auto = cheapest reliable)             |
+-----------------------------------------------------+
   |                   |                      ^
   |  run              |  rows, files         |  band per model, price
   v                   v                      |
+--------------------+ +----------------------+ +---------------------------+
| L6 ADAPTERS,MODELS | | L4 DATA, PERSISTENCE | | L7 PROOF LAB              |
| adapters/*         | | store (SQLite), docs/| | eval_run.py, status,      |
| model list + pins  | | data folder (D9):    | | per-model gate, local     |
| model-keyed proxy  | |  registry, versions, | | evidence (D18), community |
| published image    | |  catalog; the drop;  | | verified (D19), attested  |
| per platform + lock| | mirrors              | | CI (P10)                  |
+--------------------+ +----------------------+ +---------------------------+
```

The diagram shows what exists and what is new together; the tables below say which is which. L7 is not a layer a request passes through: its evidence is read to choose a model. No arrow leaves a run to a provider: the container sees the run folder and one adapter script, and reaches only the model's key proxy or, for a web run, the open network (`evals/executor.py`, lines 3 to 35).

### L1. Channels (shells)

**What it is.** One table of operations (`OPERATIONS`, 47 rows, `runtime/operations.py` line 72) and one operations layer (`runtime/ops.py` with its siblings), served by five shells that parse a message, call an operation and return what it returned. The table has a column for the channels that may call each operation, so that code, not a prompt, refuses what a channel may not do (`runtime/operations.py`, header).

**What it holds.**

| Component | State | Path |
|---|---|---|
| Table of operations, groups and channel rules (`GROUPS` line 259, `POLICY_CHANNELS` line 283, `EFFECT_CHANNELS` line 286) | exists | `runtime/operations.py` |
| Operations layer | exists | `runtime/ops.py`, `ops_core.py`, `ops_runs.py`, `ops_waits.py`, `ops_reads.py`, `ops_say.py`, `ops_config.py` |
| Terminal shell | exists | `runtime/cli.py` |
| Chat shell | exists | `runtime/chat.py` |
| Page: local service (loopback, token, origin check) and the static interface | exists | `runtime/service.py` (header, rules 1 to 5, lines 96 to 104), `interface/` |
| MCP server (tools only for rows that list `mcp`) | exists | `runtime/mcp.py` |
| Messaging bridge, inbound parser, cards, ledger, provider session | exists | `runtime/messaging.py`, `messaging_bridge.py`, `messaging_inbound.py`, `messaging_cards.py`, `messaging_ledger.py`, `messaging_provider.py` |
| Channel policy per channel (`channels` of the project's `docs/workbench/runtime.json`, accepted only in the terminal; default for messaging is read, talk, answer) | exists | `runtime/project_config.py` `_channels` (line 182), `ACCEPTED` (line 98), `runtime/operations.py` `DEFAULT_POLICY` (line 281) |
| Model picker per request and per agent, with a project default, on the page; the choice is stored (a store column, a schema change) | new (P3) | `interface/js/views/lobby-composer.js`, `lobby-request.js`; a `model` argument on rows of `operations.py`; `providers/store/sqlite.py` (`SCHEMA_VERSION`, line 53) |
| Per-model table in the Control room (today two tier columns) | new (P3) | `interface/js/views/control-skills.js` (the two tiers are named at lines 11 to 24) |
| Source verbs and screens: register a source, import, refresh, list the catalog, write a description | new (P4, P7) | rows in `runtime/operations.py`; the upload follows the existing file route (`runtime/service.py`, `FILE_LIMIT` line 214) |
| Routine verbs: create and change (terminal and page), list, pause and cancel | new (P6) | rows in `runtime/operations.py`, in groups of their own (D23) |
| Messaging groups for routines: by default only the brakes (list, pause, cancel); the person may grant creating and changing through `channels.messaging`, accepted in the terminal | new (P6) | `runtime/operations.py` (`GROUPS`, `DEFAULT_POLICY`); `runtime/project_config.py` |
| MCP and routines: it may list them; creating and changing stay outside its ceiling | new (P6) | `runtime/operations.py` |

**How it serves the idea.** Pillar 2 (the brain) is reachable from five places with one set of rules, which is what lets a person delegate from a phone and approve from a desk. Mode (a) starts on the page or in the terminal, with a model picked or `auto`; mode (b) is started the same way by naming a flow (`request --flow`, `runtime/ops.py` line 390); mode (c) is created on the page or in the terminal and fires with no channel.

**Boundaries.** An effect is approved only from the terminal or the page (`operations.EFFECT_CHANNELS`, line 286; `runtime/ops.py` `approve`, line 2051). A plan approved from messaging carries its hash (`runtime/ops_waits.py`, `only_on_plans`, line 281; the hash check is at lines 295 to 297). A routine is created and changed by the sha256 of its exact content (D23) and carries no mode, cap, policy or standing approval of its own; each fire counts against the agent's daily caps. The terminal is never narrowed by policy (`NEVER_NARROWED`, line 282), and chat, which is local access, has no policy (`POLICY_CHANNELS`, line 283, comment).

**What stays outside.** Messaging carries no attachment and no flow or model choice (`runtime/messaging_inbound.py`, header, lines 7 to 17), and no package of P0 to P10 changes that: a file, a model or a flow is chosen on the page or in the terminal, not from a phone, until the later evolution of the messaging channel after P6 (D28; section 6, F9).

### L2. Orchestration

**What it is.** The step that turns a request into a plan the person approves by hash, and the definitions that give a plan its shape: flows, routines, area agents.

**What it holds.**

| Component | State | Path |
|---|---|---|
| Router: one skill or one flow, read from the router run's reply (`read_route` line 59, `check_route` line 77) | exists | `runtime/router.py`; routing table `skills/core-orchestrator/references/routing.md` |
| Source choice by the planner: the planning run receives the catalog of the project's sources (data, never instruction) and names, for each task, the sources it needs; it asks when in doubt; an `@mention` in the request forces a source. A Y change of `core-orchestrator`, tested on the two lab models | new (P4) | `runtime/router.py`, `runtime/plan.py`; `skills/core-orchestrator/` |
| Plan: tasks, owners, contract-derived dependencies, `plan_hash` (line 316) over the tasks, approval by sha256 (`approve` line 2051); after the plan, each task entry also carries its source ids and its step arguments, so that the hash covers them | exists; sources and arguments inside the hash new (P4, P6) | `runtime/plan.py` (`combine` line 575, `agent_of` line 163), `runtime/ops.py`, `runtime/ops_waits.py` `approve_plan` (line 162) |
| Plan card: lists each task's sources and highlights a web task that receives sources | new (P4) | `interface/js/cards/plan.js` |
| Flow files, six on main (`brand`, `code-change`, `design`, `market-positioning`, `short-video`, `website`); the loader reads the workbench checkout only (`ROOT` line 44, called with `core.ROOT` at `runtime/ops.py` lines 402, 1568, 1642); a task is a skill task (`TASK_KEYS` line 47) | exists | `flows/*.json`, `runtime/flow_files.py` |
| Project flows, in a folder of the project | new (P6) | a folder of the project; the folder is not named by the spec (section 7) |
| Step entries in a flow: `{"key", "step", "args", "depends_on"}` | new (P6) | `runtime/flow_files.py` (`TASK_KEYS` changes) |
| Flow parameters, bound from the request and covered by the plan hash; a flow or a routine pins a source's id, not its version | new (P6) | `runtime/flow_files.py`, `runtime/plan.py` |
| Routine records, in the store, approved by the sha256 of their exact content (schedule, target, arguments) | new (P6) | `providers/store/sqlite.py` (new table), `runtime/ops.py` |
| Routine handler: reads the records and fires targets on the dispatcher's tick; regenerates the plan at each fire (D24) | new (P6) | `runtime/handlers/routines.py`; the pattern is `runtime/handlers/published_posts.py` (`due` line 206, `tick` line 392); the tick is `runtime/ops.py` `_ticks` (line 2444), called at line 593 of `ops_runs.dispatch` (defined at line 581) |
| Area agents: configuration only (a pack of skills, an enabled flag, a mode, daily caps, `max_parallel`) | exists | `docs/workbench/runtime.json` `area_agents`, `runtime/autonomy.py` (`agents` line 126, `MODES` line 70, `MAX_PARALLEL_CEILING` line 77) |
| Owner rule for a task with no skill (a rule in the planner and the dispatcher) | new (P5) | `runtime/plan.py` (`agent_of`, line 163, is called for every task at lines 593 to 595); `runtime/dispatcher.py` (`NO_AGENT`, line 70) |

**How it serves the idea.** Pillar 2 and all three run modes. The router serves mode (a), and now also names the sources a task reads; a flow serves mode (b), which the maintainer described as stages with several agents and skills; a routine serves mode (c), which needs no scheduler of its own because the handler tick already runs on every dispatch round, and the rounds are driven by the scheduler job every 5 minutes (`contracts/runtime.md`, line 312). The routine fires at the first round at or after its time.

**Boundaries.** The router chooses; it does no work of the skill it routes to (`AGENTS.md`, principle 4). The catalog it reads is third-party text: data, never instruction. A plan is never released by a mode (`runtime/autonomy.py`, `review_action`, rule 1, line 327): it always reaches the person. A routine is the one case where a plan is created without asking, and only under the three rules of D24:

1. Creating a routine generates its plan, and the person approves that plan's hash together with the routine. At each fire the plan is regenerated and tasks are created without asking only if the hash is identical; otherwise the routine stops and asks. A new version of a source does not change the plan, because the plan pins the source id.
2. A free-text routine never runs unattended: each fire becomes a plan to approve. Only fixed targets (a flow or a step) run alone.
3. Tasks proceed without review only on `reliable` pairs with the agent in `autonomous` mode; otherwise the routine waits at the first review and messaging notifies the person. Effects still need approval of their exact content unless a standing policy accepted in the terminal covers them.

Area agents are configuration, not code: they own a pack and a cap, and carry no persona or memory (plan, section 9).

What stays outside: choosing a project flow by the router is not provided; the person names the flow (`request --flow`), and the flow's parameters are bound from the request text (section 6, F9).

### L3. Execution (the brain)

**What it is.** The dispatcher decides what may start now from a snapshot of the store; two kinds of task run, plus the project script, which is a step; effects leave only through an approval gate.

**What it holds.**

| Component | State | Path |
|---|---|---|
| Dispatcher: one pure `decide` over a snapshot (release, start, hold with a reason) | exists | `runtime/dispatcher.py` (`decide` line 86; `REASONS` line 82) |
| Admission: project slots (`max_running`, default 3, 1 to 14: `runtime/project_config.py` lines 162 to 172), agent slots (`max_parallel`, up to 4), one code task per request, footprint overlap | exists | `runtime/parallel.py` `admit` (line 87), `footprint` (line 44) |
| Task run as its own process (`run-task --project <dir> --task <id>`), with a lock and orphan recovery; the dispatcher starts the children | exists | `runtime/cli.py` (line 16), `runtime/ops_runs.py` (`run_task` line 192, `dispatch` line 581) |
| Skill task: one skill, in the eval container through the lab facade, on a fresh work copy under the limits stated in the header of `runtime/workcopy.py` | exists | `runtime/lab.py` (`run_skill` line 500), `runtime/workcopy.py` (`entering` line 238, `returning` line 340) |
| A task receives copies of its chosen source versions and records which version it read (D11, D12); the data folder itself is always excluded from the work copy, even when it sits inside a tracked tree (D10) | new (P4) | `runtime/workcopy.py` (L2 of its header, lines 14 to 17, copies every versioned file today) |
| A routine task that receives sources runs without the web; the planner splits work that needs both into a web task without sources and an analysis task with sources and no web (D16); for a hand-written flow the flow check refuses, at routine creation and at each fire's plan, a task that requires the web and receives sources, and its message says to split the flow (D27) | new (P6) | `runtime/workcopy.py`, `runtime/plan.py` |
| Model choice by `proof.route(model=<id>` or `auto)`, with the cheapest `reliable` pair for `auto` (D22) | new (P3) | `runtime/proof.py` (replaces `TIERS` line 41 and `route` line 118) |
| Autonomy by mode and by proof: unproven goes to review; milestones and mandatory milestones hold | exists | `runtime/autonomy.py` (`review_action` line 316, rule 5 at line 336) |
| Step task: a row with a parent and no skill, today on a branch (`is_code_task`, `code_task_add`, `code_task_move`), renamed `step task` | extracted (P0) | `providers/store/sqlite.py` on `feature/short-video`, lines 1487, 1498, 1528 |
| Step task declared footprint (from its kind; until kinds exist, the one its creator declares) | new (P1) | `runtime/ops_runs.py` (`skill_facts`, line 74 on `feature/short-video`, returns an empty footprint today) |
| Step engine: resumable, with stops, its executors chosen by a registry of kinds | extracted (P5) | `runtime/pipeline.py` on `feature/short-video` (`ORDER` line 71, `STOPS` line 75, `run` line 747, `prepare_again` line 808) becomes `runtime/steps.py` (new) |
| Step task as a process of its own (`cli.py run-step`), found by its lock, ended by `stop-runs` | new (P5) | `runtime/cli.py`, `runtime/ops_runs.py` |
| Step tasks `planned` and `ready` under `depends_on` | new (P5) | `runtime/ops_runs.py`, `providers/store/sqlite.py` |
| Step kind `ingest`: fetch or receive, convert, scan, place a new immutable version in the data folder; built as plain functions in P4 and registered as a kind in P5 | new (P4, P5) | `runtime/` (module not named by the spec) |
| Step kind: file output (PDF, XLSX, DOCX, CSV) by adopted tools, no model, into the data folder or `docs/` | new (P8, registered in P5's registry) | `runtime/` (module not named by the spec) |
| Step kind: project script, approved by its exact hash; runs in the shared sandboxed container with no credentials and a read-only root; network off by default, declared destinations entering the approved hash; writes only into the data folder as a new versioned source; no direct effects; Python and shell first, dependencies declared and pinned (D25) | new (P9) | `runtime/` (module not named by the spec) |
| Step kind `media` (the short-video pipeline) | future (the side package) | `runtime/pipeline.py`, `runtime/ops_pipeline.py` on `feature/short-video`; not in P0 to P10 |
| Effects: preview, one approval of the exact content, execution by code, record | exists | `runtime/effects.py`, `effect_commit.py`, `effect_pull_request.py`, `effect_reply.py` |
| Write-back effects to Drive and Notion, with a check that the target was not edited since it was read | new (P8) | `runtime/effects.py` and a new effect module, on the existing gate |
| Costs, billing and daily caps: a cost recomputed from token counts and prices, usage read from the full model usage; caps counted by the credential's billing | exists; the full usage new (P2) | `runtime/costs.py` (`usage_of` line 48, `recompute` line 133), `runtime/billing.py`, `runtime/autonomy.py` (`may_start` line 285) |

**How it serves the idea.** This is pillar 2 for modes (a) and (b), and the place where the maintainer's "different models" becomes real: the skill task takes the model the person named, or the one `auto` picks. A step task is what lets a workflow contain plain code (ingestion, conversion, an export, the person's own script) beside skills, and what lets a routine be "plain code" for the kinds the workbench registers and for a project script the person has approved.

**Choosing the model, after the plan.** `route(model=<id>)` runs the skill on that model; if the pair has no `reliable` band the run is `supervised` and marked unproven (D8). `route(auto)` (D22):

1. The candidates are the models where the skill is `reliable` on this machine, a key is found and a price is known. `reliable` is read from the lab's evidence, the person's own local tests and the verified community evidence, with the adapter and the image digest the evidence names.
2. Pick the lowest expected cost per run: the mean usage of that model's with-skill runs times its list price (D5). There is no extra minimum score and no per-project setting.
3. A tie goes to the higher pessimistic score.
4. No candidate: the project's default model, `supervised`, with the reason shown.

A critical project selects a strong model by hand.

**Boundaries.** A run never holds a credential, never reaches a provider, sees only the artifacts its skill declares when it uses the web (limit L3, `runtime/workcopy.py`, header) and returns files only through the path rule (L7). A task sees only the sources chosen for it. The ingest functions import no part of the operations layer, so the engine can run them without a rewrite. No effect runs without the approval of its exact content, and no project script has a direct effect. The dispatcher changes no state; `ops.py` applies its decision (`runtime/dispatcher.py`, header, rule 4).

When a file in the data folder changed after its import, its hash no longer matches the recorded one: it is treated as a new version made by the person and is never handed over as the recorded one (D10).

The reading of `reliable` no longer depends on a local build: the proof file marks a pair not proven when the image on this machine is not in the evidence's images (`runtime/proof.py` `checks`, lines 104 to 115). After the plan the image is the published one, pulled by digest from the lock file (D21), so a server and a laptop that pulled the same digest agree; an image built locally yields local-only evidence that counts for that person's `auto` alone.

### L4. Data and persistence

**What it is.** The state of the work: rows in a per-project store, the project's documents under the artifact contract, the data folder the user defines for imported sources, an untracked place for files handed to a run, and the mirrors that keep documents and the task board where a person reads them.

**What it holds.**

| Component | State | Path |
|---|---|---|
| Store, one SQLite file per project: tasks, task runs, pending decisions, approvals, conversation messages, task waits, document records, platform comments, events, runs, inbox, actions, cursors | exists | `providers/store/sqlite.py` (`CREATE TABLE` lines 92 to 312) |
| Step tasks, routine records, the model chosen for a request or a task, the source registry's rows | new (P0, P6, P3, P4) | `providers/store/sqlite.py` (a schema change: `SCHEMA_VERSION`, line 53, is 9 today) |
| Project artifacts: `docs/` under the artifact contract, one owner per artifact | exists | `contracts/project-layout.md`, `runtime/path_rule.py` |
| The data folder: a folder the user defines per project; mandatory, with no default (a project without one does not run); outside the workbench's git; the user may keep it in a repository or a drive they already use and version it as they like. Its path is set in `runtime.json`, accepted only in the terminal. Guardrails in code: the runtime writes only inside it, never follows a symbolic link out, refuses dangerous paths (the home folder, the filesystem root, a folder that contains the project), and the work copy excludes it | new (P4) | `runtime/project_config.py` (the key and its checks), `runtime/path_rule.py`, `runtime/workcopy.py` |
| The source registry: each source declared with its type and origin; no credential in it (credentials stay in the OS secret store) | new (P4) | the store and the project's configuration |
| Immutable versions: each import writes the original, the converted text (Markdown or CSV) and a manifest (origin, date, sha256); a refresh writes a new version and changes none | new (P4) | the data folder |
| The rich catalog, built by code at import with no model: name, type, size, date, sheets and columns with sample values, first headings, the person's optional description | new (P4) | the data folder and the store |
| A size cap per source, with a warning; indexing and RAG wait for a real case | new (P4) | `runtime/` |
| The file drop: one folder per task under `.workbench-local/drop/<task id>/`, 25 MB at most, credential-scanned if UTF-8, entering a run of that task only; it stays for a file the person hands to one task | exists | `runtime/drop.py` (`MAX_BYTES` line 49, `hand_over` line 76) |
| The streaming, hashed intake and the content-addressed item store, generalised from media to documents (magic bytes extended to PDF, OOXML, text) | extracted (P0), extended (P4) | `runtime/media.py` on `feature/short-video` (`sniff` line 472, `receive` line 714) |
| Documents mirror (`pull`, `push`) to the platform of the project's `documents` configuration | exists | `runtime/documents.py` (`pull` line 503, `push` line 533) |
| Task board mirror (`pull`, `push`) | exists | `runtime/board.py` |
| Providers for both mirrors: Notion or local files | exists | `providers/documents/notion.py`, `providers/documents/local.py`, `providers/issue-tracker/notion.py`, `providers/issue-tracker/local.py` |
| Proof file, a cache rebuilt when its inputs change | exists | `runtime/proof.py` (`<data_dir>/proof.json`, header) |
| Option B: a non-web task gets the whole data folder read-only and reads on demand | future | per-project opt-in, off by default, only after evidence that the planner misses files, with eval cases that measure folder exploration (D11) |

**How it serves the idea.** Pillar 1. The store makes every operation resumable and auditable. The data folder is where the person's sources live in a form they can read, version and keep, and the registry and the catalog are what let the planner give a task the sources it needs and nothing else. A task records the version it read (D12), so a result can be traced to its data. The drop remains for a file handed to one task. A snapshot written under `docs/` would enter every run, since a run without the web copies every versioned file and the documents under `docs/` (`runtime/workcopy.py`, limit L2, header lines 14 to 17): that is why the data folder is excluded from the copy and sources enter only as the copies a plan lists. The documents mirror gives the person Notion as the place to read and edit what the agents write.

**Boundaries.** The store, the runtime's data folder and its configuration never enter a run (L2). A hand-over never replaces a file (`runtime/drop.py` lines 96 to 97) and is refused for a task that is done, cancelled or running (lines 81 to 83); a source version is never replaced either. The mirrors write only what a manifest lists and never write over a page a person changed (`runtime/documents.py`, header). Third-party text in a source is data, never instruction.

Integration sources are refreshed on demand or by a routine (D12); a routine that refreshes a source writes a new version into the data folder, and the weekly flow's tasks, created later, receive the newest version of the source id they pin when they start.

### L5. Providers: tools and connections

**What it is.** The set of scripts that talk to the world outside the repository, under one contract, reached only from host code through one resolver. A provider holds its credential and reads it from the secret store; nothing of it enters a run.

**What it holds.**

| Component | State | Path |
|---|---|---|
| The contract (verbs, exit codes, dry run, ledgers) | exists | `providers/CONTRACT.md` |
| The resolver: a class to a provider script; and the one call used by the runtime | exists | `providers/resolve.py` |
| Secrets: the OS secret store, the one resolver | exists | `providers/secrets/resolver.py`, `contracts/secrets.md` |
| `integration:documents`: `local`, `notion` (verbs `stat`, `read`, `comments`, `write`, `notice`, `resolve`; `read` is `cmd_read`, line 589, in `VERBS`, line 707; the contract row is `CONTRACT.md` line 116) | exists | `providers/documents/` |
| `integration:issue-tracker`: `local`, `notion` | exists | `providers/issue-tracker/` |
| `reader:email`: `gmail` (the person's own Desktop OAuth client, the app published "In production" for personal use, the refresh token in the OS secret store) | exists | `providers/mailbox/`; setup in `providers/mailbox/README.md` (steps 3 and 4, lines 17 and 18) |
| `messenger:<platform>` (a class the runtime uses, not one a skill may require): `telegram`, `discord`, `whatsapp`, `whatsapp-cloud`, `whatsapp-twilio` | exists | `providers/messenger/`, `CONTRACT.md` line 110 |
| `publisher:<platform>`: `linkedin` | exists | `providers/publisher/` |
| `scheduler:job`: `launchd`, `systemd` | exists | `providers/scheduler/` |
| `store:runtime`: `sqlite` | exists | `providers/store/` |
| `integration:vcs`: `github` | exists | `providers/vcs/` |
| `converter:document`: a runtime-only class (like the messenger), run in the shared sandboxed container with no network, converting PDF, HTML, XLSX, CSV and DOCX to Markdown or CSV by adopted open tools | new (P4) | `providers/converter/` (the resolver finds a class by its folder, `providers/resolve.py`, header) |
| Shared sandboxed-container helper: no network, read-only root, capabilities dropped, no new privileges, limits on processes, memory, swap and CPUs, memory-backed `/tmp` and `/scratch`, an image never pulled at run time; one module in place of two copies | extracted (P0) | the two copies today are `providers/renderer/_docker.py` (`container_argv`, line 311) and `providers/transcriber/whispercpp.py` (`container_argv`, line 568), both on `feature/short-video` |
| A Notion page read as a source, by address: a function extracts the 32-character id, then the existing `read` verb is called | new (P4), on an existing verb | `providers/documents/notion.py` (`doc_id`, line 527, accepts only the id) |
| Google Drive as a source: the person's own OAuth client following the Gmail provider's pattern; scope `drive.file`, and the Google Picker so that only what the person picks is reachable; a source is a folder or a single file; native Google files (Docs, Sheets, Slides) are exported by the Drive API and then converted, other files are downloaded and converted; change detection for a refresh | new (P7) | `providers/` (folder not named by the spec); `providers/mailbox/` is the pattern |
| Write-back to Drive and Notion: the provider's write verbs, called only from the effect gate | new (P8) | `providers/documents/notion.py` (`write` exists in `VERBS`, line 707); the Drive write is new |
| File-output tools (PDF, XLSX, DOCX, CSV); HTML to PDF may reuse a headless browser in a container, such as the short-video renderer's (`providers/renderer/_browser.py` on `feature/short-video`, which P0 does not port) | new (P8) | `providers/` or `runtime/` (not named by the spec) |
| OneDrive and Jira | deferred | they wait for a real project that needs them (D13) |
| An MCP server adopted as a provider implementation, with read verbs, on the host; the agent receives files, never the tool | future | D15; no package builds one |

**How it serves the idea.** Pillar 3 (tools) and the connection half of pillar 1. Adding a source adds one folder and one script under one contract (`providers/CONTRACT.md`, class table), never an edit to a skill; the same contract is what an adopted MCP server would be wrapped in.

**Boundaries.** A provider is called from host code with a timeout and returns one JSON object; a run never calls one. A provider whose verb changes the world takes a dry run and an idempotency key (`providers/CONTRACT.md`, lines 66 to 74). An MCP server never runs inside a run (D15). Drive access is as narrow as the Picker lets it be (`drive.file`, not `drive.readonly`, D14).

A Notion page or a PDF is third-party text. The target skills' lines on external content name web pages, search results, listings, sites, reviews and research briefs, not a handed-over file (`skills/biz-market-analysis/SKILL.md`, line 49), and changing that line is an X change of each skill (a full test). Version 2 does not change the line: P4 adds converted-input eval cases with `--baseline` on two target skills, with a guard assertion that converted text is treated as data, so that the behaviour is measured (section 6, O2).

To verify 1: whether picking a folder under `drive.file` grants access to the files inside it; P7 starts with a spike that answers it. To verify 2: whether the Drive API exports Google Docs directly to Markdown, and the export size limit. To verify 8: whether the Picker's desktop flow works with the loopback page.

### L6. Adapters and models

**What it is.** The harness-specific layer: how one model is called inside the eval container, and what the model list and the price table say.

**What it holds.**

| Component | State | Path |
|---|---|---|
| Adapter for an eval: `run-prompt.sh` and `eval.json`, in two folders: `agents-dir` (hosted open-weight models through an agent runner, and an `ollama/<name>` id parsed at line 99) and the folder the gate file names as `strong_harness` (the reference model) | exists | `adapters/agents-dir/`, `adapters/<strong_harness>/` |
| Adapter for the runtime: `run-agent.sh` in `api` and in the folder `strong_harness` names | exists | `adapters/api/run-agent.sh`, `adapters/<strong_harness>/run-agent.sh` |
| The eval container, its egress proxy and its key proxies (one route file per tier, each with one `provider_only` pin; floor `keyproxy.json`, reference `keyproxy-strong.json`) | exists | `evals/container/`, `evals/executor.py` (`ROUTE_FILES`, line 73) |
| The model list: today `strong_model`, `floor_model`, their harnesses and pass-through variables, keyed by tier, plus a `models` map from id to aliases | exists | `evals/eval-gate.json` (lines 2 to 10 and 20 to 23; `models` at line 33) |
| The model list as a list: each model with its adapter, its key variables, its price source and its provider pin; the lab models (the maintainer's two) are the default list | new (P2) | `evals/eval-gate.json`, `evals/eval_status.py` (`GATE_FIELDS`, line 250) |
| A model-keyed key proxy and model-keyed routes, made in one execution-side measurement change, so that a new model never changes a fingerprinted file again | new (P2) | `evals/container/keyproxy/keyproxy.py` (the route's `provider_only`, lines 79 and 187), `evals/executor.py` |
| The eval image published to a registry by digest per platform, from a pinned definition; a lock file in the repository records the digests; the runtime pulls the image automatically on first use, with a message; evidence records the published digest | new (P2) | `evals/container/`, `evals/executor.py` (builds the image locally today, lines 191 to 193), a lock file |
| Price table with source and access date, replacing `adapters/api/prices.json` (six models) and the project's `model_prices` | new (P3) | `adapters/api/prices.json`; `runtime/project_config.py` (line 159); `runtime/costs.py` |
| The adapter of a model is the one its entry in the model list names | new (P2) | `evals/eval_run.py` |

**How it serves the idea.** Pillar 3 and the "different models" of pillar 2: a model enters the platform as an entry in a list and an adapter, and is then runnable. Which models a person may run is a matter of keys, not of code.

**Boundaries.** The container is the boundary: no host mode (`evals/executor.py`, header). A run holds a placeholder for its key; the key proxy forwards one provider's API path only, and after P2 pins the provider per model from the attested model list. The proxy is not a guarantee that nothing leaves: a run on the open network can hand data to another account of the same provider (`evals/executor.py`, line 35). A model on the person's own machine (`ollama/...`) is not reachable from the container and is left out of the lab (plan, section 8). Evidence is accepted from `linux/amd64` beside `linux/arm64`, the platform recorded on each line and both counted together unless results diverge (D20).

To verify 7: the size of the published image (estimated at 1 to 2 GB, not measured).

### L7. The proof lab

**What it is.** The place where a skill's standing on a model is measured, so that autonomy and the choice of model are decided by recorded evidence and never ticked by hand (`AGENTS.md`, principles 9 and 10).

**What it holds.**

| Component | State | Path |
|---|---|---|
| Runner: full test (every case, 3 runs, baselines), partial test (named cases), platform test; writes one evidence file per test event | exists | `evals/eval_run.py` |
| Runner option `--model <id>` to test a named model with the adapter its list entry names (today `--model` is the reference model's id: `evals/eval_run.py`, lines 6 and 19 to 24); anyone may test any model | new (P2) | `evals/eval_run.py` |
| Evidence: one line per run with model, adapter, score, case hash, measurement version, optional `cost_usd` | exists | `skills/<name>/evals/evidence/lab-*.jsonl`; `RUN_OPTIONAL` (`evals/eval_status.py`, line 734) |
| A usage field on the run line (input, output, cache read, cache write tokens) from the full model usage; the platform on each line; the published image digest | new (P2) | `evals/eval_run.py`, `evals/eval_status.py` |
| Status: a band, a cause, a gate and a score for every model that has evidence, by the same rules (`as_reference` line 1095, `skill_band` line 1965; the per-model loop at line 2074) | exists | `evals/eval_status.py` |
| Gate, completion, Y-change count and stored gate selected per model | new (P2) | `evals/eval_status.py` |
| Baseline per model: `--baseline-on <model>` runs it; `baseline_lines` reads the lines of the model it is given (line 1107) | exists | `evals/eval_run.py` (option parsed at line 551), `evals/eval_status.py` |
| Gate, threshold, tolerance, runs, baseline runs, margin | exists | `evals/eval-gate.json` (`threshold` 0.8, `strong_tolerance` 0.05, `runs` 3, `baseline_runs` 1) |
| The fixed grader, the measurement version, the floor, the fingerprint, the epochs | exists | `evals/eval-gate.json`; `FINGERPRINT_FILES` (`evals/eval_status.py`, line 557) |
| Local evidence: each person's own tests of any model, kept outside the workbench checkout so `git pull` never conflicts; they feed only that person's `auto`; a locally built image yields local-only evidence | new (P2) | a folder outside the checkout (not named by the spec) |
| The proof check compares the local image with the published digest | new (P2) | `runtime/proof.py` (`checks`, line 104) |
| Community evidence: the contributor runs the official reusable workflow, referenced by commit, in their fork's CI with their own keys; the workflow checks out the official code at that commit; GitHub attests the evidence file; the pull request carries both; the workbench's CI verifies without a model call (signature, `--signer-workflow` of the official workflow, the commit is in main's history, the digest matches) and records it as "community verified" | new (P10) | a reusable workflow and a verification step in the repository's CI (`.github/workflows/checks.yml` is today's CI; the new files are not named by the spec) |
| "Community verified": its own column per model, a per-contributor cap, counted for everyone's `auto` | new (P10) | `evals/eval_status.py`, `skills/<name>/evals/evidence/` |
| The maintainer's own score tests (lab runs of `eval_run.py`) move to the same attested CI | future (after P10) | the same workflow |

**How it serves the idea.** It is what makes "a score per model" true and what `route(auto)` reads. The status is the one source; the runtime keeps only a cache of it (`runtime/proof.py`, header). Because the grader is fixed, scores compare across models.

**Boundaries.** Lab evidence is written only from the container, only when the models, adapters and grader equal the gate file's, only when the fingerprint is the committed one (`evals/eval_run.py` lines 1837 to 1863; `evals/executor.py` line 81); after P2 it is accepted from the two listed platforms and from any model of the list. A run made by anything else is a trial and writes no lab evidence. A committed evidence file is never edited. No telemetry leaves a project (`AGENTS.md`, principle 8).

The provider host and the per-model pin live in the attested code, so a fake server cannot produce an attested line. The mitigations against what attestation cannot see are these: every completed run of the fork's workflow must be submitted and a gap in the run numbers is flagged (against cherry-picking); the pessimistic score and the per-contributor cap limit what one contributor moves; field evidence demotes a pair after three `failed` verdicts. The residual risks are cherry-picking across runs the contributor never submitted, and the provider's honesty about the model it served.

To verify 3: whether GitHub offers free arm64 hosted runners to public repositories. To verify 4: whether the identity signed for a reusable workflow called from a fork is the official repository's workflow, so that `--signer-workflow` pins it. To verify 5: whether artifact attestations require a public repository (the workbench is public, so it does not block). To verify 6: whether the subscription OAuth token of the reference model works in CI, for the later move of the maintainer's tests.

## 4. The run modes, end to end

Each walk-through names the component at each step and its state. Where a step depends on a third-party fact not yet confirmed, a `To verify n:` line says so.

### (a) "Do a market research on this idea", from the page

**Beforehand: a source.** The project has a data folder (D9). The person adds the survey spreadsheet on the page.

1. The upload follows the existing file route (`runtime/service.py`, `FILE_LIMIT` line 214). The streaming intake checks magic bytes and size and hashes the bytes (`media.receive`, `sniff`). State: extracted (P0), extended (P4).
2. `converter:document` runs in the shared container with no network and a read-only root and writes CSV or Markdown; the text is scanned for credentials after conversion (`runtime/workcopy.py`, `scan`, line 227), because compressed text in a raw file is invisible to a scan of the bytes. State: new (P4).
3. The import is written as an immutable version in the data folder: the original, the converted text and a manifest (origin, date, sha256). The catalog entry is built by code, with no model: name, type, size, date, sheets and columns with sample values, first headings and the person's optional description. A source over the size cap is refused with a warning. State: new (P4).

**With a chosen model.**

1. The person types the request in the Lobby and picks a model in the picker. State: the composer exists (`interface/js/views/lobby-composer.js`); the picker and the stored choice are new (P3).
2. The page calls the `request` operation (`runtime/ops.py` line 390), then `route` (line 1618). The router is one model run of the planning agent in the eval container (`runtime/router.py`; the row has `model: "without --flow"`). State: exists.
3. The router reads `skills/core-orchestrator/references/routing.md` and the catalog, and answers with one skill, `biz-market-analysis`, and the sources it chose: here the survey. `check_route` accepts the skill if it is in an enabled agent's pack (`runtime/router.py` line 77). If the request carries an `@mention`, that source is forced; if the planner is in doubt, it asks. State: the route exists; the choice of sources is new (P4).
4. `plan.combine` builds the plan; `plan_hash` (line 316) over the tasks gives the hash, and each task entry carries its source ids, so the hash covers the choice. A pending decision of kind `plan` appears with the plan card (`interface/js/cards/plan.js`), which lists the task's sources and highlights the task because it uses the web and receives a source. State: the plan exists; the sources in it and the highlight are new (P4).
5. The person approves with the hash (`ops.approve`, line 2051). Approving is their choice about the web task (D16). The task is created and is `ready`. State: exists.
6. A dispatch round (the scheduler's `work` job every 5 minutes, or the page's own loop) runs `dispatcher.decide`: the agent's mode and daily caps (`may_start`), then `admit` (slots, footprint). The footprint of `biz-market-analysis` is its declared outputs and updates minus the state file (`runtime/parallel.py` `footprint`, line 44). State: exists.
7. The dispatcher starts `run-task` as a child process. `run_task` reaches `proof.route` through `ops._route` (`runtime/ops.py`, line 351) with the model argument. State: the call exists (`runtime/ops_runs.py`, `run_task`, line 192); `route(model=<id>)` is new (P3). The skill requires the web, and the pair runs with the web only if a case of the skill was measured with it on that model; that check is wrong today (`runtime/proof.py` line 97, `web_measured`) and is fixed per model by P1.
8. The pair has no `reliable` band: the run is `supervised` and marked unproven (D8). If it has, the mode decides. State: new (P3).
9. `workcopy.entering` assembles the run copy. A web run sees only the artifacts its skill declares (L3), plus the copies of its chosen source versions, which the plan the person approved lists; the data folder itself is excluded. The version read is recorded on the task (D12). Before the copy the file's hash is checked against the manifest; a file the person changed after import is a new version made by them. `lab.run_skill` runs the adapter in the container; the key proxy holds the key. State: the container run exists; the source copy and the version record are new (P4).
10. `workcopy.returning` brings files back through the path rule and the credential scan; `docs/business/market.md` lands in the project; a pending decision of kind `review` opens. State: exists.
11. `review_action` holds it (supervised, or the skill is unproven: rule 5, line 336), the person reads the document on the Desk and accepts. If the project's documents manifest lists the file, `documents.push` (line 533) mirrors it to the platform. State: exists.
12. The run row records model, adapter, billing and cost recomputed from the token counts, which now come from the full model usage. State: exists (`runtime/costs.py`); the full usage is new (P2).

**With `auto`.**

1. The beforehand steps and steps 1 to 6 are the same; the picker value is `auto`.
2. `route(auto)` applies the rule in L3. The inputs are each model's band for this skill (`evals/eval_status.py` per-model rows, from the lab, the person's local tests and the verified community evidence), a key found, a price, and the mean usage of its with-skill runs. State: new (P3, with the usage field and the per-model gate of P2).
3. The image check compares the digest on this machine with the published one in the lock file; the runtime pulled it on first use with a message. A locally built image would make the evidence local-only. State: new (P2).
4. Until new runs add the usage field, no model has usage on a committed line, so `auto` returns the project's default model, `supervised`, with the reason shown. After new runs, it picks the cheapest `reliable` pair.
5. The rest is the same as with a chosen model.

### (b) A project flow: refresh a Notion page, then three skills, then a file

The flow `market-to-brand`, in the project, with one parameter: the Notion address. Tasks: an `ingest` step that reads the address; `biz-market-analysis` with the survey and the refreshed page as its sources; then `biz-icp-positioning`; then `brand-strategy`; then a file-output step that writes a summary workbook. Two area agents (business, brand). The artifact chain is `docs/business/market.md`, then `docs/business/icp.md` and `docs/business/positioning.md`, then `docs/brand/strategy.md` (the skills' `inputs` and `outputs`). All three skills require the web.

1. A project flow file defines the tasks. State: new (P6). The folder that holds it is not named by the spec (section 7). The flow pins source ids, not versions.
2. The person starts the flow by name on the page (`request --flow`, `ops.request` line 390) and gives the Notion address in the request. The flow's parameter is bound from the request text, and the bound value is covered by the plan hash. State: new (P6). The router does not choose a project flow; the person names it.
3. `plan.combine` builds the plan; the owner rule gives the step task an agent, and the pending decision lists the tasks, their sources and the highlight on each web task that receives sources. State: new (P5 owner rule, P6 steps, P4 sources). Today `agent_of(t["skill"])` fails on a step task (`runtime/plan.py` lines 593 to 595).
4. The person approves with the hash. The `ingest` task has no dependency and is `ready`; the skill tasks and the file-output task are `planned` under `depends_on`. State: new (P5).
5. The dispatcher admits the `ingest` task: it has a declared footprint from its kind (P1), and it is held with "no enabled agent owns the task" only if the owner rule is missing (P5). `ops_runs.dispatch` starts `cli.py run-step` as a child process, as it starts `run-task`. State: new (P5).
6. Ingest, Notion: the documents provider's `read` is called from the host with the credential from the secret store (`providers/documents/notion.py`, `cmd_read`, line 589). State: the verb exists; reading by address is new (P4). The returned Markdown is scanned (`workcopy.credential_findings`, line 94) and written as a new version in the data folder with its manifest. State: new (P4).
7. `biz-market-analysis` becomes `ready` when the ingest task is `done`. It is a web task that receives sources; the plan card highlighted it and the person approved the plan with that in view (D16). It reads the newest version of each source id it pins at the moment it starts and records the id, version and sha256 it read on the task (D29). State: new (P4).
8. `biz-icp-positioning` starts only after `market.md` exists; `brand-strategy` only after `icp.md` and `positioning.md`. Each passes through its review. State: exists. The chain is serial by artifact, so the flow's parallelism comes only from steps with no dependency; two agents matter for caps, modes and slots, not for speed.
9. Reviews: each is released by the agent's mode or held for the person. Unproven skills and mandatory milestones always hold (`review_action`, rules 5 and 6). State: exists.
10. The file-output step reads the Markdown of the chain and writes an XLSX (or CSV, PDF, DOCX) with adopted tools and no model, into the data folder or `docs/`. State: new (P8, with the registry of P5).
11. If the flow includes a write-back to a Drive file or a Notion page, it is an effect: the preview shows the exact content, the person approves it once, the effect executes, and it is recorded; before it executes, the target is read again and compared with what was read, and if it was edited meanwhile the effect stops and asks. State: new (P8). The real case for the write-back is chosen during development (D17).
12. A step that runs the person's own code (a project script) fits anywhere in the flow: it runs only if its exact hash was approved in the plan, in the sandbox, and writes only into the data folder as a new versioned source. State: new (P9).

### (c) A routine: every Monday at 08:00, refresh the source and run the weekly flow

1. The person creates the routine on the page or in the terminal: a schedule, a target (a flow or a step) and its arguments. Creating it generates the plan of that target, and the person approves the plan's hash together with the routine, which is stored and approved by the sha256 of its exact content. State: new (P6). The spec gives no schedule format and no time zone rule (section 7). A routine cannot be created from MCP; from messaging only if the person granted that in `channels.messaging`.
2. The scheduler job `work` runs the dispatch round every 5 minutes; the round calls `_ticks` (`runtime/ops.py` line 2444), which calls the `routines` handler's `tick`. State: the tick exists; the handler is new (P6). The handler must be configured under `handlers` in the project's `runtime.json` and have an enabled agent (`_ticks`, lines 2446 to 2455).
3. The handler selects the records that are due, as `published_posts.due` does. Each fire counts against the agent's daily caps (`autonomy.may_start`, line 285). State: new.
4. At the fire the handler regenerates the plan. If its hash equals the approved one, the tasks are created without asking; if not, the routine stops and asks, and messaging notifies the person. A new version of a source does not change the plan, which pins the source id. State: new (P6, D24).
5. The first task is a step: `ingest` re-reads the Notion page (or the refresh of a Drive source) and writes a new version into the data folder. The weekly flow's tasks read the newest version when they start and record its id, version and sha256 (D29). State: new (P4, P5, P7).
6. The skill tasks run as in (b), with one difference: a task that receives sources runs without the web (D16), and a skill that requires the web never runs without it silently (D27). The flow of (b), written by hand, has web skills that receive sources, so as a routine target the flow check refuses it, at creation and at each fire's plan, and tells the person to split it into a web task without sources and a task with sources and no web; the weekly flow of this routine is written that way, so its tasks that receive the refreshed source use skills that do not require the web. A plan the planner makes for a request is split by the planner instead. State: new (P6).
7. A routine runs without a person only on pairs that are `reliable` and with the agent in `autonomous` mode; otherwise it waits at the first review and messaging notifies the person (D24 rule 3). Effects still need approval of their exact content, unless a standing policy accepted in the terminal covers them. State: new (P6).
8. A free-text routine ("every Monday, research X") never runs alone: each fire produces a plan the person approves. State: new (P6).
9. The person is told through the messaging channel (cards exist: `runtime/messaging_cards.py`) and reads the result on the page.

**A routine that is plain code.** A routine's target may be a step: `ingest` to refresh a source, a file-output step, or a project script. The project script is the person's own code, approved by its exact hash, run in the sandbox with no credentials and a read-only root, with the network off unless declared destinations entered the approved hash, writing only into the data folder as a new versioned source, with no direct effect (D25). Any side effect leaves through the effect gate. State: new (P9).

### (d) A contributor submits community evidence

The scenario: a contributor wants the workbench to know how a skill performs on a model the maintainer has not tested, and wants everyone's `auto` to benefit.

1. The contributor runs the model locally first, with their own keys. Those runs are local evidence (D18): kept outside the workbench checkout, feeding only their own `auto`. State: new (P2).
2. To share the result, the contributor forks the repository, puts their provider key in the fork's CI secrets and calls the official reusable workflow, referenced by commit. State: new (P10).
3. The workflow checks out the official code at that commit, not the fork's code, pulls the published eval image by the digest in the lock file, and runs `eval_run.py` for the skill and the model. The provider host and the model's pin come from the attested code, so the run cannot be pointed at another server. The platform of the runner is recorded on each line (D20). State: new (P10, with P2). To verify 3: whether GitHub offers free arm64 hosted runners to public repositories; amd64 is accepted either way.
4. The run writes an evidence file under the same rules as a lab file: one line per run, closed vocabulary, no free-text field. GitHub attests the file. State: new (P10). To verify 4 and 5: the signed identity of a reusable workflow called from a fork, and whether attestation needs a public repository.
5. The contributor opens a pull request with the evidence file and its attestation. Every completed run of the fork's workflow must be submitted; a gap in the run numbers is flagged. State: new (P10).
6. The workbench's CI verifies without a model call: the signature, that the signer is the official workflow (`--signer-workflow`), that the commit is in main's history, and that the digest matches the evidence. The existing validator checks of evidence files still apply. State: new (P10); the CI exists (`.github/workflows/checks.yml`).
7. A verified file is recorded as "community verified": a column of its own per model, with a per-contributor cap (the contributor is the author of the commit that added the file, as for field evidence). It counts for everyone's `auto`. State: new (P10).
8. The rest of the protection: the pessimistic score and the cap limit what one contributor moves; field evidence demotes a pair after three `failed` verdicts. Cherry-picking of runs the contributor never submitted, and the provider's honesty, are residual risks the design cannot remove.
9. Later, the maintainer's own score tests move to the same attested CI, so that lab evidence and community evidence come from one verified path. State: future (after P10). To verify 6: whether the subscription token of the reference model works in CI.

## 5. The three pillars, mapped

| Pillar | Layers that carry it | Real after the plan | Still deferred, and its trigger |
|---|---|---|---|
| 1. Data sources and persistence | L4, L5, L3 (ingest and file-output steps), L2 (flows, planner) | A SQLite store (exists). A mandatory data folder the user defines, with guardrails, a source registry, immutable versions and a rich catalog built by code. Uploaded files and Notion pages by address; Google Drive in general with `drive.file` and the Picker. PDF, HTML, XLSX, CSV and DOCX converted to Markdown or CSV in a sandbox and scanned. The planner gives a task only the sources chosen for it, and the task records the version it read. File outputs (PDF, XLSX, DOCX, CSV) and write-back to Drive and Notion as approved effects. A task's file drop (exists). | OneDrive and Jira (a real project that needs them, D13). Indexing and RAG (a real case; a source over the cap is refused). Option B, the whole folder for non-web tasks (a per-project opt-in after evidence that the planner misses files, with eval cases for folder exploration). Messaging attachments (not in P0 to P10). The real case for write-back (chosen during development, D17). |
| 2. The brain | L2, L3, L6, L7, L1 | A router that also chooses sources, plans by hash, skill tasks in a container with a model the person names or `auto` (the cheapest `reliable` pair) chooses. Step tasks on a resumable engine (kinds `ingest`, file output, project script). Flows that mix steps and skills, workbench and project, with parameters. Routines under D23 and D24. A published band for each skill, model and adapter, with local and community evidence. | Agent memory (backlog R2). A persona per agent (plan, section 9). The short-video kind `media` (the side package). A model on the person's own machine in the lab (the container reaches only hosted providers). The maintainer's tests in the attested CI (after P10). |
| 3. Tools | L5, L6, L1 | Providers under one contract, host side, with the converter, Drive and write-back added. Adapters for hosted models, a model-keyed key proxy. An MCP server of the operations layer (exists). A published image per platform. A price table with source and date. A project script as a step. | MCP as a client inside a run (rejected, D15). MCP servers adopted as host-side provider implementations with read verbs (`future`, D15, no package). An Instagram or TikTok publisher (plan, section 9). OneDrive and Jira providers. |

The modes: (a) is real once P1, P2 and P3 are done, with sources once P4 is done; (b) needs P4, P5 and P6, with outputs from P8, Drive from P7 and project scripts from P9; (c) needs P5 and P6, and gains Drive refresh from P7.

## 6. Contrast with the plan: errors, gaps and risks (history, with their resolution)

The verified findings of version 1. An error means the plan said something false or self-contradictory; a gap means the idea was unreachable without something the plan lacked; a risk is a hazard the plan did not name. Each was checked by the independent reviewer on another model, read-only, on this branch; the findings F1, F3, F4, F6 and F15 were re-checked by the supervising session; every line number was re-read at `d3e60770`. The class is the letter of the identifier, E, G or R; the reviewer's number F is kept. The text of each finding is version 1's; the last line of each is new, and says which package and decision of version 2 resolved it, and what only narrowed.

### E1 (F1). The key proxy cannot be pinned per model by changing one file

- **Finding.** The old package 4 said `evals/container/keyproxy/keyproxy.json` was the one fingerprinted file it touched. The key proxy reads one `provider_only` per route (`evals/container/keyproxy/keyproxy.py` lines 79 and 187; `keyproxy.json`, line 6); routes are keyed by tier (`evals/executor.py`, `ROUTE_FILES`, line 73); the event line's `upstream` is written for the floor tier only (`evals/eval_run.py` lines 2492 to 2496). A pin per model therefore means `keyproxy.py` reads the model from the request body, and `executor.py` (in the fingerprint) changes too.
- **Effect.** Every new OpenRouter model would be a measurement change with its own epoch. "A model is a line in a list" (L6) is false for hosted models that need a pin.
- **Correction.** Make the key proxy and the routes model-keyed once, in one execution-side change; read the pin per model from the gate file's model list (outside the fingerprint). The evidence line already records `upstream`.
- **Resolved in version 2 by:** P2, D18 (the model-keyed proxy and routes in one execution-side change; the pin per model in the model list; adding a model changes no fingerprinted file).

### G1 (F2). "Anyone may test any model" is not reachable

- **Finding.** `scratch_reason` writes evidence only when the strong and floor models, their adapters and the grader equal the gate file's (`evals/eval_run.py` lines 1855 to 1862) and the fingerprint is the committed one (line 1863); `model_id` maps an unlisted model to `unknown` (`evals/eval_status.py` lines 540 to 548); evidence is written only on `linux/arm64` (`evals/executor.py` line 81; `evals/eval_run.py` lines 1837 to 1839).
- **Effect.** A contributor would have to fork `measurement_version` and the epochs (conflicts at the next pull). On x86, such as a 24/7 server, no evidence can be written at all. Decision 2 and the "auto" for a new model rest on it.
- **Correction.** State that testing a model is private-only until community evidence exists; apply the correction of E1 so a new model is not a measurement change; decide whether amd64 evidence is wanted.
- **Resolved in version 2 by:** P2 (the model list, `--model`, local evidence outside the checkout: D2, D18), D20 (amd64 accepted beside arm64, the platform on each line), P10 (D19: community evidence reaches everyone's `auto`).

### G2 (F3). The proof holds only on the machine that measured it

- **Finding.** `runtime/proof.py` `checks` (lines 104 to 115) marks a pair not proven when the image digest on this machine is not in the evidence's images; the image is built locally (`evals/executor.py` line 193).
- **Effect.** On any other machine nothing is `reliable`: `auto` has no candidate and every run is `supervised`. A server and a laptop of the same person disagree.
- **Correction.** Publish or pin an image digest, or derive an identity from the definition's hash plus the platform that travels; state the behaviour in the auto rule.
- **Resolved in version 2 by:** P2, D21 (G2): the image is published by digest per platform, the lock file records the digests, the runtime pulls on first use, evidence records the published digest, the proof check compares it. A person only checks out main.

### E2 (F4). A routine's plan has no unattended approval

- **Finding.** The plan said a plan made by a routine "is still approved by hash, unless a standing policy covers it". No such mechanism exists: standing approvals cover effects only (`runtime/autonomy.py`, `covers`, line 358; `runtime/ops.py`, line 1456); `review_action` rule 1 holds every plan (`runtime/autonomy.py`, line 327); a plan is approved by a person's channel (`runtime/ops.py`, `approve`, lines 2051 to 2075).
- **Effect.** Mode (c) is not unattended; a Monday 08:00 routine waits for a person to approve its plan.
- **Correction.** The routine record, approved by hash, carries the plan hash of its flow or step with its arguments. At fire time tasks are created only if the regenerated hash equals the approved one. A request-text target never runs unattended, and the plan says so.
- **Resolved in version 2 by:** P6, D24 rules 1 and 2, D23 (the plan approved with the routine; regenerated and compared at each fire; a free-text routine becomes a plan to approve at each fire).

### E3 (F5). The plan keeps one deciding model against its own decision 1

- **Finding.** The old package 4 kept "the model that decides the repository's gate". Concepts that still assume one reference model: `AGENTS.md` line 154 (the band is computed on it) and line 159 ("only the reference model's band decides a skill's standing"), `done`, the inventory's tables (`docs/inventory.md`, line 214 introduces them), the field signal "on the reference model" (`AGENTS.md` line 156), and principle 12 with backlog T23 as the battery's trigger (`docs/backlog.md`, lines 83 to 88). In code: the stored-gate fallback for the configured reference (`evals/eval_status.py` lines 1180 to 1186), `complete` computed on the reference (`evals/eval_run.py` line 2507), billing history keyed to the floor model (`runtime/autonomy.py`, `history_billing`, line 220), and the fallback to the reference in `proof.route`.
- **Effect.** T23's workarounds wait for a change of reference model that will no longer exist.
- **Correction.** A per-model `done` and gate; a new trigger for a battery (a change of the lab default list or of the grader); the inventory table per model; principle 9 rewritten to match.
- **Resolved in version 2 by:** P2 (drops "the model that decides the repository's gate"; the gate and completion per model) and P3 (`AGENTS.md` principle 9, the reliability-model document, `evals/README.md` and principle 12's battery trigger rewritten without the tiers; the inventory table per model; T23's workarounds get a new trigger).

### E4 (F6). "This already holds for the two models" is wrong

- **Finding.** The gate takes the newest full test of the major version with no filter on model (`evals/eval_status.py` lines 1133 to 1136) and the Y-change count since it reads the same test (`y_changes_since`, line 1888; used at line 2034).
- **Effect.** It is hidden today because both models run in one event. With events per model, a full test on model Z resets another model's Y count or moves its `X.Y`.
- **Correction.** Select the gate events, `complete`, the Y count and the stored gate per model, from the events whose header lists that model; add it to package 4's "done when".
- **Resolved in version 2 by:** P2 (gate, completion, Y count and stored gate selected per model; it is in the package's "done when").

### E5 (F7). Data is handed to the wrong side of the step

- **Finding.** The old package 3 handed data "to each task in the step's `depends_on` closure"; `depends_on` points upstream, and the data must reach the step's dependents. Package 3 also came before step tasks existed, so it had no target.
- **Effect.** Converted files reach nobody in a flow.
- **Correction.** The person names the receiving task; from the step engine on, the transitive dependents receive it.
- **Resolved in version 2 by:** P4, D11, D12 (a task receives copies of the source versions chosen for it by the planner, shown in the plan; the drop-closure rule is replaced).

### G3 (F8). Data does not reach tasks created later, and a refreshed source has no home

- **Finding.** `hand_over` copies once and refuses a replacement (`runtime/drop.py` lines 96 to 97); a task created later never receives it; OPEN-1 put data only in drops.
- **Effect.** A routine that refreshes a source each Monday has nowhere to put the new version, and a flow's later tasks cannot read it.
- **Correction.** A project source store and a declared receive rule.
- **Resolved in version 2 by:** P4, D9, D10, D12 (the data folder the user defines, with the registry and immutable versions; a refresh is a new version; a task records which version it read). The store is the user's folder, not a directory inside the workbench's local folder.

### G4 (F9). The planner, router and channels do not take step tasks, flow parameters or attachments

- **Finding.** The router returns one skill or one flow from the routing table (`runtime/router.py` lines 59 to 93, `skills/core-orchestrator/references/routing.md`); project flows are invisible to it (adding them is a Y change of `core-orchestrator`). `plan.combine` calls `agent_of(t["skill"])` and reads the skill's metadata for every task (`runtime/plan.py` lines 163 to 173 and 595 to 603), so a step task fails at planning. Flow arguments are fixed. Messaging has no attachment (`runtime/messaging_inbound.py` lines 7 to 17), no flow choice and no model choice.
- **Effect.** A Notion address typed in a request cannot become a step argument; a PDF cannot be sent from a phone; mode (b) is startable only by naming a flow on the page or in the terminal.
- **Correction.** Flow parameters bound from the request and covered by the plan hash; an owner rule in `plan.py`; a stated path for a router-started ingest (or say that the person names the flow); messaging attachments into the source store.
- **Resolved in version 2 by:** P5 (the owner rule in the planner and the dispatcher), P6 (flow parameters bound from the request and covered by the plan hash; project flows), P4 (the planner chooses sources). **Only narrowed:** the router does not choose a project flow, so the person names it; messaging still carries no attachment, flow choice or model choice, so a file, a model or a flow is chosen on the page or in the terminal. No package of P0 to P10 changes either; they are a later evolution of the messaging channel, after P6 (D28).

### R1 (F10). Ingested content can leave through web runs

- **Finding.** `biz-market-analysis`, `biz-icp-positioning` and `brand-strategy` all require the web. A web task takes a drop because the file is the person's own choice, with a warning (`runtime/drop.py`, header lines 25 to 29); the proxy "is not a guarantee that nothing leaves" (`evals/executor.py` line 35).
- **Effect.** An automatic or routine ingest puts third-party text into an open-network run with no per-file choice: the channel the plan rejected as path C.
- **Correction.** Ingested data enters a web task only with the person's approval of that hand-over, or the task runs without the web.
- **Resolved in version 2 by:** P4 and P6, D16 and D27 (manual use: the plan card highlights a web task that receives sources, and approving the plan is the person's choice; a routine: a task that receives sources runs without the web, mixed work is split by the planner, and a hand-written flow that gives sources to a web task is refused as a routine target with a message to split it). **Only narrowed:** in manual use the web task still takes the person's data to the open network on their approval, and the proxy is still not a guarantee that nothing leaves.

### G5 (F11). A routine that is plain code is not offered

- **Finding.** Only kinds registered in the workbench exist as steps (the old package 5). Project or user code cannot run.
- **Effect.** Mode (c) "plain code" is limited to refreshing and registered kinds.
- **Correction.** A "project script" step kind with limits that satisfy principle 11: code approved by the sha256 of its exact content, run in the sandbox with no network and a read-only root, outputs only into the source store, no credentials, side effects through the effect gate; or a recorded decision against that part of mode (c).
- **Resolved in version 2 by:** P9, D25 (network off by default and declared destinations inside the approved hash; outputs only into the data folder as a new versioned source).

### R2 (F12). An overnight flow still stops at reviews

- **Finding.** `review_action` holds unproven skills (rule 5, line 336) and mandatory milestones (rule 6); a model named without evidence is supervised (decision 8).
- **Effect.** A routine on an unproven pair, or in a mode below `autonomous`, stops at its first review.
- **Correction.** State that a routine runs unattended only on pairs that are `reliable` on this machine (see G2) and in `autonomous` mode.
- **Resolved in version 2 by:** P6, D24 rule 3 (tasks proceed without review only on `reliable` pairs with the agent in `autonomous` mode; otherwise the routine waits at the first review and messaging notifies).

### E6 (F13). Auto under-prices the reference model

- **Finding.** The `usage` total of `timing.json` leaves out the subagents (13.7 million tokens against 25.6 million in the rehearsal, `docs/backlog.md` line 84); `runtime/costs.py` `usage_of` reads `usage` of `raw.json` (line 91; whether that field also leaves them out was not tested). The old package 1's `web_measured` fix was not per model. A never-configured OpenRouter model under the one-provider pin either fails or runs unpinned.
- **Effect.** `auto` prefers the reference model on a number that is too small.
- **Correction.** Read usage from the full model usage; make `web_measured` per model; refuse, or say clearly, when a named model has no pin.
- **Resolved in version 2 by:** P2 (a usage field on run lines from the full model usage; a provider pin in each model's entry) and P1 (`web_measured` requires evidence and is per model). **Only narrowed:** whether the `usage` field of `raw.json` also omits subagents was not tested (section 7); P2 reads the full usage, but a number cannot be called right until it is compared with the provider's own count.

### G6 (F14). File outputs are missing

- **Finding.** Nothing produces XLSX, CSV or PDF for the person; writing to a Notion page that is not a mirrored document is not covered (`documents.push` mirrors manifest documents only); PDF tools for the run image wait on T23. None of it was in the plan's section 9. The Jira and Google deferral (OPEN-2) is legitimate sequencing.
- **Effect.** The pillar names HTML, PDF, XLS and CSV as files, and only the reading half was planned.
- **Correction.** An output-converter step, or list it in section 9 with its trigger.
- **Resolved in version 2 by:** P8, D17 (a file-output step by adopted tools, and write-back to Drive and Notion as an effect with the edit-since-read check).

### E7 (F15). Packages 1, 3 and 5 depend on code that is not on main

- **Finding.** `runtime/media.py`, `runtime/pipeline.py`, `runtime/ops_pipeline.py`, `runtime/video.py`, `providers/renderer/_docker.py` and `providers/transcriber/whispercpp.py` are absent on `origin/main` (checked with `git ls-tree`). The old package 3 reused `receive`, `sniff` and `ENV_KEEP` without listing their port. Package 1 gave a footprint "from its kind" but kinds arrived in package 5. Package 5's "done when" needed the short-video rebase (44 conflicting files, plan section 5) and was sized M without it. Package 2's helper could not reach main until that rebase.
- **Effect.** The order 1 to 6 could not be followed from `main` as written; the sizes were understated.
- **Correction.** Explicit ports in packages 1 and 3; package 5 depends on a short-video rebase package (L), or its second consumer is measured with ingest alone.
- **Resolved in version 2 by:** P0 (the generic pieces ported first: the step task, the intake and item store `receive` and `sniff`, `ENV_KEEP` in `runtime/ops_pipeline.py` line 70 on the branch, the container helper), P1 (a declared footprint until kinds exist), P5 (its second consumer is ingest, so it does not wait for the rebase), and the side package (the short-video rebase, off the critical path).

### R3 (F16). Package 4 reshapes the gate file while T24 is open

- **Finding.** Backlog T24 (`docs/backlog.md`, lines 89 to 91) says the validator reads old evidence against the current gate file. `evals/eval_status.py` checks each model id of an event line against the current list (`_model`, line 760) and requires `strong` in the event header (`event_line_problems`, lines 773 and 795).
- **Effect.** Changing the gate file's shape could invalidate every committed evidence file in CI.
- **Correction.** Do T24 before package 4.
- **Resolved in version 2 by:** P2 (T24 is its first step).

### Corrections to the plan's own citations

Found while re-reading every line for version 1 of this document. They do not change a conclusion.

| Where in the plan | The plan says | Real, at `d3e60770` |
|---|---|---|
| Section 2, flows | five files in `flows/` | six: `flows/short-video.json` is on main |
| Section 2, Notion read | `cmd_read` line 584, `VERBS` line 699, `doc_id` line 522, `retrieve` line 530 | 589, 707, 527, 535 (`providers/documents/notion.py`) |
| Section 2, mirror | `push` line 440, `pull` line 410 | 533 and 503 (`runtime/documents.py`) |
| Section 4, hold | `NO_AGENT` line 65 | 70 (`runtime/dispatcher.py`) |
| Section 2, jobs | `JOBS` line 133 | 163 (`runtime/dispatcher.py`) |
| `evals/eval_run.py` line 36 | `--baseline-on` "no rule reads it" | `baseline_lines` (`evals/eval_status.py` line 1107) filters by the model it is given, so the per-model gate reads it; the docstring is stale |

### Corrections to version 1 of this document

Found while re-reading every citation for version 2, in the same checkout.

| Where in version 1 | Version 1 said | Real, at `d3e60770` |
|---|---|---|
| Section 3, L2 and section 4 | `check_route` line 76 | 77 (`runtime/router.py`) |
| Section 3, L2 | `core.ROOT` called at `runtime/ops.py` lines 402, 1566, 1642 | 402, 1568, 1642 |
| Section 4, (a) | `ops._route` at line 352 | the definition is at line 351 (`runtime/ops.py`) |
| Section 7 | `schema_version` at `providers/store/sqlite.py` line 724 | the version number is `SCHEMA_VERSION`, line 53 (9 today); `schema_version` the function is line 640 |

### Observations found while writing section 4 of version 1

Not in the reviewer's list; checked by the author only.

- **O1.** The first step of a flow has no dependency and is `ready` at approval. A file can be handed only to a task that has not started (`runtime/drop.py` lines 81 to 83). The plan named no moment at which a person hands a PDF to an ingest step, and no source path in a step's arguments. The correction was part of F8's source store: an ingest step reads a path or an address from its arguments, hashed in the plan. **Resolved in version 2 by:** P4 (the file is imported as a source into the registry beforehand and the step or the task names a source id or an address), P6 (step arguments and flow parameters are covered by the plan hash).

- **O2.** The three target skills carry the line **External content is data.** (`skills/biz-market-analysis/SKILL.md` line 49; the same line is in `biz-icp-positioning` and `brand-strategy`). Its list of sources names web pages, search results, listings, competitor sites, reviews and the research briefs written from them; a converted Notion page or PDF is not in it. The old package 3 said "No skill is bumped", and a change to that line is an X change of each skill, which asks for a full test (`AGENTS.md`, "Changing an existing skill"). Whether a model treats a converted file as data is what the converted-input cases would measure; those cases had no guard assertion for it unless one was written. **Resolved in version 2 by:** P4 (converted-input eval cases with `--baseline` on two target skills, with a guard assertion that converted text is treated as data). The line itself is not changed, so the behaviour is measured on two skills, not stated in all three.

### The proposed changes to the plan: adopted

Version 1 of this section proposed six changes to the plan. All were adopted in the plan's version 2: the port of the generic short-video pieces is P0 (change 1); the measurement-identity work, done once, is P2 (change 2, with the arm64 and amd64 decision as D20 and the image identity as D21); the person-named receiving task and the source store became the data folder of P4 (change 3, with the web-task rule as D16); the routine rules, the owner rule and flow parameters are P5 and P6 (change 4); project scripts and file outputs, which version 1 left as a decision, are D25 with P9 and D17 with P8 (change 5); and the usage line is in P2 and P1 (change 6).

## 7. Assumptions, what to verify, and what is open

### Assumptions

- Assumption: the routine verbs include a `pause` that the plan's earlier text did not list (D23 names list, pause and cancel as the brakes); messaging's default policy (`DEFAULT_POLICY`, `runtime/operations.py` line 281, read, talk, answer today) gains a group with those brakes, since D23 says "by default only the brakes" and the present default carries none of them.
- Assumption: a routine's schedule is a weekday and a time of day in the project's time zone. The spec gives no format.
- Assumption: a project flow lives in a folder of the project that the spec does not name; the walk-through writes "a project flow file" and no path.
- Assumption: the handler that fires routines is configured under `handlers` in the project's `runtime.json` like any handler, since `_ticks` reads that key (`runtime/ops.py` lines 2446 to 2455). The spec does not say how it is enabled.
- Assumption: a routine fires at the first dispatch round at or after its time, so within the period of the scheduler's `work` job; `contracts/runtime.md` line 312 says 5 minutes, and the period set on a person's machine was not checked.
- Assumption: the router run uses the project's default model once the tiers leave; the spec does not say.
- Assumption: the planning run that chooses sources is the router run of today (`runtime/router.py`), which receives the catalog in its input and names the sources in its reply; the spec says "the planner chooses" and that teaching it is a Y change of `core-orchestrator`.
- Assumption: the plan hash covers the sources because each task entry carries its source ids (`plan_hash` is over the tasks, `runtime/plan.py` line 316); the spec says the choice is shown in the plan the person approves by hash.
- Assumption: sources enter a run as copies in a folder of the run copy, with the converted text; whether the original also enters is not stated by the spec.
- Assumption: the write-back check "nobody edited the target since it was read" re-reads the target and compares its content hash with the sha256 in the manifest of the version that was read; the spec states the check, not the mechanism.
- Assumption: the converter's tools, the ingest kind and the container helper behave as the spec states (adopted open tools convert the formats; the limits are those of the two existing providers). Version 1 named poppler, pandoc and an XLSX reader. No converter was run. The converter and the project script share the sandboxed container helper; its present rule that an image is never pulled at run time (header of `providers/renderer/_docker.py` on `feature/short-video`) is kept, and the runtime's pull of the eval image on first use (D21) is a separate step before a run.
- Assumption: how the "community verified" column enters a pair's band is not fixed by the spec (it counts for everyone's `auto`, with its own column and a cap); P10 decides the combining rule.
- Assumption: the location of the local evidence outside the checkout is chosen in P2; the spec requires only that it be outside the workbench checkout.
- Assumption: the source verbs of L1 list the channels the spec does not state; the table of operations decides them when P4 and P7 are built.
- Assumption: whether the `usage` field of `raw.json` also omits subagents (`runtime/costs.py` line 91) was not tested; the backlog states it for the `timing.json` total.
- Assumption: the file names that this document gives to new elements (`runtime/steps.py`, `runtime/handlers/routines.py`, `providers/converter/`) are the plan's; the modules that hold the ingest functions, the file-output kinds, the project script, Drive and the community workflow are not named by the spec and are not named here.
- Assumption: P8 reuses the short-video renderer's headless browser only by porting it (P0 does not, `providers/renderer/_browser.py` is on `feature/short-video`).
- Assumption: P5 is described in the spec as registering the `ingest` and file-output kinds and P8 as building the file-output step; this document places the build in P8 and the registry in P5.

### To verify

Third-party facts that were not confirmed. None is stated as fact above.

1. Whether picking a folder under `drive.file` grants access to the files inside it. P7 starts with a spike; if not, the Picker is multi-select of files and the maintainer is asked about `drive.readonly` for folder sources.
2. Whether the Drive API exports Google Docs directly to Markdown, and the export size limit (recalled as 10 MB).
3. Whether GitHub offers free arm64 hosted runners to public repositories.
4. Whether the identity signed for a reusable workflow called from a fork is the official repository's workflow, so that `--signer-workflow` pins it.
5. Whether artifact attestations require a public repository (the workbench is public, so it does not block).
6. Whether the subscription OAuth token of the reference model works in CI, for the later move of the maintainer's tests.
7. The size of the published eval image (estimated at 1 to 2 GB, not measured).
8. Whether the Picker's desktop flow, which Google documents as returning through a callback URL, works with the loopback page.

### What is still open

Nothing from OPEN-1 to OPEN-6 remains open. What remains open is the list "To verify" above and the real cases that D17 leaves to be chosen during development (the file output and the write-back).
