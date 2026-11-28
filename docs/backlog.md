# Backlog: workbench tasks

Work on the workbench itself that is not writing a skill: tooling, checks, rules, repository settings. Skills, flows and agents are tracked in [inventory.md](inventory.md); an item that becomes a skill also gets a row there.

**Each open item is a GitHub issue** with the label `backlog` and the label of its section, tracked on the project board [openhora backlog](https://github.com/users/chrissgon/projects/1) (fields `Status` and `Area`). This file is the index, one line per open item, so that an agent finds the work without a network call. Moved from this file to the issues on 2026-11-27 by T14.

- **The issue is the item.** Its title starts with the id (`T7: ...`), because ids are cited in contracts, providers, skills, `decisions.md` and commits. Ids are never reused and never renumbered.
- **A line here is edited in the pull request that opens or closes its issue.** A new item is an issue opened with an unused id, its labels and this file's line; a closed item's line is deleted in the pull request that closes its issue.
- **Issues are public and nothing checks them**: before an issue is created or edited, its text is run through the private-term check (`scripts/validate.py`, the local `.private-terms`), and a text that fails is not posted (principle 8). English only, as everywhere.
- Each item says where it came from, so none is written from generic knowledge; where it is handled is said in the item (`Plan:`, `Trigger:`, `Decision:`). Words about a skill's status follow the reliability model ([architecture/reliability-model-2026-10-02.md](architecture/reliability-model-2026-10-02.md)).
- **History.** The full text of every item as it was moved, with the notes that opened each section, is in `git show 6d760955:docs/backlog.md`; T14, the item that moved them, closed with that move. Items closed before 2026-10-14 were in `docs/backlog-archive.md` (removed on 2026-10-14; `git show d3e60770:docs/backlog-archive.md`); the items removed on 2026-10-15 are in `git show bc830832:docs/backlog.md`; the items closed on 2026-10-16 (T15, T30 and R10 by the maintainer's decisions of 2026-10-15, FLOW-WORD by its pull request, #433, and S16, S18 and PL-validation by their own pull requests, #421, #420 and #423) are in `git show 156a08cb:docs/backlog.md`. The items closed on 2026-11-27 by the review of the backlog against the code (T28, T32, T45, EM3, EM4, AQ3, NR3 and NS7) are in `git show 3298deb9:docs/backlog.md`. Ids are never reused and never renumbered: they are cited in contracts, providers, skills, `decisions.md` and commits.

## Security

- S11: Skill `ops-repo-baseline`: a real run on a project (#859, `backlog: security`)
- S14: `eng-security-review` beyond dependency alerts (#860, `backlog: security`)
- S17: `ops-repo-baseline` applies the host settings itself, when the user wants it (#861, `backlog: security`)
- LAN-PAIRING: A phone pairs with the service by a one-time code and gets its own session (#986, `backlog: security`)

## Tooling

- T7: A routing measurement per pack (#862, `backlog: tooling`)
- T18: An installed skill keeps its description in the harness's skill list (#863, `backlog: tooling`)
- T22: Move the dated fixtures forward before 2027-10-02 (#864, `backlog: tooling`)
- T48: The runtime workarounds marked `T23:` (formerly workarounds 4 to 8 of T23) (#866, `backlog: tooling`)
- T31: The installers carry what a skill needs of `providers/` and print the workbench root (#870, `backlog: tooling`)
- T41: A step kind reaches the script provider through a `ctx.services` seam (#873, `backlog: tooling`)
- T42: Channel restrictions that stay fixed after POL-1 (phase 2) (#874, `backlog: tooling`)
- T43: What policies per person leave out (POL-2) (#875, `backlog: tooling`)
- T46: Versioned, immutable measured pairs: adding a model or updating the image never changes a pair already meas... (#877, `backlog: tooling`)
- T50: Anchor the approved digest in the job's launch arguments (#1009, `backlog: tooling`)
- SKILL-SEARCH: Before writing a new skill, look for what already exists (#980, `backlog: tooling`)
- LAYOUT-CHECK: Every project keeps the same kind of file in the same place (#981, `backlog: tooling`)

## Agent runtime

- CONS-2b: The social handlers' remaining exemptions (WP-7.6, after the launch) (#878, `backlog: runtime`)
- R9: Scenario evals (#879, `backlog: runtime`)
- R12: The adapter's report of the skills a run loaded is not reliable (#880, `backlog: runtime`)
- R14: Standard flows for common requests (#881, `backlog: runtime`)
- R16: Every skill reachable from the interface (#882, `backlog: runtime`)
- R17: A task's footprint names its own files, so tasks of one area run together (#883, `backlog: runtime`)
- R23: The interface as a virtual office: Habblaud as inspiration, and possibly as the agents' interface (#884, `backlog: runtime`)
- INSTRUCTIONS: The field evidence of a use with standing instructions (#885, `backlog: runtime`)
- UI-E2E: End-to-end tests of the interface against a mocked backend (#975, `backlog: runtime`)
- SETUP-GUIDE: A guided setup of a project from zero, in the interface, over a command-line tool (#976, `backlog: runtime`)
- VOICE-MODE: Talk to openhora by voice, and let it see what the person shows (#978, `backlog: runtime`)
- CARD-READ: Decision cards on a phone are easy to read, in the project's language (#987, `backlog: runtime`)
- AC2: A conversation per agent (#991, `backlog: runtime`)
- AC3: The conversation lane: fast replies in the service, streamed (#992, `backlog: runtime`)
- AC4: What the screen shows while an agent works (#993, `backlog: runtime`)
- AC5: Agent memory in four layers (#994, `backlog: runtime`)
- AC6: The knowledge base: hybrid search with local embeddings (#995, `backlog: runtime`)
- AC7: Messages between agents, under the audit records (#996, `backlog: runtime`)
- AC8: Self-managing agents, without managers (#997, `backlog: runtime`)
- AC9: Proof of the conversation lane (#998, `backlog: runtime`)
- AC10: The office: a spike of the Habblaud fork, then its wiring (#999, `backlog: runtime`)
- AC11: Questions between agents by level, with delegations (#1000, `backlog: runtime`)
- AC12: Peer review and the autonomous work mode (#1001, `backlog: runtime`)

## Website

- W5: The website has no documentation section (#888, `backlog: website`)
- W6: openhora.dev does not appear in search results (#889, `backlog: website`)
- DESIGN-FILES: The website, and later the interface, documented in Figma (#979, `backlog: website`)

## Files from messaging apps

- AT4: Files larger than 1 MiB by e-mail; priority high (#1025, `backlog: attachments`)
- AT1: The live checks of the attachments (ATT-1 to ATT-4) (#892, `backlog: attachments`)
- AT3: Follow-ups the maintainer deferred (#894, `backlog: attachments`)
- AT5: The files of a forwarded e-mail are offered (#1026, `backlog: attachments`)

## Publishing

- PB1: Scheduling a post from the approval path (#895, `backlog: publishing`)
- PB2: A batch of posts in one approval (#896, `backlog: publishing`)
- PB3: Starting a post from a phone (#897, `backlog: publishing`)

## Project language

- L1: The language in field evidence (#898, `backlog: language`)
- L2: A routine's language (#899, `backlog: language`)
- L3: Translated headings per skill (#900, `backlog: language`)
- L4: The language on a request's line (#901, `backlog: language`)

## Brand skills and the social agent

- PB6: Skill `mkt-engage`: the e-mail parser (#902, `backlog: brand and social`)
- PB15: A weekly post vote becomes a published post (#903, `backlog: brand and social`)
- PB16: A weekly routine that lists what was published (#904, `backlog: brand and social`)
- PB17: `brand-profile` in the task runtime, and a flow for a person's brand (#905, `backlog: brand and social`)

## Skills from outside

- I1: IMPORT-PAGE: the Control room shows imported skills, read-only (#906, `backlog: imported skills`)
- I3: Archives and registry names as sources of an import (#908, `backlog: imported skills`)
- I4: Writes from the page: fetch, accept an audit, run a test (#909, `backlog: imported skills`)
- I5: A model helper for writing the cases of an imported skill (#910, `backlog: imported skills`)
- I6: `core-security-audit` writes its vetting record beside the import (#911, `backlog: imported skills`)
- I7: An imported skill may use the web, at the person's explicit word (#1027, `backlog: imported skills`)

## Answers from the sources

- NR6: A drafted body, contacts, the titles of the calendar index, FIND-1 (#913, `backlog: answers`)

## Accounts

- ACCT-LEGACY: Remove the legacy Google records (#916, `backlog: accounts`)
- HOSTED-VERIFY: Google's verification for the hosted product (#917, `backlog: accounts`)
- ACCT-SLOT: A second Google account (#918, `backlog: accounts`)

## Next skills

- NS40: Skill `core-process-diagnosis`: the platform's starting point (#919, `backlog: next skills`)
- NS1: Skill `ops-release` (#920, `backlog: next skills`)
- NS2: Skill `mkt-launch-plan` (#921, `backlog: next skills`)
- NS3: Flow `flow-launch` (#922, `backlog: next skills`)
- NS8: Flow `flow-business-plan` (#923, `backlog: next skills`)
- NS9: Flow `flow-design` (#924, `backlog: next skills`)
- NS10: Flow `flow-social-post`: the copy and asset steps (#925, `backlog: next skills`)
- NS11: Flow `flow-new-product` (#926, `backlog: next skills`)
- NS12: Agent `explorer` (#927, `backlog: next skills`)
- NS13: The next version of `design-system` (#928, `backlog: next skills`)
- NS14: Skill `biz-validate-idea` (#929, `backlog: next skills`)
- DESIGN-BLOCKS: The design skills go from screen documents to component blocks before whole screens (#982, `backlog: next skills`)
- AIV1: AI video from start to end: script, generation, editing and voice (#983, `backlog: next skills`)
- AIV2: The person's own voice, generated: a local voice-cloning model reads the script (#984, `backlog: next skills`)
- AIV3: The presenter's image, generated: a face that speaks the script (#985, `backlog: next skills`)

## Found by the audit of 2026-10-02

- N4: The grader grades its own model's runs (#930, `backlog: audit 2026-10-02`)
- N10: CI jobs that are not required checks (#931, `backlog: audit 2026-10-02`)
- N12: The Linux scheduler has never run on a real host (#932, `backlog: audit 2026-10-02`)
- N14c: One local model's results on the skills are published (#933, `backlog: audit 2026-10-02`)
- N14a: Web cases of a local model (#934, `backlog: audit 2026-10-02`)
- N14b: The Apple GPU for a local model (#935, `backlog: audit 2026-10-02`)
- N23: Field evidence: the triggers of the recorder, and contributed files (#936, `backlog: audit 2026-10-02`)
- N24: What the reliability model leaves for later (#937, `backlog: audit 2026-10-02`)

## Cases the audit proposed and nobody has added

- K1: `biz-icp-positioning`: degraded mode, no web search: a query plan, `Status: limited`, nothing scored (#938, `backlog: audit cases`)
- K2: `biz-market-analysis`: degraded mode on the scoped fixture, no web search: `Status: limited`, a query plan... (#939, `backlog: audit cases`)
- K3: `brand-guidelines`: the trigger "after any brand file changes": a guide older than the strategy gets its st... (#940, `backlog: audit cases`)
- K4: `brand-identity`: the stop on a missing `docs/brand/strategy.md`: it says which skill writes it (#941, `backlog: audit cases`)
- K5: `brand-name`: research mode after the answers: a state file with the three answers gives checked candidates (#942, `backlog: audit cases`)
- K6: `brand-voice`: the stop on a missing `docs/brand/profile.md`; also fewer than three samples (`hypothesis`)... (#943, `backlog: audit cases`)
- K7: `core-agents-md`: an instruction inside a file the skill reads: a line addressed to a model is quoted as no... (#944, `backlog: audit cases`)
- K8: `core-clarify`: an instruction inside a ticket written by someone else that says to mark it approved and sk... (#945, `backlog: audit cases`)
- K9: `core-critique`: an instruction inside the proposal that tells reviewers to approve it without findings: qu... (#946, `backlog: audit cases`)
- K10: `design-handoff`: the "only a screenshot" mode: every timing, state and value marked as an assumption or an... (#947, `backlog: audit cases`)
- K11: `product-backlog`: planning from the specification alone: every task `design pending`, its check taken from... (#948, `backlog: audit cases`)
- K12: `product-feature-spec`: a phase with several deliverables: the skill proposes which one this specification... (#949, `backlog: audit cases`)
- K13: `product-prd`: a request that is one feature: no PRD is written, and the reply names `product-feature-spec` (#950, `backlog: audit cases`)
- K14: `eng-code-review`: a check that cannot run (a lint command that is not installed): recorded as `not run` wi... (#951, `backlog: audit cases`)
- K15: `eng-codebase-map`: a specification that is named and not found: the reply asks for its path and writes not... (#952, `backlog: audit cases`)
- K16: `eng-docs`: the first Inputs gate: no plan and a changed source file; the reply asks which change to docume... (#953, `backlog: audit cases`)
- K17: `eng-implement`: a dependency that is not done (a task that comes after one still `todo`): the reply quotes... (#954, `backlog: audit cases`)
- K18: `eng-integration-tests`: the Inputs gates: no earlier release's files and no base commit; the reply asks wh... (#955, `backlog: audit cases`)
- K19: `eng-refactor`: a red check before the start (one failing test in the project): the failing check is quoted... (#956, `backlog: audit cases`)
- K20: `eng-root-cause`: a symptom that does not reproduce: after two honest attempts, what was tried with its out... (#957, `backlog: audit cases`)
- K21: `eng-unit-tests`: the missing input (no plan, no specification): the reply asks which behaviour must change... (#958, `backlog: audit cases`)
- K22: `ops-ci-pipeline`: a red run with no message ("CI is red, fix it"): the reply asks for the failing step's m... (#959, `backlog: audit cases`)
- K23: `ops-repo-baseline`: an existing `.github/workflows` file and a planted test value: the file is unchanged,... (#960, `backlog: audit cases`)
- K24: `mkt-content-plan`: a slot whose pillar has no material: an empty topic and a question that names the pilla... (#961, `backlog: audit cases`)
- K25: `mkt-social-copy`: a sensitive hit that blocks a post: the content file is `blocked` or not written, the re... (#962, `backlog: audit cases`)
- K26: `mkt-vote-round`: fewer than three topics with material: the reply asks for material and names the pillar,... (#963, `backlog: audit cases`)

## Forward notes of the writes to the person's own accounts

- W-FRAME: A person's text on cards: the framing left per kind, and the one-line field rule (#964, `backlog: account writes`)
- W2-GMAIL-BCC: Bcc and larger attachments from a Google account (#965, `backlog: account writes`)
- PHONE-NET: A phone's net finds shell lines by their shape (#966, `backlog: account writes`)
- LIVE1-REGRESSIONS: Regressions the review of #488 listed (#967, `backlog: account writes`)
- IX-1B: Interpreter Round 1b (#968, `backlog: account writes`)
- GOLDEN-APPEND-ONLY-CHECK: A code check that the merged rows of the entry golden files are append-only (#969, `backlog: account writes`)
- P5B-SERIES: A series of the calendar is not cancelled as a series (#970, `backlog: account writes`)
- P5B-AGENDA-SERVICE: `agenda` has no `service` slot (#971, `backlog: account writes`)
- P5B-TWO-WORD-TO: A two-word recipient name in the word slot `to` (#973, `backlog: account writes`)
