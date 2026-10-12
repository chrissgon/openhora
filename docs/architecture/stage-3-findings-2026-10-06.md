# What the acceptance of stage 3 showed (2026-10-06)

Stage 3 of the platform plan (`platform-plan-2026-10-05.md`) put the tasks and the documents of the task runtime on the project's platform (a task board and a documents platform, each reached through a provider), added the router step and the plan a person approves, the brand flow, the file drop and the milestones a manifest makes mandatory. Its acceptance asks for the workbench's own brand: the request is routed, the tasks appear on the board, the person edits the brand strategy on the platform, and the name task runs on a copy that holds that edit. This file records what that acceptance and the live measurements before it showed.

It holds counts, kinds, endings, durations and token counts only: no content of a document, no answer, no identifier of the workspace and no path of the machine. The maintainer was away and had delegated supervision: every act the plan gives the person on the platform that was made was made through the platform's API by the executor, and is marked so.

## The live service, before the acceptance

The ten measurements of WP-3.10 (step 4) are recorded in the two providers' `README.md`, "Measured on the live service" (#169). One of them changed the design:

| Measurement | Observed | What it changed |
|---|---|---|
| N3 | A comment does not move a page's version (its last-edited time, rounded to the minute) | The contract said the version changes when the comments change, and the mirror read a page only when its version changed, so a new comment on an unchanged page was never saved. Decided by the supervisor on the maintainer's delegation: the version covers the content, and the comments are listed apart. Built in #171 (WP-3.15): a verb `comments --id` in both classes, called for every mirrored document and every board item at every pull, one call each, whatever the version; the comments on a page's blocks still come with the read |
| N4 | A comment on a block is listed under that block only | Fixed in #169: a read lists the page and every block |
| N8 | A row in the trash answers 404 for its body | Fixed in #169: a trashed row is read as archived, with no text |

Still to be measured by hand, by the maintainer, because the API cannot make the act or the measurement used the API instead: N5 (whether a resolved comment is listed), N10 (a page that exists and was not shared with the integration), and the by-hand variants of N1 (an edit in the app), N3 (a comment in the app), N4 (a comment on a paragraph in the app) and N8 (archiving a row in the app).

## Before any model call

| Check | Observed |
|---|---|
| The real base | It had no text property for the runtime's shown fields and its state property is a status with three options, which the API cannot extend. Added through the API: a text property and a select property with the nine task states as options; the configuration's `fields` points the title, the state and the shown fields at them. The base's own status property was left untouched and is never written |
| The acceptance checkout | Advanced to the central branch holding #171; clean |
| The eval image | The evidence's digest |
| The store | Migrated to version 4 by the first command of the advanced checkout |
| A configuration not accepted yet | `status` refused, exit 3, naming both hashes; `accept-config` accepted it |
| `sync --dry-run` | 1 s; would create 6 board items and 2 pages, read nothing, wrote nothing |
| `proof` (no model call) | The router, `brand-strategy` and `brand-name`: tier `floor`, proven, `reliable` on both models, both checks passing, key `lab` |
| `scripts/select_skills.py` on the system's Python 3.9 (O6) | Runs: `--pack brand` printed the five brand skills, exit 0 |

## The runs

| Run | Task | Skill | Tier | Key | Ending | Right? | Pending | Duration (ms) | Tokens |
|---|---|---|---|---|---|---|---|---|---|
| 11 | the request (route) | core-orchestrator | floor | lab | unclassified (no route line) | the route was right, its form was not a route line | question "The route was not recognised", then cancelled by `route --flow brand` | 213,769 | 215,313 |
| 12 | strategy | brand-strategy | floor | lab | question | yes: it wrote nothing and asked | question, left open | 96,138 | 94,851 |

Both runs: `ok` on the first attempt, `skill_loaded` 1, no value replaced in what they left, a use recorded, the image the evidence's. Run 11 entered the general copy (1,302 files, seven left out: three work-data files, the project's `AGENTS.md`, the runtime's configuration and two files the credential scan flagged), kept the state file it changed (a route-only run returns no file) and brought nothing back. Run 12 entered its declared artifacts (3 files, the workbench section of `AGENTS.md`) and changed nothing. Total: 2 runs, 309,907 ms of model time, 310,164 tokens.

## What the platform showed

| After | Board | Documents |
|---|---|---|
| `approve`, then the first `sync` (125 s) | 12 rows created: the request and its five tasks (strategy `ready`, the others `planned`) and the six requests and tasks of stages 1 and 2 (`done`) | 2 pages created, the two business documents of stage 1 |
| run 12, then `sync` (12 s) | 1 row written (strategy `waiting`); 0 read; 0 comments | nothing read (versions unchanged), nothing written; 0 comments |

On every row the base's own status property reads the platform's default for a new row, since the runtime does not write it.

## Findings

| # | Finding | Kind | What it asks of the design |
|---|---|---|---|
| 1 | The stage's real case could not be completed. The brand strategy of a company needs the positioning document (`brand-strategy`, Stop rule 2), and stage 1's case left it unwritten because the job the offer does is not decided. The strategy run stopped and asked two questions: positioning first, and which platform the brand speaks on. The facts the answers come from settle neither, so the question was left open and no second run was made. Steps 6 and 7 (the person's edit of the strategy on the platform, a comment, and the name task reading the edit) were not run | plan precondition not met (a decision of the maintainer) | The maintainer decides the job (so that the positioning can be written) and the platform, then the acceptance resumes at step 5. The router saw the same gap in its own reply |
| 2 | The router named the brand flow but wrote its route line in backticks with extra words (`flow, pending`: its routing table lists the brand flow skill as planned), which is not a route line by design; the run ended `unclassified` and the flow was named with `route --flow brand`, as step 3's table says | as designed (lab case 9 measures the strict form) | None now. If a router run writes this form again, a tolerant reading of a route line is a runtime package of its own |
| 3 | The board mirrors every task of the store, so the six requests and tasks of stages 1 and 2 appeared with the six of this request; step 4 expected six items | plan text | Step 4 expects every task of the store. Whether a board should receive only the requests made after it was configured is a decision for the maintainer |
| 4 | The base's own status property has three options and the API cannot add any, so the runtime's nine states live in a select property of their own; the person's status is not written and holds the platform's default | as designed (decided before the acceptance) | A coarse mapping of the nine states onto a board's own status property is a backlog item for the maintainer to decide |
| 5 | A run copy holds no platform reference. The brand skills read `shared/references/platforms/<platform>.md` once the platform is known; the lab gives a case those files through its `platforms` key, and the runtime stages the skill's folder only. Run 12 stopped before that step, so nothing failed; read in the run copy, not observed as a failure | runtime gap, not yet hit live | Before a brand run that names its platform: a runtime package that stages the platform references a skill cites (the folder is small and read-only). Open point O7 says to stop and ask when a run reports the reference missing |
| 6 | Run 12 reported that the market analysis named in the request was not in its copy: it is not a declared input of the strategy skill, so limit L3 left it out | as designed | None |
| 7 | A `sync` with nothing to write still makes one call per board item and per mirrored page to list their comments (#171): 12 s for 12 items and 2 pages. The first `sync`, which created 12 rows and 2 pages and read each page back, took 125 s | as designed | The cost grows with every task the store holds (finding 3). If a sync becomes slow, the board's comments can be listed only for tasks that are not final |

## Open points of part 3 that this run answered

| # | Open point | Observed |
|---|---|---|
| O1 | The behaviours of the live service | Recorded in the providers' `README.md` (#169); N3 changed the design (#171) |
| O2 | Whether the router answers the route-only text with exactly one route line | Not on the floor model in this run: the flow was named in a non-strict form (finding 2) |
| O3 | What the router does to the state file in a route-only run | Its reply says it added an open question; the runtime kept the file (class `state`) and wrote nothing to the project |
| O6 | Whether `scripts/select_skills.py` runs on Python 3.9 | Yes |
| O7 | Whether a brand run can read the platform reference its skill cites | Not reached by the run; the run copy holds none (finding 5) |
| O8 | What the voice skill does for a company with no profile | Not reached |
| O9 | Whether a run treats a handed-over file as intended | Not exercised: no file was handed over |
| O10 | Whether an edit made within the minute of the runtime's write is seen | Not exercised: no edit was made (finding 1) |
| O11 | How long a `sync` takes on the real base | 1 s dry, 125 s creating, 12 s with nothing to write (finding 7); calls not counted |

## What was not run

- Steps 6 to 8 of the acceptance: no edit and no comment on the platform, so the round trip of an edit and of a comment was not shown live (finding 1). The comment path of #171 is covered by its offline tests only.
- No lab test, no `eval_run.py`, no docker build, removal or `ensure`.

## Due at the end of this stage

Section F of part 0 of the execution plan (outside the repository) is amended to state what stage 3 built: the modules `router.py`, `plan.py`, `board.py`, `documents.py` and `drop.py`; store migration 4; the configuration keys of `task_board` (`provider`, `base`, `fields`, `states`, `dir`, `expires`) and `documents` (`provider`, `parent`, `dir`, `expires`); the operations `route`, `approve`, `reject`, `hand_over`, `sync` and `answer(..., with_comments)`; the verbs of both classes with `comments`; and the rule that a version covers the content.

## The real case, resumed on 2026-10-06

The maintainer decided, later the same day, the job the offer does, the first audience and the brand's platform, and answered the five choices the strategy asked for; the brand name stays his to choose. The acceptance resumed from finding 1 with the acceptance checkout advanced each time to the central branch then current (the store migrated to version 5 by the first command of a checkout holding it; no migration after it). The image was the evidence's each time; nothing was built. As above, counts, kinds and endings only.

### The positioning, through a one-skill plan

The runtime has no option that names one skill for a request. A plan of one skill is built when the router's route line names a capability, so the positioning was asked as a request with no flow and routed. The router answered with one strict route line naming `biz-icp-positioning` (O2: the strict form, this time), and its plan of one task was approved by its hash. The skill first stopped on its own stop rules and asked five numbered questions; the answers came only from the facts the maintainer recorded, with the narrower segment kept open as he asked; its second run wrote `docs/business/positioning.md` and updated the customer profile, ending `draft_with_questions`, released as it stood. Both documents were pushed to their pages by the run.

### The strategy, the person's edit and comment, the name

| Step | Observed |
|---|---|
| The strategy, again | First run: `question`, its stop rule refused "keep them open" for five choices (label, pillars, rhythm, numeric targets, the public product to measure), each with a recommendation. The maintainer answered the five. Second run: `draft_with_questions`, `docs/brand/strategy.md` written and pushed as a new page; released |
| The platform reference (O7) | The run copy held the platform's reference and data file under the staged skill (#173), and the reply cited what the reference says: read |
| The person's edit and comment | The maintainer appended one sentence to the strategy page and added one comment, in the app, by hand. The next `sync` imported the page (1 imported, 0 rejected, 0 conflicts) and saved 1 comment. The project's file holds the sentence once; against the run's own text the trip changed 6 diff lines (the sentence, three blank lines, one nested item's indent), and no text was lost. The comment was saved `open`; it enters a prompt only through `answer --with-comments` (choice T3) |
| The name reads the edit | The name task's run copy held the sentence (count 1): what the run saw holds the person's edit, the proof the stage asks for |
| The name, first round | `draft_with_questions`: 10 candidates checked with the skill's script, none chosen, 5 questions; released with the choice left open |
| The name, second round | The maintainer rejected the first round. A new request with no flow was routed to `brand-name` by one strict route line, its one-task plan approved; the run ended `draft_with_questions`: 10 new candidates checked with the script (the first round's dropped), 12 more names set aside, the brand's platform listed by the script as a place to check by hand, 7 questions; released with the choice left open |
| The identity | `question`: its stop rules 2 and 3, four questions; the facts settle only the platform. Left open: the answers are the maintainer's |

### The runs since the resume (13 to 23)

| Run | Task | Skill | Tier | Key | Ending | Right? | Duration (ms) | Tokens |
|---|---|---|---|---|---|---|---|---|
| 13 | route | core-orchestrator | floor | lab | done (one strict route line, a capability) | yes | 65,704 | 99,001 |
| 14 | positioning | biz-icp-positioning | floor | lab | question | yes | 200,811 | 151,925 |
| 15 | positioning | biz-icp-positioning | floor | lab | draft_with_questions | yes | 509,520 | 995,731 |
| 16 | strategy | brand-strategy | floor | lab | question | yes | 334,938 | 225,411 |
| 17 | strategy | brand-strategy | floor | lab | draft_with_questions | yes | 185,359 | 636,301 |
| 18 | name | brand-name | floor | lab | draft_with_questions | yes | 573,362 | 1,081,540 |
| 19 | identity | brand-identity | floor | lab | question | yes | 123,575 | 166,348 |
| 20 | voice | brand-voice | floor | lab | failed, `internal`, before the model | no: a runtime defect (finding 9) | 0 | 0 |
| 21 | route | core-orchestrator | floor | lab | done (one strict route line, a capability) | yes | 294,632 | 813,902 |
| 22 | name, second round | brand-name | floor | lab | draft_with_questions | yes | 341,442 | 818,165 |
| 23 | voice, retried after #201 | brand-voice | floor | lab | blocked | yes: it stopped on its missing input (O8) | 108,852 | 420,726 |

Every run that started: `ok` on the first attempt, no value replaced in what it left, a use recorded. Total: 11 runs, 10 of which called a model (run 20 failed before it), 2,738,195 ms of model time and 5,409,050 tokens. Every run went to the floor model with the lab's key, each skill proven.

### What the platform showed

| After | Board | Documents |
|---|---|---|
| the strategy written, then `sync` (17 s) | 4 rows written (the strategy `done`; name, identity, voice `ready`); 0 read; 0 comments | the strategy page written by the run's own push; 4 pages |
| the person's edit and comment, then `sync` (57 s) | nothing written | 1 page imported, 1 comment saved, 0 rejected, 0 conflicts |
| the second name round, then `sync` (22 s) | 5 rows written; 0 read | nothing imported; the name page replaced by the run's own push; 5 pages |
| run 23, then `sync` (15 s) | 1 row written (the voice `blocked`) | nothing |

At the end, by the store's mirror records: 14 rows (10 `done`, 2 `planned`, 1 `waiting`, 1 `blocked`) and 5 pages (the three business documents, the strategy and the name).

A request and its one task that started and finished between two syncs were never mirrored: the first board sync of the advanced checkout recorded the board as configured, and they were final before it (#175, as designed); every later sync reported `left_out_final` 2.

### Findings of the resumed case

| # | Finding | Kind | What it asks of the design |
|---|---|---|---|
| 8 | The person's edit was read by the next runs as content written by someone else: the name and identity runs (and the router of the second name round) listed the maintainer's appended sentence under "Instructions found in external content", not followed. The runtime handed the edited document over with nothing that says the person wrote it | runtime gap | Fixed in #201 (WP-4.12): when a `sync` imports an edit of a document, the next run of a task that reads that document gets one line written by code, next to where answers are placed, saying the person edited it on the platform and that its content is theirs; once per import, never from a run's own text. Not yet observed live: the import that would show it came before the import record existed |
| 9 | The voice task failed before any model call, kind `internal`: a task without the web gets the general copy, and its change set required a clean tracked tree; the project carries uncommitted tracked changes (the workbench's own section and ignore lines), so the task could not start. The route runs, which return no file, never hit it; the guidelines task would have | runtime defect | Fixed in #201 (WP-4.12): the clean-tree check and the change set apply only to a task whose skill belongs to a code area, never to a document task. Retried after #201 (run 23): the task ran on the same project with its uncommitted files, no change set was made, and it ended on its own stop rule: the defect is gone |
| 10 | A run's state merge refuses decision lines the run attributes to the user and the rewording of an open question; after the positioning's answer, the state file still listed the job as open although the answer, written by code, decided it | design gap | A small runtime package: the answer that settles an open question closes it, by code. Deferred |
| 11 | The second name round was routed as a new request to one capability; a rejected delivery has no "do it again" of its own | as designed | None now |

### Open points of part 3, resumed

| # | Open point | Observed |
|---|---|---|
| O7 | Whether a brand run can read the platform reference its skill cites | Yes, since #173: the strategy's reply cited it |
| O8 | What the voice skill does for a company with no profile | Run 23 ended `blocked` with nothing written: it opened with the skill's "Nothing was written" form, named the missing person's profile (its stop rule 1) and the skill that writes it, noted that skill is scoped to a person and not a company, said the missing piece is the brand's own writing samples and a voice direction, and asked which way. As the acceptance script expected; the skill was not edited. How a company brand gives the voice its material is the maintainer's to decide |
| O9 | Whether a run treats a handed-over file as intended | Not exercised: no file was handed over |
| O10 | Whether an edit made within the minute of the runtime's write is seen | Not exercised: the edit came about 20 minutes after the write, and it was seen |
| O11 | How long a `sync` takes on the real base | 17 s with board writes only; 22 s with five board writes; 57 s for one that imported a page and saved a comment; 15 s with one board write; calls not counted |

### What waits for the maintainer

- The brand name: the choice among the second round's candidates, and its open questions (who owns each place already registered, which networks, a fallback handle, a trademark search).
- The identity's answers (the first piece, a design system and where it lives, how pieces are produced); the identity task waits on them; the voice task is `blocked` on the material above; the guidelines task stays `planned`, since it depends on both.
- The measurements by hand: N5, N10 and the by-hand variants of N1, N3, N4 and N8 (O10 included).
- Finding 10's package, and whether the saved comment should enter an answer (`answer --with-comments`).

## The brand chain, completed

Later on 2026-10-06 the maintainer rejected the second round of names, chose a name from a third round, answered the identity's four questions and decided the brand's voice: the workbench, his personal project for now, speaks in his own voice, and the design system of another product of his is the identity's base, with the brand's own logo, primary colour and cover. The acceptance checkout stayed on the central branch of #201 (no migration) and the image was the evidence's; nothing was built. As above, counts, kinds and endings only.

### The runs since #202 (24 to 37)

| Run | Task | Skill | Tier | Key | Ending | Right? | Duration (ms) | Tokens |
|---|---|---|---|---|---|---|---|---|
| 24 | route, third name round | core-orchestrator | floor | lab | done (one strict route line) | yes | 38,203 | 84,437 |
| 25 | name, third round | brand-name | floor | lab | done | the document was right; the ending was not (finding 13) | 866,417 | 2,017,479 |
| 26 to 31 | route, the name decision, first form | core-orchestrator | floor | lab | done, six times (one strict route line each) | each reply right; six runs for one delivery (finding 12) | 293,435 | 759,317 |
| 32 | route, the name decision, as prose | core-orchestrator | floor | lab | done (one strict route line) | yes | 57,950 | 125,970 |
| 33 | name, the decision | brand-name | floor | lab | draft_with_questions | yes | 297,306 | 578,148 |
| 34 | identity | brand-identity | floor | lab | draft_with_questions | yes | 276,453 | 951,080 |
| 35 | voice | brand-voice | floor | lab | question | yes (O8) | 416,125 | 2,288,890 |
| 36 | voice | brand-voice | floor | lab | draft_with_questions | yes | 220,818 | 673,303 |
| 37 | guidelines | brand-guidelines | floor | lab | draft_with_questions | yes | 175,144 | 635,438 |

14 runs, each `ok` on its first attempt, no value replaced, the image the evidence's: 8 of the router, 6 of a task. Total 2,641,851 ms of model time and 8,114,062 tokens. Every delivery was released as it stood; the brand request is `done`, with its five tasks.

### How each step went

| Step | Observed |
|---|---|
| The name decision | `brand-name` has no decision mode: a chosen name is recorded in research mode, in the `Decision` section its template gives "the chosen candidate". A one-skill request (no flow, routed, its plan approved by its hash) gave the choice, the registrar's readings and the notes for the guidelines. The run recorded the choice as the maintainer's and final, re-checked the name with its script and found two places registered minutes before the run, which the facts given said were not yet registered: it kept the script's word and asked who owns them. Released with ownership, networks, a fallback handle and the primary domain open |
| The voice's source | The voice skill declares one input for the person: the profile. The maintainer's own profile was copied into the project as the brand's profile, and his confirmed voice guide beside it under another name (the skill's own output keeps its path). Both are work data of the project, ignored by its version control; nothing entered the repository |
| The voice on a person's profile given as a company's (O8) | First run: `question`, nothing written: it saw that the profile is a person's while the strategy names a company as the subject, and asked whose voice it is, and the limits if it is the person's. Answered from the maintainer's decision and his recorded limits. Second run: `draft_with_questions`, the guide written in the person's voice with the person's limits, its rewrites checked by its script, the calibration asked |
| The identity's inputs | The identity's task uses the web, so `hand-over` refused the design system's file (the constant of WP-3.12 is false). The answer gave the two paths and quoted the design system's foundations and tokens as text, since a run cannot read the machine's paths. The run took its base tokens from that text, citing their names, marked its own primary colour as the brand's, computed contrast, confirmed the cover's size on the platform's help page and rendered three variants at the exact size; it asked which variant to keep |
| The guidelines | `draft_with_questions`: the guide written from the five brand files, its checker passing, every brand file's open questions listed, approval asked |
| The last `sync` (33 s) | Board: 7 rows written, 0 read, 0 failed. Documents: 0 imported, 2 failed (finding 14) |

### Findings of the brand chain

| # | Finding | Kind | What it asks of the design |
|---|---|---|---|
| 12 | A request whose text holds two or more lines starting with `- ` is read as that many deliveries, and the router runs once per delivery (stage 6). A request that listed six facts about one delivery as bullets cost six router runs and became a plan of six chained tasks of the same skill; the plan was rejected and the request made again as prose, which cost one router run and planned one task | as designed, at a cost the person cannot see before it is paid | The request command could say how many deliveries it read, before any router run, or a plan whose deliveries all route to one skill could be offered as one |
| 13 | The third name round ended `done` with a document marked draft and a reply that closed on five numbered questions; the second round of the same skill ended `draft_with_questions`. The classifier read the reply as asking nothing | runtime gap | The ending of a run whose document says it waits for answers, or whose reply ends on numbered questions, should be `draft_with_questions` |
| 14 | Two documents could not be written to the documents platform: each holds a fenced block whose language is a word of the skill (the identity's tokens block, the voice's rules block), and the platform accepts only the languages of its own list. The push failed at the run and at the next `sync`; the store keeps no record for the two, and whether a partial page was left was not checked | provider defect | The documents provider maps a language the platform does not know to its plain-text language and keeps the word in the text, with a fidelity case per document type that carries such a block |
| 15 | The runs that read the strategy still listed the person's appended sentence as an instruction found in external content: the import of that edit came before #201's import record, so no run has yet carried the line that says the person wrote it | as designed (WP-4.12, not yet observed live) | None; a new edit imported after #201 would show it |

### Open points of part 3, completed

| # | Open point | Observed |
|---|---|---|
| O8 | What the voice skill does for a company with no profile | With no profile: `blocked` (run 23). With a person's profile given as the company's: it named the mismatch, wrote nothing and asked whose voice it is; with the answer it wrote the draft (runs 35, 36). The skill was not edited |
| O9 | Whether a run treats a handed-over file as intended | Not exercised: the one task that needed a file uses the web, and the drop refused it; the material entered as text of the answer and the run used it |
| O10 | Whether an edit made within the minute of the runtime's write is seen | Not exercised: no edit was made on the platform in this part |
