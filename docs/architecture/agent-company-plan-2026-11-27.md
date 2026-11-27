# The agent company: a plan

Version 2, of 2026-11-27. On `origin/main` at `9bacdbf9`. A proposal, written before any of it is built. The maintainer's decisions it rests on are recorded in `docs/decisions/2026-11-27-ac-0-agent-company.md`. Nothing here is built, and no `new` element is written as if it exists.

Version 1 was reviewed the same day by an independent reviewer agent on another model. The reviewer read the code and the contracts, and the two rounds that followed reached a consensus on every finding; section 10 lists the findings and where each is resolved. The main changes from version 1:
- The conversation lane needs a dated decision under L63 (OPEN-10).
- A skill run never asks a colleague in this plan's first phase.
- Persona and memory enter the lane only, never a skill run.
- Retrieval in the lane is chosen by code, by keywords.
- An agent's own plan needs a new consent of its own.
- A refusal table for agents is an allow-list.
- Deletion and where memory lives are settled.

How to read it: a path with a line number was opened and read at `9bacdbf9` for this plan or its review. A claim with no line number came from a search, and the text says so. A fact that was not confirmed is in section 9, "Not verified". Open questions are `OPEN-<n>` in section 7, each with a recommended answer; none is decided by this document. **v1** and **v2** name the two phases of this plan: v1 is what the packages of section 6 build; v2 is listed so that v1 does not close the door to it, and each v2 item needs its own decision.

## 1. The target

The maintainer's words, 2026-11-27, translated:
- A company made of agents that act like people.
- They talk to each other, ask each other questions and do tasks for each other.
- The person talks to each one alone, as the owner of the company would, and gives tasks to one agent directly.
- They share information, and the person can look it up.
- Each agent answers as a specialist of its area, fast, as in a conversation with someone. It must not feel like a one-off chat with an AI: the agent knows who it is, what it does and everything about its current work.
- What the person and the agent said is kept, as the person's memory and the agent's.
- It must be simple and look like people working, while being AI agents.

On the same day the maintainer added the points recorded as AC-D1 to AC-D7 (section 3):
- no managers;
- a persona per agent;
- agents that talk with the person and with each other without weakening security or governance;
- a knowledge base with retrieval;
- fast replies with each step shown on screen;
- a robust memory per agent, in the project.

This is the end goal recorded on 2026-09-28 (`docs/decisions.md:73`: "a company run by agents, one per department, that take tasks, talk to each other through recorded messages and keep their data"). Section 3 says which earlier choices it reverses.

## 2. Where we are

| Point | Today | Where |
|---|---|---|
| Agents | Configuration entries `area_agents` in `docs/workbench/runtime.json`. Their keys are exactly pack, enabled, mode, max_runs_per_day, max_usd_per_day, max_parallel, model and consent. There is no `area` key and no `sources` key. The planning agent is the entry named `planning`. | `runtime/autonomy.py:83` (`AGENT_KEYS`), `:156` (`agents`); `runtime/plan.py:96` |
| What an agent knows of itself in a run | Nothing. The run's text is the request ("the request in the person's words"), the task, the standing instructions, the handed files, the sources and the earlier answers. It names no agent, role, area or colleague. | `runtime/ops_runs.py:104`, `:106` (`task_prompt`) |
| Persona, memory, retrieval | Out of scope by earlier decisions. "Area agents are configuration, not code: they own a pack and a cap, and carry no persona or memory." Agent memory was replaced on 2026-10-15 by the person's standing instructions. A persona per agent was listed out of scope, and "Indexing or RAG. It waits for a real case (D11)". | `docs/architecture/delegation-platform-architecture-2026-10-14.md:179`; `docs/architecture/delegation-platform-plan-2026-10-14.md:147`, `:973`, `:975`; `contracts/runtime.md` (L40) |
| Who does a task | Code picks the one enabled agent, other than planning, whose pack holds the skill. A skill in several packs is an error: "exactly one must own its task". | `runtime/plan.py:169`–`179` (`agent_of`) |
| Conversation | One per project, with the planning agent, as a stage placeholder: `CONVERSATION = "project"  # one conversation per project until the local interface (stage 9)`. The read route takes a conversation name, but nothing writes another. | `runtime/ops_say.py:75`; `runtime/service.py:346` |
| History given back to the model | The planning agent only: the newest 6 messages after the last settled request, each cut to 600 characters, at most 4,000 in all. | `runtime/ops_say.py:76`, `:137` (`chat_memory`) |
| Messages store | The table of migration 6, "the messages of the conversation with the planning agent". It has no trigger that refuses a delete. The store runs in WAL mode. | `providers/store/sqlite.py:296`–`305`, `:1153` |
| Where the person's decisions live | A person's answer to a question is kept in `pending_decisions`, which is never deleted. | `providers/store/sqlite.py:314` (trigger) |
| Agents talking to each other | Only through artifacts and the dependencies of a flow (principle 4). No message between agents and no inbox per agent: a search for "message bus", "ask_agent" and "agent inbox" in `runtime/`, `providers/`, `contracts/` and `docs/architecture/` found none. | `flows/*.json`; `AGENTS.md`, principle 4 |
| An answer rerun | A task that stopped to ask the person reruns with the earlier questions and answers. The prompt says: "Each answer is the user's decision". | `runtime/ops_runs.py:133`–`138` |
| Shared information | Sources with immutable versions and a catalog. `ask` answers from sources chosen by code, "never a model's choice", with citations checked by code. A run sees sources only through its plan's choice or an answer's selection. No index and no retrieval: a search of `runtime/sources.py` found "indexing or retrieval waits". | `runtime/sources.py:57`; `runtime/ops_ask.py`; `contracts/runtime.md` (L26, L49) |
| Speed of a reply | Every routed line starts one contained run of the router skill (`ops_requests._router_call`, through `lab.run_skill`). There is one router run per project at a time, and the page polls a job. No streaming and no measured latency: a search of the docs, decisions and tests for "latency" and "cold start" found none. | `runtime/ops_requests.py:82`; `runtime/lab.py:994` |
| Direct model calls | The interpreter of the messaging bridge calls a model through the `model:text` provider. It makes one request and gets one reply over standard input and output, with no streaming and no tool calls. A route runs only when its hash is accepted, under a dated enable entry that pins the prompt. Only messaging lines reach the model route; page and terminal lines reach it "only by a new dated maintainer decision". The gate is p95 under 4,000 ms. | `providers/model/chat-http.py`; `providers/CONTRACT.md`; `contracts/runtime.md` (L63); `evals/interpreter/thresholds.json:4` |
| Autonomy | The reviews of runs are released by proof (a reliable pair of skill, model and adapter) or by the person's consent per agent (D38: the hash of the exact warning shown). Modes map to checkpoints, not to plan approval. An external effect needs its exact content approved or a standing policy. The ceiling is 4 parallel runs per agent; the default is 1. | `AGENTS.md`, principles 9 and 11; `runtime/autonomy.py:102`, `:104`; `contracts/runtime.md` (L15, L19) |
| The screen | A 3D building with one floor per agent, and the Lobby with the planning agent's conversation. Floors have no message box. The page polls a change signal. R23 (#884) proposes rooms per area and possibly a fork of Habblaud. | `interface/js/views/floor.js`; `interface/js/watch.js`; issue #884 |

## 3. Decisions (the maintainer, 2026-11-27)

The record is `docs/decisions/2026-11-27-ac-0-agent-company.md`. In short:

- **AC-D1. A persona per agent.** It reverses "a persona per agent" being out of scope (`docs/architecture/delegation-platform-plan-2026-10-14.md:975`).
- **AC-D2. Memory per agent, robust and in the project.** It reverses the replacement of agent memory by the standing instructions alone (2026-10-15). The standing instructions stay.
- **AC-D3. A conversation per agent.** It ends the stage placeholder of one conversation per project (`runtime/ops_say.py:75`). That was not an earlier decision.
- **AC-D4. Agents talk to each other**, with questions and tasks, through messages the runtime carries and records, without weakening the hard limits. No skill invokes another, so principle 4 is unchanged.
- **AC-D5. No managers, as a direction.** Each agent plans and manages its own work within its skills and bounds. The design and its governance are in section 4.2.
- **AC-D6. A knowledge base with retrieval.** It reverses "Indexing or RAG. It waits for a real case (D11)" (`docs/architecture/delegation-platform-plan-2026-10-14.md:973`). AC6 names its first real case in its own spec. That case is a project of the maintainer: its data and results stay in that project, and only the lesson and its numbers come back (principle 8).
- **AC-D7. Fast replies, and the screen shows each step** the agent is taking.

The maintainer has **not** decided these, and the plan does not assume them:
- the dated L63 decision for the lane (OPEN-10);
- the consent that releases an agent's own plan (OPEN-7);
- the office (R23).

## 4. Design

### 4.1 The agent's profile (persona)

- **`new`** One file per agent: `docs/workbench/agents/<agent>.md`, where `<agent>` is the key of `area_agents`. Its owner row in `contracts/project-layout.md` is `user`.
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
  - Results and cards keep no persona voice (section 4.4). That is visible to the person, and it is the price of keeping the measured condition.
- The profile is project data (principle 8); the workbench holds only its template.

### 4.2 Agents that manage themselves, and governance without managers

- **Area membership.** **`new`** A key `area` per entry of `area_agents`. An area may hold several agents, and an agent's pack stays the list of its skills.
- **`agent_of` changes.** Today it refuses a skill held by several agents (`runtime/plan.py:169`–`179`). With several agents per area, a planned task of a skill they share is **open**: it has no owner until one claims it. AC8 names the callers that change:
  - the plan's `combine`;
  - the owners of `ask` (`ops_ask.run_owners`);
  - cost attribution (`ops_core.attributed`).
- **Claims.** **`new`** store logic: a task has at most one owner at a time. A claim and its check happen in one transaction of the store, and a second claim is refused. This is new code: the runtime's file locks (`runtime/ops_core.py:364`, `_try_lock`) are another mechanism. The person can reassign at any time, and a reassignment is recorded.
- **An agent's own plan is a route.** An agent may ask for its work to be split into tasks of its own skills. What it returns is a route, and code turns it into tasks, as L19 requires (`router.read_route`, `runtime/router.py:166`, is the model). A step that needs a skill outside its pack becomes a request to the colleague who has it (section 4.3).
- **Plan approval.** Every plan waits for the person's approval, as today, until the person gives a **`new`** consent per agent, "plan release" (OPEN-7). Its form follows D38:
  - the hash of the exact warning text shown;
  - given only on the page or in the terminal;
  - revoked when the person lowers the agent's mode.

  It is its own decision, not an application of principle 9: a skill's band says nothing about whether a model-made plan is right. Its measured component, cases of agent planning with bands, belongs to AC9. Even with the consent, these stay as they are:
  - a plan with an effect (L15);
  - a networked project script (L36);
  - a web task;
  - a routine (L33).
- **Unchanged:**
  - An external effect is executed by code with the exact content approved or inside a standing policy (L15, principle 11).
  - Credentials never enter a run.
  - Caps per agent stop a runaway.
- **The planning agent becomes the reception (OPEN-4).** A request addressed to nobody is routed to the area or agent whose skills fit. This changes what the router skill `core-orchestrator` returns, which is a Y change of that skill at least, with its tests (AGENTS.md, "Changing an existing skill"). It is part of AC8.

### 4.3 Messages between agents

- **`new`** One table of messages between agents, under L13: triggers refuse a delete and refuse a change. They are the record of who asked whom, which governance needs.
- **Four kinds:**
  - **question**: expects an answer;
  - **request**: expects a task done;
  - **delivery**: a result, with the artifacts it names;
  - **notice**: no reply expected.
- **What each message names:**
  - its sender and its receiver;
  - the chain it belongs to;
  - its provenance: the person, an agent, or external content.
- **"Agent" is a channel with a literal allow-list ceiling.** It is built in `runtime/operations.py`, as `INSTRUCTIONS_CHANNELS` and the channel ceilings are.
  - The ceiling allows a read, a notice and sending a message, and nothing else. Every other operation is refused by default: approve, answer, release, reject, cancel, retry, a verdict, every configuration change, consent, a routine, a source, the instructions or a profile, and every effect or gated operation.
  - `operations.refusal` is called with that channel. A test walks the whole table.
  - It is a **`new`** limit, numbered when built.
- **v1: where agents talk.**
  - Messages are exchanged in the conversation lane (agent to agent), and a request becomes a task of the receiver.
  - **A skill run never addresses a colleague in v1.** It keeps stopping to ask the person, unchanged, so no skill and no measured condition changes.
  - A stop rule's question always goes to the person: the decision is the person's (principle 5).
  - The gap is stated: a task that needs a colleague's facts stops and asks the person in v1.
- **v1: a request written by an agent.** It becomes a task with a **`new`** field recording where its text came from.
  - The task's prompt carries that text in a block marked "written by agent X, not the person". It never passes as "the request in the person's words" (`runtime/ops_runs.py:106`).
  - A colleague's information never enters the `answered` channel (`runtime/ops_runs.py:133`–`138`).
- **v1: brakes, needed from the start.** Without the consent of 4.2, every agent-written request waits for the person, so the inbox needs these brakes:
  - every chain between agents starts from a line the person typed;
  - a small limit of hops per chain;
  - a budget per chain set where it started (OPEN-3);
  - the same question to the same agent in one chain is answered once;
  - a conversation between agents that no person started does not exist in v1.
- **External content stays data.** A message whose text came from a web page or a document keeps that provenance. The receiver treats it as data, and an instruction inside it gains no power by passing between agents.
- **Visible.** Every message between agents is on the person's screen. Nothing between agents is hidden from the owner.
- **v2, each item its own decision:**
  - factual questions from a running task, emitted by a runtime-written section of the task prompt (never by the skills), which needs measurement because it changes the run's prompt;
  - conversations between agents that no person started, once the budgets are built and measured.

### 4.4 The conversation lane

- **What it is.** **`new`** A turn of conversation with an agent runs in the service, not in a container. It is one model call per step, streamed to the page.
- **Before the lane: the same dispatch as a line to the planning agent.** A line addressed to an agent first passes the dispatch every line passes today: typed commands, tier-1 forms, the state questions code answers, and the refusals of `NATURAL` (L54). Only what would have reached the router reaches the lane. L54 is extended to say so; otherwise a line to an agent would skip every L54 check.
- **The L63 condition.** Page and terminal lines reach a model route only by a new dated maintainer decision (L63). The lane is enabled on no channel until:
  - that decision is recorded (OPEN-10);
  - the lane has a band (AC9).

  OPEN-10 lists what leaves the host, kind by kind: the profile, the thread, the memories, artifact text and source passages. It also lists the route's retention and the channels that reach the lane (on messaging, the answers also pass the platform's servers, the threats of L50).
- **Safety given up for speed (principle 13).**
  - **Given up:** the container boundary, for a turn. A turn runs in the service process, with the service's network.
  - **Kept:**
    - no tool writes outside the store's own records;
    - no tool has an external effect;
    - no credential enters the prompt;
    - the inputs are chosen by code;
    - the tool list is a literal a test compares.
  - **Saved:** a container start per turn, the cost the maintainer named as the delay.
- **The provider.** The `model:text` provider today makes one request and gets one reply. AC3 adds what the lane needs, either as a mode of that class or as a new runtime-only class:
  - streaming;
  - a bounded loop of read-only tool calls.
- **Pinning.** The pinned hash covers:
  - the lane's fixed prompt template, including the sentence that explains the nonce blocks;
  - the literal list of the lane's tools and their schema;
  - the retrieval code's version;
  - the caps on the size of each data block.

  The per-project content enters as nonce-marked data blocks and is never part of the pinned text: the profile, the working memory, the thread and the passages. Routes are enabled by a dated entry, as the interpreter's are.
- **Inputs, all chosen by code.** It is a **`new`** limit of its own; L49 covers an answer run, and the lane is not one.
  - The profile.
  - The working memory: tasks and state, computed from the store.
  - The newest part of the thread.
  - The memories and passages the retrieval finds. The query is built from the person's line and its `@` mentions only, never from the thread. It is filtered by the agent's access set and by each memory's or passage's inherited access set.
  - The channel rules of L49 are inherited:
    - a mail or calendar snapshot only with `@<id>`, and only from the terminal or the page;
    - a version the person changed by hand only where the person is.
- **Tools, read-only and run by code.**
  - Read an artifact, a task's state, or the agent's own board.
  - Each tool is limited to what that agent may read.
  - No model-issued search tool in v1 (section 4.7).
- **Bounds, with numbers fixed in AC3's spec:**
  - tool-loop iterations per turn;
  - the size of each data block and of the whole context;
  - concurrent turns per agent and per project. Today one conversation model call per project at a time is the rule (`contracts/runtime.md`, "The conversation").
- **Cost.** Each turn's tokens and cost are recorded against the agent's `max_usd_per_day`, as runs are.
- **What code checked stays as code rendered it.** "A model's text never passes for what code checked" (`contracts/runtime.md`, "The answer from sources").
  - The lane shows quotes, deliveries and the content of approval cards and decision cards as code rendered them, or links to them. The persona's text is only the framing.
  - An approval card in a thread is always rendered by code and bound to its hash (L16, L44).
- **Work becomes a task.** When the person asks for work, the lane proposes a task of that agent, or a request to a colleague. Code builds it from a route (L19), and it runs in the container as today, under the same review and approvals. If the lane writes the route, it has taken the router's place, so AC9 measures the routes it writes.
- **Speed.**
  - A fast model for the lane, chosen among the models with a lane band (AC9), separate from the run model.
  - The fixed blocks first, so the provider's cache reuses them.
  - Few passages per turn.
  - Summaries of long documents made once, ahead.
  - Measured per model: time to the first event on screen, to the first word, and the whole turn. The targets are set from the first measurements (OPEN-5).

### 4.5 What the screen shows while an agent works

- **`new`** A core event schema: one event per step, for example "looking up 'plan price' in the sources", "reading `briefing.md`", "asking the designer", "writing the answer".
- **Where the events come from:**
  - **The lane:** it emits its events itself.
  - **A contained run:** the steps exist only in the adapter's `stream.jsonl`, in a format specific to the tool. Turning that format into events belongs in `adapters/<harness>/` (principles 1 and 2): each eval adapter gains a parser, and the core reads only the schema.
- **Who sees what.** An event can carry a query's text or a file's name, so it follows the rule of the answer it belongs to (L50): its full text is readable only by the channel that asked. Other readers, the office included, see its kind and its agent.
- **How events reach the page.** The service streams them to the page; today the page polls a change signal (`interface/js/watch.js`). AC4 first checks whether the service's design can stream (section 9).
- **Where they show.** The same events feed the chat, as a line under the agent's name, and the office, as the bubble over the character (R23).

### 4.6 Memory, in four layers

1. **The thread** of each conversation, in the store (the table of migration 6, with a conversation per agent).
   - Messages between agents fall under L13 (section 4.3).
   - The person's threads with an agent can be erased by the person, because the person's decisions already live in `pending_decisions`, which is never deleted, so the threads hold no record of governance only they hold. Erasing keeps a tombstone (id, hash, time, who erased it) and erases the text.
2. **The profile** (section 4.1).
3. **The working memory:** its tasks, their state, what it waits for. Always computed from the store, never remembered by a model.
4. **The long-term memory:** facts, decisions and preferences the agent learned, each with its source, its date and its access set (inherited from the sources it came from).
   - It lives in the store, not in files, which avoids committing conversation content to the project's git.
   - It is written by agents, and read, edited and deleted by the person on the page or in the terminal. That is the place where the person reads and edits, and it is the source the agents read.
   - Edits through MCP or messaging are not allowed. Reading it there is its own decision (OPEN-11).
   - A memory that came from external content carries that mark. Such a memory never enters a turn that carries an effect proposal.
   - Old threads are summarised into it.

**Before AC6,** a memory is found by code from the person's line by keyword, inside the store's own full-text index (section 4.7). AC6 replaces that with the knowledge base's search.

**Real erasure.** A deleted row's text stays in the store's free pages and in the WAL file until a checkpoint, and the full-text index keeps a copy of its own. Erasing a memory or a thread therefore:
- turns on `secure_delete` for the erasure (or runs a vacuum);
- removes the index entries;
- keeps the tombstone, so a turn that cited it can still be audited.

An erasure does not reach an export made before it, and the page says so.

The contract says that memories and the person's threads are outside L13. L13's scope is approvals, tasks, runs and pending decisions.

### 4.7 The knowledge base (retrieval)

- **One base per project, kept by the project,** beside the project's sources folder and outside git, under that folder's guardrails (L21 to L27). It holds:
  - the sources (immutable versions, as today);
  - what agents make, each piece with its author agent, date, provenance and access set;
  - the long-term memories.
- **v1: search by code, by keywords.** It ranks passages, not whole documents. `ask_select` ranks whole documents today, so ranking passages is new code in AC6. The query is built from the person's line and its `@` mentions only.
- **Search by meaning (embeddings) is v2.** A ranking by embeddings is a ranking by a model, which L49 forbids for an answer's inputs ("never a model's choice"). It needs an explicit amendment of L49 and L26, and so does a model-issued search tool.
- **Who reads what.**
  - **`new`** A key `sources` per entry of `area_agents`: the sources that agent may read.
  - A note or memory inherits the access set of the sources it came from, and every search filters on it. Without this, a note written from a source a colleague may not read would leak that source.
- **Learning.** An agent that reads new content, in a task, writes notes into its long-term memory, with the source's access set.
- **Prompt injection through indexed content.** Every passage enters a turn as a nonce-marked data block. Passages from external content carry that mark and are never read as an instruction. The lane's guard cases (AC9) measure this, because code cannot enforce how a model reads (principle 11).
- **Adopt before building (principle 14):** for example the full-text search of SQLite, behind a provider class.
- **The person looks it up** in the conversation and through `ask`. Covering agents' work and memories in `ask` amends L49 and L26, in AC6.

### 4.8 Proof of the conversation lane

The lane is not a skill, so it has no band from skill evidence. Like the interpreter (its own evidence kind and bands per model, `evals/interpreter_status.py`), it needs **`new`** cases and bands per model. The cases run the pinned template with fictional data blocks, injected blocks among them. They measure:
- answering in role from the working memory;
- citing what code retrieved;
- keeping code-checked results intact;
- refusing what an agent channel or a line may not do;
- refusing an instruction inside a data block;
- turning work into a task instead of claiming it was done;
- the quality of the routes it writes (section 4.4);
- the quality of an agent's own plans (section 4.2, OPEN-7).

Guard cases always run. `auto` picks the lane's model only among models with a lane band, and the lane is enabled on no channel before it has one.

### 4.9 The office

If R23 chooses a fork of Habblaud, it is fed by openhora:
- rooms per area;
- characters with their appearance from the profile;
- the message box wired to the lane;
- the events of section 4.5 as bubbles.

If R23 does not choose a fork, the same data feeds `interface/`.

A fork's approvals are a new client of the service. They come under L44, or are served from the service's own origin so that its origin check holds. In either case the service checks the hash.

## 5. Hard limits

| Limit | Status |
|---|---|
| An external effect is executed by code with the exact content approved or inside a standing policy (L15) | Unchanged |
| Approvals, tasks, runs and pending decisions only grow (L13) | Unchanged; messages between agents join it; the person's threads and memories are outside it, with tombstones on erasure |
| No credential inside a run | Unchanged; the lane's provider gets its key the way the interpreter's does, and no credential enters its prompt |
| Page and terminal lines reach a model route only by a dated decision (L63) | Unchanged; the lane waits for it (OPEN-10) |
| The inputs of an answer are chosen by code (L49), and sources reach a run only through its plan or an answer (L26) | Unchanged in v1; the lane gets its own limit of inputs chosen by code; covering agents' work in `ask` amends both in AC6 |
| The person's standing instructions are written only by the person (L40) | Unchanged; profiles get the same regime |
| The agent channel has a literal allow-list ceiling: a read, a notice, sending a message | `new`, in code; a test walks the table |
| A line addressed to an agent passes the same dispatch and refusals as a line to the planning agent (L54) | `new`, L54 extended |
| The lane has no tool with an external effect and no write outside the store's records; its tool list is a literal a test compares | `new`, in code |
| A task has at most one owner at a time | `new`, in the store |
| A request an agent wrote is never "the request in the person's words"; a colleague's information never enters the `answered` channel | `new`, in code |
| A chain between agents starts from a person's line, within a hop limit and a budget | `new`, in code |
| A memory, passage or message from external content is marked and never read as an instruction | `new`; the mark is in code; the reading is a measured guard (principle 11: where code cannot enforce, the measured guards are the protection, and this document says so) |

## 6. Packages

Each package is a backlog item, sized S, M or L. A package's spec is written before it starts.

| Id | Package | Size | Needs |
|---|---|---|---|
| AC0 | The dated L63 decision for the lane and the consent of plan release, put to the maintainer with what leaves the host (OPEN-10, OPEN-7) | S | - |
| AC1 | Agent profiles: the file, its owner row, the path rule, the checks, its read into the lane as a data block, proposals by an agent accepted by the person | M | - |
| AC2 | A conversation per agent: the store, the operations, the service routes, a message box on each floor; the migration of the existing `project` conversation into the planning agent's thread; on messaging and MCP, how a sender addresses an agent, under the L46 profiles; absorbs AGENT-DIRECT (#977) | M | AC1 |
| AC3 | The conversation lane: the dispatch before it, the provider's streaming and bounded tool loop, the pinned template, the inputs by code, the bounds and costs, work proposed as a route; latency measured | L | AC0, AC2 |
| AC4 | Events: the core schema, a parser in each eval adapter, the reader rule, streaming to the page | M | AC3 |
| AC5 | Memory: the four layers, the summary of old threads, erasure with tombstones, the store's full-text search for memories, editing on the page and in the terminal | L | AC2 |
| AC6 | The knowledge base: passages, keyword search by code, the `sources` key and inherited access sets, agents' writes with provenance, `ask` over it with the L49 and L26 amendments; first real case named in its spec | L | AC5 |
| AC7 | Messages between agents: the table under L13, the four kinds, the agent channel's ceiling, the provenance field of agent-written requests, the brakes, the visibility | L | AC1, AC2 |
| AC8 | Self-managing agents: the `area` key, open tasks and claims, the change of `agent_of` and its callers, an agent's own plan as a route, the plan-release consent, the reception (`core-orchestrator`, Y change at least, tested) | L | AC7, AC0 |
| AC9 | Proof of the lane: cases, evidence and bands per model, including routes and agents' plans | L | AC3 (starts with it) |
| AC10 | The office, if R23 chooses a fork: the spike, then its source fed by AC4 | L | spike: none; wiring: AC4 |

**Order:**
1. AC0 and AC1.
2. AC2.
3. AC3, with AC9 beside it.
4. AC4, AC5 and AC7.
5. AC6 and AC8.

The AC10 spike runs whenever there is room.

**Existing items:**
- AGENT-DIRECT (#977) is AC2 and AC3. What the planner sees of a direct task is answered by claims (AC8) and by the reception.
- R23 (#884) is AC10.
- VOICE-MODE (#978) builds on AC3.
- SETUP-GUIDE (#976) adds profiles to the guided setup.

**Documents each package changes:**
- `contracts/project-layout.md`: the profile file and its owner;
- `contracts/runtime.md`: the new limits, the amendments, the operations, and that memories and the person's threads are outside L13;
- `docs/architecture/platform/`: the pages of the conversation and the agents;
- this plan's status section.

## 7. Open questions

- **OPEN-1. Embeddings (v2).** Recommended: local by default when v2 comes, behind a provider class.
- **OPEN-2. Who writes the profile.** Recommended: the person only; an agent proposes, the person accepts.
- **OPEN-3. Who pays a chain of requests.** Recommended: each task counts on its owner's caps, and the chain carries a budget set where it started; the chain stops at either.
- **OPEN-4. What the planning agent becomes.** Recommended: the reception, with no manager role.
- **OPEN-5. Targets of speed.** Recommended: set from AC3's first measurements, per model.
- **OPEN-6. How long threads and memories are kept.** Recommended: until the person erases them, with tombstones and an export; messages between agents are kept like the other governance records.
- **OPEN-7. The consent of plan release.** Recommended: offered per agent after AC9 measures agents' plans on that agent's model; until then every plan waits.
- **OPEN-8. Where the index lives.** Recommended: beside the sources folder, outside git, under its guardrails.
- **OPEN-9. Memory written by an agent.** Recommended: allowed without approval inside a task or a turn, always visible and erasable, marked when it came from external content, and kept out of turns that carry an effect proposal.
- **OPEN-10. The dated L63 decision for the lane.** The maintainer decides whether page and terminal lines (and which messaging senders) reach the lane's model route, with:
  - what leaves the host, kind by kind;
  - the route's retention.

  Recommended: page and terminal first, messaging later, with the route's retention printed beside the switch as the interpreter's is.
- **OPEN-11. Reading memories from MCP or messaging.** Recommended: not in v1.

## 8. Not in this plan

- Choosing the office (R23 decides it).
- Voice (VOICE-MODE, #978), built on the lane later.
- Agents of another project talking to this one.
- The v2 items of sections 4.3 and 4.7, each of which needs its own decision.

## 9. Not verified

- Which open full-text index fits passages, and how fast it is on a real project's sources. AC6 starts with that comparison.
- How fast the lane can be. Nothing has been measured (section 2).
- Whether the service can stream events with its current design: today it answers requests and the page polls. AC4 starts by checking it.
- Whether the adapters' `stream.jsonl` carry enough to name each step. AC4 checks one adapter first.
- The Habblaud facts behind section 4.9 come from the reading recorded in issue #884, through the GitHub API, on 2026-11-27.

## 10. Review of version 1 (2026-11-27)

An independent reviewer on another model read version 1 against the code. It raised 19 findings, and the first round left seven open (F1, F2, F4, F7, F8, F11, F12). The second round settled them and raised five new problems (N1 to N5). Every point below was checked in the code before it was accepted.

| Finding | Where it is resolved |
|---|---|
| F1. The lane goes against L63; the provider has no streaming or tools; a prompt that changes per project cannot be pinned | 4.4 (L63 condition, provider, pinning, principle 13), OPEN-10, AC0, AC3 |
| F2. An agent answering a stop-and-ask breaks principle 5 | 4.3 (v1: runs never address a colleague; a colleague's information never enters `answered`; the provenance field) |
| F3. Memory written by an agent would steer unattended runs | 4.1, 4.4 (profiles and memories in the lane only, nonce blocks and checks), 4.6 |
| F4. Releasing plan approval stretches principle 9 | 4.2 (a route turned into tasks by code; a new consent; what it never releases), OPEN-7 |
| F5. Claims contradict `agent_of`; no `area` key | 4.2, AC8 |
| F6. The refusal list was a deny list, and incomplete | 4.3 (an allow-list ceiling), section 5 |
| F7. Model-chosen retrieval against L49 and L26; leaks across agents | 4.4 (inputs by code), 4.7 (keywords in v1, the `sources` key, inherited access sets), AC6 |
| F8. Profiles and memories in runs are not the measured condition | 4.1, 4.4 (the lane only; code-checked results shown as rendered) |
| F9. The router change is not tested | 4.2, AC8 |
| F10. Where run events come from; harness parsing belongs in adapters; leaks | 4.5, AC4 |
| F11. Contradictions on L13 and deletion; the conversation has no delete trigger | 4.3, 4.6, section 5, OPEN-6 |
| F12. Who writes memory and profile files, and where | 4.1, 4.6 (memories in the store; profiles owned by `user`) |
| F13. Lane turns not under caps or costs | 4.4 (cost, bounds) |
| F14. Wrong dependencies; missing work (migration, messaging and MCP, `agent_of`, L63) | Section 6 (AC0, AC2, AC7 on AC1 and AC2, AC5 before AC6) |
| F15. R23 decided and not decided; a fork's approvals | 4.9, section 8 |
| F16. The D11 reversal not named; "three choices" inexact | Section 3 (AC-D3, AC-D6), the decision record |
| F17. Imprecise citations | Section 2, 4.2 |
| F18. Principle 8 for AC6's real case | Section 3 (AC-D6) |
| F19. #977's question; AC-D5 tentative | Section 3 (AC-D5 as a direction), section 6 |
| N1. The lane would be a second router that skips L54 | 4.4 (the dispatch before the lane), section 5 |
| N2. Agent-written requests flooding the inbox | 4.3 (brakes in v1) |
| N3. Editing memories through other channels | 4.6, OPEN-11 |
| N4. AC9 grows | Section 6 (AC9 sized L) |
| N5. No persona voice outside the lane | 4.1 |
