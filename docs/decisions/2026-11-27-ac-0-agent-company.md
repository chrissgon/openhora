## 2026-11-27: The agent company: personas, memory, a conversation per agent, agents that talk to each other, no managers, a knowledge base, fast replies, peer review (ac-0; plan `docs/architecture/agent-company-plan-2026-11-27.md`)

**Status.** Decided by the maintainer on 2026-11-27, in a conversation that compared openhora's runtime with the office of Habblaud (R23, #884). The plan was reviewed the same day by an independent reviewer agent on another model; the maintainer then answered its version 2 point by point, and version 3 records those answers. Version 3 was reviewed again in the same way, and version 4 records the consensus; it changes how the decisions are built, not what was decided. The design and its open questions are in the plan, and each package has its own spec before it is built.

**Context.** The end goal of 2026-09-28 (`docs/decisions.md`) is a company of agents that take tasks, talk to each other through recorded messages and keep their data. What was built is narrower:
- an area agent is configuration with a pack and caps, with no persona or memory (`docs/architecture/delegation-platform-architecture-2026-10-14.md`, "Area agents are configuration, not code");
- agent memory was replaced on 2026-10-15 by the person's standing instructions (`docs/architecture/delegation-platform-plan-2026-10-14.md`, the row "Agent memory"), and a persona per agent was out of scope in its section 9;
- the same plan's section 9 left "Indexing or RAG. It waits for a real case (D11)";
- there is one conversation per project, with the planning agent (`runtime/ops_say.py`, `CONVERSATION = "project"`). Its comment marks it as a placeholder until the local interface (stage 9), not a decision;
- agents hand work on only through artifacts;
- every review and every plan waits for the person, unless proof or the person's consent per agent releases the reviews (principle 9, D38).

**Decision.** The maintainer's words, translated, then what each decides.
- AC-D1. A persona per agent: "each agent will need a persona, as in Habblaud, so that it does not feel like talking to a loose agent but to a person who works on something specific for us". Reverses the persona being out of scope.
- AC-D2. Memory per agent: "we will have to bring a more robust memory for the agent, in the project"; what the person and the agent said is kept for both. Reverses the replacement of agent memory by the standing instructions alone; the standing instructions stay.
- AC-D3. A conversation per agent: the person talks to each agent alone, "as if the user were the owner of the company", and gives it tasks directly. Ends the stage placeholder of one conversation per project.
- AC-D4. Agents talk to each other, with questions and tasks, "so that they have more flexibility and capacity to do the tasks without always needing the user", in the most efficient way that does not affect security and governance. The messages are carried and recorded by the runtime; no skill invokes another, so principle 4 is unchanged.
- AC-D5. No managers: "maybe each agent could be a manager and specialist"; "company hierarchies are not very efficient". Each agent plans and manages its own work within its skills and bounds; its plan is a route that code checks and turns into tasks (L19 unchanged).
- AC-D6. A knowledge base with retrieval: agents read, analyse and learn from new content, make new documents when needed, save them for others to look up, and find what they need "without reading everything". Reverses "Indexing or RAG. It waits for a real case (D11)"; the first real case is named in the spec of package AC6, and its data stays in its project (principle 8).
- AC-D7. Fast replies, and the screen shows what the agent is doing ("looking up a specific piece of information, writing the answer"), as in a normal conversation.
- AC-D8. The persona writes the whole message in the conversation; what code checked is attached as code rendered it. Approval cards stay, bound to their hash; their phone form is improved and follows the language of the project's configuration (CARD-READ, #987).
- AC-D9. Agents ask each other: "for a company to work, if everything goes through the owner it does not scale". A question is classified by level: a fact with a source, work another agent owns and a specialist's advice go to colleagues; a decision goes to the person unless the person delegated that kind of decision; an external effect goes to the person or a standing policy. It reuses the existing governance and limits, and every conversation and action between agents is kept for audit.
- AC-D10. Search by meaning in v1, "a crucial part of the platform's foundation": keyword and embedding search together, local embeddings by default, and a search tool whose query the agent writes, in the conversation lane. It amends L49 and L26: code may rank by the similarity of a pinned embedding model, never by a generative model's choice.
- AC-D11. Agents may work from start to end without the person, when the person chooses it: "a flexibility that should be possible, if the user wants it". An agent never approves its own work; in the autonomous mode a second agent reviews it, they discuss towards a consensus, and a third decides when they cannot. Reviewers and tiebreakers are temporary, on measured models different from the author's and at least as capable (an equivalent one when the author's is the strongest), with the context to review well; their costs are stated before the consent; the person may choose their models instead of the platform. Plan release is part of the same consent. Recorded as autonomy by consent, never as proven (principle 9). The plan builds it as a consent kind of its own, whose warning's hash is stored and checked; an `auto` agent, which principle 9 gives no consent, gets plan release by proof only.
- AC-D12. Under L63, page and terminal lines may reach the conversation lane's model route; messaging lines are a later decision. The lane is enabled once its route hash is accepted as the interpreter's are, with what leaves the host and the route's retention shown, and once the lane has a reliable band. It covers the person's lines only: run replies and messages between agents are not a person's line, and whether they reach the route is a further decision (the plan's OPEN-14).
- AC-D13. The memory rules of the plan's section 4.6: records between agents are never deleted; the person's threads and the memories are erasable by the person, really erased, with a tombstone; memories live in the store, outside git.
- AC-D14. Scaling without managers: one responsible agent per request, authority from owning an artifact, priorities set by the person.

**Not decided here.** These stay open in the plan, each with a recommendation: who writes the profile (OPEN-2), who pays a chain of requests (OPEN-3), what the planning agent becomes (OPEN-4), the speed targets (OPEN-5), where the index lives (OPEN-8), memory written by an agent (OPEN-9), reading memories from MCP or messaging (OPEN-11), how a delegation names a kind of decision (OPEN-12), the review rounds (OPEN-13), run replies and messages between agents on the lane's route (OPEN-14), messaging lines in the lane, and the office (R23).

**Unchanged.** The hard limits:
- an external effect only with its exact content approved or inside a standing policy (L15); no consent, delegation or peer review removes it;
- no credential inside a run;
- the governance records only grow (L13: approvals, tasks, runs, pending decisions), and the records between agents join them.

Project data stays in the project (principle 8).

**Alternatives rejected.**
- A manager agent per area. Rejected by AC-D5: a hop and a hierarchy with no gain when an agent holds the skills itself.
- Agents that call each other's skills directly. Rejected by principle 4; the runtime carries messages instead.
- Keeping one conversation with the planning agent and routing everything through it. Rejected by AC-D3: the extra hop is the delay the person named (AGENT-DIRECT, #977).
- The persona summarising an approval card in place of the card. Rejected: the person would approve the agent's words, not the exact content (L15).
- No questions from a running task in the first phase. Rejected by AC-D9.
- Embeddings later. Rejected by AC-D10.
- Permanent agents as reviewers by default. Rejected in favour of temporary ones: they take no permanent agent's time, have no history with the author and cover an area with one agent.
