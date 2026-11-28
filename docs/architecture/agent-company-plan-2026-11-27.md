# The agent company: a plan

Version 6, of 2026-11-27. On `origin/main` at `9bacdbf9`. A proposal, written before any of it is built. The maintainer's decisions it rests on are recorded in `docs/decisions/2026-11-27-ac-0-agent-company.md`. Nothing here is built, and no `new` element is written as if it exists.

History:
- Version 1 was reviewed by an independent reviewer agent on another model, which read the code and the contracts. Two rounds reached a consensus on every finding (section 10).
- The maintainer answered version 2 point by point. Version 3 recorded those answers (section 11).
- Version 3 was reviewed again in the same way. One round of discussion reached a consensus on its 21 findings and 2 further points (section 12).
- The maintainer answered two points of version 4. Version 5 records those answers (section 13):
  - specialist review skills chosen by the kind of work, with a general one as the fallback (AC-D15, section 4.11);
  - OPEN-14 decided as a capability group of the governance: who started a chain decides whether it is autonomous, with a restrictive default the person may change (AC-D16, section 4.13).
- Version 5 was reviewed a final time by a new reviewer of the same kind. One round of discussion reached a consensus on its 12 findings, and version 6 records it (section 14):
  - plan release joins the autonomous parts that need `agent-chains`;
  - the review gets a mode of the contained run of its own;
  - the group gets one function, a closed list of starters and a row for every channel;
  - a routine's holding is put to the maintainer (OPEN-15, which the maintainer then decided: AC-D17);
  - the dependencies of the packages are corrected.

The main changes from version 3, made in version 4:
- The autonomous work mode has a consent kind of its own, with its warning's hash stored and checked. An `auto` agent gets plan release only by proof (sections 4.2, 4.11).
- A stopped task's questions are routed by what code can tell:
  - a missing input goes to the colleague who owns it;
  - a question goes to the person by default;
  - a lower level only behind a measured guard.

  So scaling comes from three things: work routed by code, the person's delegations, and measured downgrades (section 4.10).
- Delegations and budgets live in the accepted configuration. A colleague's answer is resolved by code under a resolution word of its own, never as the person's answer (section 4.10).
- Run replies and messages between agents reaching the lane's model route need a further decision of the maintainer (OPEN-14, decided in version 5 by AC-D16).
- Access sets reach the following, each checked by code:
  - messages;
  - the knowledge base's artifact versions;
  - colleagues' answers;
  - the reviewer's context.
- The review is a capability skill, `core-work-review`, whose lab band per model ranks reviewers. It needs no new evidence kind (section 4.11).
- Claims are made by code. Each artifact has an owning agent (sections 4.2, 4.12).
- The AGENTS.md amendments each package needs are listed (section 6).

How to read it:
- A path with a line number was opened and read at `9bacdbf9` for this plan or its reviews.
- A claim with no line number came from a search, and the text says so.
- A fact that was not confirmed is in section 9, "Not verified".
- Open questions are `OPEN-<n>` in section 7, each with a recommended answer; the ones the maintainer has decided say so.
- **v1** and **v2** name the two phases of this plan: v1 is what the packages of section 6 build; v2 is listed so that v1 does not close the door to it, and each v2 item needs its own decision.

**Status.** Each package adds its line when it is merged.
- AC0 (#989): the dated entries of AC-D10, AC-D11, AC-D12 and AC-D16 (with AC-D17) are in `contracts/runtime.md`: L26, L49 and L63 amended, R3 of the contained run amended, and the autonomous work mode's consent under "The choice of the model"; principle 9 of `AGENTS.md` states plan release and peer review. Nothing is built.

## 1. The target

The maintainer's words, 2026-11-27, translated:
- A company made of agents that act like people.
- They talk to each other, ask each other questions and do tasks for each other.
- The person talks to each one alone, as the owner of the company would, and gives tasks to one agent directly.
- They share information, and the person can look it up.
- Each agent answers as a specialist of its area, fast, as in a conversation with someone. It must not feel like a one-off chat with an AI: the agent knows who it is, what it does and everything about its current work.
- What the person and the agent said is kept, as the person's memory and the agent's.
- It must be simple and look like people working, while being AI agents.

On the same day the maintainer added the points recorded as AC-D1 to AC-D17 (section 3):
- no managers;
- a persona per agent;
- agents that talk with the person and with each other without weakening security or governance;
- a knowledge base with retrieval;
- fast replies with each step shown on screen;
- a robust memory per agent, in the project;
- a company that scales: "if everything goes through the owner, it does not scale";
- agents that can work from start to end without the person, when the person wants it.

This is the end goal recorded on 2026-09-28 (`docs/decisions.md:73`: "a company run by agents, one per department, that take tasks, talk to each other through recorded messages and keep their data"). Section 3 says which earlier choices it reverses.

## 2. Where we are

| Point | Today | Where |
|---|---|---|
| Agents | Configuration entries `area_agents` in `docs/workbench/runtime.json`. Their keys are exactly pack, enabled, mode, max_runs_per_day, max_usd_per_day, max_parallel, model and consent. There is no `area` key and no `sources` key. The planning agent is the entry named `planning`. | `runtime/autonomy.py:83` (`AGENT_KEYS`), `:156` (`agents`); `runtime/plan.py:96` |
| Modes and consent | The modes are stopped, supervised, milestones, autonomous and autonomous-with-policy. The default is milestones. The two autonomous modes release reviews: by proof, or, for an agent fixed to a model, by the person's consent. A stored consent is exactly `{"model", "mode"}`; the warning's hash is checked when the consent is given and is not stored. A change of the model or the mode makes the consent stale. `auto` and `default` need no consent: "in auto, release follows the evidence alone". | `runtime/autonomy.py:78`–`79`, `:87`, `:203`–`207`, `:224`–`230` (`consent_valid`); `runtime/ops_config.py:427`, `:437` |
| What an agent knows of itself in a run | Nothing. The run's text is the request ("the request in the person's words"), the task, the standing instructions, the handed files, the sources and the earlier answers. It names no agent, role, area or colleague. | `runtime/ops_runs.py:104`, `:106` (`task_prompt`) |
| Persona, memory, retrieval | Out of scope by earlier decisions. "Area agents are configuration, not code: they own a pack and a cap, and carry no persona or memory." Agent memory was replaced on 2026-10-15 by the person's standing instructions. A persona per agent was listed out of scope, and "Indexing or RAG. It waits for a real case (D11)". | `docs/architecture/delegation-platform-architecture-2026-10-14.md:179`; `docs/architecture/delegation-platform-plan-2026-10-14.md:147`, `:973`, `:975`; `contracts/runtime.md` (L40) |
| Who does a task | Code picks the one enabled agent, other than planning, whose pack holds the skill. A skill in several packs is an error: "exactly one must own its task". It is called directly at `ops_ask.py:113` and `:267`, `ops_reads.py:767`, `ops_round.py:216` and `ops_routines.py:151`, and through `agent_for` (`plan.py:188`) at `ops.py:1094`, `ops_round.py:157` and `ops_routines.py:524`. | `runtime/plan.py:169`–`179` (`agent_of`) |
| How a run ends | The ending of a run is one of done, question, draft_with_questions, gate, blocked or unclassified. It is classified on the whole reply. A question is one pending decision whose body is the whole reply. | `runtime/endings.py` (`ENDINGS`); `providers/store/sqlite.py:210`–`222` |
| An answer rerun | A task that stopped to ask the person reruns with every resolved pending decision whose resolution is `answered`. The prompt says: "Each answer is the user's decision". | `runtime/ops_task_run.py:154`; `runtime/ops_runs.py:133`–`138` |
| Conversation | One per project, with the planning agent, as a stage placeholder: `CONVERSATION = "project"  # one conversation per project until the local interface (stage 9)`. The read route takes a conversation name, but nothing writes another. | `runtime/ops_say.py:75`; `runtime/service.py:346` |
| History given back to the model | The planning agent only: the newest 6 messages after the last settled request, each cut to 600 characters, at most 4,000 in all. | `runtime/ops_say.py:76`, `:137` (`chat_memory`) |
| Messages store | The table of migration 6, "the messages of the conversation with the planning agent". It has no trigger that refuses a delete. The store runs in WAL mode. | `providers/store/sqlite.py:296`–`305`, `:1153` |
| Where the person's decisions live | A person's answer to a question is kept in `pending_decisions`, which is never deleted. | `providers/store/sqlite.py:314` (trigger) |
| Agents talking to each other | Only through artifacts and the dependencies of a flow (principle 4). No message between agents and no inbox per agent: a search for "message bus", "ask_agent" and "agent inbox" in `runtime/`, `providers/`, `contracts/` and `docs/architecture/` found none. | `flows/*.json`; `AGENTS.md`, principle 4 |
| Who owns an artifact | A skill: the owner table maps each artifact to the skill whose `outputs` lists it. It is generated and never edited by hand. Inputs no skill writes are rows of "Slots no built skill writes". | `contracts/project-layout.md` |
| Shared information | Sources with immutable versions and a catalog. `ask` answers from sources chosen by code, "never a model's choice", with citations checked by code. A run sees sources only through its plan's choice or an answer's selection. No index and no retrieval: a search of `runtime/sources.py` found "indexing or retrieval waits". The sources folder is dedicated (L21). | `runtime/sources.py:57`; `runtime/ops_ask.py`; `contracts/runtime.md` (L21, L26, L49) |
| Speed of a reply | Every routed line starts one contained run of the router skill (`ops_requests._router_call`, through `lab.run_skill`). There is one router run per project at a time, and the page polls a job. No streaming and no measured latency: a search of the docs, decisions and tests for "latency" and "cold start" found none. | `runtime/ops_requests.py:82`; `runtime/lab.py:994` |
| Direct model calls | The interpreter of the messaging bridge calls a model through the `model:text` provider. It makes one request and gets one reply over standard input and output, with no streaming and no tool calls. A route runs only while the newest entry of the enable file is in force; an entry names one route and the hashes it was decided on. Only messaging lines reach the model route; page and terminal lines reach it "only by a new dated maintainer decision". The gate is p95 under 4,000 ms. | `providers/model/chat-http.py`; `runtime/interpreter_enable.py`; `contracts/runtime.md` (L63); `evals/interpreter/thresholds.json:4` |
| Contained runs | `contained-run` runs a skill in the container, not an agent body. `agents/reviewer.md` exists, for the perspectives of `eng-code-review`, and gives no verdict. | `runtime/cli.py:120`; `agents/reviewer.md` |
| Measurement | The fingerprint covers the grading template, the measuring module and its constants, the executor, the container, the staging script and each eval adapter's `run-prompt.sh` and `eval.json`. | `evals/eval_status.py:820` (`FINGERPRINT_FILES`) |
| Decision cards on a phone | A card is said line by line in the project's language (`phrases.card_text`). The video delivery card shows full sha256 hashes for the file, the cover, each animation block, the preview and the delivery document. The phone text is a view: "the stored body and its hash do not change". An effect that stores only a body, with no card lines, is shown as it was stored. | `runtime/deliver_document.py:370`; `runtime/phrases.py:1518`; `runtime/phrases_parts/v1d-2.pt-BR.json`; `runtime/messaging_cards.py:183` |
| The screen | A 3D building with one floor per agent, and the Lobby with the planning agent's conversation. Floors have no message box. The page polls a change signal. R23 (#884) proposes rooms per area and possibly a fork of Habblaud. | `interface/js/views/floor.js`; `interface/js/watch.js`; issue #884 |

## 3. Decisions (the maintainer, 2026-11-27)

The record is `docs/decisions/2026-11-27-ac-0-agent-company.md`. In short:

- **AC-D1. A persona per agent.** It reverses "a persona per agent" being out of scope (`docs/architecture/delegation-platform-plan-2026-10-14.md:975`).
- **AC-D2. Memory per agent, robust and in the project.** It reverses the replacement of agent memory by the standing instructions alone (2026-10-15). The standing instructions stay.
- **AC-D3. A conversation per agent.** It ends the stage placeholder of one conversation per project (`runtime/ops_say.py:75`). That was not an earlier decision.
- **AC-D4. Agents talk to each other**, with questions and tasks, through messages the runtime carries and records, without weakening the hard limits. No skill invokes another, so principle 4 is unchanged.
- **AC-D5. No managers.** Each agent plans and manages its own work within its skills and bounds. Its plan is a route that code checks and turns into tasks (section 4.2).
- **AC-D6. A knowledge base with retrieval.** It reverses "Indexing or RAG. It waits for a real case (D11)" (`docs/architecture/delegation-platform-plan-2026-10-14.md:973`). AC6 names its first real case in its own spec. That case is a project of the maintainer: its data and results stay in that project, and only the lesson and its numbers come back (principle 8).
- **AC-D7. Fast replies, and the screen shows each step** the agent is taking.
- **AC-D8. The persona writes the whole message.** What code checked (approval cards, quotes, deliveries) is attached to the message as code rendered it. Approval cards stay, and their phone form is improved and follows the project's language (CARD-READ, #987).
- **AC-D9. Agents ask each other, by level of question.** A fact, work another agent owns and a specialist's advice go to colleagues; a decision goes to the person unless the person delegated that kind of decision; an external effect always goes to the person or a standing policy (section 4.10). It reuses the existing governance, and every conversation and action between agents is kept for audit.
- **AC-D10. Search by meaning in v1.** Keyword and embedding search together, with local embeddings by default, and an amendment of L49 and L26 that allows a ranking by a pinned embedding model and never by a generative model's choice. The lane gets a search tool whose query the agent writes, inside its access set (section 4.7).
- **AC-D11. Work from start to end without the person, when the person chooses it.**
  - An agent never approves its own work.
  - In an autonomous mode its work is reviewed by a temporary reviewer on a measured model that is different from the author's and at least as capable.
  - The discussion is bounded, and a temporary tiebreaker decides when there is no consensus.
  - The person may fix the reviewer's and the tiebreaker's models.
  - Plan release is part of the same consent.
  - External effects keep L15.
  - Section 4.11 implements it with a consent kind of its own and a review skill.
- **AC-D12. The L63 decision for the lane.** Page and terminal lines may reach the conversation lane's model route. Messaging lines are a later decision. The lane is enabled once:
  - its route hash is accepted, as the interpreter's are;
  - what leaves the host and the route's retention are shown;
  - the route has a reliable band.

  What else reaches that route (run replies, messages between agents) is decided by AC-D16.
- **AC-D13. The memory rules** of section 4.6.
- **AC-D14. Scaling without managers:** one responsible agent per request, authority from owning an artifact, priorities set by the person (section 4.12).
- **AC-D15. Review by specialists.** Code chooses the review skill by the kind of work: code, plans and documents, and designs each have their own, and a general review skill is the fallback for the rest (section 4.11).
- **AC-D16. Who started a chain decides whether it is autonomous** (OPEN-14).
  - **What leaves the host:** the replies of runs and the turns between agents, in chains whose starter holds a **`new`** capability group, `agent-chains`, may reach the lane's model route.
  - **The group's defaults:** it is in the terminal, which is never narrowed, and on the page by default. It is in no default on messaging. The person gives it to a sender's profile, their own or a trusted person's, with `accept-config --widen`, and may take it off the page.
  - **What it changes:** only which chains get the autonomous parts. It never changes what agents may read or do (section 4.13).
- **AC-D17. A routine holds `agent-chains` only when it was approved on a channel that holds it** (OPEN-15). That holding enters the routine's content hash, as the consent of D34 does. A routine drafted from messaging holds it only through the channel that approved it, and it loses the group at its next run when that channel no longer holds it.

## 4. Design

### 4.1 The agent's profile (persona)

- **`new`** One file per agent: `docs/workbench/agents/<agent>.md`, where `<agent>` is the key of `area_agents`. It is a row of "Slots no built skill writes" in `contracts/project-layout.md`, provided by `user`. The owner table is generated and is not edited by hand.
- **What it holds:**
  - a display name;
  - the role in a sentence;
  - how it speaks;
  - what it must never do;
  - the appearance the office draws.
- **What code adds when it reads the profile, never typed:**
  - its area;
  - its skills (its pack);
  - its colleagues (from `area_agents`).
- **Written by the person only, as the standing instructions are (L40).**
  - The path rule refuses the file as a run's output under every spelling, as L40 does.
  - Code checks it as the instructions are checked: UTF-8, a regular file inside the project, a size cap, the credential scan, no invisible character, no prompt-separator line.
  - An agent may propose a change, and the person accepts it on the page or in the terminal (OPEN-2).
- **Where it enters: the conversation lane only (section 4.4)**, as a nonce-marked data block.
  - It never enters a skill run, so the skills' bands still describe the runs (principles 9 and 10).
  - Its wording says it never overrides a stop rule, a gate or a refusal.
  - In the lane the persona writes the whole message (AC-D8); what code checked is attached (section 4.4). Artifacts a skill run writes keep no persona voice: they are documents, not conversation.
- The profile is project data (principle 8); the workbench holds only its template.

### 4.2 Agents that manage themselves, and governance without managers

- **Area membership.** **`new`** A key `area` per entry of `area_agents`. An area may hold several agents, and an agent's pack stays the list of its skills.
- **`agent_of` changes.** Today it refuses a skill held by several agents (`runtime/plan.py:169`–`179`). With several agents per area, a planned task of a skill they share is **open** until code assigns it. AC8 changes every caller listed in section 2, among them:
  - the plan's `combine`;
  - the owners of `ask`;
  - cost attribution (`ops_core.attributed`);
  - the rounds;
  - the routines, where an open task at its scheduled time is assigned by the same rule.
- **Claims are made by code.** **`new`** store logic:
  - The dispatcher assigns an open task to a free agent of the area by a deterministic rule that is recorded: the fewest running tasks first, then the agent's name.
  - A task has at most one owner at a time. The assignment and its check happen in one transaction of the store, so a second assignment is refused. This is new code: the runtime's file locks (`runtime/ops_core.py:364`, `_try_lock`) are another mechanism.
  - The person can reassign at any time, and a reassignment is recorded.
  - No agent claims by itself, so `claim` is not an operation of the agent channel.
- **An agent's own plan is a route.** An agent may ask for its work to be split into tasks of its own skills. What it returns is a route, and code turns it into tasks, as L19 requires (`router.read_route`, `runtime/router.py:166`, is the model).
  - **Who writes it:**
    - the router skill `core-orchestrator`, limited by code to that agent's pack, in a contained run. This is a Y change of that skill, with cases of routes limited to one pack (AC8);
    - or the lane, in a turn when the person talks to the agent. AC9 measures those routes.
  - **What code checks:**
    - every task is a skill of that agent's pack;
    - every step outside the pack is a request to the colleague who has it (section 4.3);
    - the route fits the agent's caps and the chain's budget.
  - A route that fails a check is refused and recorded. This is how an agent splits a task in two.
- **Plan approval.** Every plan waits for the person's approval, as today, except in the autonomous work mode of section 4.11, and only in a chain whose starter holds `agent-chains` (section 4.13). In any other chain the plan waits for the person, whatever the agent's consent.
  - **An agent fixed to a model:** plan release comes with the work mode's consent. That consent is a **`new`** consent kind:
    - **The warning:** its sha256 is stored in the consent, and the consent is valid only while that hash equals the current warning's hash. A consent given under an earlier warning, and every consent of today's kind, never gains plan release.
    - **Revocation:** it goes stale when the person changes the model or lowers the mode, as `consent_valid` does today.
    - **Where:** given only on the page or in the terminal.
    - **What it is:** a consent, not an application of proof. A skill's band says nothing about whether a model-made plan is right, so every such run is recorded as autonomy by consent (principle 9).
  - **An `auto` agent:** plan release comes only by proof: a reliable band of `core-orchestrator`'s routes limited to one pack, on the pair `auto` chose. There is never a consent for an `auto` agent (principle 9).
  - **Even with the consent or the proof, these stay as they are:**
    - a plan with an effect (L15), unless a standing policy covers it;
    - a networked project script (L36);
    - a web task;
    - a routine (L33).
- **Unchanged:**
  - An external effect is executed by code with the exact content approved or inside a standing policy (L15, principle 11).
  - Credentials never enter a run.
  - Caps per agent stop a runaway.
- **The planning agent becomes the reception (OPEN-4).** A request addressed to nobody is routed to the area or agent whose skills fit. This changes what the router skill `core-orchestrator` returns, which is a Y change of that skill at least, with its tests (AGENTS.md, "Changing an existing skill"). It is part of AC8.

### 4.3 Messages between agents

- **`new`** One table of messages between agents, under L13: triggers refuse a delete and refuse a change. They are the record of who asked whom, which governance and audit need.
- **Four kinds:**
  - **question**: expects an answer;
  - **request**: expects a task done;
  - **delivery**: a result, with the artifacts it names;
  - **notice**: no reply expected.
- **What each message names:**
  - its sender and its receiver;
  - the chain it belongs to;
  - its level, when it is a question (section 4.10);
  - its provenance: the person, an agent, or external content;
  - the sender's access set (section 4.7). The receiving side filters on it: a receiver whose access set does not cover the message's set does not see the text.
- **"Agent" is a channel with a literal allow-list ceiling.** It is built in `runtime/operations.py`, as `INSTRUCTIONS_CHANNELS` and the channel ceilings are.
  - The ceiling allows a read, a notice, sending a question, a request or a delivery, and proposing a route (section 4.2). Nothing else.
  - Every other operation is refused by default: approve, answer for the person, resolve a pending decision, claim, release, reject, cancel, retry, a verdict, every configuration change, consent, a delegation, a routine, a source, the instructions or a profile, and every effect or gated operation.
  - A reviewer's verdict (section 4.11) is not an operation of this channel: it is the output of a contained run of a review skill, which code reads, as it reads a route.
  - A colleague's answer is a message. Code, not the agent, resolves the pending decision it answers (section 4.10).
  - `operations.refusal` is called with that channel. A test walks the whole table.
  - It is a **`new`** limit, numbered when built.
- **Where agents talk.** In the conversation lane (agent to agent, in chains whose starter holds `agent-chains`, section 4.13), and from a stopped task through the routing of section 4.10. A request becomes a task of the receiver.
- **A request written by an agent.** It becomes a task with a **`new`** field recording where its text came from.
  - The task's prompt carries that text in a block marked "written by agent X, not the person". It never passes as "the request in the person's words" (`runtime/ops_runs.py:106`).
  - A colleague's information never enters the `answered` channel (`runtime/ops_task_run.py:154`, `runtime/ops_runs.py:133`–`138`); it has a block of its own (section 4.10).
  - Agent-written text that enters a run passes the credential scan of `scripts/redact.py` in code first.
- **Brakes, needed from the start:**
  - every chain between agents starts from a starter of the closed list of section 4.13 (terminal, page, a messaging sender, a routine), recorded on the chain;
  - a limit of hops per chain;
  - a budget per chain set where it started (OPEN-3);
  - the same question to the same agent in one chain is answered once;
  - a conversation between agents that nothing above started does not exist in v1.
- **External content stays data.** A message whose text came from a web page or a document keeps that provenance. The receiver treats it as data, and an instruction inside it gains no power by passing between agents.
- **Visible and kept.** Every message between agents is visible to the person and kept in the store for audit. Nothing between agents is hidden from the owner. What reaches the inbox is bounded (section 4.10).
- **v2, its own decision:** conversations between agents that nothing above started, once the budgets are built and measured.

### 4.4 The conversation lane

- **What it is.** **`new`** A turn of conversation with an agent runs in the service, not in a container. It is one model call per step, streamed to the page.
- **Before the lane: the same dispatch as a line to the planning agent.** A line addressed to an agent first passes the dispatch every line passes today: typed commands, tier-1 forms, the state questions code answers, and the refusals of `NATURAL` (L54). Only what would have reached the router reaches the lane. L54 is extended to say so; otherwise a line to an agent would skip every L54 check.
- **The L63 condition.**
  - **Decided (AC-D12):** page and terminal lines may reach the lane's route; messaging lines are a later decision.
  - **Decided (AC-D16):** run replies and turns between agents, which are not a person's line, reach the route only in chains whose starter holds the group `agent-chains` (section 4.13).
  - **Enabling:**
    - **`new`** An enable entry may list several routes (today an entry names one, `runtime/interpreter_enable.py`), each with its hashes.
    - The lane runs on a listed route only while its band is `reliable` (AC9).
    - Accepting the hash of the route that was built is the existing procedure for a route, not a new question about L63.
    - The switch is a setting of the page. The terminal is never narrowed.
    - Beside the switch, the page prints what leaves the host, kind by kind (the profile, the thread, the memories, artifact text, source passages), and the route's retention.
- **Safety given up for speed (principle 13).**
  - **Given up:**
    - the container boundary, for a turn: a turn runs in the service process, with the service's network;
    - artifact text, which today is read by runs inside the container, leaves the host to a hosted route when the lane reads it.
  - **Kept:**
    - no tool writes outside the store's own records;
    - no tool has an external effect;
    - no credential enters the prompt, and every outgoing data block passes the credential scan of `scripts/redact.py` in code;
    - the inputs are chosen by code, except the two the agent chooses: the search tool's query and the artifact it asks to read, both inside the agent's access set;
    - the tool list is a literal a test compares.
  - **Saved:** a container start per turn, the cost the maintainer named as the delay.
- **The provider.** The `model:text` provider today makes one request and gets one reply. AC3 adds what the lane needs, either as a mode of that class or as a new runtime-only class:
  - streaming;
  - a bounded loop of read-only tool calls.
- **Pinning.** The pinned hash covers:
  - the lane's fixed prompt template, including the sentence that explains the nonce blocks;
  - the literal list of the lane's tools and their schema;
  - the retrieval code's version and the embedding model's id;
  - the caps on the size of each data block.

  The per-project content enters as nonce-marked data blocks and is never part of the pinned text: the profile, the working memory, the thread and the passages.
- **Inputs.** It is a **`new`** limit of its own; L49 covers an answer run, and the lane is not one.
  - The profile.
  - The working memory: tasks and state, computed from the store.
  - The newest part of the thread.
  - The memories and passages the first retrieval finds, from a query built by code from the person's line and its `@` mentions.
  - What the two agent-chosen tools return (below).
  - Every retrieval is filtered by the agent's access set and by each memory's, passage's or artifact version's access set.
  - The channel rules of L49 are inherited:
    - a mail or calendar snapshot, and a memory derived from one, only with `@<id>`, and only from the terminal or the page;
    - a version the person changed by hand only where the person is.
- **Tools, read-only and run by code.**
  - Read an artifact, a task's state, or the agent's own board. The task-state tool returns no run-reply text for a chain whose starter does not hold `agent-chains`, nor on a page that does not hold it (section 4.13). Reading an artifact by its path follows today's rule for project files: an artifact is project content every agent may read. Restricting artifacts themselves is out of this plan (section 8).
  - Search the knowledge base with a query the agent writes (AC-D10). Code runs the search, filters it by the access sets, caps the number of passages and records the query and what came back.
  - Each tool is limited to what that agent may read.
- **Bounds, with numbers fixed in AC3's spec:**
  - tool-loop iterations per turn;
  - the size of each data block and of the whole context;
  - concurrent turns per agent and per project. Today one conversation model call per project at a time is the rule (`contracts/runtime.md`, "The conversation").
- **Cost.** Each turn's tokens and cost are recorded against the agent's `max_usd_per_day`, as runs are.
- **The persona's message and what code checked (AC-D8).** "A model's text never passes for what code checked" (`contracts/runtime.md`, "The answer from sources").
  - The persona writes the whole message in its own words.
  - What code checked is attached to the message as code rendered it: a quote as a citation that opens the exact passage, a delivery as a link, an approval or decision card as the card.
  - An approval card is always rendered by code and bound to its hash (L16, L44). The person approves the card, never the persona's summary of it.
  - The persona's text is marked as the agent's words. AC9 measures whether it misstates an attachment.
- **Work becomes a task.** When the person asks for work, the lane proposes a task of that agent, or a request to a colleague. Code builds it from a route (L19), and it runs in the container as today, under the same review and approvals.
- **Speed.**
  - A fast model for the lane, chosen among the routes with a reliable lane band, separate from the run model.
  - The fixed blocks first, so the provider's cache reuses them.
  - Few passages per turn.
  - Summaries of long documents made once, ahead.
  - Measured per model: time to the first event on screen, to the first word, and the whole turn. The targets are set from the first measurements (OPEN-5).

### 4.5 What the screen shows while an agent works

- **`new`** A core event schema: one event per step, for example "looking up 'plan price' in the sources", "reading `briefing.md`", "asking the designer", "writing the answer", "the reviewer is checking the criteria".
- **Where the events come from:**
  - **The lane:** it emits its events itself.
  - **A contained run:** the steps exist only in the adapter's `stream.jsonl`, in a format specific to the tool.
    - Turning that format into events belongs in `adapters/<harness>/` (principles 1 and 2). Each eval adapter gains a parser, and the core reads only the schema.
    - The parser is a file of its own, outside `FINGERPRINT_FILES` (`evals/eval_status.py:820`), so that adding it is not a measurement change.
    - AC4 first checks whether `stream.jsonl` is written while the run is going (section 9).
- **Who sees what.** An event can carry a query's text or a file's name, so it follows the rule of the answer it belongs to (L50): its full text is readable only by the channel that asked. Other readers, the office included, see its kind and its agent.
- **How events reach the page.** The service streams them to the page; today the page polls a change signal (`interface/js/watch.js`). AC4 first checks whether the service's design can stream (section 9).
- **Where they show.** The same events feed the chat, as a line under the agent's name, and the office, as the bubble over the character (R23).

### 4.6 Memory, in four layers (AC-D13)

1. **The thread** of each conversation, in the store (the table of migration 6, with a conversation per agent).
   - Messages between agents fall under L13 (section 4.3).
   - The person's threads with an agent can be erased by the person, because the person's decisions already live in `pending_decisions`, which is never deleted, and the tasks, approvals and decisions that came from a thread are kept in their own records. Erasing keeps a tombstone (id, hash, time, who erased it) and erases the text.
2. **The profile** (section 4.1).
3. **The working memory:** its tasks, their state, what it waits for. Always computed from the store, never remembered by a model.
4. **The long-term memory:** facts, decisions and preferences the agent learned, each with its source, its date and its access set (inherited from the sources it came from).
   - It lives in the store, with its own index, not in files and not in the sources folder. That avoids committing conversation content to the project's git.
   - It is written by agents, and read, edited and deleted by the person on the page or in the terminal. That is the place where the person reads and edits, and it is the source the agents read.
   - Edits through MCP or messaging are not allowed. Reading it there is its own decision (OPEN-11).
   - A memory that came from external content carries that mark. Such a memory never enters a turn that carries an effect proposal.
   - A memory derived from a mail or calendar snapshot surfaces only when the person names it with `@<id>` (L49).
   - Old threads are summarised into it.
   - What reviewers found in an agent's work is written into that agent's long-term memory (section 4.11).

**Before AC6,** a memory is found by code from the person's line by keyword, inside the store's own full-text index. AC6 adds the search by meaning (section 4.7).

**Real erasure.** A deleted row's text stays in the store's free pages and in the WAL file until a checkpoint, and the full-text index keeps a copy of its own. Erasing a memory or a thread therefore:
- turns on `secure_delete` for the erasure, or runs a vacuum;
- deletes the full-text index entries and runs the index's optimize;
- deletes the embedding vectors;
- runs a WAL checkpoint;
- keeps the tombstone, so a turn that cited it can still be audited.

What an erasure does not reach, and what the page says:
- Erasing a thread offers to erase the memories summarised from it too.
- Copies of the text inside L13 records stay: messages between agents and review findings.
- An erasure does not reach an export made before it.

The contract says that memories and the person's threads are outside L13. L13's scope is approvals, tasks, runs and pending decisions, and this plan adds the records between agents of sections 4.3, 4.10 and 4.11.

### 4.7 The knowledge base (retrieval)

- **What it searches.** The project's sources (immutable versions, as today), what agents make (artifact versions, each with its author agent, date, provenance and access set), and the long-term memories in the store (section 4.6).
- **Where the sources' index lives.** Beside the project's sources folder, never inside it, because that folder is dedicated (L21). It is outside git. AC6 restates for it as limits:
  - the disjointness check of L22, by device and inode, against `data_dir`, the store and the checkout;
  - no following of links (L23, `O_NOFOLLOW`).
- **v1: hybrid search (AC-D10).** It ranks passages, not whole documents. `ask_select` ranks whole documents today, so ranking passages is new code in AC6.
  - Keyword search, through a full-text index.
  - Search by meaning, through embeddings, computed by a local embedding model by default. A hosted embedding provider is an option the person turns on, and what it sends leaves the host.
  - The two rankings are combined by code, after filtering by the access sets, with a fixed number of passages. The ranking, its scores and the embedding model's id are recorded for audit.
- **Access sets.** Every search filters on them before ranking.
  - **`new`** A key `sources` per entry of `area_agents`: the sources that agent may read.
  - A memory inherits the access set of the sources it came from.
  - An artifact version in the index carries the union of the sources (`task_sources`) of the run that wrote it.
  - An answer that cites a source or an artifact version the asking agent may not read is refused by code (section 4.10). Without this, a restricted source could pass through an artifact citation.
- **The amendment of L49 and L26 (AC-D10, extended).**
  - An answer's inputs are chosen by code, which may rank by the similarity of a pinned embedding model; never by a generative model's choice.
  - An embedding model takes no instruction: it turns text into vectors, and code computes the similarity.
  - The lane's search tool, whose query the agent writes, is allowed inside the agent's access set.
  - `ask`, the answer with checked citations, keeps a query built by code.
  - L26 is also amended for two new paths into a run, the colleagues' answers block (section 4.10) and the reviewer's context (section 4.11). Passages reach them by a selection code makes, and each is recorded as a `task_sources` row of that run.
- **Learning.** An agent that reads new content, in a task, writes notes into its long-term memory, with the source's access set.
- **Prompt injection through indexed content.** Every passage enters a turn as a nonce-marked data block. Passages from external content carry that mark and are never read as an instruction. A document written to rank first is the new risk of search by meaning: its passages are still data, and the lane's guard cases (AC9) measure this, because code cannot enforce how a model reads (principle 11).
- **Adopt before building (principle 14):** for example the full-text search and a vector extension of SQLite, and an open embedding model, behind a provider class.
- **The person looks it up** in the conversation and through `ask`. Covering agents' work and memories in `ask` is part of the amendment, in AC6.

### 4.8 Proof of the conversation lane

The lane is not a skill, so it has no band from skill evidence. Like the interpreter (its own evidence kind and bands per model, `evals/interpreter_status.py`), it needs a **`new`** evidence kind with cases and bands per route. The cases run the pinned template with fictional data blocks, injected blocks among them. They measure:
- answering in role from the working memory;
- citing what code retrieved;
- describing attachments without misstating them;
- refusing what an agent channel or a line may not do;
- refusing an instruction inside a data block, including a passage written to rank first;
- turning work into a task instead of claiming it was done;
- the quality of the routes it writes (section 4.2).

Guard cases always run. `auto` picks the lane's route only among routes with a reliable lane band, and the lane is enabled on no channel before one has it.

The downgrades of questions and the matching of delegations run on the same pinned route, so their guard cases are cases of this same evidence kind, which AC11 adds (section 4.10). The review is measured as skills (section 4.11).

### 4.9 The office

R23 is decided (2026-11-28, `docs/decisions/2026-11-28-w0-decisions-backlog-wave-0.md`): the office is our own, built in `interface/` as static files from parts of permissive open projects, with their notices kept. It is not a fork of Habblaud, whose repository is kept as a reference only. The art is chosen later with the maintainer. It is fed by openhora:
- one room per area;
- characters with their appearance from the profile;
- the message box wired to the lane;
- the events of section 4.5 as bubbles, showing the kind of step only (L50).

The page polls `/versions` each second and reads the events when the number moved; there is no server-sent stream unless AC4 changes the rule by its own decision. The language is the project's language setting.

The office is part of the same page and origin, so its approvals are the page's: it shows the item and links to the existing card, and holds no approval path of its own. The service checks the hash.

### 4.10 Questions between agents, by level (AC-D9)

A task that stops keeps stopping as today: no skill changes. What changes is where the runtime sends what it stopped for. It reuses what exists: the endings of runs, the owner table, the knowledge base, the accepted configuration, the consent form and the records of L13.

**What code can tell, and what it cannot.**
- Under the writing standard, a skill stops for a decision that is the user's, or for a missing input.
- A run's ending is classified on the whole reply, and a question is one pending decision holding the whole reply (section 2).
- So most questions are decisions by construction.
- Scaling therefore comes from three things, not from free answers by colleagues:
  - work another agent owns, routed by code;
  - the person's delegations;
  - downgrades a model proposes behind a measured guard.

| Level | Kind | Who answers | How the level is set |
|---|---|---|---|
| N1 | Work another agent owns | A request to the agent that owns the missing artifact | Code: a `blocked` ending names the missing input and the skill that writes it; the owning agent comes from section 4.12 |
| N3 | A decision | The person, unless a delegation covers it | Code, by default, for every `question` and `draft_with_questions` ending; a whole reply takes its highest level |
| N0 | A fact with a source | A colleague or the knowledge base, citing the artifact or source | A model proposes the downgrade from N3, behind a measured guard (AC11). Code accepts the answer only when its citation checks and the asking agent may read what is cited; otherwise the question returns to N3 |
| N2 | A specialist's advice | A colleague of that area | A model proposes the downgrade from N3, behind a measured guard (AC11); recorded as advice, never as a decision |
| N4 | An external effect, money, credentials | The person, or a standing policy | Code for a `gate` ending, from the effect kinds (L15). A free-text question about money or credentials is kept at N3 or above by a measured guard (principle 11) |

- **Delegations.** **`new`** The person may delegate a kind of decision to an agent, for example "the designer decides fonts and colours within the brand guide".
  - **Where they live:** in `docs/workbench/runtime.json`, widened only through `accept-config --widen`, like every other bound. The default is none.
  - **What code checks and what is measured:** code checks that the delegation exists and is in force. Whether the question falls under its kind of decision is matched by a model (OPEN-12). That match is a measured guard, and a doubtful match goes to the person.
  - **The record:** a decision under a delegation is recorded as "decided by X under delegation Y".
  - **No delegation covers N4.**
- **How an answer from a colleague is resolved.** The colleague sends a message, which the agent channel allows. Code, never the agent, then resolves the pending decision:
  - with a **`new`** resolution word, `answered-by-agent`;
  - with `resolved_by` naming the agent, and the delegation when there is one;
  - after the checks above.

  At `runtime/ops_task_run.py:154` the rerun keeps only `answered` for the person's answers; `answered-by-agent` feeds a block of its own. The person's resolution `answered`, whose prompt text says "Each answer is the user's decision" (`runtime/ops_runs.py:133`–`138`), is never used for an agent.
- **The colleagues' block.** It carries each answer with who answered, at which level and with which citation. It tells the skill that the answer is not the user's decision. Its passages are selected by code and recorded as `task_sources` (section 4.7).
- **No loop.** A question routed below N3 that the next rerun asks again goes to the person, by code.
- **Measured.** A rerun with that block is a condition the skills' bands do not cover. AC11 adds:
  - cases of such reruns on a set of skills;
  - the cases of the downgrade guard;
  - the cases of the delegation match.

  Until a skill's cases pass on a model, its reruns with colleagues' answers are reviewed, by the person or by the review of section 4.11.
- **The model route.** The downgrade and the delegation match read run replies, which are not a person's line. They run only in chains whose starter holds `agent-chains` (AC-D16, section 4.13). In every other chain, and until the guards have a reliable band, the levels are the ones code sets alone: N1, N3 and N4. In a chain whose starter does not hold the group, an N1 request becomes a proposed request the person approves.
- **The person is informed, not flooded.**
  - Only N3 without a delegation, and N4, wait for the person.
  - Answers at N0, N1 and N2, and decisions under a delegation, go to the inbox under a daily cap. Beyond the cap they go to the periodic summary.
  - Any of them can be reversed.
- **Kept for audit.** Every question, answer, level, downgrade and delegation is recorded under L13.

### 4.11 Work from start to end without the person (AC-D11)

The person chooses the mode per agent. The default mode stays milestones (`runtime/autonomy.py:79`). The autonomous work mode applies to both autonomous modes, autonomous and autonomous-with-policy.

- **Three layers.**
  1. **Reviews of internal work** (code, documents, designs).
     - **Runs released by proof:** they keep today's behaviour. The person may opt in to peer review for them too.
     - **Runs that would need the person's review:** the peer review below does it, under the work mode's consent (section 4.2). Such a run is recorded as autonomy by consent, reviewed by peers, never as proven (principle 9).
  2. **Plan approval.** Released by the same consent for an agent fixed to a model, and by proof for an `auto` agent (section 4.2), and only in a chain whose starter holds `agent-chains` (section 4.13).
  3. **External effects.** The exact content approved by the person, or a standing policy accepted once in the terminal (L15, principle 11). No consent removes this. Example: a policy "deploy to staging at any time" lets a site be built and deployed to staging without the person; production needs the person's yes, or a policy of its own.
- **An agent never approves its own work.**
- **The review.**
  1. Checks by code first: the project's tests, the validator, the checks the skill names. **`new`** A step kind of the step engine (`runtime/steps.py`) runs them before the review, with no network. A check that needs the network is a networked project script and waits for the person (L36). Their results enter the reviewer's context.
  2. A **temporary reviewer** runs the review skill chosen for that kind of work (below). It reads the work against the author skill's `## Quality criteria`, criterion by criterion, citing evidence for each, and adds its own specialty's checks. Every one of the 52 skills has that section. Code refuses a verdict that does not address every criterion.
  3. If the reviewer rejects, the author answers. The discussion is bounded by a number of rounds fixed in AC12's spec (OPEN-13).
  4. Without consensus, a **temporary tiebreaker** decides on quality.
  5. A disagreement about a decision (N3) goes to the person, not to the tiebreaker, unless a delegation covers it.
- **The review skills (AC-D15).** One review skill cannot review code, designs and documents equally well, so code chooses the skill by the kind of work. The kind comes from the run's returned change set, because code is not declared in a skill's `outputs` (AGENTS.md), by a path classification AC12's spec fixes, for example:
  - a changed path under `docs/` is a document;
  - every other changed path is code;
  - a run with no change set is classified by the declared outputs it wrote;
  - work of several kinds goes to each matching reviewer, and all of them must approve;
  - design work goes to the fallback until `design-review` exists.

  | Work | Review skill | Why its own |
  |---|---|---|
  | Code | `eng-code-review`, which exists: six perspectives, the project's checks, a verdict (approve, approve with changes, request changes) | It runs tests and reads the diff; it needs `integration:vcs` |
  | Plans, proposals, documents | `core-critique`, which exists: failure modes with trigger, impact and mitigation, a verdict (approved, approved with changes, needs revision) | Its adversarial method fits text that will be acted on |
  | Designs | `design-review` (planned), built when a real design task needs it (AGENTS.md: never from generic knowledge) | It must see the rendered result at several widths, captured by code; no backlog item builds that capture yet, and the spec of `design-review` names it |
  | Anything else | **`new`** `core-work-review`, the fallback: the author skill's quality criteria, criterion by criterion | The criteria carry the area's knowledge; the procedure is general |

  - A specialist skill is split off because it has requirements of its own (design rule 4). Each review skill needs its own lab tests (principle 12), so a specialist is built where the volume of that kind of work justifies it, and the fallback covers the rest.
  - Code maps each skill's verdict words to approve or reject. When a skill's output does not address the author's criteria one by one, AC12 makes the smallest change that does: a Y change of that skill, with its tests.
  - Each review skill's lab band per model is the reviewer band for that kind of work, so the review needs no new evidence kind.
  - A skill's band holds only for the task text it was measured on (`contracts/runtime.md`, "The contained run"). Each review skill therefore gets cases in the shape of the context code assembles, held by a byte-for-byte test of that prompt.
  - `core-work-review` is a new skill. Its cases are work with planted defects. It follows "Adding a skill": it is done when its first full test, or a closed pool, passes on the two lab models. Its name avoids `agents/reviewer.md`, which has another role.
  - `eng-security-review` has no place here: it triages and dismisses dependency alerts, and the security perspective is one of `eng-code-review`'s six.
- **Temporary reviewers.** Each review is a contained run, started for one review and ended after it (principles 12 and 14). Today's contained run does not fit a review, so AC12 adds a **`new`** review mode of it:
  - **Scope check:** a closed list of review skills, checked in code, in place of the check that the skill is in an enabled agent's pack.
  - **The copy:** the task's tracked files plus the diff as a patch file. Today's copy holds only the artifacts the skill declares, and a task copy has no `.git` (`runtime/workcopy.py`), so `eng-code-review` gets a Y change to review from a patch with no git history and to read the checks already run from the context.
  - **The model:** the review choice, computed by code from the ranking or read from the person's reviewer-model key. It is never what a caller asks. Restriction R3 of the contained run is amended to name the review choice, by a dated entry in AC0, and its test asserts on both modes that no caller argument sets the model.
  - **Commands:** the reviewer may run commands in the container, with no network and no credential (R2, R3).
  - **What comes back:** nothing but the reply (R4). The verdict is read from the reply alone, and the review file a skill such as `eng-code-review` writes is discarded with the copy.
  - A temporary reviewer has no memory and no inbox.
  - It takes no permanent agent's time, has no history with the author, and also covers an area with a single agent.
  - A permanent colleague may review when the person prefers.
- **Context for a good review.** Code assembles it, each block nonce-marked, capped and passed through the credential scan:
  - the request and the route the task came from;
  - the task's pending decisions and how each was resolved, because some quality criteria are about the process ("agreed by the user");
  - the skill's quality criteria;
  - the artifact and its diff;
  - the inputs the run read;
  - the results of the checks by code;
  - the area's standards artifacts and the recorded decisions that apply. They are found through the knowledge base, filtered by the author's access set, and recorded as `task_sources` (section 4.7);
  - the author's notes on the task.

  Not the author's memory or thread.
- **Mitigations of the temporary reviewer's weak points.**
  - No context of the house: the context above, chosen by code.
  - No learning between reviews: what a reviewer found is written into the author's long-term memory. A finding that repeats becomes a proposed change to the area's standards artifact, made by that artifact's owning agent (section 4.12) and reviewed like any other work.
  - The author knows more and may talk the reviewer into agreeing: the rounds are bounded, and the tiebreaker exists.
  - No name: it appears as "Independent review", which is honest.
- **Which models.**
  - **Ranking.** Models are ranked as reviewers on the review skill chosen for the work, by their pessimistic score on it when that pool is closed; otherwise by band first. Ties are broken by price. A model can be a strong reviewer of code and a weak one of designs.
  - **"At least as capable as the author".** The reviewer model's score on that review skill is at least the author model's own score on it.
    - This is a proxy on a common scale. It does not measure how well the author model writes the work itself.
    - An author model with no evidence on that review skill counts as the lowest score, and the reviewer must then be `reliable` on it.
  - **The tiebreaker** is the best-ranked model, different from both.
  - **When the author already uses the best-ranked model:** the reviewer is another model of an equivalent band. When there is none, the review goes back to the person.
  - **The person's choice.** The person may fix the reviewer's and the tiebreaker's models per agent or per area, instead of the platform choosing. The reviewer-model key lives in the accepted configuration and is widened only with `accept-config --widen`. A model the person names runs whatever its band says, and the record says it was the person's choice.
- **Costs, stated before the consent.**
  - **What a review adds:** a reviewer run; for each round of discussion, a turn of the author and of the reviewer; for a tiebreak, one more run, often on a more expensive model.
  - **The warning:** its text is fixed and hashed. It says that the costs are estimates and that the agent's daily caps are the real bound on spend.
  - **The estimate:** code computes it from the price table (`runtime/prices.json`) and the agent's recent runs, and shows it beside the warning, outside the hash. The consent record keeps the figure shown, the price table's date and the reviewer models it assumed (principle 10).
  - **Who pays:** every review counts on the author's caps and on the chain's budget.
- **The person is informed, not blocked.** Every disagreement and every tiebreak reaches the person, under the cap of section 4.10. A periodic summary lists what was approved between agents. The person may reverse any approval.
- **Kept for audit.** Each review, round, verdict and tiebreak is recorded under L13, with the models, the context hashes and the findings.

### 4.12 Scaling without managers (AC-D14)

| Problem | Answer without a manager |
|---|---|
| Two agents of one area do the same work, or decide differently | **`new`** An owning agent per artifact, recorded in the store: the agent whose run first delivers it, reassignable only by the person. It is the reference on that artifact, and N1 routing uses it. The owner table still maps each artifact to its skill. Assignment by code stops duplicated work (section 4.2). |
| Priorities between areas | **`new`** A priorities file the person writes, `docs/workbench/priorities.md`, holding only the order. It is a row of "Slots no built skill writes", under L40's path rule. Code orders the queue by it. Budgets stay in `runtime.json` (`max_usd_per_day`), widened only through `accept-config`. |
| A request that needs five agents has no owner | **`new`** One responsible agent per request: the agent that received it answers for it from start to end. It is a role per request, not a rank. |
| Nobody checks quality | The review of section 4.11, and the lab's bands. |
| The person approving everything | Delegations (section 4.10), standing policies, and the autonomous work mode (section 4.11). |

### 4.13 Who gets autonomous chains (AC-D16)

**The risk.** What an agent may read does not depend on who asked: each agent keeps its access set (`sources`, section 4.7) for every request. What depends on who started a chain is how much the chain does by itself:
- whether a model reads the run replies;
- whether questions are downgraded and sent to colleagues;
- whether agents talk to each other.

A request from someone other than the person, or a forwarded text with a hidden instruction, could use those automatic steps to gather information inside the agents' access sets and return it in a reply. External effects stay blocked by L15, but the automatic chain is the path such a request would use.

**The mechanism already exists.** The channel policy (`runtime/operations.py`, `GROUPS`) gives groups per channel and, on messaging, per sender profile (L46). Messaging is closed by default (`DEFAULT_POLICY`). A group is widened only with `accept-config --widen`, in the terminal, with the hash of the widening list, and the terminal is never narrowed (`NEVER_NARROWED`). Some groups only add a capability to an operation another group grants (`KIND_ONLY`: `ask-mail`, `interpret`, `send-files`, `confirm-reads-off`, `interpret-fallback`). A group is held only by being listed: `holds()` answers False for a channel with no entry of its own (`runtime/operations.py:1650`).

**The group.** **`new`** `agent-chains`, a capability group of that kind. It attaches to the operations that start a chain (`say`, `request`, `route`) with a kind of its own, `chain-autonomy`. A chain gets the autonomous parts only when its starter holds it:
- plan release, by consent or by proof (section 4.2);
- the run replies read by the lane's model route;
- the measured downgrades and the delegation match (section 4.10);
- the turns between agents (section 4.3).

**The starter.** Starters are a closed list: terminal, page, `messaging:<sender>`, routine.
- **When it is recorded:** at the creation of the request, as the actor label `ops_actor.label` writes.
- **What inherits it:** every task, message and rerun of the chain.
- **What never changes it:** approving or answering.
- **Other paths:**
  - a line carried by `chat` is recorded as the channel that carried it;
  - a handler tick or anything else is not a starter of the list, and its chain never holds the group.

**One function.** `chain_autonomy(starter, cfg)`, with a closed truth table, answers whether a chain holds the group. It is asked again against the current accepted configuration at each autonomous step, so taking the group away works at once.

| Who started the chain | Default | Can the person change it? |
|---|---|---|
| The terminal | Holds it | No: the terminal is never narrowed |
| The page | Holds it when the page has no entry of its own in the configuration; with an entry, only if the entry lists the group. An entry written before the group existed does not list it, so that page loses the group: the safe direction | Yes: a cautious person writes a page entry without it |
| The MCP mode | Never, in v1: a model client must not start autonomous chains | No |
| The person's own messaging profile | Does not hold it: the runtime does not know which sender is the person until the person says so | Yes: one `accept-config --widen` for that profile; the guided setup (SETUP-GUIDE, #976) offers it |
| Another messaging sender, for example a team member | Does not hold it | Yes: the exception, widened for that sender's profile |
| A routine | Holds it only when it was approved on a channel that holds it; the holding enters the routine's content hash (AC-D17) | Yes: through the channel that approves it |
| A handler tick, or anything else (a chain started by external content) | Never | No: it is not a starter of the list |

A chain whose starter does not hold the group still runs, with the person in between:
- its plans wait for the person's approval, whatever the agent's consent;
- its questions go to the person, and an N1 request to the owning agent becomes a proposed request the person approves;
- agents exchange only requests and deliveries, and no turn between agents runs;
- the lane's task-state tool returns no run-reply text for it, and on a page that does not hold the group.

**What the group never changes**, because these are hard limits, not configuration:
- L15 for external effects;
- the access sets;
- the agent channel's ceiling;
- the marking of external content;
- the credential scan;
- the reliable band a guard needs before it runs.

**Two decisions, two levels.**
- The dated decision under L63 is the maintainer's, for the workbench. It allows the mechanism: the content of chains whose starter holds `agent-chains` may reach the lane's route.
- Who holds the group is each person's decision, in their own project's accepted configuration.

## 5. Hard limits

| Limit | Status |
|---|---|
| An external effect is executed by code with the exact content approved or inside a standing policy (L15) | Unchanged; no consent, delegation or peer review removes it |
| Approvals, tasks, runs and pending decisions only grow (L13) | Unchanged; messages between agents, questions and answers between agents, delegated decisions and reviews join it; the person's threads and memories are outside it, with tombstones on erasure |
| No credential inside a run | Unchanged; the lane's provider gets its key the way the interpreter's does; every outgoing lane block and every agent-written text entering a run passes the credential scan in code |
| Page and terminal lines reach a model route only by a dated decision (L63) | Decided for the lane (AC-D12); run replies and messages between agents reach it only in chains whose starter holds `agent-chains` (AC-D16); messaging lines in the lane wait for their own decision |
| A chain gets the autonomous parts (plan release, run replies on the lane's route, downgrades, turns between agents) only when its starter holds `agent-chains`, checked by `chain_autonomy` at each step; otherwise its plans wait for the person whatever the consent | `new`, in code (L46's mechanism) |
| Starters are a closed list (terminal, page, a messaging sender, a routine), recorded at the request's creation and never changed; the MCP mode and handler ticks never hold the group; the group is widened only with `accept-config --widen` in the terminal | `new`, in code |
| The inputs of an answer are chosen by code (L49), and sources reach a run only through its plan or an answer (L26) | Amended (AC-D10): code may rank by a pinned embedding model, never by a generative model's choice; L26 also admits the colleagues' block and the reviewer's context, selected by code and recorded as `task_sources`; the lane gets its own limit of inputs, with two agent-chosen tools inside the access set |
| A memory derived from a mail or calendar snapshot surfaces only with `@<id>` from the terminal or the page (L49) | Unchanged rule, applied to memories |
| The person's standing instructions are written only by the person (L40) | Unchanged; profiles and the priorities file get the same path rule; delegations and budgets are bounds of the accepted configuration |
| A consent is valid only while its warning's hash equals the current warning's | `new` for the autonomous work mode's consent kind, in code |
| An `auto` agent's plans are released only by proof | `new`, in code |
| The agent channel has a literal allow-list ceiling: a read, a notice, a question, a request, a delivery, a route proposal | `new`, in code; a test walks the table |
| An agent never approves its own work; a reviewer's verdict is the output of a contained run of a review skill, read by code from the reply alone | `new`, in code |
| A review run's model comes from the review choice (the ranking, or the person's reviewer-model key widened like any bound), never from what a caller asks (R3, amended) | `new`, in code; R3's test asserts it on both modes of the contained run |
| A colleague's answer is resolved by code as `answered-by-agent`, never as `answered`, and never enters the person's answers in a rerun | `new`, in code |
| A question routed below N3 and asked again goes to the person | `new`, in code |
| An answer citing a source or an artifact version the asking agent may not read is refused; a message is filtered by the sender's access set | `new`, in code |
| A `gate` ending is N4 and reaches the person or a standing policy; no delegation covers N4 | `new`, in code |
| A free-text question about money or credentials stays at N3 or above; a downgrade below N3 and a delegation match are right | `new`, measured guards (principle 11: where code cannot enforce, the measured guards are the protection, and this document says so) |
| A line addressed to an agent passes the same dispatch and refusals as a line to the planning agent (L54) | `new`, L54 extended |
| The lane has no tool with an external effect and no write outside the store's records; its tool list is a literal a test compares | `new`, in code |
| A task has at most one owner at a time, assigned by code | `new`, in the store |
| A request an agent wrote is never "the request in the person's words" | `new`, in code |
| A chain between agents starts from a starter of the closed list, within a hop limit and a budget | `new`, in code |
| The sources' index is disjoint from the data folder, the store and the checkout, and follows no link (L22, L23 restated) | `new`, in code, in AC6 |
| A memory, passage or message from external content is marked and never read as an instruction | `new`; the mark is in code; the reading is a measured guard |

## 6. Packages

Each package is a backlog item, sized S, M or L. A package's spec is written before it starts.

| Id | Package | Size | Needs |
|---|---|---|---|
| AC0 | The dated entries in `contracts/runtime.md`: the L63 decision for page and terminal (AC-D12); the amendment of L49 and L26, with the colleagues' block and the reviewer's context (AC-D10); the autonomous work mode's consent kind (AC-D11); the amended R3 of the contained run, naming the review choice (AC-D11); the decision that the content of chains whose starter holds `agent-chains` may reach the lane's route, with what leaves the host kind by kind (AC-D16) | S | - |
| AC1 | Agent profiles: the slot row, the path rule, the checks, its read into the lane as a data block, proposals by an agent accepted by the person | M | - |
| AC2 | A conversation per agent: the store, the operations, the service routes, a message box on each agent, placed where R23 (#884) puts the agent and moved by AC10 or the rebuilt `interface/`; the migration of the existing `project` conversation into the planning agent's thread; on messaging and MCP, how a sender addresses an agent, under the L46 profiles; absorbs AGENT-DIRECT (#977) | M | AC1 |
| AC3 | The conversation lane: the dispatch before it, the provider's streaming and bounded tool loop, the pinned template, an enable entry with several routes and the page's switch, the inputs, the tools to read an artifact, a task's state and the agent's board, the credential scan of outgoing blocks, the persona's message with attachments, the bounds and costs, work proposed as a route; latency measured | L | AC0, AC2 |
| AC4 | Events: the core schema, a parser in each eval adapter outside the fingerprint, the reader rule, streaming to the page | M | AC3 |
| AC5 | Memory: the four layers in the store, memories with their access sets, the summary of old threads, erasure with tombstones and the offered cascade, the store's full-text search for memories and their retrieval into the lane, editing on the page and in the terminal | L | AC3, AC7 |
| AC6 | The knowledge base: passages, hybrid search with local embeddings, the index beside the sources folder with the L22 and L23 limits, the access sets of artifact versions, the lane's search tool, agents' writes with provenance, `ask` over it; first real case named in its spec | L | AC0, AC5, AC7 |
| AC7 | Messages between agents: the table under L13, the four kinds, the `sources` key and the access sets that messages, memories and answers use, the access set per message, the agent channel's ceiling, the capability group `agent-chains` with its defaults, the closed list of starters recorded on each chain and `chain_autonomy`, the provenance field of agent-written requests, the credential scan, the brakes, the visibility | L | AC1, AC2 |
| AC8 | Self-managing agents: the `area` key, open tasks and assignment by code, the change of `agent_of` and all its callers, the owning agent per artifact, an agent's own plan as a route (`core-orchestrator` limited to one pack, Y change with cases), the reception (`core-orchestrator`, Y change, tested), one responsible agent per request, the priorities file | L | AC7 |
| AC9 | Proof of the lane: its evidence kind, cases and bands per route, including attachments, injected passages and routes | L | AC3 (starts with it) |
| AC10 | The office: our own, in `interface/` as static files, with no fork, the fork repository kept as a reference only (R23 decided, `docs/decisions/2026-11-28-w0-decisions-backlog-wave-0.md`); built in slices behind a painter interface, the art chosen later with the maintainer, fed by AC4 | L | spike: none; wiring: AC4 |
| AC11 | Questions between agents by level: N1, N3 and N4 by code; `answered-by-agent` and the colleagues' block; the no-loop rule; delegations in the accepted configuration; the inbox cap; the cases of reruns with colleagues' answers. For chains whose starter holds `agent-chains`: the measured downgrades to N0 and N2 and the delegation match, with their cases | L | AC6, AC7, AC8; the downgrades and the match: AC3, AC9 (their cases are cases of the lane's evidence kind) |
| AC12 | Peer review and the autonomous work mode: the choice of the review skill by the kind of work; `eng-code-review` and `core-critique` as reviewers, with the smallest change each needs to address the author's criteria (Y changes, tested); the new skill `core-work-review` with its cases and first full test; `design-review` left planned until a real design task; the review mode of the contained run (a closed list of review skills checked in code in place of the pack check, the task's tracked files and the diff as a patch file, the model from the review choice); `eng-code-review` changed to review from a patch with no git history and to read the checks already run from the context (Y change, tested); cases of each review skill in the assembled-prompt shape, held by a byte-for-byte test; the step kind that runs the project's checks before the review; temporary reviewer and tiebreaker runs, the context assembled by code, bounded discussion, the ranking of models and the person's choice, the consent kind with its stored warning hash, the cost estimate recorded with the consent, plan release, the opt-in for proven runs, the inbox summary | L | AC0, AC8, AC11 |

**Order:**
1. AC0 and AC1.
2. AC2.
3. AC3, with AC9 beside it.
4. AC4 and AC7.
5. AC5 and AC8.
6. AC6.
7. AC11.
8. AC12.

The AC10 first slice and CARD-READ (#987) run whenever there is room; neither needs another package.

**Existing items:**
- AGENT-DIRECT (#977) is AC2 and AC3, and was closed into them on 2026-11-27. What the planner sees of a direct task is answered by assignment by code (AC8) and by the reception.
- R23 (#884) keeps the decision and the scene's model; AC10 is its build, and the runtime side of several agents per area is AC8.
- AQ4 (#915) and EMB (#914) were closed into AC6 on 2026-11-27: the size limit of `ask` is the case AC6 must beat, and EMB's provider design goes into AC6's spec.
- T42 (#874) records three rows as staying code: the autonomous work mode's consent kind, widening `agent-chains`, and the agent channel's ceiling.
- R16 (#882) counts the review mode of AC12 as a path to the review skills; R17 (#883) is cited by AC8's spec.
- CARD-READ (#987) is the phone form of the cards the lane attaches (AC-D8).
- VOICE-MODE (#978) builds on AC3.
- SETUP-GUIDE (#976) adds profiles, delegations, the autonomous work mode and giving `agent-chains` to the person's own messaging profile to the guided setup.

**Documents each package changes:**

| Document | What changes | Package |
|---|---|---|
| `AGENTS.md`, principle 9 | The autonomous work mode's consent kind, plan release (by consent for a fixed model, by proof for `auto`), and peer review as the release of a run that would need the person's review | AC0 (the text), AC12 (built) |
| `AGENTS.md`, principle 5 | A decision taken under a delegation the person wrote is the person's decision, delegated, and recorded as such | AC11 |
| `AGENTS.md`, the reliability model and the validator's evidence checks | The lane's evidence kind beside lab, field and interpreter | AC9 |
| `contracts/runtime.md` | The new limits, the amendments, the operations, the resolution word `answered-by-agent`, the consent kind, the group `agent-chains`, and that memories and the person's threads are outside L13 | each package for its part; AC0 for the decisions |
| `contracts/project-layout.md` | The slot rows of the profile file and the priorities file, provided by `user` | AC1, AC8 |
| `docs/architecture/platform/` | The pages of the conversation, the agents and the review | each package for its part |
| This plan | Its status section | each package |

## 7. Open questions

Decided by the maintainer on 2026-11-27 (section 11) and 2026-11-28 (`docs/decisions/2026-11-28-w0-decisions-backlog-wave-0.md`):
- **OPEN-1. Embeddings.** Decided: in v1, local by default, behind a provider class (AC-D10).
- **OPEN-6. How long threads and memories are kept.** Decided: until the person erases them, with tombstones and an export; records between agents are kept like the other governance records (AC-D13).
- **OPEN-7. The consent of plan release.** Decided: part of the autonomous work mode's consent (AC-D11); section 4.2 makes it a consent kind of its own, and `auto` agents get plan release by proof only.
- **OPEN-10. The dated L63 decision for the lane.** Decided: page and terminal lines; messaging later (AC-D12).
- **OPEN-15. Whether a routine holds `agent-chains`.** Decided: only when it was approved on a channel that holds it, with the holding in the routine's content hash (AC-D17).
- **OPEN-14. Run replies and messages between agents on the lane's route.** Decided (section 13): by who started the chain, through the ca
- **OPEN-2. Who writes the profile.** Decided: the person only; an agent proposes, the person accepts (AC-D18, `docs/decisions/2026-11-28-w0-decisions-backlog-wave-0.md`).
- **OPEN-3. Who pays a chain of requests.** Decided: each task counts on its owner's caps, and the chain carries a budget set where it started; it stops at either (AC-D19).
- **OPEN-4. What the planning agent becomes.** Decided: the reception, with no manager role (AC-D20).
- **OPEN-5. Targets of speed.** Decided: set from AC3's first measurements, per model (AC-D21).
- **OPEN-8. Where the sources' index lives.** Decided: beside the sources folder, outside git, under the limits restated in section 4.7 (AC-D22).
- **OPEN-9. Memory written by an agent.** Decided: allowed without approval inside a task or a turn, visible and erasable, marked when it came from external content, and kept out of turns that carry an effect proposal (AC-D23).
- **OPEN-11. Reading memories from MCP or messaging.** Decided: not in v1 (AC-D24).
- **OPEN-12. How a delegation names a kind of decision.** Decided: the person's own words, matched by a model behind a measured guard, with a doubtful match sent to the person (AC-D25).
- **OPEN-13. The number of review rounds and the reviewer's budget.** Decided: two rounds before the tiebreak, the budget fixed in AC12's spec from the first measurements (AC-D26).ounds before the tiebreak, fixed in AC12's spec from the first measurements.

## 8. Not in this plan

- Choosing the office: R23 decided it, an own office in `interface/` with no fork (`docs/decisions/2026-11-28-w0-decisions-backlog-wave-0.md`). The art is chosen later with the maintainer.
- Voice (VOICE-MODE, #978), built on the lane later.
- Agents of another project talking to this one.
- Messaging lines reaching the lane as a conversation (a later decision under L63). A chain started from messaging by a sender who holds `agent-chains` does send its run replies, which may quote the line, to the lane's route (AC-D16).
- Restricting who may read an artifact as a project file. Today any run may read the project's artifacts as inputs; the plan keeps that rule and filters only what it creates (section 4.7). Changing it is its own decision.
- The v2 item of section 4.3, which needs its own decision.

## 9. Not verified

- Which open full-text index, vector extension and local embedding model fit passages, and how fast they are on a real project's sources and on the maintainer's machine. AC6 starts with that comparison.
- How fast the lane can be. Nothing has been measured (section 2).
- Whether the service can stream events with its current design: today it answers requests and the page polls. AC4 starts by checking it.
- Whether the adapters' `stream.jsonl` is written while a run is going, and carries enough to name each step. AC4 checks one adapter first.
- How much a review costs compared with the run it reviews. AC12 measures it before the warning's estimate is shown.
- How often a stopped task's question is a fact or advice rather than a decision, and so how much the measured downgrades can save. AC11 measures it.
- Whether the outputs of `eng-code-review` and `core-critique` can address an author skill's criteria one by one without a change. AC12 checks each before it uses it as a reviewer.
- Whether a chain's starter can be recorded on every path that starts work today (a line, an approved task, a routine, a messaging act). AC7 checks each path.
- Which effect kinds store only a body, with no card lines, and so reach a phone in English (CARD-READ, #987).
- The Habblaud facts behind section 4.9 come from the reading recorded in issue #884, through the GitHub API, on 2026-11-27.

## 10. Review of version 1 (2026-11-27)

An independent reviewer on another model read version 1 against the code. It raised 19 findings, and the first round left seven open (F1, F2, F4, F7, F8, F11, F12). The second round settled them and raised five new problems (N1 to N5). Every point below was checked in the code before it was accepted. Versions 3 and 4 changed some of the answers; the last column says where each stands now.

| Finding | Where it is resolved |
|---|---|
| F1. The lane goes against L63; the provider has no streaming or tools; a prompt that changes per project cannot be pinned | 4.4 (L63 decided for the person's lines, AC-D16 for the rest, provider, pinning, principle 13), AC-D12, AC0, AC3 |
| F2. An agent answering a stop-and-ask breaks principle 5 | 4.10 (decisions stay with the person or a delegation the person wrote; `answered-by-agent` resolved by code; measured reruns) |
| F3. Memory written by an agent would steer unattended runs | 4.1, 4.4 (profiles and memories in the lane only, nonce blocks and checks), 4.6 |
| F4. Releasing plan approval stretches principle 9 | 4.2 (a route turned into tasks by code; a consent kind of its own for a fixed model; proof only for `auto`; what it never releases), 4.11, AC-D11 |
| F5. Claims contradict `agent_of`; no `area` key | 4.2 (assignment by code), AC8 |
| F6. The refusal list was a deny list, and incomplete | 4.3 (an allow-list ceiling), section 5 |
| F7. Model-chosen retrieval against L49 and L26; leaks across agents | 4.7 (the amendment by AC-D10, extended; access sets on memories, artifact versions, messages and answers), AC0, AC6 |
| F8. Profiles and memories in runs are not the measured condition | 4.1, 4.4 (the lane only; code-checked results attached as rendered) |
| F9. The router change is not tested | 4.2, AC8 |
| F10. Where run events come from; harness parsing belongs in adapters; leaks | 4.5, AC4 |
| F11. Contradictions on L13 and deletion; the conversation has no delete trigger | 4.3, 4.6, section 5, OPEN-6 |
| F12. Who writes memory and profile files, and where | 4.1 (a slot row provided by `user`), 4.6 (memories in the store) |
| F13. Lane turns not under caps or costs | 4.4 (cost, bounds) |
| F14. Wrong dependencies; missing work (migration, messaging and MCP, `agent_of`, L63) | Section 6 |
| F15. R23 decided and not decided; a fork's approvals (R23 is decided, with no fork: the office's approvals are the page's) | 4.9, section 8 |
| F16. The D11 reversal not named; "three choices" inexact | Section 3 (AC-D3, AC-D6), the decision record |
| F17. Imprecise citations | Section 2, 4.2 |
| F18. Principle 8 for AC6's real case | Section 3 (AC-D6) |
| F19. #977's question; AC-D5 tentative | Section 3 (AC-D5 decided with the route), section 6 |
| N1. The lane would be a second router that skips L54 | 4.4 (the dispatch before the lane), section 5 |
| N2. Agent-written requests flooding the inbox | 4.3 (brakes), 4.10 (only N3 without a delegation and N4 wait for the person; the daily cap) |
| N3. Editing memories through other channels | 4.6, OPEN-11 |
| N4. AC9 grows | Section 6 (AC9 sized L) |
| N5. No persona voice outside the lane | 4.1, 4.4 (the persona writes the lane's message; artifacts keep no persona voice) |

## 11. The maintainer's answers to version 2 (2026-11-27)

The maintainer read version 2 and answered point by point. Each answer below is recorded in section 3 and in the decision record.

| Point of version 2 | The maintainer's answer | Where |
|---|---|---|
| The lane needs a dated L63 decision | Approved: page and terminal lines reach the lane | AC-D12, 4.4 |
| Code-checked results keep no persona voice | The persona writes the whole message; code-checked items are attached; approval cards stay, improved for phones and in the project's language | AC-D8, 4.4, CARD-READ (#987) |
| A skill run never asks a colleague in v1 | Rejected: "if everything goes through the owner, it does not scale"; questions by level, with delegations, reusing the existing governance, every conversation and action between agents kept for audit | AC-D9, 4.10 |
| An agent's own plan as a route checked by code | Approved | AC-D5, 4.2 |
| Embeddings in v2 | Rejected: search by meaning is a foundation of the platform; hybrid search in v1, local embeddings by default, and the lane's search tool | AC-D10, 4.7 |
| The agent channel allows a read, a notice, a message | Clarified: proposing a route, which splits a task, is allowed; approving is not, and an agent never approves its own work | 4.3, section 5 |
| Every approval passes the person | Rejected for internal work: agents may work from start to end without the person, with a second agent reviewing and a third breaking ties; reviewers are temporary, on measured models different from and at least as capable as the author's (an equivalent one when the author's is the strongest); the costs are stated; the person may choose the reviewer's and the tiebreaker's models | AC-D11, 4.11 |
| The memory rules | Approved | AC-D13, 4.6 |
| Specialist and manager in one agent, at scale | Agreed, with one responsible agent per request, authority from owning an artifact and priorities set by the person | AC-D14, 4.12 |

## 12. Review of version 3 (2026-11-27)

The same kind of reviewer read version 3 against the code. It raised 21 findings: 1 blocker, 11 major and 9 minor. Every piece of evidence was checked in the code. One round of discussion reached a consensus: the plan's author accepted 14 findings as proposed and the rest with changes the reviewer agreed to. The reviewer added two points of its own.

| Finding | Where it is resolved |
|---|---|
| 1. Blocker: a stored consent is `{"model", "mode"}` without the warning's hash, so a consent could widen without the person seeing it; `auto` needs no consent; a warning with costs is not a constant | 4.2 (a consent kind with its warning hash stored and checked; stale on a change of model or mode; `auto` by proof only), 4.11 (fixed warning, the estimate shown and recorded outside the hash), section 5 |
| 2. Delegations contradict the agent channel's ceiling; a colleague's answer would flow into "Each answer is the user's decision" | 4.3, 4.10 (`answered-by-agent` resolved by code, `resolved_by`, filtered at `ops_task_run.py:154`; the delegation match is a measured guard) |
| 3. A stopped run's questions are not structured enough to route by level | 4.10 (N1 and N3 by code from the endings; downgrades only behind a measured guard; N4 for free text a measured guard; the no-loop rule) |
| 4. Run replies, delegation matching and agent turns reach the lane's route without a decision | OPEN-14, 4.4, 4.10, AC0, AC11 |
| 5. Access sets cover notes and memories but not artifacts or messages | 4.3 (access set per message), 4.7 (artifact versions in the index, answers refused across sets), 4.6 (snapshot-derived memories), section 8 (reading artifacts by path stays today's rule) |
| 6. The L26 amendment does not cover the colleagues' block and the reviewer's context | 4.7, 4.10, 4.11, AC0 |
| 7. Owning an artifact does not settle two agents of one area | 4.12 (an owning agent per artifact in the store) |
| 8. Who acts as "the agent" outside the lane: claims, own routes, N1 requests | 4.2 (assignment by code, deterministic and recorded; routes by `core-orchestrator` limited to one pack, or by the lane) |
| 9. Priorities and delegations outside the accepted configuration | 4.10 (delegations in `runtime.json` through `accept-config --widen`), 4.12 (the priorities file holds the order only) |
| 10. The AGENTS.md amendments are missing | Section 6, "Documents each package changes" |
| 11. The reviewer as an agent body: `agents/reviewer.md` has another role; `contained-run` runs a skill | 4.11 (version 4: the skill `core-work-review`; version 5 made it the fallback beside specialist review skills, AC-D15; whose lab band is the reviewer band) |
| 12. Model choice compares different scales; "best" is undefined; proven runs | 4.11 (ranking by the scores on the chosen review skill, since version 5; ties by price; the proxy stated; proven runs keep today's behaviour, with an opt-in) |
| 13. "Supervised stays the default" is false; two autonomous modes | 4.11 |
| 14. The list of `agent_of` callers is incomplete; open tasks in routines | Section 2, 4.2 |
| 15. An enable entry pins one route; "has a band" is ambiguous; the switch | 4.4 |
| 16. Where memories live; what erasure reaches | 4.6, 4.7 |
| 17. No credential scan before text leaves | 4.3, 4.4, 4.11, section 5 |
| 18. The event parser and the measurement fingerprint | 4.5, section 9 |
| 19. "Read an artifact" is a second input the model chooses | 4.4 |
| 20. AC11 needs AC3 and AC9 | Section 6 |
| 21. The profile's row belongs in the slots table | 4.1, 4.12, section 6 |
| Added: the inbox under load | 4.10 (a daily cap, the overflow to the periodic summary) |
| Added: AC0 carries the consent kind's dated entry and principle 9's wording | Section 6 |

## 13. The maintainer's answers to version 4 (2026-11-27)

| Point of version 4 | The maintainer's answer | Where |
|---|---|---|
| One review skill, `core-work-review`, for every kind of work | Too general: code, a design and a document need different reviews. Approved: code chooses the review skill by the kind of work (`eng-code-review`, `core-critique`, a planned `design-review`), with `core-work-review` as the fallback | AC-D15, 4.11, AC12 |
| OPEN-14, recommended by the channel where a chain began | Asked for the pros and cons of deciding by the channel and of deciding by the declared governance limits alone; agreed that the risk lies in who started the chain, not in the channel; asked whether it fits the current governance as a default the person may change. Approved: the capability group `agent-chains`, in the terminal and on the page by default, given to a messaging sender's profile with `accept-config --widen` | AC-D16, 4.13, AC0, AC7 |

## 14. Final review of version 5 (2026-11-27)

A new reviewer of the same kind read version 5 against the code. It raised 12 findings: 9 major and 3 minor. Every piece of evidence was checked in the code. One round of discussion reached a consensus: the plan's author accepted 7 findings as proposed and 5 with changes the reviewer agreed to.

| Finding | Where it is resolved |
|---|---|
| 1. Plan release by consent was not limited by who started the chain, so any sender with `talk` could launch work that runs end to end | 4.2, 4.11, 4.13 (plan release is an autonomous part; otherwise the plan waits for the person whatever the consent), section 5 |
| 2. "Each review is a contained run" is false as built: the model, the pack check, the copy without the source or `.git`, the commands a run may use, bands bound to the measured task text | 4.11 (a review mode of the contained run; R3 amended in AC0; `eng-code-review` changed; cases in the assembled-prompt shape; the verdict from the reply alone), AC0, AC12 |
| 3. A capability group cannot produce the stated defaults: `holds()` is False for a channel with no entry; no operation named | 4.13 (attached to `say`, `request` and `route` with the kind `chain-autonomy`; `chain_autonomy` with a closed truth table; a page entry written before the group loses it) |
| 4. No row for MCP, `chat` or handler ticks | 4.13 (a closed list of starters; MCP never in v1; `chat` recorded as the carrying channel; handler ticks never) |
| 5. When the group is checked, and who the starter is, were undefined | 4.13 (the actor label at the request's creation, inherited, never changed by approving or answering; checked again at each autonomous step) |
| 6. The routine row was not in the decision record | OPEN-15, put to the maintainer and decided as AC-D17 |
| 7. Chains without the group contradicted 4.10 and the brakes | 4.10, 4.13 (N1 becomes a proposed request the person approves), 4.3 and section 5 (starters of the closed list) |
| 8. Package dependencies did not match the text | Section 6 (the `sources` key and the access sets in AC7; AC3's tools limited to reading; AC5 adds memory retrieval and needs AC3 and AC7; AC6 adds the search tool and needs AC7; AC11 needs AC8; a new order) |
| 9. The guards of the downgrades and the delegation match had no evidence kind | 4.8 (cases of the lane's evidence kind, added by AC11), section 6 |
| 10. The kind of work cannot come from declared outputs | 4.11 (the run's change set, a path classification, all reviewers approve mixed work, design to the fallback; `eng-security-review` has no place) |
| 11. Stale or inexact text | Header, section 1, 4.13 (the five capability groups), section 8, section 12 |
| 12. A page without the group could still send run replies through the lane's task-state tool | 4.4, 4.13 |
