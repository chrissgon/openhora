# The agent company: a plan

Version 1, of 2026-11-27. On `origin/main` at `9bacdbf9`. A proposal, written before any of it is built. The maintainer's decisions it rests on are recorded in `docs/decisions/2026-11-27-ac-0-agent-company.md`. Nothing here is built, and no `new` element is written as if it exists.

How to read it: a path with a line number was opened and read at `9bacdbf9` for this plan. A claim with no line number came from a search, and the text says so. A fact about a third-party project that was not confirmed is in section 9, "Not verified". Open questions are `OPEN-<n>` in section 7, each with a recommended answer; none is decided by this document.

## 1. The target

The maintainer's words, 2026-11-27 (translated): a company made of agents that act like people. They talk to each other, ask each other questions and do tasks for each other. The person talks to each one alone, as the owner of the company would, and gives tasks to one agent directly. They share information, and the person can look it up. Each agent answers as a specialist of its area, fast, as in a conversation with someone; it must not feel like a one-off chat with an AI: the agent knows who it is, what it does and everything about its current work. What the person and the agent said is kept, as the person's memory and the agent's. It must be simple and look like people working, while being AI agents.

On the same day the maintainer added these points (each is a decision of the record named above):

- No managers. An agent with the right skills is its own manager and its own specialist; company hierarchies are often not efficient, and an agent does not have a person's limit on how much it can know.
- Each agent has a persona, so that the person talks to someone who works on something specific, not to a loose agent.
- Agents talk with the person and with each other, in the most efficient way that does not weaken security or governance, so that they can finish work without always needing the person.
- Agents produce content and keep a fast memory to find it (retrieval, "RAG"): they read, analyse and learn from new content, make new documents when needed, and what they make is saved so that others can look it up.
- Replies as fast as possible, and the screen shows what the agent is doing (looking up something, writing the answer), as a person would.
- A robust memory for each agent, in the project.

This is the end goal recorded on 2026-09-28 (`docs/decisions.md:73`: "a company run by agents, one per department, that take tasks, talk to each other through recorded messages and keep their data"), with three choices of 2026-10-14 and 2026-10-15 reversed (section 3).

## 2. Where we are

Read for this plan; the agent's knowledge of itself, the conversation and the memory are the gaps.

| Point | Today | Where |
|---|---|---|
| Agents | Configuration entries `area_agents` in `docs/workbench/runtime.json`: a pack of skills, a mode, caps per day, parallel slots, a model, a consent. The planning agent is the entry named `planning`. | `runtime/autonomy.py:156` (`agents`), `runtime/plan.py:96` |
| What an agent knows of itself in a run | Nothing: the run's text is the request, the task, the standing instructions, the handed files, sources and earlier answers. It names no agent, role, area or colleague. | `runtime/ops_runs.py:104` (`task_prompt`) |
| Persona and memory per agent | Out of scope by decision: "Area agents are configuration, not code: they own a pack and a cap, and carry no persona or memory". Agent memory was replaced on 2026-10-15 by the person's standing instructions. | `docs/architecture/delegation-platform-architecture-2026-10-14.md:179`; `docs/architecture/delegation-platform-plan-2026-10-14.md:147`, `:975`; `contracts/runtime.md` (limit L40) |
| Who does a task | Code: the one enabled agent, other than planning, whose pack holds the skill. No hierarchy. | `runtime/plan.py:169` (`agent_of`) |
| Conversation | One per project, with the planning agent only. The read route takes a conversation name, but nothing writes another. | `runtime/ops_say.py:75`; `runtime/service.py:346` |
| History given back to the model | The planning agent only: the newest 6 messages after the last settled request, each cut to 600 characters, at most 4,000 in all. | `runtime/ops_say.py:76`, `:137` (`chat_memory`) |
| Messages store | Table of migration 6, "the messages of the conversation with the planning agent". | `providers/store/sqlite.py:296` |
| Agents talking to each other | Only through artifacts and the dependencies of a flow (principle 4). No message between agents, no inbox per agent (searched: "message bus", "ask_agent", "agent inbox" in `runtime/`, `providers/`, `contracts/`, `docs/architecture/`). | `flows/*.json`; `AGENTS.md`, principle 4 |
| Shared information | Sources with immutable versions and a catalog; `ask` answers from chosen sources with citations checked by code; artifacts on the desk. No index and no retrieval: they wait for a real case. | `runtime/sources.py`, `runtime/ops_ask.py`; search of `runtime/sources.py` for "indexing or retrieval" |
| Speed of a reply | Every routed line starts one contained run of the router skill; one router run per project at a time; the page polls a job. No streaming, no measured latency (searched docs, decisions and tests for "latency", "cold start"). The interpreter of the messaging bridge calls a model directly over HTTP, with a gate of p95 under 4,000 ms. | `runtime/lab.py:994` (`run_skill`); `providers/model/chat-http.py`; `evals/interpreter/thresholds.json:4` |
| Autonomy | Released by proof (a reliable pair of skill, model and adapter) or by the person's consent per agent (D38); external effects need the exact content approved or a standing policy. At most 4 parallel runs per agent. | `AGENTS.md`, principles 9 and 11; `contracts/runtime.md` (L15); `runtime/autonomy.py:104` |
| The screen | A 3D building, one floor per agent, the Lobby with the planning agent's conversation; floors have no message box. R23 (#884) proposes rooms per area and a fork of Habblaud. | `interface/js/views/floor.js`, `interface/js/views/lobby.js`; issue #884 |

## 3. Decisions (the maintainer, 2026-11-27)

The record is `docs/decisions/2026-11-27-ac-0-agent-company.md`. In short:

- **AC-D1. A persona per agent.** Reverses "a persona per agent" being out of scope (`docs/architecture/delegation-platform-plan-2026-10-14.md:975`).
- **AC-D2. Memory per agent, robust and in the project.** Reverses the replacement of agent memory by the standing instructions alone (2026-10-15); the standing instructions stay.
- **AC-D3. A conversation per agent.** The person talks to any agent; "one conversation per project" (`runtime/ops_say.py:75`) ends.
- **AC-D4. Agents talk to each other**, questions and tasks, through messages the runtime carries and records, without weakening the hard limits. No skill invokes another: principle 4 is unchanged.
- **AC-D5. No managers.** Each agent plans and manages its own work within its skills and bounds; how several agents in one area share work is designed in section 4.2.
- **AC-D6. A knowledge base with retrieval**, in the project: what agents read, learn and make is saved and can be looked up by others and by the person.
- **AC-D7. Fast replies, and the screen shows each step** the agent is taking.

## 4. Design

### 4.1 The agent's profile (persona)

- **`new`** One file per agent in the project: `docs/workbench/agents/<agent>.md`, where `<agent>` is the key of `area_agents`. It holds: a display name, the role in a sentence, the area, what it is good at (its pack, read by code, never typed), how it speaks, what it must never do, its colleagues (computed by code from `area_agents`, never typed), and the appearance the office draws.
- Written by the person, as the standing instructions are (limit L40). An agent may propose a change; the person accepts it on the page or in the terminal (OPEN-2).
- Read by code into every conversation turn and every run of that agent, as a fixed first block (the same bytes every time, so that the provider's prompt cache can reuse it; section 4.4).
- The profile is project data (principle 8); the workbench holds only its template.

### 4.2 Agents that manage themselves, and governance without managers

- **Each agent has its own board**: the tasks it owns. **`new`** A task has exactly one owner at a time; an agent **claims** an open task of its area, and the store refuses a second claim in the same transaction (the runtime already takes named locks for a project's router and tasks, `runtime/ops_core.py:364`). The person can reassign at any time.
- **An agent plans its own work** within its pack: it may split a request into tasks of its own skills and run them. A step that needs a skill outside its pack becomes a request to the colleague who has it (section 4.3), never a skill it runs itself.
- **What moves, and what does not.** Today the person approves each plan by its hash (limit L19: the planning agent creates no task, code builds the plan). With self-managing agents, the person approves each agent's **bounds** once (its pack, its caps per day, the sources it may read, the effects it may prepare), and an agent's own plans inside those bounds run without a plan approval **only** where the pair is released by proof or by the person's consent per agent (principle 9, D38); elsewhere its plan is shown and waits, as today (OPEN-7).
- **Unchanged.** An external effect is executed by code with the exact content approved or inside a standing policy (L15, principle 11). Credentials never enter a run. Caps per agent stop a runaway (`runtime/autonomy.py`).
- **The planning agent becomes the reception** (OPEN-4): a request addressed to nobody is routed to the agent whose skills fit; a request addressed to an agent goes to it.

### 4.3 Messages between agents

- **`new`** One table of messages between agents, kept like the conversation (a record only grows, L13). Four kinds: **question** (expects an answer), **request** (expects a task done), **delivery** (a result, with the artifacts it names), **notice** (no reply expected). Each names its sender, its receiver, the task or chain it belongs to, and where its text came from (the provenance: the person, an agent, or external content).
- **A message from an agent is information, never authority.** Code refuses, for a sender that is an agent: approving, consenting, changing a mode, a model, a bound or a cap, creating or approving a routine, writing the standing instructions or a profile. This is the same shape as the refusal table of a line in natural language (L54), with a new carrying channel for agents. **`new`** limit, numbered when built.
- **A request becomes a task of the receiver**, inside the receiver's bounds; the answer of a question comes back as a message. A task that asked a colleague continues with the answer, by the mechanism that already reruns a task with its earlier questions and answers (`runtime/ops_runs.py:104`, the `answered` argument), with an agent in place of the person.
- **Brakes on loops**: a limit of hops per chain, a budget per chain set where the chain started (OPEN-3), and the same question to the same agent in one chain answered once.
- **External content stays data.** A message whose text came from a web page or a document keeps that provenance; the receiver treats it as data, and an instruction inside it gains no power by passing between agents.
- **Visible.** Every message is on the person's screen: two agents talking, and the thread readable. Nothing between agents is hidden from the owner.

### 4.4 The conversation lane: fast, streamed, read-only

- **`new`** A turn of conversation with an agent runs in the service, not in a container: one model call through the `model:text` provider (`providers/model/chat-http.py`, the one the interpreter already uses), streamed to the page.
- **Tools of the lane are read-only and run by code**: search the knowledge base, read an artifact, read a task's state, read the agent's own board. Each is limited to what that agent may read (its sources, as tasks see only chosen sources today). The lane has no tool that writes outside the store's own records and no tool with an external effect: it cannot cause one.
- **Work becomes a task.** When the person asks for work, the lane proposes a task of that agent (or a request to a colleague), which runs in the container as today, under the same review and approvals.
- **Speed**: a fast model for the lane, chosen by the lane's own proof (section 4.8) and separate from the run model; the profile and the agent's fixed context first, so the provider's cache reuses them; few retrieved passages per answer; summaries of long documents made once, ahead; lookups in parallel.
- **Measured, not guessed**: time to the first event on screen, time to the first word of the answer, and the whole turn, per model. Targets are set from the first measurements (OPEN-5).

### 4.5 What the screen shows while an agent works

- **`new`** Each step of a turn or of a run is an event: "looking up 'plan price' in the sources", "reading `briefing.md`", "asking the designer", "writing the answer". The service streams events to the page (today the page polls a change signal, `interface/js/watch.js`).
- The same events feed the chat (a line under the agent's name) and the office (the bubble over the character, the "real" layer of the Habblaud scene, R23).

### 4.6 Memory, in four layers

1. **The thread** of each conversation, whole, in the store (the table of migration 6, with a conversation per agent).
2. **The profile** (section 4.1): who the agent is.
3. **The working memory**: its tasks, their state, what it is waiting for. Always computed from the store, never remembered by a model.
4. **The long-term memory**: facts, decisions and preferences the agent learned, each with its source and date, as files in the project that the person can read, correct and delete (the interaction surface is the source agents read), and indexed in the knowledge base. Old threads are summarised into it. A memory that came from external content carries that mark and is never read as an instruction.

What a turn receives: the profile, the working memory, the newest part of the thread, and the long-term memories and passages the retrieval finds for this turn, within a size budget.

### 4.7 The knowledge base (retrieval)

- **One base per project, kept by the project** (in the folder outside git that holds the sources, under the guardrails of the sources folder, L21 to L27). It holds the sources (immutable versions, as today), what agents make (each piece with its author agent, date and provenance) and the long-term memories.
- **Search by words and by meaning** (keyword and embeddings together); every passage found comes back with the place it came from, and an answer cites it.
- **Learning**: an agent that reads new content writes notes into its long-term memory; they are indexed and its colleagues can find them.
- **Who reads what**: each agent searches only the sources it may read.
- **Adopt before building** (principle 14): an existing open index (for example the full-text search of SQLite with a vector extension, or an embedded vector database), behind a provider class; embeddings by a `new` provider class, local by default (OPEN-1).
- **The person looks it up** in the conversation ("what does marketing know about X?") and through `ask`, which then covers agents' work and memories as well as sources.

### 4.8 Proof of the conversation lane

The lane is not a skill, so it has no band from skill evidence. Like the interpreter (its own evidence kind and bands per model, `evals/interpreter_status.py`), it needs **`new`** cases and bands per model: the agent answers in role, uses its working memory and cites the base, refuses what a message or a line may not do, and turns work into a task instead of claiming it was done. Guard cases are always run. `auto` picks the lane's model among the reliable ones.

### 4.9 The office

The screen is R23 (#884): a fork of Habblaud fed by openhora, rooms per area, characters per agent with their appearance from the profile, the message box wired to the conversation lane, the events of section 4.5 as bubbles, and approvals sent to our service, which checks the hash. Its spike can run in parallel with everything below; it is wired once the events exist.

## 5. Hard limits

| Limit | Status |
|---|---|
| An external effect is executed by code with the exact content approved or inside a standing policy (L15) | Unchanged |
| A record only grows; an approval is never deleted (L13) | Unchanged; messages and threads follow it |
| No credential inside a run | Unchanged; the lane's provider gets its key the way the interpreter's does |
| A message from an agent cannot approve, consent, change a mode, model, bound or cap, or write a profile or the instructions | `new`, in code (a refusal table), numbered when built |
| The conversation lane has no tool with an external effect and no write outside the store's records | `new`, in code (the lane's tool list is a literal a test compares) |
| A task has one owner at a time | `new`, in the store |
| A memory or message from external content is marked and never read as an instruction | `new`; the mark is in code, the reading is a measured guard (principle 11: where code cannot enforce, the measured guards are the protection, and the document says so) |

## 6. Packages

Each is a backlog item; sizes S, M, L. A package's spec is written before it starts.

| Id | Package | Size | Needs |
|---|---|---|---|
| AC1 | Agent profiles: the file, its checks, its read into runs and turns, proposals by an agent accepted by the person | M | - |
| AC2 | A conversation per agent: the store, the operations, the service routes, a message box on each floor; absorbs AGENT-DIRECT (#977) | M | AC1 |
| AC3 | The conversation lane: a direct streamed call, read-only tools run by code, work proposed as a task, latency measured | L | AC2 |
| AC4 | Events of each step, streamed to the page and to the office | M | AC3 |
| AC5 | Memory in four layers, with the summary of old threads and the files the person edits | L | AC2 |
| AC6 | The knowledge base: index, hybrid search, access per agent, agents' writes with provenance, `ask` over it | L | AC5 |
| AC7 | Messages between agents: the table, the four kinds, the refusal table, the brakes, the visibility | L | AC3 |
| AC8 | Self-managing agents: the board, claims, own plans inside bounds, bounds approved once, the planning agent as reception | L | AC7 |
| AC9 | Proof of the lane: cases, evidence and bands per model | M | AC3 (starts with it) |
| AC10 | The office: the fork's spike, then its source fed by AC4 (R23, #884) | L | spike: none; wiring: AC4 |

Order: AC1, then AC2 and AC3 with AC9 beside them, then AC4 and AC5, then AC6, AC7, AC8. The AC10 spike runs whenever there is room. Existing items: AGENT-DIRECT (#977) is AC2 and AC3; R23 (#884) is AC10; VOICE-MODE (#978) builds on AC3; SETUP-GUIDE (#976) adds the profiles to the guided setup.

Documents each package changes: `contracts/project-layout.md` (the profile and memory files, their owner), `contracts/runtime.md` (the new limits and operations), `docs/architecture/platform/` (the pages of the conversation and the agents), and this plan's status section.

## 7. Open questions

- **OPEN-1. Embeddings.** A local model by default (no content leaves the machine, no cost per call), a hosted one as an option behind the same class. Recommended: local by default.
- **OPEN-2. Who writes the profile.** Recommended: the person only, as the standing instructions (L40); an agent proposes, the person accepts.
- **OPEN-3. Who pays a chain of requests.** Recommended: each task is counted on its owner's caps, and the chain carries a budget set where it started; the chain stops at either.
- **OPEN-4. What the planning agent becomes.** Recommended: the reception, routing what is addressed to nobody; no manager role.
- **OPEN-5. Targets of speed.** Recommended: set from the first measurements of AC3, per model, for the first event, the first word and the whole turn.
- **OPEN-6. How long threads and memories are kept.** Recommended: until the person deletes them, with an export; a deleted memory leaves the index at once.
- **OPEN-7. An agent's own plan.** Recommended: no plan approval inside its bounds where the pair is reliable or under consent (principle 9); elsewhere shown and waiting, as today.
- **OPEN-8. Where the index lives.** Recommended: beside the project's sources folder, outside git, under its guardrails.
- **OPEN-9. Memory written by an agent.** Recommended: allowed without approval, always visible and reversible, marked when it came from external content.

## 8. Not in this plan

- Choosing the office (R23 decides it; this plan works with today's screen and with a fork).
- Voice (VOICE-MODE, #978), built on the lane later.
- Agents of another project talking to this one.

## 9. Not verified

- Which open index and which local embedding model fit; AC6 starts with a comparison on a real project's sources.
- How fast the lane can be; nothing has been measured (section 2).
- Whether the service can stream events with its current design (today it answers requests and the page polls); AC4 starts by checking it.
- The Habblaud facts used in section 4.9 come from the reading recorded in issue #884, through the GitHub API, on 2026-11-27.
