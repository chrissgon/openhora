## 2026-11-28: The maintainer's decisions of the backlog's wave 0 (w0-decisions; AC-D18 to AC-D26, R23, W0-D1 to W0-D9)

**Status.** Decided by the maintainer in chat on 2026-11-27 and 2026-11-28. This entry records them. It changes no code, contract, test or skill: each decision names what it unblocks, and the package that does the work is named beside it.

**Quotes.** Each section carries the maintainer's own words in a code span. Where he answered with a letter, the letter is the option recommended in the question he was asked.

## Agent company: the open questions of the plan (AC-D18 to AC-D26)

These continue the AC-D series of `docs/decisions/2026-11-27-ac-0-agent-company.md` (last number AC-D17). Each closes one `OPEN-<n>` of section 7 of `docs/architecture/agent-company-plan-2026-11-27.md`.

### AC-D18. Who writes an agent's profile (OPEN-2)

- **Decided.** The person only. An agent may propose a change to a profile, and the person accepts it on the page or in the terminal.
- **His answer.** `A` (validate: allow english-only -- the maintainer's verbatim answer)
- **Changes.** Section 4.1 of the plan (the profile) is settled as written. The package that builds profiles (AC1) holds no agent write path to a profile.

### AC-D19. Who pays a chain of requests (OPEN-3)

- **Decided.** Each task counts on its owner's caps, and the chain carries a budget set where it started. The chain stops at either limit.
- **His answer.** `A` (validate: allow english-only -- the maintainer's verbatim answer)
- **Changes.** The messages between agents (AC4) carry the starter's budget. A task's own caps are unchanged.

### AC-D20. What the planning agent becomes (OPEN-4)

- **Decided.** The planning agent becomes the reception. There is no manager role (AC-D5 stands).
- **His answer.** `A` (validate: allow english-only -- the maintainer's verbatim answer)
- **Changes.** The agent-company packages treat "planning agent" as "reception" from here on.

### AC-D21. Targets of speed (OPEN-5)

- **Decided.** The targets are set from the first measurements of AC3, per model, not before.
- **His answer.** `A` (validate: allow english-only -- the maintainer's verbatim answer)
- **Changes.** AC3 writes the targets with its first measurements. No number is fixed now.

### AC-D22. Where the sources' index lives (OPEN-8)

- **Decided.** Beside the sources folder, outside git, under the limits restated in section 4.7 of the plan.
- **His answer.** `A` (validate: allow english-only -- the maintainer's verbatim answer)
- **Changes.** AC6 (the knowledge base) places its index there. Principle 8 and the sources model are unchanged.

### AC-D23. Memory written by an agent (OPEN-9)

- **Decided.** An agent may write memory without approval inside a task or a turn. The memory is always visible and erasable. It is marked when it came from external content. It is kept out of turns that carry an effect proposal.
- **His answer.** `A` (validate: allow english-only -- the maintainer's verbatim answer)
- **Changes.** Section 4.6 of the plan (AC-D13) is settled for agent-written memory. L15 is untouched: an effect still needs the approval of its exact content.

### AC-D24. Reading memories from MCP or messaging (OPEN-11)

- **Decided.** Memories are not readable from MCP or from messaging in v1.
- **His answer.** `A` (validate: allow english-only -- the maintainer's verbatim answer)
- **Changes.** The memory read operation is not exposed on those channels. A later decision may widen it.

### AC-D25. How a delegation names a kind of decision (OPEN-12)

- **Decided.** A delegation names its kind of decision in the person's own words. A model behind a measured guard matches the words. A doubtful match goes to the person.
- **His answer.** `A` (validate: allow english-only -- the maintainer's verbatim answer)
- **Changes.** Section 4.10 of the plan (AC-D9) is settled. The guard's cases belong to the package that builds it.

### AC-D26. Review rounds and the reviewer's budget (OPEN-13)

- **Decided.** Two review rounds before the tiebreak. The reviewer's budget is fixed in the spec of AC12 from the first measurements.
- **His answer.** `A` (validate: allow english-only -- the maintainer's verbatim answer)
- **Changes.** Section 4.11 of the plan (AC-D11) is settled. AC12's spec states the budget with its measurements.

With these, every `OPEN-<n>` of the plan's section 7 is decided.

## R23: the office is our own, in `interface/` (R23, #884; replaces the AC10 spike)

The decision is the sum of four answers: AC10 (release the spike), the repository given for it, the redirection after the alternatives research, and O1 to O4.

- **First answers.** On AC10 he answered `A` (validate: allow english-only -- the maintainer's verbatim answer): release the spike of a fork of Habblaud now. He then gave the fork repository, https://github.com/chrissgon/habblaud (2026-11-28), and asked for research on the alternatives before the spike.
- **What was decided, replacing the AC10 spike.**
  1. Map five open projects (done, outside this repository, with `eng-codebase-map`).
  2. Choose the parts per need (done, outside this repository, with `eng-tradeoffs`).
  3. Build our own office in `interface/` as static files, reusing permissive code with its notices. There is no fork of Habblaud.
- **His answer to this redirection.** `Aceito. Quando for o momento de selecionar a arte, vamos conversar novamente qual das artes iremos escolher` (validate: allow english-only -- the maintainer's verbatim words)
- **The art.** Not chosen. Before any art is chosen, the maintainer is asked again. The code is built behind a painter interface so that the art stays open; slice 1 paints a placeholder.
- **The fork repository** is kept as a reference only. No code is built in it.
- **Changes.** Section 4.9 of the plan now says R23 decided an own office in `interface/`. The AC10 package is re-scoped from "a spike of a fork" to "the own office", in slices.

### What the research found, condensed

The research was done on 2026-11-28 on five public projects (Habblaud, pixel-agents, two projects named claude-office, and cubicle). Prototypes ran in Node 20, 22 and 24. Nothing was run in a browser. The sizes and times are those of that research.

- **Why not a fork.** Its client is a Vite and TypeScript build, which R2 (no build step) excludes. Its comments and UI strings are mostly Portuguese. Its World service is on by default. One author wrote most of its commits.
- **Rendering and camera.** Canvas 2D with no library. The existing on-demand loop (`interface/js/scene/loop.js`) drew 2,520 frames in 60 s with walking and 22 under reduced motion, against 3,601 for a standing loop. Add an integer-zoom rule.
- **Characters (code).** A small sprite pipeline of our own with a cache per look, pose, frame and direction, and a painter interface. A cache gives 30 draws a frame for 30 agents against up to 510 rectangle fills.
- **Pathfinding.** Port the A* of Habblaud (7,715 B), with its comments translated and its MIT notice kept. It was the fastest in every run and never returned an invalid path or gave up on a large building.
- **Space model.** Our own slot model, `floors[].rooms[{area, slot}]`, 403 B for 3 floors of 4 rooms against 17,085 B for a tile grid. Room insides are generated by code, and a DOM form edits the layout. The person alone writes the layout, through a service operation with a base hash.
- **Feed (O4).** Keep the poll of `GET /versions` each second, and add one read of the events when the number moved. Measured: median 551 to 604 ms from write to screen, 0 connections held. Server-sent events and a long poll cut the delay to a few milliseconds but cross R7 (one response per request, no streaming), so they are not built. Only AC4 can reopen them, by its own decision.
- **Screen model.** "Waiting for you" counts open decisions, not agents in the waiting state: on one fixture, 4 decisions against 1 agent. Bubbles are DOM labels.
- **Approvals.** The office shows the item and links to the existing card. It never holds an approval path of its own (L15, L44).
- **Events (O1).** Schema version 1, `{"schema", "events": [{"id", "at", "agent", "kind", "task"}]}`, with `kind` from a closed list. The office shows the kind of step only (L50).
- **Languages (O2).** English and pt-BR dictionaries as static files, English fallback, `Intl.PluralRules`.
- **The notices of ported code.** A ported file is not a vendored library, so R3 does not cover it. Each ported file keeps its notice in a header, and `interface/README.md` lists them. A notice with a non-ASCII character needs an allow line for `english-only`.
- **Not verified.** Anything in a browser (drawing cost, canvas memory, connection limits) and the port of any large module.

### O1. What the office shows as "doing now"

- **Decided.** The kind of step only (L50). No file or query names.
- **His answer.** `A` (validate: allow english-only -- the maintainer's verbatim answer)

### O2. The office's language

- **Decided.** The project's language setting, as the phrase table does.
- **His answer.** `A` (validate: allow english-only -- the maintainer's verbatim answer)

### O3. Rooms

- **Decided.** One room per area (R23).
- **His answer.** `A` (validate: allow english-only -- the maintainer's verbatim answer)

### O4. The office's feed

- **Decided.** Poll `/versions` each second, plus an events read. No server-sent events unless AC4 changes the rule by its own decision.
- **His answer.** `A` (validate: allow english-only -- the maintainer's verbatim answer)

## Other decisions of the wave (W0-D1 to W0-D9)

### W0-D1. End the legacy Google fallback now (ACCT-LEGACY)

- **Decided.** The legacy Google fallback ends now, together with T47 in wave 2. Before the merge, the maintainer is asked to confirm that Gmail, Calendar and Drive work on the new records.
- **His answer.** `A` (validate: allow english-only -- the maintainer's verbatim answer)
- **Changes.** Unblocks the removal of the fallback (ACCT-LEGACY, with T47). The merge waits for his check.

### W0-D2. The scheduler's label prefix and home (T47)

- **Decided.** The label prefix becomes `dev.openhora.scheduler.` and the home becomes `.../openhora/scheduler`. A one-time move command lists first, moves on the maintainer's yes, and refuses while a job points at the old home. Then each job is scheduled again once.
- **His answer.** `A` (validate: allow english-only -- the maintainer's verbatim answer)
- **Changes.** Unblocks the scheduler part of T47.

### W0-D3. The old data folders, ledgers and the secret-store fallback (T47)

- **Decided.** The old data folders are moved: shown first, moved on his yes. The old Notion test ledgers are deleted. The legacy fallback of the secret store is removed. The resolver's list (`resolver.py --list`) is run and shown before any removal.
- **His answer.** `Pergunta 13: A` (validate: allow english-only -- the maintainer's verbatim answer)
- **Verified.** On 2026-11-28, on the maintainer's machine, the list showed no `(legacy)` entry. The old per-service Google and Microsoft records still sit beside the account tokens.
- **Changes.** Unblocks the data part of T47. Nothing is removed before the list is shown again and he says yes.

### W0-D4. `<task>` comes from the task key (R17)

- **Decided.** The `<task>` placeholder comes from the task key. R17 keeps the declared paths: renaming an output is an X change, which R17 does not do.
- **His answer.** `A` (validate: allow english-only -- the maintainer's verbatim answer)
- **Changes.** Unblocks R17 (the placeholder vocabulary of `contracts/project-layout.md`).

### W0-D5. Post images: a template brief and an HTML/CSS render (NS10)

- **Decided.** A template design brief is approved once per post format. The design-execution skill renders the post image from HTML and CSS (code-prototype mode) with the post copy. An image the person attaches replaces it. The flow is: social copy, then the template render or the attached image, then the approval of the exact content, then the publication.
- **His answer.** `D` (validate: allow english-only -- the maintainer's verbatim answer), after he pointed out that the design-execution skill already renders images with HTML and CSS.
- **Changes.** Unblocks NS10. The approval of the exact content stays the gate (principle 11).

### W0-D6. The e-mail question's words (P5B, #972)

- **Decided.** The question keeps its existing forms: pt-BR "Qual o e-mail de {name}?" and English "What is the e-mail address of {name}?". An empty `{name}` defaults to "quem vai receber" in pt-BR and "the recipient" in English. There is no separate name question by default; it is asked only when the text needs it.
- **His answers.** First `A` (validate: allow english-only -- the maintainer's verbatim answer), which chose new wording ("Para quem é o e-mail? Me diga o endereço."). He then proposed the default-value approach: `Pode ser assim, "quem vai receber"` (validate: allow english-only -- the maintainer's verbatim words). The second answer supersedes the first.
- **Changes.** Unblocks P5B (#972) with the wording above.

### W0-D7. Housekeeping of three items

- **Decided.** T49 (#867, an OpenCode runner pair on the OpenCode 2 line) is closed: it is not planned. N14b (#935) is left out for now: it stays open and out of the queue. Items 4, 5 and 7 of T48 (#866) ride with the next battery.
- **His answer.** `Pergunta 17: A` (validate: allow english-only -- the maintainer's verbatim answer)
- **Changes.** The index line of T49 leaves `docs/backlog.md`. The batch closes the issue.

### W0-D8. One rule for one-line fields (W-FRAME)

- **Decided.** One rule for every kind of field. One-line fields are normalised to NFC, and a no-break space becomes a plain space. A field is refused only when a base character carries three or more combining marks in a row.
- **His answer.** `A` (validate: allow english-only -- the maintainer's verbatim answer)
- **Changes.** Unblocks W-FRAME.

### W0-D9. The lookup of `resolver.py --list` on 2026-11-28

- **Recorded.** There is no `(legacy)` entry on the maintainer's machine on 2026-11-28 (see W0-D3). It is the fact W0-D3 and W0-D1 rest on, not a decision.

### Decision ids

W0-D1 to W0-D8 are the decisions above. W0-D9 is the recorded fact. The answers `AC10`, `10b` and `10c` of the source list are the R23 section. No other id is used.
