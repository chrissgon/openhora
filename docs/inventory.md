# Inventory: capabilities, flows and agents

What the workbench should contain, per area. This is a plan, not a promise: a skill exists only after it has been written from the template, validated, and refined against at least one real task (see `skills/core-skill-creator/references/authoring-guide.md`).

**State legend.** `reuse`: content carried over from earlier work, adapted to the template. `rewrite`: same purpose, new content (the earlier one was organization-specific, stack-bound or duplicated). `merge`: folded into another skill. `create`: no prior content; must be written alongside a real task, never from generic knowledge. `planned`: not built until a real project demands it.

**Wave** is the build order (see the end of this document). A row that is not built names its id in [backlog.md](backlog.md), where the plan for it is.

## Core (`core-`), horizontal

| Skill | Produces | Reads | State | Wave |
|-------|----------|-------|-------|------|
| core-orchestrator | routes a request to one capability or flow across all areas; reads project state first | docs/workbench/state.md | rewrite | 0 |
| core-clarify | interrogation until shared understanding; decisions recorded in state | — | reuse | 0 |
| core-research | sourced research brief: claims with URL and access date, recency check, contradictions flagged | — | create | 0 |
| core-critique | adversarial review of any plan or artifact; at least two failure modes, each with a test | any artifact | rewrite, generalized | 0 |
| core-project-init | `docs/` layout, `docs/workbench/state.md`, autonomy mode, project `AGENTS.md` | — | rewrite | 0 |
| core-agents-md | create or update a project's `AGENTS.md` from its codebase and conventions | codebase | reuse | 0 |
| core-skill-creator | a new skill scaffolded, grounded, given its first full test in the lab, refined | authoring guide | create | 0 |
| core-security-audit | audit of the whole workbench against the security checklist; vetting of third-party skills before install | skills, agents, providers, adapters | built; grounded in the audit of 2026-09-27 | — |

`core-research` requires `search:web`. Tooling that is not a skill but belongs to wave 0: `evals/eval_run.py` (runs an eval case with and without a skill, on each lab model of the gate file, and grades assertions).

## Business (`biz-`)

All six come from splitting two earlier prompts of more than 500 lines each, which duplicated each other. Content is reused; structure is rewritten.

| Skill | Produces | Reads | State | Wave |
|-------|----------|-------|-------|------|
| biz-validate-idea | docs/business/idea-validation.md | — | rewrite (backlog NS14) | 2 |
| biz-market-analysis | docs/business/market.md | idea-validation (optional), research briefs | built; grounded in earlier content and in a real market research; requires `search:web`; scripts rank.py, capacity.py, check_refs.py, lint_market.py | 2 |
| biz-icp-positioning | docs/business/icp.md, docs/business/positioning.md | market | built; grounded in earlier content and in a real segment research; requires `search:web`; scripts rank.py, check_refs.py, lint_icp.py | 2 |
| biz-business-model | docs/business/business-model.md, docs/business/pricing.md | icp, positioning | rewrite (backlog NS15) | 2 |
| biz-gtm | docs/business/gtm.md | icp, positioning, business-model | rewrite (backlog NS16) | 2 |
| biz-business-plan | docs/business/business-plan.md | all of the above | rewrite (backlog NS17) | 2 |

## Product (`product-`)

| Skill | Produces | Reads | State | Wave |
|-------|----------|-------|-------|------|
| product-feature-spec | docs/product/specs/<feature>.md: requirements, edge cases, acceptance criteria | prd (optional) | reuse | 1 |
| product-backlog | docs/product/backlog.md: epics, stories, tasks, dependencies | prd or spec | reuse | 1 |
| product-discovery | docs/product/discovery.md: problem, hypotheses, segments | business artifacts | create (backlog NS18) | 2 |
| product-prd | docs/product/prd.md | discovery, positioning | rewrite | 2 |
| product-roadmap | docs/product/roadmap.md: prioritized, with method stated | prd | create | 2 |
| product-metrics | docs/product/metrics.md: north star, KPIs, instrumentation | prd | create (backlog NS19) | 2 |

Two spec levels on purpose: `product-prd` is product-level, `product-feature-spec` is feature-level and is what engineering flows consume.

## Brand (`brand-`)

The strategy, identity, voice and guidelines skills come from splitting two earlier prompts (392 and 1901 lines), which duplicated each other.

| Skill | Produces | Reads | State | Wave |
|-------|----------|-------|-------|------|
| brand-profile | docs/brand/profile.md: a person's trajectory, proof, goals, audiences, limits, writing samples | — | create (backlog PB1) | 3 |
| brand-name | docs/brand/name.md: name or handle research (candidates, availability of handles, domains and package scopes, conflicts, pronunciation in each language), or an audit of a name already in use | profile, strategy | create; first written for the audit mode (backlog PB12) | 3 |
| brand-strategy | docs/brand/strategy.md, for a person or a company | profile (person) or positioning, icp (company) | rewrite | 3 |
| brand-identity | docs/brand/identity.md plus brand tokens | strategy | rewrite; `generator:image` optional for moodboards; grounded in a cover image made for a real case (backlog PB10) | 3 |
| brand-voice | docs/brand/voice.md, for posts and replies | strategy, real writing samples | rewrite | 3 |
| brand-guidelines | docs/brand/guidelines.md: the brand guide, for a person or a company; for a person, one guide an agent and a human both follow (who, positioning, name, visual, voice, claims, never-expose and the sensitive-topics lock, do and don't, examples) | profile, name, strategy, identity, voice | rewrite; grounded in a real brand guide (backlog PB13) | 3 |

## Design (`design-`)

| Skill | Produces | Reads | State | Wave |
|-------|----------|-------|-------|------|
| design-ux-flows | docs/design/flows.md: user flows, information architecture, wireframe notes | prd, research | create | 3 |
| design-system | docs/design/design-system.md: tokens, components, states | brand identity | create | 3 |
| design-brief | docs/design/briefs/<artifact>.md: brief and prompt for an AI design tool, any visual artifact (screen, mockup, logo, presentation, animation, image) | design-system, flows, messaging | create; replaces design-ui | 3 |
| design-execute | docs/design/results/<artifact>.md: runs per direction, outputs, critique, decision | briefs | create; automatic with `integration:design-tool`, `generator:image` or a browser, assisted otherwise; side effect `create`; replaces design-generate-asset | 3 |
| design-handoff | docs/design/handoff/<screen>.md: implementation spec from an approved design or export | results, briefs, design-system, flows, specs | create | 3 |
| design-implementation-validation | validation report, design vs. code | handoff or design tool, code | reuse, restructure to standard folders; requires `integration:design-tool` (backlog NS20) | 3 |
| design-user-research | docs/design/research.md: plan, guide, synthesis | discovery | create (backlog NS21) | 3 |
| design-accessibility-review | docs/design/a11y-audit.md | screens or code | create (backlog NS22) | 5 |

## Engineering (`eng-`)

The most mature area: its content comes from earlier work. Stack-agnostic procedures; stacks arrive as `references/stacks/<stack>.md` from real projects.

| Skill | Produces | Reads | State | Wave |
|-------|----------|-------|-------|------|
| eng-codebase-map | docs/engineering/architecture.md for an existing system | codebase | rewrite | 1 |
| eng-architecture | architecture and ADRs for a feature or system | feature spec | reuse | 1 |
| eng-tradeoffs | ADR comparing options | options | reuse | 1 |
| eng-impact-analysis | impact section of docs/engineering/plans/<task>.md | codebase | reuse | 1 |
| eng-root-cause | root-cause section of the plan; never proposes fixes | bug report | merge | 1 |
| eng-unit-tests | failing unit tests before implementation | spec, plan | reuse | 1 |
| eng-implement | code that makes tests pass; feature and patch paths | tests, plan | merge | 1 |
| eng-integration-tests | integration and end-to-end tests after implementation | implementation | reuse | 1 |
| eng-refactor | improved code with tests green | implementation | reuse | 1 |
| eng-code-review | review report; perspectives (quality, edge cases, regression, performance, security) and a bug-fix checklist | diff | merge | 1 |
| eng-docs | documentation updates for the change | changes | reuse | 1 |
| eng-security-review | security review of a project: 0.1 triages dependency alerts (grouped by manifest and package, update or dismiss with the host's reason, dismissals behind a confirmation gate); later secrets, authentication and authorization, input handling, configuration (backlog S14) | alerts from `integration:vcs`, codebase | built, 0.1 (dependency alerts); grounded in the triage of this repository's 30 dependency alerts on 2026-09-28 | — |
| eng-data-model | schema and migration plan | architecture | planned (backlog NS23) | — |

## Delivery and operations (`ops-`)

| Skill | Produces | Reads | State | Wave |
|-------|----------|-------|-------|------|
| ops-pull-request | a pull request | branch, spec or plan | rewrite, organization specifics removed; requires `integration:vcs`; side effect `create` | 1 |
| ops-branch-sync | branch updated with its base, conflicts resolved | — | rewrite, generic; side effect `push` | 1 |
| ops-repo-baseline | a repository's security baseline: CI with pinned actions, CODEOWNERS, Dependabot, SECURITY.md, pre-commit hook, and the host settings (ruleset with signed commits, linear history and required checks; squash only; secret scanning with push protection; private reporting) applied after one approval or as a checklist | repository | built, 0.1; grounded in this repository's setup of 2026-09-27; writes the in-repository files and the host checklist, changes no host setting (backlog S17 for that) | — |
| ops-ci-pipeline | pipeline configuration, settings checklist, Pipeline section of the plan | repository | create; requires `integration:vcs`; side effect `push` | 4 |
| ops-release | release notes and version | changes | create; side effect `publish` (backlog NS1) | 4 |
| ops-qa-handover | docs/delivery/qa/<ticket>.md | diff, spec | rewrite (backlog NS24) | 5 |
| ops-infra | infrastructure as code | architecture | planned (backlog NS25) | — |
| ops-observability | dashboards and alerts plan | architecture | planned (backlog NS26) | — |
| ops-incident | runbook and postmortem | incident | planned (backlog NS27) | — |

## Marketing and growth (`mkt-`)

No prior content. Every skill here is `create` and must be written alongside a real launch.

| Skill | Produces | Reads | State | Wave |
|-------|----------|-------|-------|------|
| mkt-messaging | docs/marketing/messaging.md | positioning, brand voice | create | 4 |
| mkt-launch-plan | docs/marketing/launch-plan.md | messaging, gtm | create (backlog NS2) | 4 |
| mkt-content-plan | docs/marketing/calendar.md | launch-plan | create | 4 |
| mkt-social-copy | docs/marketing/content/<post>.md | messaging, voice | create | 4 |
| mkt-publish | a scheduled or published post, recorded in calendar and state | content, asset | create; requires `publisher:<platform>`; side effect `publish` | 4 |
| mkt-engage | replies to comments on the person's own posts inside an engagement policy | voice, strategy, notification e-mails | create; requires `publisher:<platform>` and a mailbox class; side effect `publish` (backlog PB6) | 4 |
| mkt-vote-round | the weekly vote's post and the next round's topics, for one approval | vote files, calendar, voice, strategy | create; requires `integration:vcs` (backlog PB15) | 4 |
| mkt-landing-page | docs/marketing/landing.md: structure and copy | messaging | create (backlog NS28) | 5 |
| mkt-seo | docs/marketing/seo.md | landing, content | create (backlog NS29) | 5 |
| mkt-email | docs/marketing/campaigns/<name>.md | messaging | create; requires `mailer` for the send step; side effect `send` (backlog NS30) | 5 |
| mkt-analytics | docs/marketing/analytics.md: measurement plan, experiments | launch-plan | create (backlog NS31) | 5 |

## AI and machine learning (`ai-`), horizontal

| Skill | Produces | Reads | State | Wave |
|-------|----------|-------|-------|------|
| ai-opportunity-assessment | docs/ai/opportunity.md; must be able to conclude "no AI here" | idea or discovery | create (backlog NS32) | 2 |
| ai-feature-requirements | docs/ai/requirements.md: quality metrics, fallbacks, cost ceiling | prd, opportunity | create (backlog NS33) | 5 |
| ai-ux-patterns | docs/ai/ux.md: uncertainty, feedback, human-in-the-loop | flows | create (backlog NS34) | 5 |
| ai-llm-integration | code plus docs/ai/integration.md: prompts, retrieval, tool use | requirements | create (backlog NS35) | 5 |
| ai-evals | docs/ai/evals/: datasets, graders, thresholds for the product's AI | requirements | create (backlog NS36) | 5 |
| ai-governance | docs/ai/governance.md: privacy, prompt injection, compliance | requirements | create (backlog NS37) | 5 |
| ai-observability-cost | monitoring and cost plan | integration | planned (backlog NS38) | — |
| ai-ml-model | classical model and its training data plan | data | planned (backlog NS39) | — |

## Assistant (`asst-`), optional

Nothing until the actuators, the pre-approved gate and a runtime exist. Candidates, each only for a recurring task with a real procedure: asst-inbox-triage, asst-daily-brief, asst-follow-ups.

## Flows (`flow-`)

A flow is a file, `flows/<name>.json`, that the task runtime plans at once with no model call; a row whose State says so is built as a file, and its route is `flow-<name>`. `flow-fix-bug` was a skill until 2026-10-15; its nine phases are now `flows/fix-bug.json`. Every other row is planned: its name may be cited as a route, never as something that can run today.

| Flow | Area | Phases | State | Wave |
|------|------|--------|-------|------|
| flow-fix-bug | engineering | root-cause → unit-tests → implement → code-review → pull-request | built as a file, `flows/fix-bug.json` (replaces the skill of the same name; its four optional phases, impact, options, integration tests and docs, are not tasks: a static file cannot read the plan's conditions, so they are separate requests) | 1 |
| flow-build-feature | engineering | feature-spec → architecture → unit-tests → implement → integration-tests → code-review → docs → pull-request | built as a file, `flows/build-feature.json` (backlog NS4) | 1 |
| flow-improve-code | engineering | impact-analysis → tradeoffs → refactor → code-review → pull-request | built as a file, `flows/improve-code.json` (backlog NS5); it takes the impact analysis because the request names the code, and an area nobody knows yet starts with a codebase map as a request of its own | 1 |
| flow-new-project | engineering | clarify → feature-spec → architecture → backlog | built as a file, `flows/new-project.json` (backlog NS6): the feature specification, because the design and the backlog read it and the PRD writes none; the design before the backlog, which stops without it. It ends at the backlog: the runtime adds one implementation sub-task for each todo task of the released backlog (`runtime/plan.py` `backlog_tasks`, `runtime/ops.py` `_backlog_subtasks`), and each sub-task's change becomes its pull request in a later request | 1 |
| flow-code-change | engineering | implement → pull-request | built as a file, `flows/code-change.json`: one change to existing code, with its check, to its pull request | 1 |
| flow-website | cross-area | prd → feature-spec → ux-flows → system → brief → execute → handoff → implement | built as a file, `flows/website.json`: a website from the idea to static pages | 3 |
| flow-market-positioning | business | market-analysis → icp-positioning | built as a file, `flows/market-positioning.json` | 2 |
| flow-short-video | marketing | social-copy | built as a file, `flows/short-video.json`: the script and the caption of a short video post, text only | 4 |
| flow-implement-ticket | engineering | read ticket → clarify → route to fix-bug, build-feature or improve-code → update ticket | create; requires `integration:issue-tracker` (backlog NS7) | 1 |
| flow-business-plan | business | validate-idea → ai-opportunity-assessment → market-analysis → icp-positioning → business-model → gtm → business-plan | rewrite (backlog NS8) | 2 |
| flow-brand | brand | strategy → name → identity → voice → guidelines | built as a file, `flows/brand.json` (backlog PB14); routed as `flow-brand` | 3 |
| flow-design | design | feature-spec → ux-flows → system → brief → brief → brief → brief → brief | built as a file, `flows/design.json` (backlog NS9): it plans the screens of the workbench's own interface (the specification, the UX flows, the design system, then one brief per screen); a general flow to design any product is not built | 3 |
| flow-social-post | marketing | social-copy → generate-asset → confirmation gate → publish → calendar | create (backlog NS10) | 4 |
| flow-launch | marketing | messaging → launch-plan → content-plan → landing-page → analytics | create (backlog NS3) | 4 |
| flow-new-product | cross-area | business-plan → discovery, prd, roadmap → brand (optional) → design → new-project → ci-pipeline, release → launch | create (backlog NS11) | 5 |

Flows may invoke flows one level deep (`flow-new-product` invokes `flow-business-plan`, `flow-new-project`, `flow-launch`). Never deeper.

## Agents

| Agent | Purpose | Skills | State | Wave |
|-------|---------|--------|-------|------|
| researcher | sourced research in isolation, returns a brief | core-research | create | 0 |
| explorer | read-only codebase exploration, returns a map or impact list | eng-codebase-map, eng-impact-analysis | planned: no file under `agents/` yet (backlog NS12) | 1 |
| implementer | writes code and tests for one task in isolation, stack from the project's `AGENTS.md` | eng-implement, eng-unit-tests | rewrite, stack-agnostic | 1 |
| reviewer | one review perspective per instance; several run in parallel when the harness allows | eng-code-review, core-critique | rewrite | 1 |
| social-manager | classifies each new comment on a person's own posts and drafts a reply in their voice, and proposes the post and next round of a closed weekly vote; returns a proposal the runtime checks against the approved engagement policy, never acts | mkt-engage, mkt-vote-round | create | 4 |

## Counts

Counted on 2026-10-02 from the tables above and from what exists under `skills/` and `agents/`.

| Kind | Built | Not built | Total |
|------|-------|-----------|-------|
| Capabilities | 47 | 28 | 75 |
| Flows | 1 | 10 | 11 |
| Agents | 4 | 1 | 5 |

A catalogue of this size is the reason packs exist. It is also why each wave must ship refined skills, not drafts of everything.

## Build order

| Wave | Content | Why this order |
|------|---------|----------------|
| 0 | core (7 skills), researcher agent, eval tooling | every flow depends on orchestrator, clarify, critique, state; the eval runner is needed to refine anything |
| 1 | engineering (11), product-feature-spec, product-backlog, ops-pull-request, ops-branch-sync, 5 engineering flows, explorer, implementer, reviewer | the most mature content, and the area used daily, so the refinement loop runs on real tasks from day one |
| 2 | business (6), product (4 remaining), ai-opportunity-assessment, flow-business-plan | top of the lifecycle chain; earlier content exists; needed before anything downstream in flow-new-product |
| 3 | brand (4), design (7), flow-brand, flow-design | content exists for brand; design needs a real product to be written against |
| 4 | marketing first slice (5), ops-ci-pipeline, ops-release, flow-social-post, flow-launch, first providers (publisher, image) | actuators and the scheduled-post scenario; needs a real launch |
| 5 | flow-new-product, remaining marketing (4), remaining AI (5), ops-qa-handover, design-accessibility-review, assistant candidates | the capstone flow ties every area; the rest fills in behind real demand |

Planned items are never scheduled; they are built when a project needs them.

## Real projects

Skills in waves 2 to 5 are written alongside the phase of a real project that needs them and refined against it before they count as done. When that project is an AI product, the AI skills it needs (`ai-feature-requirements`, `ai-llm-integration`, `ai-evals`, `ai-governance`) move forward to the wave of its engineering, not wave 5; `ai-opportunity-assessment` still runs first and must still be able to say which parts do not need AI.

## Evaluation status

A skill's standing is computed from its evidence, never written by hand (the reliability model, `docs/architecture/reliability-model-2026-10-02.md`; its rules are in `AGENTS.md`, "Writing standard"). `python3 evals/eval_status.py status` computes it live from the evidence files, `skills/<name>/evals/evidence/`: the pessimistic score, always with the mean and the number of runs, and the band, a rule computed for every lab model by the same rules and shown with its cause and the command that clears it.

- `needs a test`: no full test of the current major version passes the gate; or a guard assertion has a confirmed failure, or no run, in the current set; or the newest full test fails the gate, or a case changed again after it, after its changed text had run.
- `watch`: no lab run with the skill in the current set; or only guard cases have run in it; or the pessimistic score is under 0.70; or three or more Y changes since the newest full test; or a case changed after the newest full test waits for its runs; or a baseline with fewer lines per case than `runs` is within `baseline_margin` of the mean with the skill; or the field signal is on.
- `reliable`: otherwise.

A skill is done when its first full test has passed; it can be done and in `watch`. The records of the first measurement, `skills/<name>/evals/result.json`, are history and nothing reads them.

The two tables below are a published snapshot, generated by `python3 evals/eval_status.py inventory --write` at the commit they name. Do not edit them. No pull request has to regenerate them: one that adds evidence leaves them alone, `scripts/validate.py` reports tables behind the evidence as a warning, and the maintainer regenerates them in a small pull request of their own after evidence merges. The band table has one row per skill, the row of the lead model (the first of `lab_models` in the gate file, a model to show and not one that decides), and its field column sums every model; the model table has one row per skill and model that has any evidence, the lead model first, with that model's band, cause and gate (passed or failed, the mean with the skill vs the baseline mean, or not computed) beside its score, mean, runs, field and platforms, computed by the same rules on that model's lines. Every model's band is computed the same way and none ranks above another: the person's choice of model, or `auto`, decides where a skill runs, and proof decides what runs without a person by default (principle 9 of `AGENTS.md`); an explicit consent can grant what proof has not. Field columns are self-reported and never raise a band.

<!-- eval-status:begin -->
Generated at commit `54f08b5f0417` by `python3 evals/eval_status.py inventory --write`.

| Skill | Version | Band | Cause | Score | Mean | Runs (N) | Last full test | Field: uses, judged, mean (self-reported) |
|-------|---------|------|-------|-------|------|----------|----------------|-------------------------------------------|
| `biz-icp-positioning` | 1.0.0 | needs a test | guard assertion(s) 1.1, 2.1, 2.2, 2.5, 3.2 have no run in the current set | 0.65 | 1.00 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `biz-market-analysis` | 1.0.0 | needs a test | guard assertion(s) 1.1, 2.1, 2.2, 2.5 have no run in the current set | 0.61 | 0.97 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `brand-guidelines` | 1.0.0 | needs a test | guard assertion(s) 1.6, 2.1, 2.2, 2.3 have no run in the current set | 0.65 | 1.00 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `brand-identity` | 1.0.0 | needs a test | guard assertion(s) 1.4, 2.7, 3.7 have no run in the current set; pending: 3 | 0.65 | 1.00 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `brand-name` | 1.0.0 | needs a test | guard assertion(s) 1.3, 1.4, 2.1, 2.5, 3.1 have no run in the current set | 0.61 | 0.97 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `brand-profile` | 1.0.0 | needs a test | guard assertion(s) 1.10, 2.1, 2.6 have no run in the current set | 0.63 | 0.98 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `brand-strategy` | 1.1.0 | needs a test | guard assertion(s) 1.4, 1.5, 2.8, 2.9, 3.8, 3.9 have no run in the current set; pending: 3 | 0.60 | 0.96 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `brand-voice` | 1.0.0 | needs a test | guard assertion(s) 1.4, 1.5, 2.6 have no run in the current set | 0.65 | 1.00 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `core-agents-md` | 1.0.0 | needs a test | guard assertion(s) 2.1, 2.2 have no run in the current set | 0.57 | 0.93 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `core-clarify` | 1.0.0 | needs a test | guard assertion(s) 1.5, 2.1, 2.3 have no run in the current set | 0.65 | 1.00 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `core-critique` | 2.1.0 | needs a test | guard assertion(s) 3.1, 3.2, 3.3 have no run in the current set | 0.65 | 1.00 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `core-orchestrator` | 2.3.0 | needs a test | guard assertion(s) 1.4, 2.4, 3.4, 4.3, 4.4, 4.6, 5.1, 6.4, 7.4, 7.5, 8.4, 8.5, 9.3, 9.4 have no run in the current set; pending: 9 | 0.59 | 0.96 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `core-project-init` | 1.0.0 | needs a test | guard assertion(s) 1.4, 5.4 have no run in the current set | 0.65 | 1.00 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `core-research` | 1.1.0 | needs a test | guard assertion(s) 2.1, 5.1, 5.3, 5.4 have no run in the current set | 0.60 | 0.97 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `core-security-audit` | 1.0.0 | needs a test | guard assertion(s) 1.1, 1.2, 2.1, 2.2, 2.3 have no run in the current set; pending: 2 | 0.65 | 1.00 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `core-skill-creator` | 3.1.0 | needs a test | guard assertion(s) 1.1, 1.2, 1.3, 2.6, 4.7 have no run in the current set; pending: 2, 3, 4 | 0.50 | 0.87 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `design-brief` | 1.1.0 | needs a test | guard assertion(s) 2.1, 2.3, 2.4 have no run in the current set | 0.65 | 1.00 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `design-execute` | 2.0.0 | needs a test | guard assertion(s) 1.1, 1.3, 2.3, 2.5, 3.4, 4.1, 4.2, 4.3 have no run in the current set | 0.64 | 0.99 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `design-handoff` | 1.0.0 | needs a test | guard assertion(s) 1.9, 2.2 have no run in the current set | 0.65 | 1.00 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `design-system` | 2.0.0 | needs a test | guard assertion(s) 1.2, 1.6, 2.1, 2.2, 2.4, 3.1, 3.2 have no run in the current set | 0.62 | 0.98 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `design-ux-flows` | 1.0.0 | needs a test | guard assertion(s) 1.5, 2.2, 2.3 have no run in the current set | 0.58 | 0.94 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `eng-architecture` | 1.2.0 | needs a test | guard assertion(s) 2.1 have no run in the current set | 0.65 | 1.00 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `eng-code-review` | 1.1.0 | needs a test | guard assertion(s) 1.5, 2.5, 3.6, 4.2, 4.3 have no run in the current set | 0.65 | 1.00 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `eng-codebase-map` | 1.1.0 | needs a test | guard assertion(s) 1.5, 2.1, 2.3, 3.2 have no run in the current set | 0.65 | 1.00 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `eng-docs` | 1.0.0 | needs a test | guard assertion(s) 1.7, 2.1 have no run in the current set | 0.58 | 0.94 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `eng-impact-analysis` | 1.0.0 | needs a test | guard assertion(s) 1.6, 2.2, 3.1, 3.2, 3.3 have no run in the current set | 0.65 | 1.00 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `eng-implement` | 1.0.0 | needs a test | guard assertion(s) 1.4, 2.3, 2.4, 3.1, 4.2 have no run in the current set | 0.63 | 0.98 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `eng-integration-tests` | 1.0.0 | needs a test | guard assertion(s) 1.6, 2.1, 2.2, 2.3 have no run in the current set | 0.65 | 1.00 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `eng-refactor` | 1.0.0 | needs a test | guard assertion(s) 1.5, 2.3, 2.4, 3.2 have no run in the current set | 0.65 | 1.00 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `eng-root-cause` | 1.0.0 | needs a test | guard assertion(s) 1.6, 2.2, 2.4, 3.1, 3.2, 3.3, 4.1, 4.2, 4.3 have no run in the current set | 0.62 | 0.98 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `eng-security-review` | 2.0.0 | needs a test | guard assertion(s) 1.4, 1.5, 1.7, 2.1, 2.3, 2.4, 2.5, 3.2, 3.3, 3.4, 4.3, 4.4, 4.5 have no run in the current set | 0.65 | 1.00 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `eng-tradeoffs` | 1.0.0 | needs a test | guard assertion(s) 1.6, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3 have no run in the current set | 0.65 | 1.00 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `eng-unit-tests` | 1.0.0 | needs a test | guard assertion(s) 1.1, 1.6, 2.1, 2.2, 2.3, 2.4, 3.1, 3.3 have no run in the current set | 0.65 | 1.00 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `flow-fix-bug` | 1.2.0 | needs a test | guard assertion(s) 1.4, 1.5, 2.4, 2.5, 3.3, 3.4, 3.5, 4.5, 4.6, 5.5, 5.6 have no run in the current set | 0.60 | 0.96 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `mkt-content-plan` | 1.0.0 | needs a test | guard assertion(s) 1.5, 1.6, 1.7, 2.1, 2.2, 2.4, 2.5 have no run in the current set | 0.65 | 1.00 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `mkt-engage` | 1.2.0 | needs a test | guard assertion(s) 1.1, 2.1, 2.2, 2.3, 4.3, 4.4, 5.4 have no run in the current set | 0.64 | 0.99 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `mkt-messaging` | 1.0.0 | needs a test | guard assertion(s) 1.2, 2.1, 3.1, 3.2, 3.3 have no run in the current set | 0.65 | 1.00 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `mkt-publish` | 1.0.0 | needs a test | guard assertion(s) 1.1, 1.5, 1.6, 1.8, 3.2, 4.4 have no run in the current set | 0.65 | 1.00 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `mkt-social-copy` | 2.0.0 | needs a test | no full test of version 2.x | 0.00 | n/a | 0 | none | 0, 0, n/a |
| `mkt-vote-round` | 1.1.0 | needs a test | guard assertion(s) 1.3, 1.5, 2.4, 3.5, 3.7 have no run in the current set | 0.59 | 0.96 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `ops-branch-sync` | 1.0.0 | needs a test | guard assertion(s) 1.1, 1.4, 2.1, 2.3, 3.2, 3.4, 3.5, 4.4 have no run in the current set | 0.65 | 1.00 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `ops-ci-pipeline` | 2.0.0 | needs a test | guard assertion(s) 1.3, 1.8, 2.1, 2.2, 2.3, 3.3, 4.4 have no run in the current set; pending: 1 | 0.65 | 1.00 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `ops-pull-request` | 1.0.0 | needs a test | guard assertion(s) 1.4, 1.5, 2.4, 2.5, 3.1, 4.1, 4.2, 4.3, 4.4, 5.4 have no run in the current set | 0.65 | 1.00 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `ops-repo-baseline` | 1.0.0 | needs a test | guard assertion(s) 1.6, 2.2, 2.3, 2.4, 2.5, 3.2, 3.3 have no run in the current set; pending: 1 | 0.60 | 0.97 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `product-backlog` | 1.0.0 | needs a test | guard assertion(s) 2.1, 2.3, 3.2, 4.1, 4.2, 4.3 have no run in the current set | 0.65 | 1.00 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `product-feature-spec` | 1.0.0 | needs a test | guard assertion(s) 1.7, 2.1, 2.3 have no run in the current set | 0.65 | 1.00 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `product-prd` | 1.0.0 | needs a test | guard assertion(s) 1.3, 1.7, 2.1, 2.3 have no run in the current set | 0.65 | 1.00 | 3 | 2026-10-04, passed | 0, 0, n/a |
| `product-roadmap` | 1.0.0 | needs a test | guard assertion(s) 1.3, 2.1, 3.1, 3.3 have no run in the current set | 0.65 | 1.00 | 3 | 2026-10-04, passed | 0, 0, n/a |

Counts: 48 needs a test, 0 watch, 0 reliable; 48 skills.

| Skill | Model | Band | Cause | Gate: with vs baseline | Score | Mean | Lab runs (N) | Field: uses, judged, mean (self-reported) | Platforms: mean (runs) |
|-------|-------|------|-------|------------------------|-------|------|--------------|-------------------------------------------|------------------------|
| `biz-icp-positioning` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.1, 2.1, 2.2, 2.5, 3.2 have no run in the current set | passed (baseline expired), 1.00 vs 0.40 | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `biz-icp-positioning` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2, 3 | not computed | 0.60 | 0.96 | 3 | 0, 0, n/a | - |
| `biz-market-analysis` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.1, 2.1, 2.2, 2.5 have no run in the current set | passed (baseline expired), 0.96 vs 0.22 | 0.61 | 0.97 | 3 | 0, 0, n/a | - |
| `biz-market-analysis` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2, 3 | not computed | 0.50 | 0.87 | 3 | 0, 0, n/a | - |
| `brand-guidelines` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.6, 2.1, 2.2, 2.3 have no run in the current set | passed (baseline expired), 1.00 vs 0.31 | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `brand-guidelines` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2 | not computed | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `brand-identity` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.4, 2.7, 3.7 have no run in the current set | passed (baseline expired), 1.00 vs 0.00 | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `brand-identity` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2 | not computed | 0.63 | 0.98 | 3 | 0, 0, n/a | - |
| `brand-name` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.3, 1.4, 2.1, 2.5, 3.1 have no run in the current set | passed (baseline expired), 0.97 vs 0.39 | 0.61 | 0.97 | 3 | 0, 0, n/a | - |
| `brand-name` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2, 3 | not computed | 0.57 | 0.94 | 3 | 0, 0, n/a | - |
| `brand-profile` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.10, 2.1, 2.6 have no run in the current set | passed (baseline expired), 0.98 vs 0.23 | 0.63 | 0.98 | 3 | 0, 0, n/a | - |
| `brand-profile` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2 | not computed | 0.63 | 0.98 | 3 | 0, 0, n/a | - |
| `brand-strategy` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.4, 1.5, 2.8, 2.9, 3.8, 3.9 have no run in the current set | passed (baseline expired), 1.00 vs 0.67 | 0.60 | 0.96 | 3 | 0, 0, n/a | - |
| `brand-strategy` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2 | not computed | 0.59 | 0.95 | 3 | 0, 0, n/a | - |
| `brand-voice` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.4, 1.5, 2.6 have no run in the current set | passed (baseline expired), 1.00 vs 0.38 | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `brand-voice` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2 | not computed | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `core-agents-md` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 2.1, 2.2 have no run in the current set | passed (baseline expired), 0.93 vs 0.52 | 0.57 | 0.93 | 3 | 0, 0, n/a | - |
| `core-agents-md` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2, 3 | not computed | 0.57 | 0.93 | 3 | 0, 0, n/a | - |
| `core-clarify` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.5, 2.1, 2.3 have no run in the current set | passed (baseline expired), 1.00 vs 0.08 | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `core-clarify` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2, 3 | not computed | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `core-critique` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 3.1, 3.2, 3.3 have no run in the current set | passed (baseline expired), 1.00 vs 0.23 | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `core-critique` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2, 3, 4 | not computed | 0.55 | 0.91 | 3 | 0, 0, n/a | - |
| `core-orchestrator` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.4, 2.4, 3.4, 4.3, 4.4, 4.6, 5.1, 6.4, 7.4, 7.5, 8.4, 8.5, 9.3, 9.4 have no run in the current set | passed (baseline expired), 1.00 vs 0.43 | 0.59 | 0.96 | 3 | 0, 0, n/a | - |
| `core-orchestrator` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2, 3, 4, 5, 6, 7, 8 | not computed | 0.64 | 0.99 | 3 | 0, 0, n/a | - |
| `core-project-init` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.4, 5.4 have no run in the current set | passed (baseline expired), 1.00 vs 0.31 | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `core-project-init` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2, 3, 4, 5 | not computed | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `core-research` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 2.1, 5.1, 5.3, 5.4 have no run in the current set | passed (baseline expired), 0.97 vs 0.32 | 0.60 | 0.97 | 3 | 0, 0, n/a | - |
| `core-research` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2, 3, 4, 5 | not computed | 0.60 | 0.97 | 3 | 0, 0, n/a | - |
| `core-security-audit` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.1, 1.2, 2.1, 2.2, 2.3 have no run in the current set | passed (baseline expired), 0.92 vs 0.19 | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `core-security-audit` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 3 | not computed | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `core-skill-creator` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.1, 1.2, 1.3, 2.6, 4.7 have no run in the current set | passed (baseline expired), 0.90 vs 0.27 | 0.50 | 0.87 | 3 | 0, 0, n/a | - |
| `core-skill-creator` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1 | not computed | 0.58 | 0.94 | 3 | 0, 0, n/a | - |
| `design-brief` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 2.1, 2.3, 2.4 have no run in the current set | passed (baseline expired), 1.00 vs 0.08 | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `design-brief` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2, 3 | not computed | 0.62 | 0.98 | 3 | 0, 0, n/a | - |
| `design-execute` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.1, 1.3, 2.3, 2.5, 3.4, 4.1, 4.2, 4.3 have no run in the current set | passed (baseline expired), 0.99 vs 0.39 | 0.64 | 0.99 | 3 | 0, 0, n/a | - |
| `design-execute` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2, 3, 4 | not computed | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `design-handoff` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.9, 2.2 have no run in the current set | passed (baseline expired), 1.00 vs 0.17 | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `design-handoff` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2 | not computed | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `design-system` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.2, 1.6, 2.1, 2.2, 2.4, 3.1, 3.2 have no run in the current set | passed (baseline expired), 0.96 vs 0.35 | 0.62 | 0.98 | 3 | 0, 0, n/a | - |
| `design-system` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2, 3 | not computed | 0.60 | 0.96 | 3 | 0, 0, n/a | - |
| `design-ux-flows` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.5, 2.2, 2.3 have no run in the current set | passed (baseline expired), 0.94 vs 0.33 | 0.58 | 0.94 | 3 | 0, 0, n/a | - |
| `design-ux-flows` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2 | not computed | 0.46 | 0.83 | 3 | 0, 0, n/a | - |
| `eng-architecture` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 2.1 have no run in the current set | passed (baseline expired), 1.00 vs 0.39 | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `eng-architecture` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2, 3, 4 | not computed | 0.62 | 0.98 | 3 | 0, 0, n/a | - |
| `eng-code-review` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.5, 2.5, 3.6, 4.2, 4.3 have no run in the current set | passed (baseline expired), 1.00 vs 0.54 | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `eng-code-review` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2, 3, 4 | not computed | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `eng-codebase-map` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.5, 2.1, 2.3, 3.2 have no run in the current set | passed (baseline expired), 1.00 vs 0.24 | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `eng-codebase-map` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2, 3 | not computed | 0.62 | 0.98 | 3 | 0, 0, n/a | - |
| `eng-docs` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.7, 2.1 have no run in the current set | passed (baseline expired), 0.94 vs 0.21 | 0.58 | 0.94 | 3 | 0, 0, n/a | - |
| `eng-docs` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2 | not computed | 0.48 | 0.85 | 3 | 0, 0, n/a | - |
| `eng-impact-analysis` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.6, 2.2, 3.1, 3.2, 3.3 have no run in the current set | passed (baseline expired), 1.00 vs 0.39 | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `eng-impact-analysis` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2, 3 | not computed | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `eng-implement` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.4, 2.3, 2.4, 3.1, 4.2 have no run in the current set | passed (baseline expired), 0.98 vs 0.37 | 0.63 | 0.98 | 3 | 0, 0, n/a | - |
| `eng-implement` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2, 3, 4 | not computed | 0.60 | 0.96 | 3 | 0, 0, n/a | - |
| `eng-integration-tests` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.6, 2.1, 2.2, 2.3 have no run in the current set | passed (baseline expired), 1.00 vs 0.42 | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `eng-integration-tests` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2 | not computed | 0.54 | 0.91 | 3 | 0, 0, n/a | - |
| `eng-refactor` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.5, 2.3, 2.4, 3.2 have no run in the current set | passed (baseline expired), 1.00 vs 0.25 | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `eng-refactor` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2, 3 | not computed | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `eng-root-cause` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.6, 2.2, 2.4, 3.1, 3.2, 3.3, 4.1, 4.2, 4.3 have no run in the current set | passed (baseline expired), 0.98 vs 0.35 | 0.62 | 0.98 | 3 | 0, 0, n/a | - |
| `eng-root-cause` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2, 3, 4 | not computed | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `eng-security-review` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.4, 1.5, 1.7, 2.1, 2.3, 2.4, 2.5, 3.2, 3.3, 3.4, 4.3, 4.4, 4.5 have no run in the current set | passed (baseline expired), 1.00 vs 0.57 | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `eng-security-review` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2, 3, 4 | not computed | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `eng-tradeoffs` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.6, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3 have no run in the current set | passed (baseline expired), 1.00 vs 0.25 | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `eng-tradeoffs` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2, 3 | not computed | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `eng-unit-tests` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.1, 1.6, 2.1, 2.2, 2.3, 2.4, 3.1, 3.3 have no run in the current set | passed (baseline expired), 1.00 vs 0.42 | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `eng-unit-tests` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2, 3 | not computed | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `flow-fix-bug` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.4, 1.5, 2.4, 2.5, 3.3, 3.4, 3.5, 4.5, 4.6, 5.5, 5.6 have no run in the current set | passed (baseline expired), 0.99 vs 0.68 | 0.60 | 0.96 | 3 | 0, 0, n/a | - |
| `flow-fix-bug` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2, 3, 4, 5 | not computed | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `mkt-content-plan` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.5, 1.6, 1.7, 2.1, 2.2, 2.4, 2.5 have no run in the current set | passed (baseline expired), 1.00 vs 0.70 | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `mkt-content-plan` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2 | not computed | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `mkt-engage` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.1, 2.1, 2.2, 2.3, 4.3, 4.4, 5.4 have no run in the current set | passed (baseline expired), 0.98 vs 0.48 | 0.64 | 0.99 | 3 | 0, 0, n/a | - |
| `mkt-engage` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2, 3, 4, 5 | not computed | 0.58 | 0.94 | 3 | 0, 0, n/a | - |
| `mkt-messaging` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.2, 2.1, 3.1, 3.2, 3.3 have no run in the current set | passed (baseline expired), 1.00 vs 0.33 | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `mkt-messaging` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2, 3 | not computed | 0.56 | 0.93 | 3 | 0, 0, n/a | - |
| `mkt-publish` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.1, 1.5, 1.6, 1.8, 3.2, 4.4 have no run in the current set | passed (baseline expired), 1.00 vs 0.22 | 0.65 | 1.00 | 3 | 0, 0, n/a | `linkedin`: 1.00 (3) |
| `mkt-publish` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 3, 4 | not computed | 0.65 | 1.00 | 3 | 0, 0, n/a | `linkedin`: 1.00 (3) |
| `mkt-vote-round` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.3, 1.5, 2.4, 3.5, 3.7 have no run in the current set | passed (baseline expired), 0.96 vs 0.48 | 0.59 | 0.96 | 3 | 0, 0, n/a | - |
| `mkt-vote-round` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2, 3 | not computed | 0.63 | 0.98 | 3 | 0, 0, n/a | - |
| `ops-branch-sync` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.1, 1.4, 2.1, 2.3, 3.2, 3.4, 3.5, 4.4 have no run in the current set | passed (baseline expired), 1.00 vs 0.35 | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `ops-branch-sync` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2, 3, 4 | not computed | 0.63 | 0.99 | 3 | 0, 0, n/a | - |
| `ops-ci-pipeline` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.3, 1.8, 2.1, 2.2, 2.3, 3.3, 4.4 have no run in the current set | passed (baseline expired), 1.00 vs 0.72 | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `ops-ci-pipeline` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 2, 3, 4 | not computed | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `ops-pull-request` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.4, 1.5, 2.4, 2.5, 3.1, 4.1, 4.2, 4.3, 4.4, 5.4 have no run in the current set | passed (baseline expired), 1.00 vs 0.52 | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `ops-pull-request` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2, 3, 4, 5 | not computed | 0.62 | 0.98 | 3 | 0, 0, n/a | - |
| `ops-repo-baseline` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.6, 2.2, 2.3, 2.4, 2.5, 3.2, 3.3 have no run in the current set | passed (baseline expired), 0.84 vs 0.41 | 0.60 | 0.97 | 3 | 0, 0, n/a | - |
| `ops-repo-baseline` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 2, 3 | not computed | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `product-backlog` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 2.1, 2.3, 3.2, 4.1, 4.2, 4.3 have no run in the current set | passed (baseline expired), 1.00 vs 0.17 | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `product-backlog` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2, 3, 4 | not computed | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `product-feature-spec` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.7, 2.1, 2.3 have no run in the current set | passed (baseline expired), 1.00 vs 0.23 | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `product-feature-spec` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2, 3 | not computed | 0.62 | 0.98 | 3 | 0, 0, n/a | - |
| `product-prd` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.3, 1.7, 2.1, 2.3 have no run in the current set | passed (baseline expired), 1.00 vs 0.17 | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `product-prd` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2, 3 | not computed | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `product-roadmap` | `claude-sonnet-5-5` | needs a test | guard assertion(s) 1.3, 2.1, 3.1, 3.3 have no run in the current set | passed (baseline expired), 1.00 vs 0.50 | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
| `product-roadmap` | `openrouter/deepseek/deepseek-v4.1-flash` | needs a test | no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2, 3 | not computed | 0.65 | 1.00 | 3 | 0, 0, n/a | - |
<!-- eval-status:end -->

## Progress

A tick means the skill is built. Whether it passed its tests is in the band table above, not in the tick. The scores quoted in the notes below were measured while each skill was written, under the gate of that day (another strong model, another floor model, runs on a person's machine); they are history, and none of them is a skill's current result.

Wave 0:
- [x] core-orchestrator
- [x] core-project-init
- [x] core-clarify
- [x] core-research
- [x] core-critique
- [x] core-agents-md
- [x] core-skill-creator
- [x] researcher agent
- [x] eval runner (`evals/eval_run.py`; first runs on real tasks of the engineering skills; each case now runs in its own git repository, after a floor run's `git commit` reached the workbench, and may declare `setup` commands (a branch with commits) and `skills` it depends on (a flow's phases, linked in both variants); it does not yet report whether the model invoked the skill, which had to be read from the session transcripts)

Wave 1:
- [x] eng-codebase-map
- [x] eng-impact-analysis
- [x] eng-root-cause
- [x] eng-architecture
- [x] eng-tradeoffs
- [x] eng-unit-tests
- [x] eng-implement
- [x] eng-integration-tests
- [x] eng-refactor
- [x] eng-code-review
- [x] eng-docs
- [x] product-feature-spec
- [x] product-backlog
- [x] ops-pull-request (from two real pull requests and the generic part of an earlier prompt; bundles `scripts/pr-context.sh`; the floor model once changed code while preparing a pull request, to watch in real use)
- [x] ops-branch-sync
- [x] flow-fix-bug as `flows/fix-bug.json` (the skill, its cases and its evidence are in git history at the parent of pull request #426; from a real bug taken through the nine phases, the fix in one repository and the records in another; floor 0.8 at the threshold, the floor model sometimes starts eng-root-cause directly instead of the flow)
- [x] flow-build-feature, flow-improve-code, flow-new-project as flow files (backlog NS4 to NS6; no lab test, a flow file is code and its tests are offline)
- [ ] flow-implement-ticket (backlog NS7; a router's decision, not a static flow: not built)
- [x] agents implementer, reviewer
- [ ] agent explorer (planned; backlog NS12)

Built ahead of their wave, with a real project that needed them:
- [x] product-prd, product-roadmap (wave 2)
- [x] design-ux-flows, design-system (wave 3)
- [x] design-brief, design-execute (wave 3; replace design-ui and design-generate-asset: design skills produce the inputs, a specialized AI design tool or a code prototype produces the design)
- [x] mkt-messaging (wave 4)
- [x] ops-ci-pipeline (wave 4; from a real project's pipeline: one build tested and deployed, previews per pull request, a protected main branch; the floor model still misses the revoke-the-pasted-token rule and exact version pins now and then)
- [x] design-handoff (wave 3; unpacks single-file HTML exports, maps invented tokens, reads motion from scripts)
- [ ] design-system v0.3: any input (code, images, documents, a live site) or a short interview; onboarding prompt for the design tool (backlog NS13)

Built against a real personal brand (2026-09-29). Evals: strong claude-code Opus 5.5 (also the grader), floor DeepSeek V3.2 through agents-dir, 3 runs per case, floor runs in parallel with `eval_run.py --jobs`:
- [x] brand-profile 0.4 (strong 1.0 with vs 0.58 without; floor 0.917. Floor went 0.48 → 0.51 while the gate said "ask only what is missing": the floor model kept asking to confirm recorded decisions and stopped without writing. What worked was writing the profile first and turning every question into an open question inside it, with a default recommendation per item. Scripts: `linkedin_export.py` (drops contact data, computes durations), `check_profile.py`, `sensitive_topics.py`.)
- [x] brand-strategy 0.2 (strong 1.0 vs 0.80; floor 0.897 at 0.1; 0.2 fixes the two floor misses, re-offering recorded choices and writing 0 for a product that was not found, not rerun. Script: `baselines.py`.)
- [x] brand-voice 0.2 (strong 0.97 vs 0.58; floor 0.783 at 0.1, 0.878 at 0.2 after banning ranges as recommendations, "reconsider" labels and added words in rewrites. Script: `voice_stats.py`, counts and a `voice-rules` check.)
- [x] brand-identity 0.1 (strong 1.0 vs 0.50; floor 0.95 over five runs plus 1.0 on the rerun of the one run that hit the 900 s timeout while fetching font licences. Script: `contrast.py`; asset: `piece-template.html`.)
- [x] brand-name 0.3 (strong 1.0 vs 0.61 at 0.3; floor 0.72 at 0.2, 0.944 at 0.3 after default recommendations, an explicit "this skill never buys" and naming each login-only network. Script: `handle_check.py`.)
- [x] brand-guidelines 0.2 (strong 1.0 vs 0.68 at 0.2; floor about 0.5 at 0.1, when it wrote a placeholder guide with strategy and voice missing and put paraphrased rules among the examples; 0.845 at 0.2 after the gate and two checks in `check_guide.py`: every do-and-don't cell a quote, and every missing brand file named with its skill.)
- [ ] flow-brand (backlog PB14)

The content engine and the 24-hour agent (2026-09-29; backlog PB4 to PB7). Same eval setup as the brand skills; fixtures use the fictional persona Dana Example:
- [x] mkt-content-plan 0.1 (strong 1.0 vs 0.90; floor 0.844 at iteration 1, 0.944 at iteration 3 after `slots.py --after-calendar` took over continuing the language rotation, which the floor model got wrong by hand. Script: `slots.py`.)
- [x] mkt-social-copy 0.1 (strong 1.0 vs 0.71; floor 0.889, then 0.875 at iteration 4. Still failing: asked to "say how much money it saved", the floor model writes a vague figure ("six figures", "tens of thousands") in about one run in three, despite the rule against any form of an unmeasured number. Script: `check_post.py`, which runs `voice_stats.py` and `sensitive_topics.py` on the exact post and first comment.)
- [x] mkt-publish 0.1 (strong 1.0 vs 0.625; floor 0.889, then 0.875 at iteration 4. Still failing: when the token check stops the run before the payload exists, the floor model calls an older approval with a different hash "matching"; `payload.py approval` decides it once the payload is built. Script: `payload.py` (build, verify, approval).)
- [x] mkt-engage 0.1 (runtime mode and the policy procedure; iteration 1: strong 0.917 without the skill; iteration 2: strong 0.967, floor 0.911; iteration 3 after "no motive the post does not state": strong 1.0 on the praise case, floor 0.87 there. Still failing on the floor model: it adds a cause or a motive to a thank-you ("that's why I built it this way") in two runs of three, and once reused a self-reported 64% latency cut as a product benchmark. A comparison on real comments the same night (Sonnet 5.5 16/16, DeepSeek V3.2 10/16, one invented technical claim) made Sonnet the runtime model and added the source check to the gate. Scripts: `policy_gate.py`, `parse_notification.py` (comment links; the e-mail layout is still unverified).)
- [x] mkt-vote-round 0.1 (2026-09-30; runtime mode and the interactive procedure. Iteration 1: strong 0.83 (0.57 without), floor 0.74. Iteration 2, after "facts from the material behind this topic", "a used topic the person asks for is named and left out", "one block, no draft before it", two assertions aligned with their expected output and `grader_files` in eval_run.py: strong 0.96 (0.67 without), floor 0.89 over the two runtime cases; the interactive case timed out at 900 s on the floor model in all three runs, and with 1800 s (iteration 3) scored 0.67: asked to put an already used topic (tinykv 0.5 TTL) in the next round, the floor model rewords it and keeps it in all three runs, and once calls the draft approved. The runtime mode, the one the weekly step uses, passes; the interactive mode does not yet pass on the floor model. Still failing on the floor model: numbers from another note put into the winner's post, and a second, duplicated proposal block. Scripts: `vote_state.py`, `vote_update.py`.)

Built against a real company's research (2026-09-28/29):
- [x] biz-market-analysis (wave 2; 8 eval iterations. What moved the floor model from 0.475 to 0.917 was scripts, not wording: `check_refs.py` for citations, `lint_market.py` for prices under Implications, price cells, citation form and uncited figures, `rank.py` refusing free-text sources. Wording alone left the same mistakes in place from iteration 2 to 6. Remaining misses: summaries labelled as quotes, uncited figures in the Comparison reading.)
- [x] biz-icp-positioning (wave 2; passes at eval iteration 1: strong claude-code Opus 0.933 with vs 0.700 without, floor DeepSeek V3.2 0.85; built with `lint_icp.py`, `check_refs.py` and `rank.py` from the start, after what biz-market-analysis taught. 0.3 adds a `Recommended:` line under every scope question and sourced alternatives, the two iteration-1 misses, not rerun. The positioning step has not met a real case yet.)
