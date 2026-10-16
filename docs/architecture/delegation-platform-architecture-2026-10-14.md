# Delegation platform: the architecture after the plan

Version 3, of 2026-10-14, on `origin/main` at `d3e60770`. Describes the system as it would be once the packages of the plan's version 3 are done: P-1, SEC, P0 to P10 (P2 as P2a to P2d) and P-OPS (the side package, the short-video rebase, is off this path). Nothing new in it is built. Section 6 keeps the findings F1 to F16 of version 1 with how version 2 resolved each, and adds the findings of the two review rounds of 2026-10-14 with how version 3 resolves them; they were checked against the code by independent reviewers and by the supervising session.

Companion of [the plan](delegation-platform-plan-2026-10-14.md). The plan says what to build and in which order; this document shows the whole once it is built. Package numbers (P-1, SEC, P0 to P10, P-OPS) and decision numbers (D1 to D37) are those of the plan's version 3.

**How to read the markers.** Every element carries one state.

- `exists`: on `origin/main` at `d3e60770` today. The path is given, with a line where one was read.
- `extracted (Pn)`: exists on `origin/feature/short-video` at `6794905e`, absent from `main`, and moved to `main` by package `Pn`. Its path and line are on that branch.
- `new (Pn)`: built by package `Pn`. Nothing of it exists. It is written in the present tense because the text describes the target, never because it is built.
- `future`: named by a decision, built by no package of the plan, and only after a stated trigger.
- `deferred`: waits for a real project that needs it.

A sentence marked "After the plan" describes the target. A line that starts `To verify n:` marks a fact about a third-party service that was not confirmed; `n` is its number in section 7. No other open gap remains in the target. Every main-side line number below was read in this checkout, which is `d3e60770` plus the plan's commits. Several of them differ from the plan's, which read main at `9bc9b863` and did not re-number them (section 6, "Corrections to the plan's own citations"), and a few differ from earlier versions of this document (same section).

**Words that are easy to confuse.** The *sources folder* is the folder of D9, key `sources_dir`, where imported sources live. The *data folder* of the runtime is a different, required folder: `data_dir` in `runtime.json` (`runtime/project_config.py`, lines 12 and 88), where the runtime keeps run folders, locks and the proof file; it stays outside every repository and it is never the sources folder. A *workflow* and a *flow* are the same thing: a file of tasks and their written dependencies. The *planner* is the router run. A *step kind* (ingest, file output, project script), an *effect kind* (what an approval covers) and a *pending-decision kind* (plan, review, effect) are three different lists.

## What changed from version 2

Version 2 described the system after ten packages (P0 to P10) and twenty-nine decisions. Two review rounds of 2026-10-14 (round 1: S1 to S10 and I1 to I6; round 2: Q1 to Q6 and M1 to M6) and the maintainer's decisions after them produced version 3: ten decisions (D30 to D39; D38 and D39 were taken when the maintainer accepted two points left pending, and complete version 3) and a package list of P-1, SEC, P0 to P10 (P2 split in four) and P-OPS. The differences that matter to the architecture:

- **The folder is the sources folder (D30).** Version 2 called D9's folder "the data folder", the same words as the runtime's `data_dir`. It is now the *sources folder*, key `sources_dir`, with extended guardrails (S6): dedicated, mode 0700, disjoint from `data_dir`, `store_db`, the workbench checkout and the local evidence folder; container outputs go to a size-capped tmpfs and the host copies back only regular files; a file changed outside the runtime is never used unattended; the catalog is built only from converted output.
- **A routine always targets a workflow (D31, D32, D33).** Free-text routines no longer exist (D24 rule 2 and D16's planner split, as far as routines go, are superseded). A single step or a project script is a one-step workflow. The web-plus-sources mix is settled when the workflow is created: the flow check refuses it and offers a code-made split for the two skills that accept a research brief. A free-text request planned once may be saved as a workflow and scheduled on the same screen. Workflows take date variables filled at fire time.
- **Autonomy: by proof in `auto`, by consent with a fixed model (D34, D36, D38).** Scores inform the person and are the basis of `auto`; they do not gate a model the person chose. Community evidence counts for choice and for manual use and never by itself releases a run unattended. Principle 9 of `AGENTS.md` is reworded in P3. In manual use the consent is the setting of an agent's model while the agent is `autonomous`, given once with the same warning (D38); in `auto`, manual use keeps D34's rule.
- **The routine's approved hash is wider (D35).** It covers each skill's `X.Y`, the image digest, the project script's sha256 and declared destinations, the consent, and, for `auto`, the approved provider set.
- **The key proxy is per run, and a live defect is closed first (SEC, P2b).** Today a run whose key a key proxy holds is also given the egress proxy, which lets the two model-provider hosts through for any account, and the key proxy does not strip an `x-api-key` header. SEC closes that; P2b makes the key proxy one per run, for exactly one model, metering tokens and stopping at a per-run budget.
- **The image has an identity and a source (P2d).** A lock file maps the definition hash to digests per platform; identity is read from the repo digest; the image is built and pushed only by a protected CI workflow with provenance; the first pull is an explicit setup step (D39), never automatic on first use or in a dispatch, and a run that finds no image refuses and prints the command to run.
- **Drive and Notion sources are narrower (P4, P7).** Notion sources use a separate read-only secret. The Google Picker runs on a one-shot loopback page, never inside the interface; Drive is an implementation of `integration:documents`.
- **Project scripts are contained harder (P9).** A per-step egress proxy built from the hashed declaration, an internal network without external DNS, a separate build container for dependencies, and a credential scan before approval.
- **Attestation is hardened (P10).** `id-token: write` only in a separate attestation job; verification pins signer workflow and signer digest; self-hosted runners refused; the verifier runs the base commit's code under `pull_request`.
- **Operations for 24/7 use are a package (P-OPS).** A distinct "secret store locked" error, a headless secret backend, doctor checks, log limits, orphan removal, retention, a lease file for a synced sources folder.
- **Packages shrink and move (Q1, Q4, M2, M3, M5).** P0 ports only the streaming intake and the container helper; there is no store code to port. The step task is designed once in P5. P2 is four packages. P3 carries a symbol-level inventory of the tiers. A test-speed package (P-1) comes first.
- **Named homes.** `runtime/sources.py` (registry, versions, catalog, guardrails, `import_version`) and `providers/_container.py` (the whole container lifecycle) are fixed; new code never goes in `ops.py`.
- **Corrections to version 2 of this document** are in section 6: the content-addressed store that `media.py` does not have, the resolver that does not find a new role by its folder, and an evidence key (`platform`) that already means something else.
- **Findings.** F1 to F16 are kept as history. A short subsection "Review rounds of 2026-10-14" in section 6 points to the plan's table and lists, for each layer, which findings changed it. The "To verify" list gains items 9 to 13.

## 1. Why this document

The plan fixes the target (its section 1: three pillars, three run modes), the order of the work and the decisions. This document does the other half: it lays out the finished system layer by layer and says, for each layer, which pillar and which run mode it makes possible, so that a reader can see where a package lands.

It restates nothing of the plan's section 1. The three pillars are (1) data sources and persistence, (2) the brain, (3) tools; the three run modes are (a) a simple agent, (b) a workflow, (c) a routine.

## 2. The principles that shape every layer

| Principle (`AGENTS.md`) | What it forces in the architecture |
|---|---|
| 11. Hard limits live in code | A credential never enters a run: providers hold credentials on the host (`providers/secrets/resolver.py`), a run sees only its folder and one adapter script (`evals/executor.py`, header), and the model's key sits in a key proxy (`evals/container/keyproxy/keyproxy.py`, header). After SEC and P2b a run whose key a key proxy holds reaches only its own key proxy, which serves one model, forwards only the model endpoints, strips credential headers and stops at a per-run budget. An external effect is shown, approved by the hash of its exact content, executed by code, recorded (`runtime/effects.py`, header); after the plan this includes writing back to Drive or Notion (D17, P8). Converted and ingested files pass a credential scan before a run (`runtime/workcopy.py`, `scan`, line 227). The sources folder is guarded in code (D10, D30): dedicated, 0700, disjoint from the runtime's data folder, store, checkout and local evidence; written only by the runtime, never through a symbolic link, with only regular files copied back from a container. A project script runs only by its approved hash, without credentials, with a read-only root, behind a per-step egress proxy and with no direct effects (D25, P9). A routine that contains a networked script, or that a standing effect policy covers, is creatable only from the terminal or the page (S10, P6). |
| 9. Proof decides | Reworded in P3 (D34): proof decides autonomy by default; an explicit per-routine consent can grant it. Proof is kept per model and adapter. In `auto`, unattended release (review release in `autonomous` mode, routine tasks) happens only for pairs proven by lab evidence or the person's own local tests; a pair reliable only through community evidence is chosen and used, with its output reviewed (D36). With a model the person fixed, an `autonomous` routine may run without review by explicit consent, even with no evidence; each run is recorded as "autonomy by consent", never as "proven". In manual use the same consent is given once by fixing an agent's model while the agent is `autonomous` (D38). Today proof decides access too (`runtime/proof.py`, `route`, line 118). |
| 10. A claim says what it rests on | Community evidence is a column of its own, per model, with a per-contributor cap, and never merged into the lab's figures (D19); each line records its CPU platform (D20) and the published image digest it ran in (D21). A run released by consent says so on its record (D34). |
| 4. Artifacts over invocation | Skills never call each other. Tasks exchange files under the artifact contract (`contracts/project-layout.md`); a flow orders tasks by `depends_on` (`runtime/flow_files.py`). A step task, which is not a skill, exchanges files the same way; a source reaches a task as a copy of a recorded version, never as a call. |
| 14. Adopt before building | The converter adopts open document tools behind a provider (P4); Drive is an implementation of the existing `integration:documents` class and is read through its own API and the Picker (D13, D14, P7); Notion through the same class; file outputs by adopted tools (D17); evidence is attested by the code host's own attestation (D19). An MCP server may be adopted only as a provider implementation on the host (D15). |
| 1 and 2. A harness-agnostic core and open-closed adapters | `runtime/`, `providers/`, `skills/` name no AI tool. What belongs to one tool lives in `adapters/<harness>/`; the runner finds an adapter from the gate file's model list (`evals/eval-gate.json`), and adding a model adds an entry there, not a branch in the core and not a change to a fingerprinted file (D18, P2). |
| 7. Parallel by default | Tasks run at once unless a slot or a file in use forbids it: `runtime/parallel.py` `admit` (line 87) walks the project's slots, the agent's slots and the footprint of the files a task writes. A step task gets a declared footprint, derived from its kind (P5). The test suites run in parallel too (P-1). |
| 8. Shared core, projects outside | A project's data, flows, routines and imported sources live in that project: `docs/` for artifacts, `.workbench-local/` (untracked) for the drop (`runtime/path_rule.py`, `DROP_DIR`, line 41), and the sources folder the user defines for the sources (D9, D30), outside the workbench's git. A person's own lab evidence lives outside the checkout, so a pull never conflicts (D18). The workbench checkout holds none of it. |
| 12. A change pays for what it can reach | Adding a model changes no fingerprinted file (D18); SEC and P2b are one execution-side measurement change, paid by one battery after P2b; publishing the image is one more (P2d); teaching the planner to choose sources is one X change of one skill with one full test on the two lab models (P4). |
| 13. A saving must exceed its loss of safety | Accepting `linux/amd64` evidence beside `linux/arm64` (D20) is accepted because the alternative (amd64 only) costs the maintainer an emulated machine and an epoch for every skill. Giving every non-web task the whole folder (option B) is left `future`: it saves the planner's choice and loses the property that a task sees only what was chosen. Community evidence does not release a run unattended (D36): it would save the person's own tests and lose the guard that the person, or the maintainer, measured the pair. |
| 5. Never assume; ask | The planner asks when in doubt about a source; a step task can stop and ask the person (a pending decision); a plan and an effect always reach the person, and a review does unless an autonomy mode releases it (`runtime/autonomy.py`, `review_action`, line 316). A routine stops and asks when the approved hash no longer matches; a better candidate from a provider outside the approved set stops and asks (D35). A routine is not created from free text: the person approves a workflow first. |

## 3. The layers

```
L1 CHANNELS: five shells over one table of operations and one operations layer
+------------+ +---------+ +---------------+ +---------------+ +----------------+
| terminal   | | chat    | | page          | | MCP           | | messaging      |
| cli.py     | | chat.py | | service.py    | | mcp.py        | | messaging.py   |
| all verbs  | |         | | + interface/  | | read verbs;   | | policy groups: |
| routines   | |         | | picker,       | | lists         | | brakes only by |
| (create)   | |         | | save as flow  | | routines only | | default (D23)  |
+------------+ +---------+ +---------------+ +---------------+ +----------------+
      |            |              |                 |                  |
      +------------+--------------+-----------------+------------------+
                                  |  operations.py (the table), ops.py (the layer)
                                  v                  siblings for new code (P4 to P7)
+-----------------------------------------------------+  +------------------------------+
| L2 ORCHESTRATION                                    |  | L5 PROVIDERS (host side only)|
| router: one skill or flow, and the sources from     |  | documents (local, notion,    |
|   the catalog (P4); free text is planned once       |  |   Drive: P7)  issue-tracker  |
| plan (sha256, sources inside) -> approval by hash   |  | mailbox    messenger         |
| save a plan as a workflow (D32, P6)                 |  | publisher  scheduler         |
| workflows: workbench + project, parameters, date    |  | vcs        store             |
|   variables (D33); flow check (D31)                 |  | converter:document (P4)      |
| routines: always a workflow; hash with X.Y, image,  |  | Notion by address, read-only |
|   script, provider set, consent (D34, D35; P6)      |  |   secret (P4)                |
| area agents = configuration in runtime.json         |  | write-back effects (P8)      |
+-----------------------------------------------------+  | secrets: OS keyring (P-OPS)  |
                          |  tasks: skill, step         +------------------------------+
                          v                                Providers are called by host
+-----------------------------------------------------+    code only. A run never calls
| L3 EXECUTION                                        |    one and holds no credential.
| dispatcher + admission (slots, footprints, caps)    |    MCP only here, never in a run.
| skill task: lab -> eval container, on a copy that   |
|   holds copies of its chosen source versions        |
| step task: its own process; kinds: ingest, file     |
|   output, project script (P5, P8, P9)               |
| effects: preview -> approval -> execute -> record   |
| route(model | auto = cheapest reliable); consent    |
+-----------------------------------------------------+
   |                   |                      ^
   |  run              |  rows, files         |  band per model, price
   v                   v                      |
+--------------------+ +----------------------+ +---------------------------+
| L6 ADAPTERS,MODELS | | L4 DATA, PERSISTENCE | | L7 PROOF LAB              |
| adapters/*         | | store (SQLite), docs/| | eval_run.py, status,      |
| model list + pins  | | sources folder (D30):| | per-model gate, local     |
| key proxy per run, | |  registry, versions, | | evidence (D18), community |
|  one model, metered| |  catalog; the drop;  | | verified (D19, D36),      |
| image by lock file | | mirrors; data_dir    | | attested CI (P10)         |
+--------------------+ +----------------------+ +---------------------------+
```

The diagram shows what exists and what is new together; the tables below say which is which. L7 is not a layer a request passes through: its evidence is read to choose a model. No arrow leaves a run to a provider: the container sees the run folder and one adapter script, and reaches only its own model key proxy or, for a web run, the open network (`evals/executor.py`, lines 3 to 35). After SEC a run whose key a key proxy holds has no egress proxy at all.

### L1. Channels (shells)

**What it is.** One table of operations (`OPERATIONS`, 47 rows, `runtime/operations.py` line 72) and one operations layer (`runtime/ops.py` with its siblings), served by five shells that parse a message, call an operation and return what it returned. The table has a column for the channels that may call each operation, so that code, not a prompt, refuses what a channel may not do (`runtime/operations.py`, header).

**What it holds.**

| Component | State | Path |
|---|---|---|
| Table of operations, groups and channel rules (`GROUPS` line 259, `POLICY_CHANNELS` line 283, `EFFECT_CHANNELS` line 286) | exists | `runtime/operations.py` |
| Operations layer | exists | `runtime/ops.py`, `ops_core.py`, `ops_runs.py`, `ops_waits.py`, `ops_reads.py`, `ops_say.py`, `ops_config.py` |
| New operations land in a sibling module, never in `ops.py`: `ops.py` is 2690 lines against a budget of 2776 (`OPS_PY_BUDGET`, `runtime/tests/test_runtime_rules.py` line 242), 86 lines left | exists (the budget); the rule is new (P4 to P7) | `runtime/` (module names are left to each package) |
| Terminal shell | exists | `runtime/cli.py` |
| Chat shell | exists | `runtime/chat.py` |
| Page: local service (loopback, token, origin check) and the static interface, whose rule is that nothing is loaded from another host | exists | `runtime/service.py` (header, rules 1 to 5, lines 96 to 104; `CSP`, line 228), `interface/` (`interface/README.md`, line 112) |
| MCP server (tools only for rows that list `mcp`) | exists | `runtime/mcp.py` |
| Messaging bridge, inbound parser, cards, ledger, provider session | exists | `runtime/messaging.py`, `messaging_bridge.py`, `messaging_inbound.py`, `messaging_cards.py`, `messaging_ledger.py`, `messaging_provider.py` |
| Channel policy per channel (`channels` of the project's `docs/workbench/runtime.json`, accepted only in the terminal; default for messaging is read, talk, answer) | exists | `runtime/project_config.py` `_channels` (line 182), `ACCEPTED` (line 98), `runtime/operations.py` `DEFAULT_POLICY` (line 281) |
| Model picker per request and per agent, with a project default, on the page; the choice is stored (a store column, a schema change); the product may recommend a model from the scores, and for a routine with a fixed model the screen carries the consent warning of D34, and fixing an agent's model while the agent is `autonomous` shows the same warning and stores the consent with the agent (D38) | new (P3) | `interface/js/views/lobby-composer.js`, `lobby-request.js`; a `model` argument on rows of `operations.py`; `providers/store/sqlite.py` (`SCHEMA_VERSION`, line 53) |
| Per-model table in the Control room (today two tier columns) | new (P3) | `interface/js/views/control-skills.js` (the two tiers are named at lines 11 to 24) |
| Source verbs and screens: register a source, import (a synchronous operation or a background job; no task row before P5), refresh, list the catalog, write a description | new (P4, P7) | rows in `runtime/operations.py`; the upload follows the existing file route (`runtime/service.py`, `FILE_LIMIT` line 214) |
| "Save this plan as a workflow": a free-text request planned once, adjusted and approved, saved as a project workflow, then scheduled on the same screen (D32) | new (P6) | a row in `runtime/operations.py`; `interface/js/cards/plan.js` |
| Routine verbs: create and change (terminal and page), list, pause and cancel | new (P6) | rows in `runtime/operations.py`, in groups of their own (D23); the code in a sibling module, not `ops.py` |
| A hard limit: a routine whose workflow contains a networked script, or that a standing effect policy covers, is creatable only from the terminal or the page, whatever `channels.messaging` grants (S10) | new (P6) | `runtime/operations.py`, as `EFFECT_CHANNELS` is |
| Messaging groups for routines: by default only the brakes (list, pause, cancel); the person may grant creating and changing through `channels.messaging`, accepted in the terminal, except for what S10 reserves | new (P6) | `runtime/operations.py` (`GROUPS`, `DEFAULT_POLICY`); `runtime/project_config.py` |
| MCP and routines: it may list them; creating and changing stay outside its ceiling | new (P6) | `runtime/operations.py` |
| One-shot loopback page of the Drive authorization, with the Picker (served by the authorization script, never by the interface) | new (P7) | see L5 |

**How it serves the idea.** Pillar 2 (the brain) is reachable from five places with one set of rules, which is what lets a person delegate from a phone and approve from a desk. Mode (a) starts on the page or in the terminal, with a model picked or `auto`; mode (b) is started the same way by naming a flow (`request --flow`, `runtime/ops.py` line 390); mode (c) is created on the page or in the terminal from a saved workflow and fires with no channel.

**Boundaries.** An effect is approved only from the terminal or the page (`operations.EFFECT_CHANNELS`, line 286; `runtime/ops.py` `approve`, line 2051). A plan approved from messaging carries its hash (`runtime/ops_waits.py`, `only_on_plans`, line 281; the hash check is at lines 295 to 297). A routine is created and changed by the sha256 of its exact content (D23, D35) and carries no mode, cap, policy or standing approval of its own, only the consent of D34 when the model is fixed; each fire counts against the agent's daily caps. The terminal is never narrowed by policy (`NEVER_NARROWED`, line 282), and chat, which is local access, has no policy (`POLICY_CHANNELS`, line 283, comment). The interface never loads a page from another host; the Picker therefore runs outside it.

**What stays outside.** Messaging carries no attachment and no flow or model choice (`runtime/messaging_inbound.py`, header, lines 7 to 17), and no package of the plan changes that: a file, a model or a flow is chosen on the page or in the terminal, not from a phone, until the later evolution of the messaging channel after P6 (D28; section 6, F9). Free-text requests in manual use are unchanged: the router, a plan approved by hash (D37).

### L2. Orchestration

**What it is.** The step that turns a request into a plan the person approves by hash, and the definitions that give a plan its shape: flows, routines, area agents.

**What it holds.**

| Component | State | Path |
|---|---|---|
| Router: one skill or one flow, read from the router run's reply (`read_route` line 59, `check_route` line 77) | exists | `runtime/router.py`; routing table `skills/core-orchestrator/references/routing.md` |
| Source choice by the planner: the planning run receives the catalog of the project's sources (data, never instruction) and names, for each task, the sources it needs; it asks when in doubt; an `@mention` in the request forces a source. One X change of `core-orchestrator`, which carries source choice and the catalog in its external-content line, with one full test on the two lab models (about 54 to 72 runs) | new (P4) | `runtime/router.py`, `runtime/plan.py`; `skills/core-orchestrator/` |
| Plan: tasks, owners, contract-derived dependencies, `plan_hash` (line 316) over the tasks, approval by sha256 (`approve` line 2051); after the plan, each task entry also carries its source ids and its step arguments, so that the hash covers them | exists; sources and arguments inside the hash new (P4, P6) | `runtime/plan.py` (`combine` line 575, `agent_of` line 163), `runtime/ops.py`, `runtime/ops_waits.py` `approve_plan` (line 162) |
| Plan card: lists each task's sources and highlights a web task that receives sources (a manual plan keeps D16's highlight); offers "Save this plan as a workflow" | new (P4, P6) | `interface/js/cards/plan.js` |
| Flow files, six on main (`brand`, `code-change`, `design`, `market-positioning`, `short-video`, `website`); the loader reads the workbench checkout only (`ROOT` line 44, called with `core.ROOT` at `runtime/ops.py` lines 402, 1568, 1642); a task is a skill task (`TASK_KEYS` line 47) | exists | `flows/*.json`, `runtime/flow_files.py` |
| Project workflows, in a folder of the project | new (P6) | a folder of the project; the folder is not named by the spec (section 7) |
| Step entries in a flow: `{"key", "step", "args", "depends_on"}` | new (P6) | `runtime/flow_files.py` (`TASK_KEYS` changes) |
| Flow parameters, bound from the request and covered by the plan hash; a flow or a routine pins a source's id, not its version | new (P6) | `runtime/flow_files.py`, `runtime/plan.py` |
| Date variables in a workflow (`{today}`, `{week}`), filled at fire time; the approved hash covers the template and the fixed arguments, not the date values (D33) | new (P6) | `runtime/flow_files.py` |
| The flow check, when a workflow is created or saved: it refuses a task that requires the web and receives sources. When the skill accepts a research brief as input (among the skills that require the web, today `biz-market-analysis` and `biz-icp-positioning`, whose `inputs` list `docs/workbench/research/<topic>.md`), it offers a code-made split: `core-research` with the web and without the sources, then the skill without the web, with the sources and the brief. For any other skill it asks (D31) | new (P6) | `runtime/flow_files.py`, `runtime/plan.py` |
| Routine records, in the store, approved by the sha256 of their exact content: schedule, target workflow, fixed arguments, each skill's `X.Y`, the image digest, the project script's sha256 and declared destinations, the consent of D34 with the model, and for `auto` the approved provider set (D35) | new (P6) | `providers/store/sqlite.py` (new table), a sibling module of `ops.py` |
| Routine handler: reads the records and fires the target on the dispatcher's tick; a fire is idempotent, keyed by (routine, slot) under the claim lock, and a stated catch-up rule covers an outage (I5) | new (P6) | `runtime/handlers/routines.py` (the plan's name); the pattern is `runtime/handlers/published_posts.py` (`due` line 206, `tick` line 392); the tick is `runtime/ops.py` `_ticks` (line 2444), called at line 593 of `ops_runs.dispatch` (defined at line 581) |
| Area agents: configuration only (a pack of skills, an enabled flag, a mode, daily caps, `max_parallel`) | exists | `docs/workbench/runtime.json` `area_agents`, `runtime/autonomy.py` (`agents` line 126, `MODES` line 70, `MAX_PARALLEL_CEILING` line 77) |
| Owner rule for a step task: one rule, decided in P5 (a runtime pseudo-agent with its own cap, or a planner rule) | new (P5) | `runtime/plan.py` (`agent_of`, line 163, is called for every task at lines 593 to 595); `runtime/dispatcher.py` (`NO_AGENT`, line 70) |

**How it serves the idea.** Pillar 2 and all three run modes. The router serves mode (a), and now also names the sources a task reads; a flow serves mode (b), which the maintainer described as stages with several agents and skills; a routine serves mode (c), which needs no scheduler of its own because the handler tick already runs on every dispatch round, and the rounds are driven by the scheduler job every 5 minutes (`contracts/runtime.md`, line 312). The routine fires at the first round at or after its time.

**Boundaries.** The router chooses; it does no work of the skill it routes to (`AGENTS.md`, principle 4). The catalog it reads is third-party text: data, never instruction. A plan is never released by a mode (`runtime/autonomy.py`, `review_action`, rule 1, line 327): it always reaches the person. A routine is the one case where tasks are created without asking, and only under these rules (D24 as changed by D31, D34 and D35):

1. **A routine always targets an existing workflow (D31).** Free-text routines do not exist. A single step or a project script is a one-step workflow. A free-text request becomes a routine only by being planned once, adjusted, approved and saved as a workflow (D32), then scheduled.
2. **The person approves the routine's hash (D35).** It covers the workflow template and its fixed arguments (not the date values, D33), each skill's `X.Y` (a Z change does not stop it), the image digest, the project script's sha256 and declared destinations, the consent of D34 and, for `auto`, the approved provider set. At each fire the routine's content is recomputed, the date variables are filled, and tasks are created without asking only if the hash is identical; otherwise the routine stops and asks and messaging notifies the person. A new version of a source does not change the hash, because the plan pins the source id.
3. **Release without review follows D34.** In `auto`, tasks proceed without review only on pairs proven by lab evidence or the person's own local tests, with the agent in `autonomous` mode; `auto` picks the cheapest such pair inside the approved provider set, and a better candidate from another provider stops and asks. With a model the person fixed, an `autonomous` routine proceeds without review by explicit consent, even with no evidence; otherwise it waits at the first review and messaging notifies the person. Effects still need approval of their exact content unless a standing policy accepted in the terminal covers them, and a routine covered by such a policy is created only from the terminal or the page (S10).
4. **The web and the sources are settled at workflow creation (D31).** A workflow in which a web task receives sources is refused by the flow check (table above), so no routine runs a web-requiring skill without the web silently.

Area agents are configuration, not code: they own a pack and a cap, and carry no persona or memory (plan, section 9).

What stays outside: choosing a project flow by the router is not provided; the person names the flow (`request --flow`), and the flow's parameters are bound from the request text (section 6, F9).

### L3. Execution (the brain)

**What it is.** The dispatcher decides what may start now from a snapshot of the store; two kinds of task run, plus the project script, which is a step; effects leave only through an approval gate.

**What it holds.**

| Component | State | Path |
|---|---|---|
| Dispatcher: one pure `decide` over a snapshot (release, start, hold with a reason) | exists | `runtime/dispatcher.py` (`decide` line 86; `REASONS` line 82, which already lists "secret store", "credential" and "image") |
| Admission: project slots (`max_running`, default 3, 1 to 14: `runtime/project_config.py` lines 162 to 172), agent slots (`max_parallel`, up to 4), one code task per request, footprint overlap | exists | `runtime/parallel.py` `admit` (line 87), `footprint` (line 44) |
| Task run as its own process (`run-task --project <dir> --task <id>`), with a lock and orphan recovery; the dispatcher starts the children | exists | `runtime/cli.py` (line 16), `runtime/ops_runs.py` (`run_task` line 192, `dispatch` line 581) |
| Skill task: one skill, in the eval container through the lab facade, on a fresh work copy under the limits stated in the header of `runtime/workcopy.py` | exists | `runtime/lab.py` (`run_skill` line 500), `runtime/workcopy.py` (`entering` line 238, `returning` line 340) |
| A task receives copies of its chosen source versions and records which version it read (D11, D12); the sources folder itself is always excluded from the work copy, even when it sits inside a tracked tree (D10) | new (P4) | `runtime/workcopy.py` (L2 of its header, lines 14 to 17, copies every versioned file today) |
| The web-plus-sources split, settled when a workflow is created (D31, L2): a task that receives sources runs without the web, and the web work is a separate `core-research` task | new (P6) | `runtime/workcopy.py`, `runtime/plan.py`, `runtime/flow_files.py` |
| Model choice by `proof.route(model=<id>` or `auto)`, with the cheapest `reliable` pair for `auto` (D22) | new (P3) | `runtime/proof.py` (replaces `TIERS` line 41 and `route` line 118) |
| A symbol-level inventory of what the tiers touch: `TIERS` deleted; the lab API keyed by model (`lab.reference` line 138, `credential_missing` line 154, `run_skill(tier=)` line 500); the runtime's own floor key and tier billing (`runtime/ops_core.py`) generalised to per-model key names; billing history (`runtime/autonomy.py`); the dispatcher snapshot's tier; `site/tools/build_proof_json.py` and `site/assets/js/proof.js`; no `strong_*` or `floor_*` key in the gate file; the 16 runtime test files. "Floor" also names interface floors and the measurement floor, so no blind search | new (P3) | the files named |
| Autonomy by mode and by proof: unproven goes to review; milestones and mandatory milestones hold | exists | `runtime/autonomy.py` (`review_action` line 316, rule 5 at line 336) |
| Autonomy by consent (D34, D38): for a routine with a model the person fixed and the agent `autonomous`, the review is released without evidence; the consent is in the routine's approved hash, changing the model asks again, and each run is recorded as "autonomy by consent", not "proven". In manual use the consent is the agent's fixed model with the agent `autonomous`, given once on the page or in the terminal with the same warning; `review_action` releases the reviews of that agent's tasks on an unproven pair | new (P6 for routines; P3, with the picker, for agents) | `runtime/autonomy.py` (`review_action`), the routine record |
| Step task: a store row with a parent and no skill; it exists on the branch as the "code task" (`is_code_task`, `code_task_add`, `code_task_move`) and is designed once by P5 as the step task: columns kind, args, footprint (derived from the kind), states, one owner rule | extracted and designed (P5) | `providers/store/sqlite.py` on `feature/short-video`, lines 1487, 1498, 1528 |
| Step engine: resumable, with stops, its executors chosen by a registry of kinds | extracted (P5) | `runtime/pipeline.py` on `feature/short-video` (`ORDER` line 71, `STOPS` line 75, `run` line 747, `prepare_again` line 808) becomes `runtime/steps.py` (the plan's name) |
| Step task as a process of its own (`cli.py run-step`), found by its lock with a lock-liveness check, ended by `stop-runs` | new (P5) | `runtime/cli.py`, `runtime/ops_runs.py` |
| Step tasks `planned` and `ready` under `depends_on` | new (P5) | `runtime/ops_runs.py`, `providers/store/sqlite.py` |
| Step kind `ingest`: fetch or receive, convert, scan, place a new immutable version in the sources folder; built in P4 as `sources.import_version` and wrapped as a kind in P5 | new (P4, P5) | `runtime/sources.py` |
| Step kind: file output (PDF, XLSX, DOCX, CSV) by adopted tools, no model, into the sources folder or `docs/`; spreadsheet cells that start with `=`, `+`, `-` or `@` are guarded against formula injection, and hidden text in converted HTML or PDF is flagged (S9) | new (P8, registered in P5's registry) | `runtime/` (module not named by the spec) |
| Step kind: project script, approved by its exact hash; runs in the shared sandboxed container with no credentials and a read-only root; network off by default, the declared destinations enforced by a per-step egress proxy built from the hashed declaration, on an internal network without external DNS; dependencies installed in a separate build container from hashed lock files with no mounts; the script scanned for credentials before approval; writes only into the sources folder as a new versioned source; no direct effects; Python and shell first (D25, S8) | new (P9) | `runtime/` (module not named by the spec) |
| Step kind `media` (the short-video pipeline) | future (the side package) | `runtime/pipeline.py`, `runtime/ops_pipeline.py` on `feature/short-video`; not in the plan's packages |
| Effects: preview, one approval of the exact content, execution by code, record | exists | `runtime/effects.py`, `effect_commit.py`, `effect_pull_request.py`, `effect_reply.py` |
| Write-back effects to Drive and Notion, with a check that the target was not edited since it was read, and the target id inside the approved payload hash (S9) | new (P8) | `runtime/effects.py` and a new effect module, on the existing gate |
| Costs, billing and daily caps: a cost recomputed from token counts and prices, usage read from the full model usage; caps counted by the credential's billing. After the plan the token count comes from the per-run key proxy's own metering, not from what the run reports (S2) | exists; the proxy's count new (P2b) | `runtime/costs.py` (`usage_of` line 48, `recompute` line 133), `runtime/billing.py`, `runtime/autonomy.py` (`may_start` line 285) |

**How it serves the idea.** This is pillar 2 for modes (a) and (b), and the place where the maintainer's "different models" becomes real: the skill task takes the model the person named, or the one `auto` picks. A step task is what lets a workflow contain plain code (ingestion, conversion, an export, the person's own script) beside skills, and what lets a routine be "plain code" for the kinds the workbench registers and for a project script the person has approved.

**Choosing the model, after the plan.** `route(model=<id>)` runs the skill on that model. The scores inform the person and may recommend a model in the picker; they do not gate a model the person chose (D34). A pair with no `reliable` band is marked unproven. In manual use it runs `supervised` (D8) when it is named on a single request or the agent is below `autonomous`; when it is the agent's fixed model and the agent is `autonomous`, the person's consent (D38) releases the reviews and each run is recorded as "autonomy by consent". In `auto`, manual use keeps D34's rule: unattended release only for pairs proven by lab evidence or the person's own local tests. `route(auto)` (D22, D34, D35, D36):

1. The candidates are the models where the skill is `reliable` on this machine, a key is found, a price is known and, for a routine, the provider is in the approved provider set. `reliable` is read from the lab's evidence, the person's own local tests and the verified community evidence, with the adapter and the image digest the evidence names. All three count for ranking (D36).
2. Pick the lowest expected cost per run: the mean usage of that model's with-skill runs times its list price (D5). There is no extra minimum score and no per-project setting.
3. A tie goes to the higher pessimistic score.
4. No candidate: the project's default model, `supervised`, with the reason shown. A better candidate from a provider outside the approved set stops a routine and asks.
5. Unattended release follows the evidence's source: only a pair proven by lab evidence or the person's own local tests is released without review in `auto`. A pair that is reliable only through community evidence is chosen and used, and its output is reviewed.

A critical project selects a strong model by hand.

**Boundaries.** A run never holds a credential, never reaches a provider, sees only the artifacts its skill declares when it uses the web (limit L3, `runtime/workcopy.py`, header) and returns files only through the path rule (limit L7). A task sees only the sources chosen for it. The ingest functions import no part of the operations layer (`runtime/sources.py` does not import `ops`), so the engine can run them without a rewrite. No effect runs without the approval of its exact content, and no project script has a direct effect. The dispatcher changes no state; `ops.py` applies its decision (`runtime/dispatcher.py`, header, rule 4).

When a file in the sources folder changed after its import, its hash no longer matches the recorded one: it is re-sniffed, re-converted and re-scanned, labelled as a version made by the person, and never used unattended or handed over as the recorded one (D10, D30).

The reading of `reliable` no longer depends on a local build: the proof file marks a pair not proven when the image on this machine is not in the evidence's images (`runtime/proof.py` `checks`, lines 104 to 115). After the plan the image is the published one, identified by its repo digest and pulled by digest from the lock file (D21 as changed by D39, P2d: the first pull is an explicit setup step), so a server and a laptop that pulled the same digest agree; an image built locally yields local-only evidence that counts for that person's `auto` alone.

### L4. Data and persistence

**What it is.** The state of the work: rows in a per-project store, the project's documents under the artifact contract, the sources folder the user defines for imported sources, an untracked place for files handed to a run, and the mirrors that keep documents and the task board where a person reads them.

**What it holds.**

| Component | State | Path |
|---|---|---|
| Store, one SQLite file per project: tasks, task runs, pending decisions, approvals, conversation messages, task waits, document records, platform comments, events, runs, inbox, actions, cursors | exists | `providers/store/sqlite.py` (`CREATE TABLE` lines 92 to 312) |
| Step tasks, routine records, the model chosen for a request or a task, the source registry's rows: migrations numbered in the plan, in the order P3, P4, P5, P6, with `scripts/architecture_tables.py --check` clean | new (P3, P4, P5, P6) | `providers/store/sqlite.py` (a schema change: `SCHEMA_VERSION`, line 53, is 9 today); `scripts/architecture_tables.py` exists |
| Project artifacts: `docs/` under the artifact contract, one owner per artifact | exists | `contracts/project-layout.md`, `runtime/path_rule.py` |
| The runtime's data folder `data_dir`: required, outside every repository, for run folders, locks and the proof file; it is not the sources folder | exists | `runtime/project_config.py` (header line 12, `REQUIRED` line 88) |
| The sources folder (D9, D30): a folder the user defines per project, key `sources_dir` in `runtime.json`; mandatory, with no default (a project without one does not run); outside the workbench's git; accepted only in the terminal. Guardrails in code: dedicated (empty, or marked at acceptance); mode 0700; disjoint from `data_dir`, `store_db`, the workbench checkout and the local evidence folder (D18); the runtime writes only inside it, never follows a symbolic link out, refuses dangerous paths (the home folder, the filesystem root, a folder that contains the project); the work copy excludes it. The limits are numbered L21 and up in `contracts/runtime.md` (L1 to L20 exist, line 285), each with a named test | new (P4) | `runtime/project_config.py` (the key, in `REQUIRED`, and its checks), `runtime/sources.py`, `runtime/path_rule.py`, `runtime/workcopy.py` |
| Test fixtures: a helper adds `sources_dir` to the 43 runtime test files that write their own `runtime.json`, before the key becomes mandatory | new (P4) | `runtime/tests/` |
| `runtime/sources.py`: the registry, the versions, the catalog, the guardrails and `import_version`; it imports nothing of `ops` | new (P4) | `runtime/sources.py` |
| The source registry: each source declared with its type and origin; no credential in it (credentials stay in the OS secret store) | new (P4) | the store and the project's configuration |
| Immutable versions: each import writes the original, the converted text (Markdown or CSV) and a manifest (origin, date, sha256); a refresh writes a new version and changes none. Container outputs go to a size-capped tmpfs and the host copies back only regular files, read with `lstat` and `O_NOFOLLOW`, under a byte cap and naming rules | new (P4) | the sources folder; `providers/_container.py`, `runtime/sources.py` |
| A file changed outside the runtime: re-sniffed, re-converted, re-scanned, labelled, and never used unattended | new (P4) | `runtime/sources.py` |
| The rich catalog, built by code with no model and only from the converted output (never by parsing a raw file on the host): name, type, size, date, sheets and columns with sample values, first headings, the person's optional description | new (P4) | the sources folder and the store |
| A size cap per source, with a warning; indexing and RAG wait for a real case | new (P4) | `runtime/sources.py` |
| The file drop: one folder per task under `.workbench-local/drop/<task id>/`, 25 MB at most, credential-scanned if UTF-8, entering a run of that task only; it stays for a file the person hands to one task | exists | `runtime/drop.py` (`MAX_BYTES` line 49, `hand_over` line 76) |
| The generic streaming intake: bound the length before reading, sniff the type from the bytes, write in chunks to an exclusive no-follow temporary file while hashing, a deadline against a slow sender, one upload at a time. About 120 lines of `runtime/media.py` on the branch (`_Lock` 221, `sniff` 472, `_pull` 669, `_read_head` 688, `_bound_length` 702, `_stream_to` 827), with the magic bytes extended to PDF, OOXML and text. There is no content-addressed store in `media.py` (its records are folders named by an id code issues, and it holds recordings), and none is ported | extracted (P0), extended (P4) | `runtime/sources.py` or `runtime/intake.py` (P0 decides); the source is `runtime/media.py` on `feature/short-video` |
| Documents mirror (`pull`, `push`) to the platform of the project's `documents` configuration | exists | `runtime/documents.py` (`pull` line 503, `push` line 533) |
| Task board mirror (`pull`, `push`) | exists | `runtime/board.py` |
| Providers for both mirrors: Notion or local files | exists | `providers/documents/notion.py`, `providers/documents/local.py`, `providers/issue-tracker/notion.py`, `providers/issue-tracker/local.py` |
| Proof file, a cache rebuilt when its inputs change | exists | `runtime/proof.py` (`<data_dir>/proof.json`, header) |
| A lease file with the host id when a sources folder is synced between machines; no SQLite file and no lock inside a synced folder (I4) | new (P-OPS) | `runtime/sources.py`; documentation |
| Retention of source versions, documented | new (P-OPS) | documentation |
| Option B: a non-web task gets the whole sources folder read-only and reads on demand | future | per-project opt-in, off by default, only after evidence that the planner misses files, with eval cases that measure folder exploration (D11) |

**How it serves the idea.** Pillar 1. The store makes every operation resumable and auditable. The sources folder is where the person's sources live in a form they can read, version and keep, and the registry and the catalog are what let the planner give a task the sources it needs and nothing else. A task records the version it read (D12), so a result can be traced to its data. The drop remains for a file handed to one task. A snapshot written under `docs/` would enter every run, since a run without the web copies every versioned file and the documents under `docs/` (`runtime/workcopy.py`, limit L2, header lines 14 to 17): that is why the sources folder is excluded from the copy and sources enter only as the copies a plan lists. The documents mirror gives the person Notion as the place to read and edit what the agents write.

**Boundaries.** The store, the runtime's data folder `data_dir` and its configuration never enter a run (limit L2). A hand-over never replaces a file (`runtime/drop.py` lines 96 to 97) and is refused for a task that is done, cancelled or running (lines 81 to 83); a source version is never replaced either. The mirrors write only what a manifest lists and never write over a page a person changed (`runtime/documents.py`, header). Third-party text in a source is data, never instruction. The host never parses a raw file: only the converter's output reaches the catalog.

Integration sources are refreshed on demand or by a routine (D12); a routine that refreshes a source writes a new version into the sources folder, and the weekly workflow's tasks, created later, receive the newest version of the source id they pin when they start (D29).

### L5. Providers: tools and connections

**What it is.** The set of scripts that talk to the world outside the repository, under one contract, reached only from host code through one resolver. A provider holds its credential and reads it from the secret store; nothing of it enters a run.

**What it holds.**

| Component | State | Path |
|---|---|---|
| The contract (verbs, exit codes, dry run, ledgers) | exists | `providers/CONTRACT.md` |
| The resolver: a class to a provider script, and the one call used by the runtime. A class is found by its folder only for the roles in `ROLES` (`integration`, `search`, `generator`, `publisher`, `messenger`, line 95); `LISTED` (line 91) holds the classes of `contracts/environment.md`. `converter` is not a role today, so a new role is a change to `ROLES`, `LISTED`, the `contracts/environment.md` row and the class rows of `CONTRACT.md` | exists; the new role new (P4) | `providers/resolve.py` (`variables`, line 163, gives the environment variables that select an implementation) |
| Secrets: the OS secret store, the one resolver. A locked or unavailable store answers "not found" today (`_ask`, lines 269 to 272); P-OPS adds a distinct error, and one supported headless backend | exists; the error and the backend new (P-OPS) | `providers/secrets/resolver.py`, `contracts/secrets.md` |
| `integration:documents`: `local`, `notion` (verbs `stat`, `read`, `comments`, `write`, `notice`, `resolve`; `read` is `cmd_read`, line 589, in `VERBS`, line 707; the contract row is `CONTRACT.md` line 116, which says the class is found by its folder and that `write` replaces the whole document) | exists | `providers/documents/` |
| `integration:issue-tracker`: `local`, `notion` | exists | `providers/issue-tracker/` |
| `reader:email`: `gmail` (the person's own Desktop OAuth client, the app published "In production" for personal use, the refresh token in the OS secret store; the authorization listens on a loopback address with PKCE and a checked `state`) | exists | `providers/mailbox/`; setup in `providers/mailbox/README.md` (steps 3 and 4, lines 17 and 18); `providers/mailbox/auth.py` (`pkce_pair` line 144, `authorize_url` line 151, `state_matches` line 165) |
| `messenger:<platform>` (a class the runtime uses, not one a skill may require): `telegram`, `discord`, `whatsapp`, `whatsapp-cloud`, `whatsapp-twilio` | exists | `providers/messenger/`, `CONTRACT.md` line 110 |
| `publisher:<platform>`: `linkedin` | exists | `providers/publisher/` |
| `scheduler:job`: `launchd`, `systemd` | exists | `providers/scheduler/` |
| `store:runtime`: `sqlite` | exists | `providers/store/` |
| `integration:vcs`: `github` | exists | `providers/vcs/` |
| `converter:document`: a runtime-only class (like the messenger), run in the shared sandboxed container with no network, converting PDF, HTML, XLSX, CSV and DOCX to Markdown or CSV by adopted open tools; hidden text in converted HTML and PDF is flagged | new (P4, P8 for the flag) | `providers/converter/` |
| The container helper `providers/_container.py`: one module that owns the whole container lifecycle (argv, docker binary and environment, run, stop, remove, reap), with no network, a read-only root, capabilities dropped, no new privileges, limits on processes, memory, swap and CPUs, memory-backed `/tmp` and `/scratch`, and an image never pulled at run time. The provider environment is derived from `resolve.variables(cls)`, not from a hard-coded list. `evals/executor.py` does not import it, so the fingerprint is untouched | extracted (P0) | the two copies today are `providers/renderer/_docker.py` (`docker_environment` 143, `docker_binary` 148, `container_argv` 311, `remove_container` 330, `run_container` 341, `reap_containers` 503) and `providers/transcriber/whispercpp.py` (`container_argv` 568), both on `feature/short-video`; the hard-coded list to replace is `ENV_KEEP`, `runtime/ops_pipeline.py` line 70 on that branch |
| A Notion page read as a source, by address: a function extracts the 32-character id, then the existing `read` verb is called, with a separate read-only Notion secret of its own, so that reading a source never uses the secret that can write the board and the documents (S7). The existing `NOTION_TOKEN` reads and writes (`contracts/secrets.md` line 63) | new (P4), on an existing verb | `providers/documents/notion.py` (`doc_id`, line 527, accepts only the id; `SECRET`, line 112) |
| Google Drive as a source: an implementation of `integration:documents` (`providers/documents/gdrive.py`) under the existing verbs, which P8's write-back reuses. The person's own OAuth client following the Gmail provider's pattern; scope `drive.file`, and the Google Picker so that only what the person picks is reachable, stated plainly: `drive.file` reads and writes every file the person picks. The Picker runs on a one-shot loopback page served by the authorization script (state, PKCE), never inside the interface. A source is a folder or a single file; native Google files (Docs, Sheets, Slides) are exported by the Drive API and then converted, other files are downloaded and converted; change detection for a refresh | new (P7) | `providers/documents/gdrive.py`; `providers/mailbox/auth.py` is the pattern |
| Write-back to Drive and Notion: the provider's write verbs, called only from the effect gate, with the target id inside the approved payload hash. `write` replaces the whole document, so the edit-since-read check is the guard | new (P8) | `providers/documents/notion.py` (`write` exists in `VERBS`, line 707); the Drive write is new |
| File-output tools (PDF, XLSX, DOCX, CSV); HTML to PDF may reuse a headless browser in a container, such as the short-video renderer's (`providers/renderer/_browser.py` on `feature/short-video`, which P0 does not port) | new (P8) | `providers/` or `runtime/` (not named by the spec) |
| OneDrive and Jira | deferred | they wait for a real project that needs them (D13) |
| An MCP server adopted as a provider implementation, with read verbs, on the host; the agent receives files, never the tool | future | D15; no package builds one |

**How it serves the idea.** Pillar 3 (tools) and the connection half of pillar 1. Adding a source adds one script under one contract (`providers/CONTRACT.md`, class table), never an edit to a skill; Drive is one more file in the existing documents folder, and the same contract is what an adopted MCP server would be wrapped in.

**Boundaries.** A provider is called from host code with a timeout and returns one JSON object; a run never calls one. A provider whose verb changes the world takes a dry run and an idempotency key (`providers/CONTRACT.md`, lines 66 to 74). An MCP server never runs inside a run (D15). Drive access is as narrow as the Picker lets it be (`drive.file`, not `drive.readonly`, D14), and the person is told that every picked file is readable and writable. The interface rule "nothing from another host" (`interface/README.md`, line 112) stands because the Picker is on the authorization script's own loopback page.

A Notion page or a PDF is third-party text. The target skills' lines on external content name web pages, search results, listings, sites, reviews and research briefs, not a handed-over file (`skills/biz-market-analysis/SKILL.md`, line 49), and changing that line is an X change of each skill (a full test). Version 3 does not change the line: P4 adds converted-input eval cases with `--baseline` on two target skills, with a guard assertion that converted text is treated as data, so that the behaviour is measured (section 6, O2).

To verify 1: whether picking a folder under `drive.file` grants access to the files inside it; P7 starts with a spike that answers it. To verify 2: whether the Drive API exports Google Docs directly to Markdown, and the export size limit. To verify 8: whether the Picker's desktop flow works with the loopback page. To verify 12: macOS file-access permissions for launchd jobs on synced folders.

### L6. Adapters and models

**What it is.** The harness-specific layer: how one model is called inside the eval container, and what the model list and the price table say.

**What it holds.**

| Component | State | Path |
|---|---|---|
| Adapter for an eval: `run-prompt.sh` and `eval.json`, in two folders: `agents-dir` (hosted open-weight models through an agent runner, and an `ollama/<name>` id parsed at line 99) and the folder the gate file names as `strong_harness` (the reference model) | exists | `adapters/agents-dir/`, `adapters/<strong_harness>/` |
| Adapter for the runtime: `run-agent.sh` in `api` and in the folder `strong_harness` names | exists | `adapters/api/run-agent.sh`, `adapters/<strong_harness>/run-agent.sh` |
| The eval container, its egress proxy and its key proxies (today one route file per tier, each with one `provider_only` pin; floor `keyproxy.json`, reference `keyproxy-strong.json`) | exists | `evals/container/`, `evals/executor.py` (`ROUTE_FILES`, line 73) |
| The live defect (S1), in today's code: a run whose key a key proxy holds is also given the egress proxy (the `proxy` branch sets `HTTPS_PROXY` and the like, `evals/executor.py` lines 347 to 353); the egress proxy lets the two model-provider hosts of `evals/container/proxy/allow.txt` through for any account; the key proxy removes `authorization` but not `x-api-key` (`NOT_FORWARDED`, `evals/container/keyproxy/keyproxy.py` line 47, applied at line 200) | exists (the defect) | the files named |
| SEC: a run whose key a key proxy holds reaches only its own key proxy (no `HTTPS_PROXY`, no egress proxy on its network); the key proxy strips credential headers such as `x-api-key` and forwards only the model endpoints. An execution-side measurement change; before it, the egress proxy's connection logs of a recent battery are read to see whether the path was used | new (SEC) | `evals/executor.py`, `evals/container/keyproxy/keyproxy.py`, `evals/container/proxy/allow.txt` |
| The model list: today `strong_model`, `floor_model`, their harnesses and pass-through variables, keyed by tier, plus a `models` map from id to aliases | exists | `evals/eval-gate.json` (lines 2 to 10 and 20 to 23; `models` at line 33) |
| The model list as a list: each model with its adapter, its key variables, its price source and its provider pin; the lab models (the maintainer's two) are the default list; a reader accepts both gate-file shapes | new (P2a, P2b) | `evals/eval-gate.json`, `evals/eval_status.py` (`GATE_FIELDS`, line 250) |
| One key proxy per run, started with exactly one model id and its pin, refusing any other model, metering tokens and stopping at a per-run budget; adding a model never changes a fingerprinted file again. Review checks that the upstream request of the two lab models is unchanged except for credential headers. The epoch entry covers SEC and P2b, paid by one battery after P2b | new (P2b) | `evals/container/keyproxy/keyproxy.py` (the route's `provider_only`, lines 79 and 187), `evals/executor.py` (`keyproxy_url`, line 165; `places`, line 157) |
| The image's identity and source: a lock file maps the definition hash to config and manifest digests per platform; the image the evidence was measured in is the one published, because a rebuilt image would make every measurement stale; identity is read from the repo digest, never `.Id`; built and pushed only by a protected CI workflow on main with short-lived registry credentials, with build provenance verified before a lock-file change and before the first pull; the key proxy and egress proxy images are built locally or with pinned packages; the first pull is an explicit setup or doctor step (D39), never automatic on first use or mid-dispatch; a run that finds no image refuses and prints the command (the refusal exists for a missing image, `runtime/lab.py`, lines 406 to 409, and its message changes) | new (P2d) | `evals/container/`, `evals/executor.py` (builds the image locally today, lines 191 to 193), a lock file, a CI workflow |
| Price table with source and access date: one table, whose home P3 decides, replacing `adapters/api/prices.json` (six models) and the project's `model_prices` or deriving them from it | new (P3) | `adapters/api/prices.json`; `runtime/project_config.py` (line 159); `runtime/costs.py` |
| The adapter of a model is the one its entry in the model list names | new (P2b) | `evals/eval_run.py` |
| Log limits on the egress and key proxy containers (the egress proxy logs each connection, `evals/container/proxy/tinyproxy.conf`), retention of run folders, orphan containers removed by label on recovery | new (P-OPS) | `evals/container/`, `runtime/`, `providers/_container.py` |
| Doctor checks: linger, macOS file-access permissions on the sources folder, the image present, free disk | new (P-OPS) | `scripts/doctor.py` |

**How it serves the idea.** Pillar 3 and the "different models" of pillar 2: a model enters the platform as an entry in a list and an adapter, and is then runnable. Which models a person may run is a matter of keys, not of code.

**Boundaries.** The container is the boundary: no host mode (`evals/executor.py`, header). A run holds a placeholder for its key; after SEC and P2b the key proxy is the run's own, serves one model, forwards the model endpoints only and meters the run. A run on the open network (a web case) can still hand data to another account of the same provider (`evals/executor.py`, line 35): the proxy filters by host name only. A model on the person's own machine (`ollama/...`) is not reachable from the container and is left out of the lab (plan, section 8). Evidence is accepted from `linux/amd64` beside `linux/arm64`; the event line records the image's CPU platform today (`evals/eval_run.py`, the event line description near line 365, and the check at lines 1837 to 1839), and each run line records it after P2b, under a key that is not `platform`, which already names a social platform (`evals/eval_status.py` lines 734 and 905 to 907); both are counted together unless results diverge (D20).

To verify 7: the size of the published image (estimated at 1 to 2 GB, not measured). To verify 9: whether the provider API prefers a client's `x-api-key` over the proxy's Bearer token when both are present; SEC strips the client's header either way, and the answer says whether today's defect was exploitable. To verify 10: whether `.Id` of a pulled image differs between the classic and the containerd image stores; P2d reads the repo digest either way. To verify 11: DNS behaviour on Docker `--internal` networks, which P9's per-step egress proxy relies on.

### L7. The proof lab

**What it is.** The place where a skill's standing on a model is measured, so that autonomy and the choice of model are decided by recorded evidence and never ticked by hand (`AGENTS.md`, principles 9 and 10).

**What it holds.**

| Component | State | Path |
|---|---|---|
| Runner: full test (every case, 3 runs, baselines), partial test (named cases), platform test; writes one evidence file per test event | exists | `evals/eval_run.py` |
| Runner option `--model <id>` to test a named model with the adapter its list entry names (today `--model` is the reference model's id: `evals/eval_run.py`, lines 6 and 19 to 24); anyone may test any model | new (P2b) | `evals/eval_run.py` |
| Evidence: one line per run with model, adapter, score, case hash, measurement version, optional `cost_usd`; the reading of evidence lines extracted from `evals/eval_status.py` into a module of its own, with T24 done first | exists; the module new (P2a) | `skills/<name>/evals/evidence/lab-*.jsonl`; `RUN_OPTIONAL` (`evals/eval_status.py`, line 734) |
| A usage field on the run line (input, output, cache read, cache write tokens), from the full model usage and, for a run through a key proxy, from the proxy's metering; the CPU platform on each line; the published image digest | new (P2b) | `evals/eval_run.py`, `evals/eval_status.py` |
| Status: a band, a cause, a gate and a score for every model that has evidence, by the same rules (`as_reference` line 1095, `skill_band` line 1965; the per-model loop at line 2074) | exists | `evals/eval_status.py` |
| Gate, completion, Y-change count and stored gate selected per model; checked against a golden `status` output | new (P2c) | `evals/eval_status.py` (`y_changes_since`, line 1888) |
| Baseline per model: `--baseline-on <model>` runs it; `baseline_lines` reads the lines of the model it is given (line 1107) | exists | `evals/eval_run.py` (option parsed at line 551), `evals/eval_status.py` |
| Gate, threshold, tolerance, runs, baseline runs, margin | exists | `evals/eval-gate.json` (`threshold` 0.8, `strong_tolerance` 0.05, `runs` 3, `baseline_runs` 1) |
| The fixed grader, the measurement version, the floor, the fingerprint, the epochs | exists | `evals/eval-gate.json`; `FINGERPRINT_FILES` (`evals/eval_status.py`, line 557) |
| Local evidence: each person's own tests of any model, kept outside the workbench checkout so `git pull` never conflicts, and outside the sources folder; they feed only that person's `auto` and may release a run unattended for that person; a locally built image yields local-only evidence | new (P2b) | a folder outside the checkout (not named by the spec) |
| The proof check compares the local image with the published digest | new (P2d) | `runtime/proof.py` (`checks`, line 104) |
| Community evidence: the contributor runs the official reusable workflow, referenced by commit, in their fork's CI with their own keys; the workflow checks out the official code at that commit; `id-token: write` is granted only in a separate attestation job that receives the evidence file's digest, never in the job that runs the model; the actions cache is not used in the reusable workflow; GitHub attests the evidence file; the pull request carries both; the workbench's CI verifies without a model call (signature, `--signer-workflow` of the official workflow, `--signer-digest` bound to the checked-out commit, self-hosted runners refused, the commit is in main's history, the digest matches), running the verifier from the base commit's code under `pull_request`, never under `pull_request_target`, and records the file as "community verified" | new (P10) | a reusable workflow and a verification step in the repository's CI (`.github/workflows/checks.yml` is today's CI; the new files are not named by the spec) |
| "Community verified": its own column per model, a per-contributor cap, counted for everyone's choice and `auto` ranking, and never by itself for unattended release (D36) | new (P10) | `evals/eval_status.py`, `skills/<name>/evals/evidence/` |
| The maintainer's own score tests (lab runs of `eval_run.py`) move to the same attested CI | future (after P10) | the same workflow |
| Test speed: the suites run in parallel (`pytest-xdist` in CI; `-n auto` in the pre-commit hook, which runs them serially today, `.githooks/pre-commit` line 76); the conftest that clears the `STOPPING` flag after each test and the test fixes are taken from `origin/feature/short-video`, commit `e1202879`. The hook's `env -u GIT_*` stays before the call. Risks: tests that share ports or the per-user state folder | extracted (P-1) | `.githooks/pre-commit`, `.github/workflows/checks.yml`, a `conftest.py` in `runtime/tests/` (none exists on main; it comes from that commit) |

**How it serves the idea.** It is what makes "a score per model" true and what `route(auto)` reads. The status is the one source; the runtime keeps only a cache of it (`runtime/proof.py`, header). Because the grader is fixed, scores compare across models.

**Boundaries.** Lab evidence is written only from the container, only when the models, adapters and grader equal the gate file's, only when the fingerprint is the committed one (`evals/eval_run.py` lines 1837 to 1863; `evals/executor.py` line 81); after the plan it is accepted from the two listed platforms and from any model of the list. A run made by anything else is a trial and writes no lab evidence. A committed evidence file is never edited. No telemetry leaves a project (`AGENTS.md`, principle 8).

The provider host and the per-model pin live in the attested code, so a fake server cannot produce an attested line. The mitigations against what attestation cannot see are these: every completed run of the fork's workflow must be submitted and a gap in the run numbers is flagged (against cherry-picking); the pessimistic score and the per-contributor cap limit what one contributor moves; field evidence demotes a pair after three `failed` verdicts. The residual risks are cherry-picking across runs the contributor never submitted, and the provider's honesty about the model it served. Because of them, community evidence informs the person's choice and never alone releases a run unattended (D36).

To verify 3: whether GitHub offers free arm64 hosted runners to public repositories. To verify 4: whether the identity signed for a reusable workflow called from a fork is the official repository's workflow, so that `--signer-workflow` pins it. To verify 5: whether artifact attestations require a public repository (the workbench is public, so it does not block). To verify 6: whether the subscription OAuth token of the reference model works in CI, for the later move of the maintainer's tests. To verify 13: whether `gh attestation verify` in the CLI version CI pins supports refusing self-hosted runners.

### Rules every package keeps, and the fixed homes

| Rule or home | State | Path |
|---|---|---|
| Migration numbers are assigned in the plan (P3, P4, P5, P6 in that order) and `scripts/architecture_tables.py --check` is clean | rule new; script exists | `scripts/architecture_tables.py`, `providers/store/sqlite.py` |
| New code never goes in `ops.py`; a sibling module holds it | rule new (P4 to P7) | `runtime/` |
| `runtime/sources.py` is the home of the registry, the versions, the catalog, the guardrails and `import_version`, and imports nothing of `ops` | new (P4) | `runtime/sources.py` |
| `providers/_container.py` is the home of the whole container lifecycle | extracted (P0) | `providers/_container.py` |
| One price table | new (P3) | home decided in P3 |
| Each package's done-when updates: the limits table L21 and up, with named tests, in `contracts/runtime.md`; `contracts/environment.md` together with `ROLES` and `LISTED` of `providers/resolve.py`; the class rows of `providers/CONTRACT.md`; the generated tables; the pages the package touches | rule new | those files |
| Other module names are left to each package's executor | rule | |

## 4. The run modes, end to end

Each walk-through names the component at each step and its state. Where a step depends on a third-party fact not yet confirmed, a `To verify n:` line says so.

### (a) "Do a market research on this idea", from the page

**Beforehand: a source.** The project has a sources folder (D9, D30), dedicated and accepted in the terminal. The person adds the survey spreadsheet on the page.

1. The upload follows the existing file route (`runtime/service.py`, `FILE_LIMIT` line 214). The streaming intake checks the type from the bytes and the size and hashes the bytes (`sniff`, `_stream_to`). State: extracted (P0), extended (P4).
2. `converter:document` runs in the shared container (`providers/_container.py`) with no network and a read-only root, writes into a size-capped tmpfs, and the host copies back only regular files. The text is scanned for credentials after conversion (`runtime/workcopy.py`, `scan`, line 227), because compressed text in a raw file is invisible to a scan of the bytes. State: new (P4), on the helper extracted in P0.
3. `sources.import_version` writes an immutable version in the sources folder: the original, the converted text and a manifest (origin, date, sha256). The catalog entry is built by code from the converted output, with no model: name, type, size, date, sheets and columns with sample values, first headings and the person's optional description. A source over the size cap is refused with a warning. State: new (P4).

**With a chosen model.**

1. The person types the request in the Lobby and picks a model in the picker. State: the composer exists (`interface/js/views/lobby-composer.js`); the picker and the stored choice are new (P3).
2. The page calls the `request` operation (`runtime/ops.py` line 390), then `route` (line 1618). The router is one model run of the planning agent in the eval container (`runtime/router.py`; the row has `model: "without --flow"`). Free text in manual use is unchanged (D37). State: exists.
3. The router reads `skills/core-orchestrator/references/routing.md` and the catalog, and answers with one skill, `biz-market-analysis`, and the sources it chose: here the survey. `check_route` accepts the skill if it is in an enabled agent's pack (`runtime/router.py` line 77). If the request carries an `@mention`, that source is forced; if the planner is in doubt, it asks. State: the route exists; the choice of sources is new (P4).
4. `plan.combine` builds the plan; `plan_hash` (line 316) over the tasks gives the hash, and each task entry carries its source ids, so the hash covers the choice. A pending decision of kind `plan` appears with the plan card (`interface/js/cards/plan.js`), which lists the task's sources and highlights the task because it uses the web and receives a source (D16, a manual plan). State: the plan exists; the sources in it and the highlight are new (P4).
5. The person approves with the hash (`ops.approve`, line 2051). Approving is their choice about the web task. The task is created and is `ready`. The same card offers "Save this plan as a workflow", which mode (c) uses. State: approving exists; saving is new (P6).
6. A dispatch round (the scheduler's `work` job every 5 minutes, or the page's own loop) runs `dispatcher.decide`: the agent's mode and daily caps (`may_start`), then `admit` (slots, footprint). The footprint of `biz-market-analysis` is its declared outputs and updates minus the state file (`runtime/parallel.py` `footprint`, line 44). State: exists.
7. The dispatcher starts `run-task` as a child process. `run_task` reaches `proof.route` through `ops._route` (`runtime/ops.py`, line 351) with the model argument. State: the call exists (`runtime/ops_runs.py`, `run_task`, line 192); `route(model=<id>)` is new (P3). The skill requires the web, and the pair runs with the web only if a case of the skill was measured with it on that model; that check is wrong today (`runtime/proof.py` line 97, `web_measured`) and is fixed per model, requiring evidence, by P1.
8. The pair has no `reliable` band: the run is marked unproven. If the model is named on this request only, or the agent is below `autonomous`, it is `supervised` (D8); if it is the agent's fixed model and the agent is `autonomous`, the person's consent (D38) releases the review and the run is recorded as "autonomy by consent". If the pair has a `reliable` band, the agent's mode decides, and a pair that is reliable only through community evidence is used with its output reviewed (D36). State: new (P3).
9. `workcopy.entering` assembles the run copy. A web run sees only the artifacts its skill declares (limit L3), plus the copies of its chosen source versions, which the plan the person approved lists; the sources folder itself is excluded. The version read is recorded on the task (D12). Before the copy the file's hash is checked against the manifest; a file the person changed after import is re-sniffed, re-converted, re-scanned, labelled, and never used unattended. `lab.run_skill` runs the adapter in the container; the run gets its own key proxy, for this one model, which holds the key, meters the tokens and stops at the budget; the container has no egress proxy; the web run has the open network. State: the container run exists; the per-run proxy is new (SEC, P2b); the source copy and the version record are new (P4).
10. `workcopy.returning` brings files back through the path rule and the credential scan; `docs/business/market.md` lands in the project; a pending decision of kind `review` opens. State: exists.
11. `review_action` holds it (supervised, or the skill is unproven: rule 5, line 336; an agent with the consent of D38 releases it), the person reads the document on the Desk and accepts. If the project's documents manifest lists the file, `documents.push` (line 533) mirrors it to the platform. State: exists.
12. The run row records model, adapter, billing and a cost recomputed from the token counts, which now come from the key proxy's metering. State: exists (`runtime/costs.py`); the proxy's count is new (P2b, S2).

**With `auto`.**

1. The beforehand steps and steps 1 to 6 are the same; the picker value is `auto`.
2. `route(auto)` applies the rule in L3. The inputs are each model's band for this skill (`evals/eval_status.py` per-model rows, from the lab, the person's local tests and the verified community evidence, all of which count for ranking), a key found, a price, and the mean usage of its with-skill runs. State: new (P3, with the usage field of P2b and the per-model gate of P2c).
3. The image check compares the digest on this machine (the repo digest) with the published one in the lock file; the first pull was an explicit setup step (D39: the doctor or the setup command; a machine without the image refuses the run and prints the command). A locally built image would make the evidence local-only. State: new (P2d).
4. Until new runs add the usage field, no model has usage on a committed line, so `auto` returns the project's default model, `supervised`, with the reason shown. After new runs, it picks the cheapest `reliable` pair. In a single request the output of a pair reliable only through community evidence is still reviewed.
5. The rest is the same as with a chosen model.

### (b) A project workflow: refresh a Notion page, research, then three skills, then a file

The workflow `market-to-brand`, in the project, with one parameter: the Notion address. Because it is a workflow, the flow check ran when it was saved and refused a web task that receives sources, so the web work is its own task. Tasks: an `ingest` step that reads the address; `core-research` (the web, no sources), which writes the brief `docs/workbench/research/<topic>.md`; `biz-market-analysis` with the survey, the refreshed page and the brief (sources, no web); then `biz-icp-positioning`; then `brand-strategy`; then a file-output step that writes a summary workbook. Two area agents (business, brand). The artifact chain is the brief, then `docs/business/market.md`, then `docs/business/icp.md` and `docs/business/positioning.md`, then `docs/brand/strategy.md` (the skills' `inputs` and `outputs`). `biz-icp-positioning` and `brand-strategy` receive no sources, only artifacts, so they keep the web.

1. A project workflow file defines the tasks. State: new (P6). The folder that holds it is not named by the spec (section 7). The workflow pins source ids, not versions. It was either written by hand or saved from a plan (D32); in both cases the flow check ran at that moment, and for `biz-market-analysis` it offered the code-made split into `core-research` and the analysis task.
2. The person starts the workflow by name on the page (`request --flow`, `ops.request` line 390) and gives the Notion address in the request. The workflow's parameter is bound from the request text, and the bound value is covered by the plan hash. State: new (P6). The router does not choose a project workflow; the person names it.
3. `plan.combine` builds the plan; the owner rule gives the step task an agent, and the pending decision lists the tasks and their sources. State: new (P5 owner rule, P6 steps, P4 sources). Today `agent_of(t["skill"])` fails on a step task (`runtime/plan.py` lines 593 to 595).
4. The person approves with the hash. The `ingest` task has no dependency and is `ready`; the skill tasks and the file-output task are `planned` under `depends_on`. State: new (P5).
5. The dispatcher admits the `ingest` task: it has a declared footprint derived from its kind, and it is held with "no enabled agent owns the task" only if the owner rule is missing (P5). `ops_runs.dispatch` starts `cli.py run-step` as a child process, as it starts `run-task`, and finds it later by its lock. State: new (P5).
6. Ingest, Notion: the documents provider's `read` is called from the host with the separate read-only Notion secret from the secret store (`providers/documents/notion.py`, `cmd_read`, line 589). State: the verb exists; reading by address and the read-only secret are new (P4). The returned Markdown is scanned (`workcopy.credential_findings`, line 94) and written as a new version in the sources folder with its manifest by `sources.import_version`. State: new (P4).
7. `core-research` runs with the web and without sources (one skill task, as in (a) steps 6 to 12). When it is `done`, the brief exists. State: the skill exists; the arrangement is new (P6).
8. `biz-market-analysis` becomes `ready` when the ingest task and the research task are `done`. It receives sources and no web. It reads the newest version of each source id it pins at the moment it starts and records the id, version and sha256 it read on the task (D29). State: new (P4, P6).
9. `biz-icp-positioning` starts only after `market.md` exists; `brand-strategy` only after `icp.md` and `positioning.md`. Each passes through its review. State: exists. The chain is serial by artifact, so the workflow's parallelism comes only from steps with no dependency; two agents matter for caps, modes and slots, not for speed.
10. Reviews: each is released by the agent's mode or held for the person. Unproven skills and mandatory milestones always hold (`review_action`, rules 5 and 6). State: exists.
11. The file-output step reads the Markdown of the chain and writes an XLSX (or CSV, PDF, DOCX) with adopted tools and no model, into the sources folder or `docs/`; cells that start with `=`, `+`, `-` or `@` are guarded. State: new (P8, with the registry of P5).
12. If the workflow includes a write-back to a Drive file or a Notion page, it is an effect: the preview shows the exact content and the target id, which is inside the approved hash; the person approves it once, the effect executes, and it is recorded; before it executes, the target is read again and compared with what was read, and if it was edited meanwhile the effect stops and asks. State: new (P8). The real case for the write-back is chosen during development (D17).
13. A step that runs the person's own code (a project script) fits anywhere in the workflow: it runs only if its exact hash was approved in the plan, in the sandbox, behind its own egress proxy for the destinations it declared, and writes only into the sources folder as a new versioned source. State: new (P9).

### (c) A routine: every Monday at 08:00, refresh the source and run the weekly workflow

The routine starts from a saved workflow. Its target is `weekly-market`, a workflow like the one of (b), whose file-output step names its file `summary-{week}.xlsx`.

1. **Get a workflow.** Either the person wrote `weekly-market` as a project workflow, or they ran the weekly work once as a free-text request, as in (a), adjusted and approved the plan, and pressed "Save this plan as a workflow" (D32). Saving runs the flow check: a plan in which a web task received sources is offered the split into `core-research` and the analysis task, or the person is asked. State: new (P6).
2. **Schedule it on the same screen.** A routine record is created, on the page or in the terminal: a schedule, the target workflow, its fixed arguments. The date variables (`{today}`, `{week}`) stay variables; they are filled at fire time. State: new (P6). The spec gives no schedule format and no time zone rule (section 7).
3. **Choose how it runs.** Either `auto`, with the approved provider set (the providers the person accepts); or a fixed model. With `auto`, unattended release applies only to pairs proven by lab evidence or the person's own local tests. With a fixed model and the agent `autonomous`, the screen warns that no evidence may exist and asks for explicit consent. State: new (P3 picker, P6 consent).
4. **Approve the hash.** The person approves the routine's sha256: the workflow template and its fixed arguments, each skill's `X.Y`, the image digest, the project script's sha256 and declared destinations if the workflow has a script, the consent with its model, and for `auto` the provider set. State: new (P6). A routine cannot be created from MCP; from messaging only if the person granted that in `channels.messaging`, and never when the workflow contains a networked script or a standing effect policy covers it: those are created only from the terminal or the page (S10).
5. **The tick.** The scheduler job `work` runs the dispatch round every 5 minutes; the round calls `_ticks` (`runtime/ops.py` line 2444), which calls the `routines` handler's `tick`. State: the tick exists; the handler is new (P6). The handler must be configured under `handlers` in the project's `runtime.json` and have an enabled agent (`_ticks`, lines 2446 to 2455).
6. **The fire.** The handler selects the records that are due, as `published_posts.due` does. A fire is keyed by (routine, slot) under the claim lock, so a second tick or a restart does not fire twice; after an outage a stated catch-up rule decides what is fired (I5). Each fire counts against the agent's daily caps (`autonomy.may_start`, line 285). State: new.
7. **The check.** At the fire the handler recomputes the routine's content and fills the date variables. If the approved hash is identical, the tasks are created without asking; if not (a skill's `X.Y` changed, the image digest moved, a script file changed, a better candidate sits in a provider outside the approved set), the routine stops and asks, and messaging notifies the person. A Z change of a skill, a new version of a source and the date values do not stop it. State: new (P6, D35).
8. **The tasks.** The first task is a step: `ingest` re-reads the Notion page (or the refresh of a Drive source) and writes a new version into the sources folder. The weekly workflow's tasks read the newest version when they start and record its id, version and sha256 (D29). `core-research` runs with the web and no sources; the analysis skill runs with sources and no web. State: new (P4, P5, P7).
9. **Release.** With `auto`, the review is released only for a pair proven by lab evidence or local tests; a pair reliable only through community evidence is chosen and used and its review waits for the person. With a fixed model and the consent, the review is released and each run is recorded as "autonomy by consent", not "proven". Otherwise the routine waits at the first review and messaging notifies the person. Effects still need approval of their exact content, unless a standing policy accepted in the terminal covers them. State: new (P6, D34, D36).
10. The person is told through the messaging channel (cards exist: `runtime/messaging_cards.py`) and reads the result on the page.

**A routine that is plain code.** A routine's target is a workflow of one step: `ingest` to refresh a source, a file-output step, or a project script. The project script is the person's own code, approved by its exact hash, run in the sandbox with no credentials and a read-only root, with the network off unless declared destinations entered the approved hash, and then only through the per-step egress proxy built from that declaration, writing only into the sources folder as a new versioned source, with no direct effect (D25). Any side effect leaves through the effect gate. State: new (P9).

**Running it 24/7 (P-OPS).** The routine fires only if the machine is on and the scheduler's jobs run: the doctor checks linger and the macOS file-access permissions for jobs that read a synced sources folder; a locked secret store is reported as "locked or unavailable", not "not found", and one headless secret backend is supported; the egress and key proxy containers have log limits, run folders have a retention, and orphan containers are removed by label on recovery. The page is reached remotely through an SSH tunnel, never with `--lan` (plain HTTP with the bearer token), and the OAuth consent for Drive is given on a machine with a browser. State: new (P-OPS). To verify 12: macOS file-access permissions for launchd jobs on synced folders.

### (d) A contributor submits community evidence

The scenario: a contributor wants the workbench to know how a skill performs on a model the maintainer has not tested, and wants everyone's choice of model, and `auto` ranking, to benefit.

1. The contributor runs the model locally first, with their own keys. Those runs are local evidence (D18): kept outside the workbench checkout and the sources folder, feeding only their own `auto`, and able to release a run unattended for them. The run uses the published image pulled by digest and its own per-run key proxy. State: new (P2b, P2d).
2. To share the result, the contributor forks the repository, puts their provider key in the fork's CI secrets and calls the official reusable workflow, referenced by commit. State: new (P10).
3. The workflow checks out the official code at that commit, not the fork's code, pulls the published eval image by the digest in the lock file, and runs `eval_run.py` for the skill and the model, with no actions cache. The provider host and the model's pin come from the attested code, so the run cannot be pointed at another server. The CPU platform of the runner is recorded on each line (D20). State: new (P10, with P2). To verify 3: whether GitHub offers free arm64 hosted runners to public repositories; amd64 is accepted either way.
4. The run writes an evidence file under the same rules as a lab file: one line per run, closed vocabulary, no free-text field. A separate attestation job, the only one with `id-token: write`, receives the file's digest and GitHub attests the file; the job that ran the model never holds that permission. State: new (P10). To verify 4 and 5: the signed identity of a reusable workflow called from a fork, and whether attestation needs a public repository.
5. The contributor opens a pull request with the evidence file and its attestation. Every completed run of the fork's workflow must be submitted; a gap in the run numbers is flagged. State: new (P10).
6. The workbench's CI verifies without a model call, running the verifier from the base commit's code under `pull_request` (never `pull_request_target`): the signature, that the signer is the official workflow (`--signer-workflow`), that `--signer-digest` equals the checked-out commit, that the runner was not self-hosted, that the commit is in main's history, and that the digest matches the evidence. The existing validator checks of evidence files still apply. State: new (P10); the CI exists (`.github/workflows/checks.yml`). To verify 13: whether the pinned CLI can refuse self-hosted runners.
7. A verified file is recorded as "community verified": a column of its own per model, with a per-contributor cap (the contributor is the author of the commit that added the file, as for field evidence). It counts for everyone's choice and `auto` ranking. It does not by itself release a run unattended (D36): for another person, a pair reliable only through this column is chosen and used, with its output reviewed, until their own tests or the lab prove it. State: new (P10).
8. The rest of the protection: the pessimistic score and the cap limit what one contributor moves; field evidence demotes a pair after three `failed` verdicts. Cherry-picking of runs the contributor never submitted, and the provider's honesty, are residual risks the design cannot remove.
9. Later, the maintainer's own score tests move to the same attested CI, so that lab evidence and community evidence come from one verified path. State: future (after P10). To verify 6: whether the subscription token of the reference model works in CI.

## 5. The three pillars, mapped

| Pillar | Layers that carry it | Real after the plan | Still deferred, and its trigger |
|---|---|---|---|
| 1. Data sources and persistence | L4, L5, L3 (ingest and file-output steps), L2 (workflows, planner) | A SQLite store (exists). A mandatory sources folder the user defines, dedicated and disjoint from the runtime's folders, with guardrails, a source registry, immutable versions and a rich catalog built by code from converted output. Uploaded files and Notion pages by address (with a read-only secret); Google Drive in general with `drive.file` and the Picker on a loopback page. PDF, HTML, XLSX, CSV and DOCX converted to Markdown or CSV in a sandbox and scanned. The planner gives a task only the sources chosen for it, and the task records the version it read. File outputs (PDF, XLSX, DOCX, CSV) and write-back to Drive and Notion as approved effects. A task's file drop (exists). | OneDrive and Jira (a real project that needs them, D13). Indexing and RAG (a real case; a source over the cap is refused). Option B, the whole folder for non-web tasks (a per-project opt-in after evidence that the planner misses files, with eval cases for folder exploration). Messaging attachments (not in the plan's packages). The real case for write-back (chosen during development, D17). |
| 2. The brain | L2, L3, L6, L7, L1 | A router that also chooses sources, plans by hash, skill tasks in a container with a model the person names or `auto` (the cheapest `reliable` pair) chooses, each on its own metered key proxy. Step tasks on a resumable engine (kinds `ingest`, file output, project script). Workflows that mix steps and skills, workbench and project, with parameters and date variables, saved from a plan. Routines that always target a workflow, under D23, D24 as changed, D34 and D35: by proof in `auto`, by consent with a fixed model. A published band for each skill, model and adapter, with local and community evidence. | Agent memory (backlog R2, removed on 2026-10-15; `git show bc830832:docs/backlog.md`), replaced by the per-project standing instructions of package INSTRUCTIONS of the delegation plan. A persona per agent (plan, section 9). The short-video kind `media` (the side package). A model on the person's own machine in the lab (the container reaches only hosted providers). The maintainer's tests in the attested CI (after P10). |
| 3. Tools | L5, L6, L1 | Providers under one contract, host side, with the converter, Drive (as `integration:documents`) and write-back added. Adapters for hosted models, a per-run key proxy for one model. An MCP server of the operations layer (exists). A published image per platform, identified by its repo digest and built only in CI. One price table with source and date. A project script as a step. | MCP as a client inside a run (rejected, D15). MCP servers adopted as host-side provider implementations with read verbs (`future`, D15, no package). An Instagram or TikTok publisher (plan, section 9). OneDrive and Jira providers. |

The modes: (a) is real once P1, P2 and P3 are done, with sources once P4 is done (SEC and P2b before any run is trusted with a key); (b) needs P4, P5 and P6, with outputs from P8, Drive from P7 and project scripts from P9; (c) needs P5 and P6 (and the picker of P3 for the consent), gains Drive refresh from P7 and is fit to run 24/7 once P-OPS is done.

## 6. Contrast with the plan: errors, gaps and risks (history, with their resolution)

The verified findings of version 1. An error means the plan said something false or self-contradictory; a gap means the idea was unreachable without something the plan lacked; a risk is a hazard the plan did not name. Each was checked by the independent reviewer on another model, read-only, on this branch; the findings F1, F3, F4, F6 and F15 were re-checked by the supervising session; every line number was re-read at `d3e60770`. The class is the letter of the identifier, E, G or R; the reviewer's number F is kept. The text of each finding is version 1's; the "Resolved in version 2 by" line is version 2's, and a "Version 3:" line says what the two review rounds changed in the resolution.

### E1 (F1). The key proxy cannot be pinned per model by changing one file

- **Finding.** The old package 4 said `evals/container/keyproxy/keyproxy.json` was the one fingerprinted file it touched. The key proxy reads one `provider_only` per route (`evals/container/keyproxy/keyproxy.py` lines 79 and 187; `keyproxy.json`, line 6); routes are keyed by tier (`evals/executor.py`, `ROUTE_FILES`, line 73); the event line's `upstream` is written for the floor tier only (`evals/eval_run.py` lines 2492 to 2496). A pin per model therefore means `keyproxy.py` reads the model from the request body, and `executor.py` (in the fingerprint) changes too.
- **Effect.** Every new OpenRouter model would be a measurement change with its own epoch. "A model is a line in a list" (L6) is false for hosted models that need a pin.
- **Correction.** Make the key proxy and the routes model-keyed once, in one execution-side change; read the pin per model from the gate file's model list (outside the fingerprint). The evidence line already records `upstream`.
- **Resolved in version 2 by:** P2, D18 (the model-keyed proxy and routes in one execution-side change; the pin per model in the model list; adding a model changes no fingerprinted file).
- **Version 3:** the change is P2b, and the proxy is one per run, started with exactly one model id and its pin and refusing any other model; SEC comes before it and closes the live defect described under L6.

### G1 (F2). "Anyone may test any model" is not reachable

- **Finding.** `scratch_reason` writes evidence only when the strong and floor models, their adapters and the grader equal the gate file's (`evals/eval_run.py` lines 1855 to 1862) and the fingerprint is the committed one (line 1863); `model_id` maps an unlisted model to `unknown` (`evals/eval_status.py` lines 540 to 548); evidence is written only on `linux/arm64` (`evals/executor.py` line 81; `evals/eval_run.py` lines 1837 to 1839).
- **Effect.** A contributor would have to fork `measurement_version` and the epochs (conflicts at the next pull). On x86, such as a 24/7 server, no evidence can be written at all. Decision 2 and the "auto" for a new model rest on it.
- **Correction.** State that testing a model is private-only until community evidence exists; apply the correction of E1 so a new model is not a measurement change; decide whether amd64 evidence is wanted.
- **Resolved in version 2 by:** P2 (the model list, `--model`, local evidence outside the checkout: D2, D18), D20 (amd64 accepted beside arm64, the platform on each line), P10 (D19: community evidence reaches everyone's `auto`).
- **Version 3:** `--model` and the list are P2a and P2b; the CPU platform on a run line needs a key other than `platform` (see "Corrections to version 2 of this document"); community evidence reaches choice and ranking and never alone releases a run unattended (D36).

### G2 (F3). The proof holds only on the machine that measured it

- **Finding.** `runtime/proof.py` `checks` (lines 104 to 115) marks a pair not proven when the image digest on this machine is not in the evidence's images; the image is built locally (`evals/executor.py` line 193).
- **Effect.** On any other machine nothing is `reliable`: `auto` has no candidate and every run is `supervised`. A server and a laptop of the same person disagree.
- **Correction.** Publish or pin an image digest, or derive an identity from the definition's hash plus the platform that travels; state the behaviour in the auto rule.
- **Resolved in version 2 by:** P2, D21 (G2): the image is published by digest per platform, the lock file records the digests, the runtime pulls on first use, evidence records the published digest, the proof check compares it. A person only checks out main.
- **Version 3:** P2d. The lock file maps the definition hash to config and manifest digests per platform; identity is the repo digest, never `.Id` (I1; To verify 10); the image is built and pushed only by a protected CI workflow with provenance (a rebuilt image would de-prove everything); the first pull is an explicit setup or doctor step, not a pull during a run (I2); D39 fixes this as a decision and changes D21's "pulls on first use".

### E2 (F4). A routine's plan has no unattended approval

- **Finding.** The plan said a plan made by a routine "is still approved by hash, unless a standing policy covers it". No such mechanism exists: standing approvals cover effects only (`runtime/autonomy.py`, `covers`, line 358; `runtime/ops.py`, line 1456); `review_action` rule 1 holds every plan (`runtime/autonomy.py`, line 327); a plan is approved by a person's channel (`runtime/ops.py`, `approve`, lines 2051 to 2075).
- **Effect.** Mode (c) is not unattended; a Monday 08:00 routine waits for a person to approve its plan.
- **Correction.** The routine record, approved by hash, carries the plan hash of its flow or step with its arguments. At fire time tasks are created only if the regenerated hash equals the approved one. A request-text target never runs unattended, and the plan says so.
- **Resolved in version 2 by:** P6, D24 rules 1 and 2, D23 (the plan approved with the routine; regenerated and compared at each fire; a free-text routine becomes a plan to approve at each fire).
- **Version 3:** a free-text routine no longer exists (D31): the target is always a saved workflow, and "Save this plan as a workflow" (D32) is how free text becomes one. The approved hash is wider (D35: skill `X.Y`, image digest, script sha256 and destinations, consent, approved provider set) and excludes date values (D33).

### E3 (F5). The plan keeps one deciding model against its own decision 1

- **Finding.** The old package 4 kept "the model that decides the repository's gate". Concepts that still assume one reference model: `AGENTS.md` line 154 (the band is computed on it) and line 159 ("only the reference model's band decides a skill's standing"), `done`, the inventory's tables (`docs/inventory.md`, line 214 introduces them), the field signal "on the reference model" (`AGENTS.md` line 156), and principle 12 with backlog T23 as the battery's trigger (`docs/backlog.md`). In code: the stored-gate fallback for the configured reference (`evals/eval_status.py` lines 1180 to 1186), `complete` computed on the reference (`evals/eval_run.py` line 2507), billing history keyed to the floor model (`runtime/autonomy.py`, `history_billing`, line 220), and the fallback to the reference in `proof.route`.
- **Effect.** T23's workarounds wait for a change of reference model that will no longer exist.
- **Correction.** A per-model `done` and gate; a new trigger for a battery (a change of the lab default list or of the grader); the inventory table per model; principle 9 rewritten to match.
- **Resolved in version 2 by:** P2 (drops "the model that decides the repository's gate"; the gate and completion per model) and P3 (`AGENTS.md` principle 9, the reliability-model document, `evals/README.md` and principle 12's battery trigger rewritten without the tiers; the inventory table per model; T23's workarounds get a new trigger).
- **Version 3:** the per-model gate is P2c; P3 carries a symbol-level inventory of what the tiers touch (M3) and rewords principle 9 as D34 states it: proof decides autonomy by default, and an explicit consent, per routine (D34) or per agent (D38), can grant it.

### E4 (F6). "This already holds for the two models" is wrong

- **Finding.** The gate takes the newest full test of the major version with no filter on model (`evals/eval_status.py` lines 1133 to 1136) and the Y-change count since it reads the same test (`y_changes_since`, line 1888; used at line 2034).
- **Effect.** It is hidden today because both models run in one event. With events per model, a full test on model Z resets another model's Y count or moves its `X.Y`.
- **Correction.** Select the gate events, `complete`, the Y count and the stored gate per model, from the events whose header lists that model; add it to package 4's "done when".
- **Resolved in version 2 by:** P2 (gate, completion, Y count and stored gate selected per model; it is in the package's "done when").
- **Version 3:** P2c, with a golden `status` output as the check.

### E5 (F7). Data is handed to the wrong side of the step

- **Finding.** The old package 3 handed data "to each task in the step's `depends_on` closure"; `depends_on` points upstream, and the data must reach the step's dependents. Package 3 also came before step tasks existed, so it had no target.
- **Effect.** Converted files reach nobody in a flow.
- **Correction.** The person names the receiving task; from the step engine on, the transitive dependents receive it.
- **Resolved in version 2 by:** P4, D11, D12 (a task receives copies of the source versions chosen for it by the planner, shown in the plan; the drop-closure rule is replaced).

### G3 (F8). Data does not reach tasks created later, and a refreshed source has no home

- **Finding.** `hand_over` copies once and refuses a replacement (`runtime/drop.py` lines 96 to 97); a task created later never receives it; OPEN-1 put data only in drops.
- **Effect.** A routine that refreshes a source each Monday has nowhere to put the new version, and a flow's later tasks cannot read it.
- **Correction.** A project source store and a declared receive rule.
- **Resolved in version 2 by:** P4, D9, D10, D12 (the folder the user defines, with the registry and immutable versions; a refresh is a new version; a task records which version it read). The store is the user's folder, not a directory inside the workbench's local folder.
- **Version 3:** the folder is the *sources folder* (D30), with S6's guardrails; the registry, versions and catalog live in `runtime/sources.py`.

### G4 (F9). The planner, router and channels do not take step tasks, flow parameters or attachments

- **Finding.** The router returns one skill or one flow from the routing table (`runtime/router.py` lines 59 to 93, `skills/core-orchestrator/references/routing.md`); project flows are invisible to it (adding them is a Y change of `core-orchestrator`). `plan.combine` calls `agent_of(t["skill"])` and reads the skill's metadata for every task (`runtime/plan.py` lines 163 to 173 and 595 to 603), so a step task fails at planning. Flow arguments are fixed. Messaging has no attachment (`runtime/messaging_inbound.py` lines 7 to 17), no flow choice and no model choice.
- **Effect.** A Notion address typed in a request cannot become a step argument; a PDF cannot be sent from a phone; mode (b) is startable only by naming a flow on the page or in the terminal.
- **Correction.** Flow parameters bound from the request and covered by the plan hash; an owner rule in `plan.py`; a stated path for a router-started ingest (or say that the person names the flow); messaging attachments into the source store.
- **Resolved in version 2 by:** P5 (the owner rule in the planner and the dispatcher), P6 (flow parameters bound from the request and covered by the plan hash; project flows), P4 (the planner chooses sources). **Only narrowed:** the router does not choose a project flow, so the person names it; messaging still carries no attachment, flow choice or model choice, so a file, a model or a flow is chosen on the page or in the terminal. No package changes either; they are a later evolution of the messaging channel, after P6 (D28).
- **Version 3:** unchanged in substance. The step task, with its owner rule, is designed once in P5 (Q1, M2). One thing is new: a free-text request planned by the router may be saved as a workflow (D32).

### R1 (F10). Ingested content can leave through web runs

- **Finding.** `biz-market-analysis`, `biz-icp-positioning` and `brand-strategy` all require the web. A web task takes a drop because the file is the person's own choice, with a warning (`runtime/drop.py`, header lines 25 to 29); the proxy "is not a guarantee that nothing leaves" (`evals/executor.py` line 35).
- **Effect.** An automatic or routine ingest puts third-party text into an open-network run with no per-file choice: the channel the plan rejected as path C.
- **Correction.** Ingested data enters a web task only with the person's approval of that hand-over, or the task runs without the web.
- **Resolved in version 2 by:** P4 and P6, D16 and D27 (manual use: the plan card highlights a web task that receives sources, and approving the plan is the person's choice; a routine: a task that receives sources runs without the web, mixed work is split by the planner, and a hand-written flow that gives sources to a web task is refused as a routine target with a message to split it). **Only narrowed:** in manual use the web task still takes the person's data to the open network on their approval, and the proxy is still not a guarantee that nothing leaves.
- **Version 3:** D31 settles it when the workflow is created: the flow check refuses a web task that receives sources and offers a code-made split (`core-research` without sources, then the skill without the web, with the sources and the brief) for the skills that accept a research brief, and asks for the others. A manual free-text plan keeps D16's highlight and is still only narrowed.

### G5 (F11). A routine that is plain code is not offered

- **Finding.** Only kinds registered in the workbench exist as steps (the old package 5). Project or user code cannot run.
- **Effect.** Mode (c) "plain code" is limited to refreshing and registered kinds.
- **Correction.** A "project script" step kind with limits that satisfy principle 11: code approved by the sha256 of its exact content, run in the sandbox with no network and a read-only root, outputs only into the source store, no credentials, side effects through the effect gate; or a recorded decision against that part of mode (c).
- **Resolved in version 2 by:** P9, D25 (network off by default and declared destinations inside the approved hash; outputs only into the sources folder as a new versioned source).
- **Version 3:** S8 hardens it: declared destinations are enforced by a per-step egress proxy built from the hashed declaration, on an internal network without external DNS (To verify 11); dependencies are installed in a separate build container from hashed lock files with no mounts; the script is scanned for credentials before approval.

### R2 (F12). An overnight flow still stops at reviews

- **Finding.** `review_action` holds unproven skills (rule 5, line 336) and mandatory milestones (rule 6); a model named without evidence is supervised (decision 8).
- **Effect.** A routine on an unproven pair, or in a mode below `autonomous`, stops at its first review.
- **Correction.** State that a routine runs unattended only on pairs that are `reliable` on this machine (see G2) and in `autonomous` mode.
- **Resolved in version 2 by:** P6, D24 rule 3 (tasks proceed without review only on `reliable` pairs with the agent in `autonomous` mode; otherwise the routine waits at the first review and messaging notifies).
- **Version 3:** D34 amends it. In `auto`, release happens only for pairs proven by lab evidence or the person's own tests (community evidence does not release, D36). With a fixed model the person may consent to an `autonomous` routine with no evidence; the consent is in the approved hash and each run is recorded as "autonomy by consent". D38 gives manual use the same consent: an agent's fixed model with the agent `autonomous`.

### E6 (F13). Auto under-prices the reference model

- **Finding.** The `usage` total of `timing.json` leaves out the subagents (13.7 million tokens against 25.6 million in the rehearsal, backlog T23, "What waits"); `runtime/costs.py` `usage_of` reads `usage` of `raw.json` (line 91; whether that field also leaves them out was not tested). The old package 1's `web_measured` fix was not per model. A never-configured OpenRouter model under the one-provider pin either fails or runs unpinned.
- **Effect.** `auto` prefers the reference model on a number that is too small.
- **Correction.** Read usage from the full model usage; make `web_measured` per model; refuse, or say clearly, when a named model has no pin.
- **Resolved in version 2 by:** P2 (a usage field on run lines from the full model usage; a provider pin in each model's entry) and P1 (`web_measured` requires evidence and is per model). **Only narrowed:** whether the `usage` field of `raw.json` also omits subagents was not tested (section 7); P2 reads the full usage, but a number cannot be called right until it is compared with the provider's own count.
- **Version 3:** P2b takes the runtime's cost from the key proxy's own token count (S2), which is the provider-side count the entry above asked for; P1 shrinks to `web_measured` per model, requiring evidence. Whether the `raw.json` field omits subagents still matters only for lines written before P2b.

### G6 (F14). File outputs are missing

- **Finding.** Nothing produces XLSX, CSV or PDF for the person; writing to a Notion page that is not a mirrored document is not covered (`documents.push` mirrors manifest documents only); PDF tools for the run image wait on T23. None of it was in the plan's section 9. The Jira and Google deferral (OPEN-2) is legitimate sequencing.
- **Effect.** The pillar names HTML, PDF, XLS and CSV as files, and only the reading half was planned.
- **Correction.** An output-converter step, or list it in section 9 with its trigger.
- **Resolved in version 2 by:** P8, D17 (a file-output step by adopted tools, and write-back to Drive and Notion as an effect with the edit-since-read check).
- **Version 3:** P8 adds S9: formula injection is guarded in XLSX and CSV outputs (cells starting with `=`, `+`, `-` or `@`), hidden text in converted HTML and PDF is flagged, and the write-back target id is inside the approved payload hash.

### E7 (F15). Packages 1, 3 and 5 depend on code that is not on main

- **Finding.** `runtime/media.py`, `runtime/pipeline.py`, `runtime/ops_pipeline.py`, `runtime/video.py`, `providers/renderer/_docker.py` and `providers/transcriber/whispercpp.py` are absent on `origin/main` (checked with `git ls-tree`). The old package 3 reused `receive`, `sniff` and `ENV_KEEP` without listing their port. Package 1 gave a footprint "from its kind" but kinds arrived in package 5. Package 5's "done when" needed the short-video rebase (44 conflicting files, plan section 5) and was sized M without it. Package 2's helper could not reach main until that rebase.
- **Effect.** The order 1 to 6 could not be followed from `main` as written; the sizes were understated.
- **Correction.** Explicit ports in packages 1 and 3; package 5 depends on a short-video rebase package (L), or its second consumer is measured with ingest alone.
- **Resolved in version 2 by:** P0 (the generic pieces ported first: the step task, the intake and item store `receive` and `sniff`, `ENV_KEEP` in `runtime/ops_pipeline.py` line 70 on the branch, the container helper), P1 (a declared footprint until kinds exist), P5 (its second consumer is ingest, so it does not wait for the rebase), and the side package (the short-video rebase, off the critical path).
- **Version 3:** P0 shrinks (Q1, Q4). It ports only the generic streaming intake (about 120 lines of `runtime/media.py`) and the container helper `providers/_container.py`, which owns the whole lifecycle; there is no item store in `media.py` to port, and `ENV_KEEP` is replaced by an environment derived from `resolve.variables(cls)`. The step task and its footprint move to P5, which designs them once; P1 keeps only `web_measured`.

### R3 (F16). Package 4 reshapes the gate file while T24 is open

- **Finding.** Backlog T24 (removed on 2026-10-15; `git show bc830832:docs/backlog.md`) says the validator reads old evidence against the current gate file. `evals/eval_status.py` checks each model id of an event line against the current list (`_model`, line 760) and requires `strong` in the event header (`event_line_problems`, lines 773 and 795).
- **Effect.** Changing the gate file's shape could invalidate every committed evidence file in CI.
- **Correction.** Do T24 before package 4.
- **Resolved in version 2 by:** P2 (T24 is its first step).
- **Version 3:** T24 is P2a, the first of the four, together with a reader that accepts both gate-file shapes and the extraction of the evidence-line reading into its own module.

### Review rounds of 2026-10-14

Two independent review rounds, on the plan and on this document's version 2, produced the findings S1 to S10 and I1 to I6 (round 1) and Q1 to Q6 and M1 to M6 (round 2). Each finding's text, severity and the place where version 3 resolves it are in **the plan's table "Review rounds of 2026-10-14"** ([the plan](delegation-platform-plan-2026-10-14.md)); this document does not repeat them. The list below says, for each layer, which findings changed it, using the tags the version-3 specification attaches to each change. Where a finding is cross-cutting, it is listed last.

| Layer | Findings that changed it | What changed |
|---|---|---|
| L1 Channels | S10, M3, Q6 | S10: the creation limit for a routine with a networked script or a standing effect policy. Free text in manual use is unchanged (D37). M3: the model picker and the per-model table follow the tier inventory. Q6: fixture helper for the runtime tests' configuration. |
| L2 Orchestration | S3, S10, I5, M4 | S3: the wider approved hash (D35). S10: where a routine may be created. I5: idempotent fires and a catch-up rule. D37 leaves free-text requests as they are. M4: one X change of `core-orchestrator`, with one full test on the two lab models. |
| L3 Execution | S2, S4, S8, S9, Q1, M2, M3 | S2: cost from the proxy's count. S4: autonomy by consent and by proof (D34, D38). S8: project-script containment. S9: spreadsheet formula injection, hidden text, write-back target in the hash. Q1 and M2: the step task designed once in P5 with one owner rule. M3: the symbol-level tier inventory. |
| L4 Data | S6, I4, Q1, Q2, Q3, Q4, Q6 | Q2: the folder is the sources folder, `sources_dir` (D30). Q3: the registry, versions and catalog have one home, `runtime/sources.py`. S6: the extended guardrails of the sources folder (D30). I4: the lease file and no SQLite in a synced folder. Q1 and Q4: P0 ports only the intake, with no store code. Q6: the `sources_dir` fixture helper. |
| L5 Providers | S7, S8, S9, I3, I6, Q1, Q3, Q4, Q5 | S7: the separate read-only Notion secret and the Picker on a loopback page, with Drive as `integration:documents`. S8 and S9: the script and output hardening. I3 and I6: a distinct locked-store error and a headless backend. Q1 and Q4: `providers/_container.py` owns the whole lifecycle, and the environment comes from `resolve.variables`. Q5: the resolver does not find a new role by its folder. |
| L6 Adapters and models | S1, S2, I1, I2, I3, I6, M3, M5 | S1: SEC. S2: the per-run proxy meters tokens. I1: identity by repo digest. I2: an explicit first pull (D39). I3 and I6: log limits, retention, orphan removal, doctor checks. M3: one price table. M5: P2 as P2a to P2d. |
| L7 Proof lab | S4, S5, I1, Q6, M5 | S4: community evidence counts for choice, not for unattended release (D36). S5: the attestation hardening of P10. I1: the proof check compares repo digests. Q6: parallel tests (P-1). M5: the split of P2 (P2a, P2c). |
| Cross-cutting | M1, M2, M6, Q3, Q5 | Migration numbers assigned in the plan; new code never in `ops.py`; the fixed homes; each package's done-when updates the limits table, the contracts, the class rows and the generated tables; the glossary. |

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

### Corrections to version 2 of this document

Found while re-reading every citation for version 3, in the same checkout.

| Where in version 2 | Version 2 said | Real, at `d3e60770` and on `origin/feature/short-video` at `6794905e` |
|---|---|---|
| L4, the intake row | "the streaming, hashed intake and the content-addressed item store", generalised from media | `runtime/media.py` has the streaming intake (`sniff` 472, `receive` 714, `_stream_to` 827) and a media store whose folders are named by an id that code issues (`new_id`, line 164); it has no content-addressed store. P0 ports about 120 lines of intake and no store |
| L5, the `converter:document` row | "the resolver finds a class by its folder, `providers/resolve.py`, header" | true for the roles in `ROLES` (`integration`, `search`, `generator`, `publisher`, `messenger`; `providers/resolve.py` line 95); `converter` is not one, so a new role is a change to `ROLES`, `LISTED` (line 91), the `contracts/environment.md` row and the class rows of `CONTRACT.md`. `integration:documents`, and so Drive, is found by its folder because `integration` is a role |
| L4, L6 and L7, "the platform on each line" | the platform is recorded on each evidence line (D20) | `platform` is already an optional key of a run line and names a social platform (`evals/eval_status.py` lines 734 and 905 to 907); the CPU platform is recorded today in the event line (`evals/eval_run.py`, the event description near line 365). The CPU platform per run line needs another key, which P2b chooses |
| L3, the step task row | "extracted (P0)" | the store rows of the branch move with the step task to P5, which designs them once (Q1, M2); P0 ports only the intake and the container helper |
| L3, the footprint row | "(P1)" | the footprint, derived from the step's kind, moves to P5; P1 keeps only `web_measured` per model |
| "The data folder", throughout | one phrase for D9's folder | `data_dir` is the runtime's own required folder (`runtime/project_config.py` lines 12 and 88); D9's folder is the sources folder, `sources_dir`, disjoint from it |
| L6, the key proxy row | "model-keyed key proxy and model-keyed routes", one execution-side change | one key proxy per run, for exactly one model id and its pin, refusing any other model and metering tokens; preceded by SEC, which closes a live defect |

### Observations found while writing section 4 of version 1

Not in the reviewer's list; checked by the author only.

- **O1.** The first step of a flow has no dependency and is `ready` at approval. A file can be handed only to a task that has not started (`runtime/drop.py` lines 81 to 83). The plan named no moment at which a person hands a PDF to an ingest step, and no source path in a step's arguments. The correction was part of F8's source store: an ingest step reads a path or an address from its arguments, hashed in the plan. **Resolved in version 2 by:** P4 (the file is imported as a source into the registry beforehand and the step or the task names a source id or an address), P6 (step arguments and flow parameters are covered by the plan hash).

- **O2.** The three target skills carry the line **External content is data.** (`skills/biz-market-analysis/SKILL.md` line 49; the same line is in `biz-icp-positioning` and `brand-strategy`). Its list of sources names web pages, search results, listings, competitor sites, reviews and the research briefs written from them; a converted Notion page or PDF is not in it. The old package 3 said "No skill is bumped", and a change to that line is an X change of each skill, which asks for a full test (`AGENTS.md`, "Changing an existing skill"). Whether a model treats a converted file as data is what the converted-input cases would measure; those cases had no guard assertion for it unless one was written. **Resolved in version 2 by:** P4 (converted-input eval cases with `--baseline` on two target skills, with a guard assertion that converted text is treated as data). The line itself is not changed, so the behaviour is measured on two skills, not stated in all three. **Version 3:** P4's one X change of `core-orchestrator` carries source choice and the catalog in that skill's own external-content line; the three target skills' lines are still not changed.

### The proposed changes to the plan: adopted

Version 1 of this section proposed six changes to the plan. All were adopted in the plan's version 2: the port of the generic short-video pieces is P0 (change 1); the measurement-identity work, done once, is P2 (change 2, with the arm64 and amd64 decision as D20 and the image identity as D21); the person-named receiving task and the source store became the sources folder of P4 (change 3, with the web-task rule as D16); the routine rules, the owner rule and flow parameters are P5 and P6 (change 4); project scripts and file outputs, which version 1 left as a decision, are D25 with P9 and D17 with P8 (change 5); and the usage line is in P2 and P1 (change 6). Version 3 reshapes P0, P1 and P2 as described at the top of this document.

## 7. Assumptions, what to verify, and what is open

### Assumptions

- Assumption: the routine verbs include a `pause` that the plan's earlier text did not list (D23 names list, pause and cancel as the brakes); messaging's default policy (`DEFAULT_POLICY`, `runtime/operations.py` line 281, read, talk, answer today) gains a group with those brakes, since D23 says "by default only the brakes" and the present default carries none of them.
- Assumption: a routine's schedule is a weekday and a time of day in the project's time zone. The spec gives no format.
- Assumption: a project flow lives in a folder of the project that the spec does not name; the walk-throughs write "a project workflow file" and no path.
- Assumption: the handler that fires routines is configured under `handlers` in the project's `runtime.json` like any handler, since `_ticks` reads that key (`runtime/ops.py` lines 2446 to 2455). The spec does not say how it is enabled.
- Assumption: a routine fires at the first dispatch round at or after its time, so within the period of the scheduler's `work` job; `contracts/runtime.md` line 312 says 5 minutes, and the period set on a person's machine was not checked.
- Assumption: the catch-up rule after an outage (I5) is stated by P6; the spec fixes that one exists and that fires are keyed by (routine, slot) under the claim lock, not what the rule is.
- Assumption: how the fire-time check combines the routine's approved hash with the regenerated plan is for P6. The spec fixes what the approved hash covers (D33, D35), not the comparison.
- Assumption: the flow check of D31 runs when any project workflow is created or saved, including one that is only ever started by hand, since the spec says the mix is resolved "when the workflow is created"; a manual free-text plan keeps D16's highlight. Walk-through (b) is written that way.
- Assumption: D38's consent is the agent-level setting (the agent's fixed model with the agent `autonomous`), given on the page or in the terminal and not from a messaging channel, which the maintainer's wording does not say; and a model named on a single request that no agent has fixed keeps D8's hold, since no agent-level setting exists to carry a consent. Both readings can be changed by the maintainer.
- Assumption: the router run uses the project's default model once the tiers leave; the spec does not say.
- Assumption: the planning run that chooses sources is the router run of today (`runtime/router.py`), which receives the catalog in its input and names the sources in its reply; the spec says "the planner chooses" and that teaching it is one X change of `core-orchestrator`.
- Assumption: the plan hash covers the sources because each task entry carries its source ids (`plan_hash` is over the tasks, `runtime/plan.py` line 316); the spec says the choice is shown in the plan the person approves by hash.
- Assumption: sources enter a run as copies in a folder of the run copy, with the converted text; whether the original also enters is not stated by the spec.
- Assumption: the write-back check "nobody edited the target since it was read" re-reads the target and compares its content hash with the sha256 in the manifest of the version that was read; the spec states the check, not the mechanism.
- Assumption: the converter's tools, the ingest kind and the container helper behave as the spec states (adopted open tools convert the formats; the limits are those of the two existing providers). Version 1 named poppler, pandoc and an XLSX reader. No converter was run. The converter and the project script share the sandboxed container helper; its present rule that an image is never pulled at run time (header of `providers/renderer/_docker.py` on `feature/short-video`) is kept, and the runtime's pull of the eval image (D21) is a separate, explicit setup step before a run (I2).
- Assumption: the branch's `read_regular` (line 396) and `check_out_folder` (line 417) in `providers/renderer/_docker.py` are the nearest existing code to "the host copies back only regular files"; which package takes them is not stated (this document places the helper in P0 and the use for sources in P4).
- Assumption: how the "community verified" column enters a pair's band is not fixed by the spec (it counts for everyone's choice and `auto` ranking, with its own column and a cap, and never alone for unattended release); P10 decides the combining rule.
- Assumption: the location of the local evidence outside the checkout is chosen in P2b; the spec requires only that it be outside the workbench checkout and, by D30, disjoint from the sources folder.
- Assumption: the key under which the CPU platform is recorded on a run line is chosen in P2b; the existing `platform` key names a social platform and cannot be reused.
- Assumption: the source verbs of L1 list the channels the spec does not state; the table of operations decides them when P4 and P7 are built.
- Assumption: whether the `usage` field of `raw.json` also omits subagents (`runtime/costs.py` line 91) was not tested; the backlog states it for the `timing.json` total.
- Assumption: the file names that this document gives to new elements (`runtime/steps.py`, `runtime/handlers/routines.py`, `providers/converter/`) are the plan's; the modules that hold the file-output kinds, the project script, the routine verbs and the community workflow are not named by the spec and are not named here. The fixed homes are `runtime/sources.py`, `providers/_container.py` and the one price table.
- Assumption: P8 reuses the short-video renderer's headless browser only by porting it (P0 does not, `providers/renderer/_browser.py` is on `feature/short-video`).
- Assumption: P5 is described in the spec as registering the `ingest` and file-output kinds and P8 as building the file-output step; this document places the build in P8 and the registry in P5.
- Assumption: the time that the full runtime and evals test run takes serially (about 10 minutes) is the plan's figure for P-1; it was not measured for this document.

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
9. Whether the provider API prefers a client's `x-api-key` over the proxy's Bearer token when both are present. It says whether today's defect (S1) was exploitable; SEC strips the client's header regardless.
10. Whether `.Id` of a pulled image differs between the classic and the containerd image stores. P2d reads the repo digest, which does not depend on the answer.
11. DNS behaviour on Docker `--internal` networks, on which P9's per-step egress proxy relies.
12. macOS file-access permissions for launchd jobs on synced folders, relevant to the doctor check and to a sources folder kept in a synced location (P-OPS).
13. Whether `gh attestation verify` in the CLI version CI pins supports refusing self-hosted runners (P10).

### What is still open

Nothing from OPEN-1 to OPEN-6 remains open. What remains open is the list "To verify" above and the real cases that D17 leaves to be chosen during development (the file output and the write-back).
