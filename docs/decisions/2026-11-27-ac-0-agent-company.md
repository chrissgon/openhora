## 2026-11-27: The agent company: personas, memory, a conversation per agent, agents that talk to each other, no managers, a knowledge base, fast replies (ac-0; plan `docs/architecture/agent-company-plan-2026-11-27.md`)

**Status.** Decided by the maintainer on 2026-11-27, in a conversation that compared openhora's runtime with the office of Habblaud (R23, #884). These are directions; the design and its open questions are in the plan, and each package has its own spec before it is built. The plan was reviewed the same day by an independent reviewer agent on another model, and its version 2 records the consensus.

**Context.** The end goal of 2026-09-28 (`docs/decisions.md`) is a company of agents that take tasks, talk to each other through recorded messages and keep their data. What was built is narrower:
- an area agent is configuration with a pack and caps, with no persona or memory (`docs/architecture/delegation-platform-architecture-2026-10-14.md`, "Area agents are configuration, not code");
- agent memory was replaced on 2026-10-15 by the person's standing instructions (`docs/architecture/delegation-platform-plan-2026-10-14.md`, the row "Agent memory"), and a persona per agent was out of scope in its section 9;
- the same plan's section 9 left "Indexing or RAG. It waits for a real case (D11)";
- there is one conversation per project, with the planning agent (`runtime/ops_say.py`, `CONVERSATION = "project"`). Its comment marks it as a placeholder until the local interface (stage 9), not a decision;
- agents hand work on only through artifacts.

**Decision.** The maintainer's words, translated, then what each decides.
- AC-D1. A persona per agent: "each agent will need a persona, as in Habblaud, so that it does not feel like talking to a loose agent but to a person who works on something specific for us". Reverses the persona being out of scope.
- AC-D2. Memory per agent: "we will have to bring a more robust memory for the agent, in the project"; what the person and the agent said is kept for both. Reverses the replacement of agent memory by the standing instructions alone; the standing instructions stay.
- AC-D3. A conversation per agent: the person talks to each agent alone, "as if the user were the owner of the company", and gives it tasks directly. Ends the stage placeholder of one conversation per project.
- AC-D4. Agents talk to each other, with questions and tasks, "so that they have more flexibility and capacity to do the tasks without always needing the user", in the most efficient way that does not affect security and governance. The messages are carried and recorded by the runtime; no skill invokes another, so principle 4 is unchanged.
- AC-D5. No managers: "maybe each agent could be a manager and specialist"; "company hierarchies are not very efficient". A direction: each agent manages its own work within its skills and bounds. How several agents of one area share work, and what it does to governance, is designed in the plan (section 4.2) and is not decided here.
- AC-D6. A knowledge base with retrieval: agents read, analyse and learn from new content, make new documents when needed, save them for others to look up, and find what they need "without reading everything". Reverses "Indexing or RAG. It waits for a real case (D11)"; the first real case is named in the spec of package AC6, and its data stays in its project (principle 8).
- AC-D7. Fast replies, and the screen shows what the agent is doing ("looking up a specific piece of information, writing the answer"), as in a normal conversation.

**Not decided here.** Three points stay with the maintainer, each put as a question with a recommendation:
- the dated decision that L63 asks for before page and terminal lines reach the conversation lane's model route (the plan's OPEN-10, package AC0);
- the consent that would release an agent's own plan without the person's approval (OPEN-7, package AC0);
- the office (R23).

**Unchanged.** The hard limits:
- an external effect only with its exact content approved or inside a standing policy (L15);
- no credential inside a run;
- the governance records only grow (L13: approvals, tasks, runs, pending decisions), and messages between agents join them.

Autonomy is still decided by proof or by the person's consent (principle 9). Project data stays in the project (principle 8).

**Alternatives rejected.** A manager agent per area (rejected by AC-D5: a hop and a hierarchy with no gain when an agent holds the skills itself). Agents that call each other's skills directly (rejected: principle 4; the runtime carries messages instead). Keeping one conversation with the planning agent and routing everything through it (rejected by AC-D3: the extra hop is the delay the person named, AGENT-DIRECT, #977).
