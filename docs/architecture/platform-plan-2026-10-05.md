# Platform plan: the base of agents and tasks, the local interface, the site

Version 22, of 2026-10-05, checked on `main` at `17ea247`. It replaces the open stages of the earlier platform plan, which was never committed. It is the plan in force for the task runtime (`runtime/`), the local interface and the site.

## What changed from version 21

Version 22 comes from the discussion with a new agent, on another model, that assessed the architecture and the plan for the balance between effort, maintenance and quality. The architecture held. The order and four points of design changed:

1. **It starts with an end-to-end skeleton,** in place of the twelve-point rehearsal. The maintainer sees a request become two documents before any large piece.
2. **The extraction of the shared module waits until after engineering.** Before it, one file of the runtime imports the lab's runner as it is.
3. **The claim about the proof became narrower,** and the classifier of how a run ended stopped guessing.
4. **The documents on Notion became cheaper:** a medium item, not a large one.

Decisions taken in the maintainer's absence are in section 12.

## 1. Where we are

- The 48 skills have a full test. On the reference model, all 48 are `reliable`. On the floor model, 43 are `reliable`, 1 is in `watch` and 4 are in `needs a test`.
- With the skill, the reference model scored 0.979 and the floor model 0.970. Without it, 0.369 and 0.359.
- A run with the skill costs about US$ 0.010 on the floor model. The recorded cost of the reference model is fictitious: the pinned tool does not recognise the model.
- The runtime exists for one agent only, the social agent. Its code names the skills.
- The checkout the runtime uses today is at `3bee91e`, before the battery.
- The battery's runs are in the archive of the battery's runs, kept outside the repository.

## 2. Decisions this plan assumes

Taken by the maintainer:

1. The order is: the base of agents and tasks, then the local interface, and last the promotional site and the launch.
2. The floor model's provider stays DeepInfra.
3. The 5 skills that are not `reliable` on the floor model are not repaired now; they run on the reference model.
4. The early-end detector (T27) waits for the change of reference model.
5. The "7 days" of `ops-repo-baseline` is corrected at the next change of that skill.
6. The interface lives in this repository, in a folder of its own. The promotional site is another thing.
7. This plan goes into the repository, in English, in a pull request.
8. One area agent per area, each with its skills, its queue, its spend cap and its autonomy mode.
9. The central piece is the task. A flow is a set of tasks with dependencies.
10. The task board and the documents live where the project chooses: on the machine, on Notion, on Jira or on another platform. The workbench's case uses Notion.
11. The place where the maintainer interacts is the source the agents read.
12. A project is entered through a conversation with a planning agent, which uses the core's skills without modifying them.
13. The approval of a plan covers the subtasks that follow the plan.
14. The autonomy mode is set per area agent, among five modes. The default is "milestones".
15. The first real case is the workbench itself, and a real project is the second. In the repository, it appears only as "a real project".
16. Working material does not enter the public repository; the new name is a brand name; the agent that improves the tool does not change what controls it; the launch happens only with the interface finished.
17. Extra effort is accepted when it is justified by the quality of the architecture and by maintenance.

## 3. The architecture

### The rules

**1. The agent runs in the same container in which the skill was proven,** through the same entry. With no credentials, seeing only one folder.

**2. The runtime talks to the lab through one file only.** At first it is a lab facade: a file of the runtime that imports the runner as it is and calls its functions to pause on the account limit, recognise refusals and stop what a run started. Only the control of the loop is written again, and a parity test gives both the same outputs and expects the same classification. In stage 5 the facade's loop is deleted, and the lab and the runtime both call one function only. What is measurement is never shared: the variants, the baseline, the grading and the evidence lines.

**3. There is one operations layer only.** The terminal command, the conversation and the interface are shells over it. Every operation checks the hash of the project's configuration, which holds the modes, the caps and the protected paths.

**4. There is one store only,** the one the runtime already has. The new tables come in as migrations of the same file, and the contract is its functions, with one transaction per operation. There is a table of pending decisions, with a closed list of kinds (plan, question, review, effect, acceptance, your document), and one of approvals, with the three scopes the environment contract already defines.

**5. Each thing has one source.**

| What | The source |
|---|---|
| A flow | One data file per flow, in `flows/`, with the tasks and the dependencies written out. The validator checks the dependencies against the skills' required inputs and the table of owners, and checks the inventory's table of flows against the file |
| What the runtime knows of a skill | One runtime manifest per skill, with only what cannot be derived from what the skill already declares |
| The proof | What the status script already computes, per pair of model and adapter |
| The scope of an area agent | A pack of skills, in `packs/` |

**6. The platform owns only what a person edits.** On a task: title, text, state and comments. The rest stays in the runtime's store and is shown on the platform.

**7. The task board and the documents are providers, like the others.** The task board uses the issue-tracker class the contract already lists; the documents use a class the resolver already knows how to find by its name. The new row of the class table goes in together with the first change of the router, so that the router is tested once.

### What the proof covers, and what it does not

The battery measured one skill, in one run, with an input in the form of the cases. That holds for the runtime, because the container and the entry are the same.

What the runtime adds was not measured: resuming a task with the person's answers in the request, and running a skill on a document another model wrote. For those the only check is field evidence, recorded from the first task.

The runtime uses the band of the proof file after checking two things: that the measurement files in the checkout are the recorded ones, and that the image is the evidence's. If either fails, the skill runs on the reference model and without autonomy. The image is of one platform only, so on a machine of another architecture the skills run as unproven.

A skill runs in the condition in which it was measured. Of the 11 that require the web, 5 have cases with the web. The two brand skills the first case uses get one case with the web each, which costs only the runs of that case.

### One mode of execution

Every run is contained. The social agent, which reads text written by strangers, moves to the container last, in stage 7, when the policy approvals and a key with a cap exist. Until then it stays as it is, receiving repairs only. The new tables live in the same database, so there are not two runtimes.

| | Today, read-only on the person's machine | In the container |
|---|---|---|
| What a malicious comment reaches | The files the tool lets it read on the person's machine | Only the copy with that area agent's documents |
| What the model can do | Read and reply | Read, reply and run commands in the container, with no credential |
| What it can spend | Only its own run | It can call the provider in a loop. Limited by: the maximum time and a key of the runtime's own, with a cap |
| Where something can leave | Only through the reply | Through the reply, and through the two hosts of the model providers |
| Proof | None through that entry | The battery's, with the same task text as the measured cases |

### Limits that live in code

Each limit has a test with its name.

What enters:

1. Every run starts from a new copy, with the skills installed again from the fixed checkout.
2. What enters: the versioned files, the project's documents, the machine files the skills use and what the person handed over through the file drop. No other file outside git enters. The store and the runtime's configuration never enter.
3. A task with the web receives only the artifacts the skill declares. Web and code together: allowed in a public repository; in a private one, with the person's approval per task.
4. The tool's configuration files are removed at any depth.
5. The project's `AGENTS.md` enters when the skill declares it. The two lines of the workbench section that the container cannot serve leave in a base commit, undone on the way back.
6. No credential enters the container.

What comes back:

7. The destination of each file comes from a path rule: the state file through the merge; documents bound to an approval and data files as machine files; the other texts as documents; what is versioned as a change set. The rest does not come back and is listed for the person.
8. Only a regular file, with its real path inside the copy.
9. Code comes back as a change set, and the commit is one, made by the code provider with the git and the signature the person already uses.
10. The state file comes back through a merge made by one module only. Of a run it accepts drafts of the skill that ran, decisions attributed to it and new questions. Only code writes what is the person's: the person's answer, "approved", the autonomy mode and the approval rows.
11. A working document never enters a commit.
12. What comes back does not overwrite what changed at the origin.
13. A record only grows.
14. Everything passes the credential scan before it leaves.

What authorises:

15. An external effect is executed by code, with the exact content approved or inside an approved policy.
16. A skill with a confirmation gate runs up to the gate. What it shows there is what the person approves.
17. The approval lives in the approvals table. The rows in the state file are generated copies.
18. A document bound to an approval by hash is a machine file.
19. The planning agent creates no task: it returns the route, and code builds the plan.
20. The measurement files are not changed.

### How code knows how a run ended

First the failures, with the lab's functions: timeout, refusal by the provider, refused credential, failure of the adapter and early end.

Then the ending: done, question, draft with questions, confirmation gate, or blocked on a missing input. The classifier never guesses. What it does not recognise becomes "unclassified" and reaches the person with the whole reply. It is tested against the archived runs of the battery, in which the guards already say which ones stopped to ask, without spending on a model.

Resuming after a question is a new run, on a new copy, with the request and the answers in the text.

## 4. How work moves

### The human flow

1. The person says what they want, in the conversation or by writing a request on the task board.
2. The router returns the route. The questions of scope belong to each skill and arrive when its task runs.
3. Code builds the plan: the tasks, the dependencies, the milestones, the limits and the estimate.
4. The person approves, adjusts or cuts.
5. Code creates the tasks, and each one runs when it becomes ready.
6. The person reads, comments on and edits the deliveries where the project keeps them. Questions and approvals arrive as pending decisions.
7. The person asks for progress, and the answer comes from the records.

Most tasks cost two runs and one answer from the person, because the skills stop to ask. That is why the surface that matters most is the list of pending decisions, and the interface starts with it.

### The states of a task

Requested, planned, ready, running, waiting, blocked, done, failed, cancelled. "Waiting" always points to a pending decision. Releasing is not approving: a delivery released by the area agent's mode stays a draft.

### How a request becomes tasks

At first, the minimum: one run of the router asking only for the route. Code reads only the route line and checks the name against the flow files and the area agent's pack. Anything else stays unclassified, and the person chooses. The router's questions become pending decisions. The router can be skipped by naming the flow.

In stage 6 these come in: several deliveries listed in one request, the brief of `core-clarify`, the subtasks and the memory of the conversation.

The router was measured returning only the route to one skill. For a flow, it gets a new case, which costs only its runs.

### Documents on a platform

What the person edits there is what the agents read. The cheapest design that guarantees it:

- **An edit replaces the whole document.** There is never a merge.
- **The read happens only when the page changed.** While the person does not edit, the run reads the text the previous run wrote. That way the conversion does not wear the document down at every task.
- **The person's edit passes the skill's checker** before it counts. If it breaks, the person receives the reason.
- **The write happens only when the content changed,** and the open comments are saved first, as requests for review, because replacing the page would delete them.
- **Fidelity is required in one direction only:** what goes and comes back must pass the skill's checker, tested without the network on each skill's document template. It is not required to come back identical.
- **Each type of document enters by choice, in the skill's runtime manifest.** What does not pass the test stays read-only.

Rules for an external platform: only code talks to it; a task runs only if the person created or accepted it; writing to it is an external effect, covered by a standing approval with bounds; the approval of an effect stays in the runtime's pending decisions.

### The autonomy modes

| Mode | When the person reviews the deliveries | External effect |
|---|---|---|
| Stopped | The area agent takes no task | Nothing runs |
| Supervised | Every delivery | Always asks for approval |
| Milestones | Only those marked as a milestone | Always asks for approval |
| Autonomous | The set, at the end | Always asks for approval |
| Autonomous with a policy | The set, at the end | Runs alone inside an approved policy |

Underneath there are three facts: whether the area agent is enabled, one of the three values the state file already has, and whether a standing approval is in force. The default is "milestones". Some deliveries are a mandatory milestone in every mode: those the next skill accepts only with the person's approval written inside the document, such as the themes of the calendar and the design direction.

### Other rules

- **One task at a time, per project.** The skills write to common files.
- **Area agents communicate through the task layer:** the document, a note on the next task, a proposal of a task.
- **An area agent is a scope:** a pack of skills, the queue, the cap and the mode. No persona text.
- **Two currencies of spend:** dollars on the floor model, with a key of the runtime's own and a cap; runs per day on the reference model.
- **The dispatcher is a function,** called by the system's scheduler and, later, by the interface's service.

## 5. The first case: the workbench itself

- **One project only:** a checkout of the workbench dedicated to the work, with the documents outside git. Only code goes to the public repository, through a pull request.
- **Two checkouts:** the work checkout, and the one the runtime uses to run itself, fixed on a revision the maintainer reviewed.
- **`AGENTS.md` is a protected path in this case.** The skills that work on the code receive the real file; the others that declare it receive only the workbench section.
- **The first engineering tasks stay outside what controls the agent.** The rest of the installer serves.
- **The name** must be free on every platform at once. Inside, `docs/workbench/`, `WORKBENCH_ROOT` and the names of the skills do not change.

| Delivery | Skills | Stage |
|---|---|---|
| Market and positioning | `biz-market-analysis`, `biz-icp-positioning` | 1 |
| Brand strategy, name, identity, voice and guide | The five brand skills | 3 |
| The rest of the installer | The engineering skills, and `ops-pull-request` up to the gate | 4 |
| The campaign and the site | Message, calendar, posts, design, site, publication | 10 |

## 6. The stages

Sizes: S, M and L.

### Stage 0. Prepare

| # | Item | Size |
|---|---|---|
| 0.1 | This plan in the repository, in English, with the names of section 10 and the backlog items R2, R3, R4, R8 and R11 amended | S |
| 0.2 | A sentence in `AGENTS.md` and in the reliability model: another model's band decides where the runtime may run a skill. And the paragraph on the two records of approvals corrected | S |
| 0.3 | The list of what leaves at the change of model, in backlog item T23 | S |
| 0.4 | With the maintainer: advance the checkout the runtime uses, schedule the social agent again, copy the archive of the runs off the machine and remove the old proxy containers | S |

### Stage 1. The end-to-end skeleton

It is what shows the thing working, and it is also the feasibility rehearsal.

| # | Item | Size |
|---|---|---|
| 1.1 | The lab facade: a file of the runtime that imports the runner and runs a skill in the container, on a copy of the project | M |
| 1.2 | Three new tables in the store: task, run and pending decision | S |
| 1.3 | A flow file with two tasks and the dependency written: market, then positioning | S |
| 1.4 | A terminal shell: request, run the next, answer, release | S |
| 1.5 | The documents come back to a local folder, by the path rule. Only the reference model | S |

In parallel, without depending on the skeleton:

| # | Item | Size |
|---|---|---|
| 1.6 | The Notion test: the document templates of three skills go and come back, and pass each one's checker | S |
| 1.7 | The classifier's corpus, taken from the archived runs | S |

Done when: the maintainer requests, the two tasks run in a chain, the maintainer answers and releases from the terminal, and the two documents appear. What the skeleton shows wrong in the design is corrected before stage 2, and the runtime contract is rewritten there: it is the design document.

### Stage 2. Harden

| # | Item | Size |
|---|---|---|
| 2.1 | Limits 1 to 8, 10, 12 and 14, each with its test; the merge of the state file | L |
| 2.2 | The classifier of endings, total, with the test against the corpus | M |
| 2.3 | The proof file, the two checks and the routing by it | S |
| 2.4 | The project's configuration and its hash; the operations layer, with the terminal shell over it | M |
| 2.5 | The runtime manifest per skill, in `skills/<name>/evals/`, required by a test for the skills of the packs in use | S |
| 2.6 | The `runtime/` folder wired to CI, to the hooks, to the code owners file and to the description of the repository | S |
| 2.7 | The use and the verdict through the recorder that already exists; the key with a cap for the floor model | S |
| 2.8 | Tests without a model that hold the runtime to the text of the skills it depends on | S |
| 2.9 | The effect of the project's `AGENTS.md` on the two adapters, measured | S |

### Stage 3. The brand, with the task board on Notion

| # | Item | Size |
|---|---|---|
| 3.1 | The task-board provider for Notion, and the local one; the contract tests | M |
| 3.2 | The minimum step of the router, and a new case of it: only the route, for a flow | S |
| 3.3 | The `flows/` folder, linked to the validator, and the flow file of the brand | M |
| 3.4 | The documents on Notion, as section 4 describes | M |
| 3.5 | A case with the web for `brand-strategy` and another for `brand-identity` | S |
| 3.6 | The mandatory milestones and the file drop, which the logo uses | S |

Real case: the maintainer requests the workbench's brand. The tasks appear on Notion; the maintainer edits the strategy there, and the name task reads the edit.

### Stage 4. Engineering, from the change to the pull request

| # | Item | Size |
|---|---|---|
| 4.1 | The dependencies installed by code, in the same image, in a step without a model; and again when a run changes the dependency files | M |
| 4.2 | The change set and the refusal of a working document's path | M |
| 4.3 | `ops-pull-request` up to the gate. First, recovering the file it writes there is tried; if that does not work, it gets a measured runtime mode, which costs its test | S |
| 4.4 | The pending decision of an effect, with the hash of the content; the code provider with removal in the commit and a verb to open the pull request | M |
| 4.5 | The protected paths checked on the change set | S |

Real case: the rest of the installer.

### Stage 5. The extraction

| # | Item | Size |
|---|---|---|
| 5.1 | The lab and the runtime both call one function only for one attempt of a run. The facade's loop is deleted. The runner loads the module only when it runs a run, because three cases of `core-skill-creator` carry it alone | L |
| 5.2 | T25: the regrading respects the turn and the pause, which touches the same functions | S |

Done when: the lab's tests pass, a trial test of one skill gives the same result before and after, and the runtime no longer has a loop of its own.

### Stage 6. The full planning agent, the dispatcher and autonomy

| # | Item | Size |
|---|---|---|
| 6.1 | Several deliveries in one request, the brief, and the subtasks inside the plan's limits; the tasks of the product's backlog, read with the script that already exists | M |
| 6.2 | The progress and the summary of a period, computed | S |
| 6.3 | The dispatcher: the function, and the scheduler's two jobs, with the check that everything runs on the system's Python | M |
| 6.4 | The autonomy modes per area agent; the approved policy in the approvals table, with the state file's row generated and the limits per day counted in the store | M |
| 6.5 | The conversation with the planning agent in the terminal | S |

Real case: the weekly routine that lists the published posts (PB16).

### Stage 7. The social agent in the container

| # | Item | Size |
|---|---|---|
| 7.1 | The port behind a handler: the tick, the vote step and the scheduled publication | L |
| 7.2 | The switch to the container, with the restrictions of section 3. The maintainer schedules again | M |
| 7.3 | After a real week: delete the read-only script, the three scripts of the old runtime with their tests, and the API adapter | S |

### Stage 8. The skills the cases ask for

They move alongside, as the cases advance. Each one gets its runtime manifest in the same pull request, its first full test and its baseline on the floor model.

| Skill | Case |
|---|---|
| `biz-validate-idea`, `biz-business-model`, `biz-gtm`, `biz-business-plan` | A real project |
| `mkt-launch-plan`, `mkt-landing-page` | The workbench, in stage 10 |

### Stage 9. The local interface

| # | Item | Size |
|---|---|---|
| 9.1 | The local service: the operations layer through an API, with a token and an origin check, calling the dispatcher | M |
| 9.2 | The list of pending decisions, with one card per kind | M |
| 9.3 | Projects, tasks and area agents | M |
| 9.4 | The project's conversation | L |
| 9.5 | Skills, costs and connections, with the reference model's cost recomputed | S |

### Stage 10. The site and the launch

| # | Item | Size |
|---|---|---|
| 10.1 | The flow file of the launch, with what it is the first to ask for: a flow that includes another, and the task in which the maintainer writes the document | M |
| 10.2 | The two new marketing skills | M |
| 10.3 | The static site, with the proof table | M |
| 10.4 | What someone from outside installs: the interface and the runtime, with the published image, and the skills listed in the registries | M |
| 10.5 | The campaign: the posts approved by the maintainer and published by code | S |

## 7. The cost in tests

The base is the battery: about 0.3 points of the weekly limit per skill.

| What runs | Points of the week |
|---|---|
| Three new cases: two brand cases with the web and one of the router | 0.2 |
| The three cases of `core-skill-creator`, after the stages that edit the files they carry | 0.5 |
| `ops-pull-request`, only if it needs the runtime mode | 0.3 |
| 4 business skills, with the baseline on the floor model and the router | 1.5 |
| 2 marketing skills, with the baseline on the floor model and the router | 1.0 |

In total, between 3 and 3.5 points, near a fifth of the battery. Nothing redoes the 48, and no measurement file is edited.

## 8. Parked, and what brings it back

| What | Comes back when |
|---|---|
| Moving the documents from one implementation to another | A project changes platform with documents already made |
| A third model, and the status with more than two levels | There is demand |
| The flows as skills, for whoever uses an interactive tool | Someone needs them outside the runtime |
| Tasks in parallel in the same project | The single queue delays the work |
| Synchronising a branch with the base through the runtime | It is missed; it asks for a verb of the provider that redoes the merge |
| Starting a code project with dependencies from zero | The next case asks for it |
| Approving an external effect through the task board's platform | The maintainer asks for it |
| Persona text per area agent | A case shows a gain; it would have to be measured |
| Implementations for Jira, Confluence and others | A real project uses the platform |
| An image provider, and the step of the code that calls it | Generating through the file drop gets in the way |
| Tests on GitHub, attested evidence, external skills and the two badges | There is an audience, or at the change of reference model |
| An always-on server outside the maintainer's machine | The maintainer chooses the host |

## 9. What leaves at the change of model

Workarounds for files that cannot change now. Each one is marked in the code, and the list goes into backlog item T23.

| The workaround | What it lets be deleted |
|---|---|
| Dependencies installed outside the image | The install step |
| The request passed as one argument only in the floor model's adapter | The forced summary of the conversation |
| The reference model's cost recomputed | The recomputation |
| Removing two lines of `AGENTS.md` in the copy | The base commit |
| Copying the approvals into the state file | The copy, with the policy checker reading the runtime's record |
| The runtime manifest per skill outside the frontmatter | The stable part goes into the skills' frontmatter |
| The skill runs only up to the gate | A runtime mode in the skills with an external effect |
| Six skills that require the web run without the web | The restriction, with cases with the web in the next battery |

## 10. The names

| Concept | What the word already means in the repository | Name used |
|---|---|---|
| Backlog (where tasks are kept) | The workbench's own tasks, and the product-backlog artifact | Task board |
| Pending items and the delivery folder | The table of items of the store, and a marketing artifact | Pending decisions; file drop |
| Agent | The delegation persona in `agents/` | Area agent |
| Flow | A kind of skill | Flow file, for the data file |
| The per-skill manifest | `runtime.json` is already the project's configuration | Runtime manifest, `skills/<name>/evals/runtime-manifest.json` |

## 11. Risks

| Risk | What limits it |
|---|---|
| The contained mode does not work as designed | The skeleton is the first thing built |
| The lab facade and the runner diverge before the extraction | The parity test; the facade only duplicates the control of the loop |
| The classifier gets the ending of a run wrong | It does not guess; it is tested against the archived runs |
| Resumptions and chains were not measured | Field evidence; the milestones, where the person reviews |
| A run forges an approval or a decision of the person's | What is the person's in the state file is written only by code |
| The agent improves the tool and alters what controls it | A fixed checkout; the result is a pull request; the protected paths |
| Working material leaks into the public repository | The exclusion list in the copy and the refusal on the way back |
| The conversion with Notion damages a document | The read only when the page changed; the skill's checker; the test per type of document |
| The social agent in the container | It comes last, with a key with a cap; the old script stays until the real week |
| The campaign claims more than the proof supports | The message reads the proof file, and section 3 says what it does not cover |

## 12. Decisions taken in the maintainer's absence

The plan's author followed their own recommendation, as the maintainer asked. All of them are decisions of the plan; none changed the repository.

| # | Decision | Why | How to undo |
|---|---|---|---|
| 1 | One mode of execution only; the social agent goes to the container, last | Today it reads the maintainer's machine and has no proof; in the container both are solved. The trade is in the table of section 3 | Keep the read-only mode |
| 2 | The lab facade first, and the extraction in stage 5 | The part the runtime needs is mixed with the code that writes evidence; extracting before knowing what is shared put the lab at risk | Extract first |
| 3 | The skeleton in place of the twelve-point rehearsal | The maintainer sees it work early, and what it shows corrects the design before the large pieces | Go back to the rehearsal |
| 4 | Dependencies written in the flow file and checked, not computed | Only 69 of the 174 inputs could be computed | Compute |
| 5 | Task board and documents as providers from the start | One provider mechanism only, with no extra test cost | A mechanism of the runtime's own |
| 6 | The store's functions as the contract | One transaction per operation | Go back to the verbs |
| 7 | Code comes back as a change set; synchronising a branch stays out | The final commit is made again with the maintainer's signature, so the history made inside does not survive | A merge verb in the provider |
| 8 | Delete the API adapter in stage 7 | Its only entry stops existing. It was the maintainer's work, so it waits for the maintainer's look | Keep it |
| 9 | Park the third model | It was the author's recommendation, with no demand | Reopen |
| 10 | One more case with the web for two brand skills, and a case of the router | They cost a few runs and remove two restrictions of the first case | Do not add |

Still the maintainer's, when the time comes: which Notion base receives the project; where the site is hosted; where the copy of the archive of the runs is kept; and, for a real project, its boundary with a sister product and its repository.

## 13. How this plan was reviewed

- Two independent reviewers read the plan against the code: one for correctness and security, in five passes; another for architecture and maintenance, in three.
- A third agent, on another model, assessed the architecture and the plan and discussed five points with the plan's author. They agreed on all of them. On the only one where it proposed the opposite of a decision of the maintainer's, the one-way mirror of the documents, the author kept the maintainer's decision and the agent helped make the design cheaper.
- What no review on paper settles is what depends on running. That is why the first stage of construction is the skeleton.

## 14. Verified and not verified

Verified in the code, by the plan's author and by the reviewers: the numbers of section 1; that the executor mounts only the run's folder; that the pause on the account, the refusals and the ending of processes are in the runner, which is not a measurement file; that the runner's retry loop is mixed with the grading; that the container's network reaches only two hosts; that the router has the rule of returning only the route, measured for one skill; that the cases of the runtime mode were measured through the container's entry; that 22 skills declare `AGENTS.md`; that the resolver finds an integration class by the name of its folder; that the store runs one process per command; that the code provider has no pull-request verb and no removal in the commit.

Not verified: everything that depends on running; whether the battery's archive keeps the grading of each run; whether the runner imports on the system's Python; how Notion reports the version of a page; whether an added case costs only its runs; how much work the extraction asks of the runner's tests.
