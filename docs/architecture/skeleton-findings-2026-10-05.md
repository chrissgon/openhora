# What the skeleton showed: the acceptance of stage 1 (2026-10-05)

Stage 1 of the platform plan (`platform-plan-2026-10-05.md`) built an end-to-end skeleton of the task runtime: a request becomes the tasks of a flow file, each task runs as one skill, once, in the eval container, and a person answers and releases through pending decisions. Its acceptance ran the flow `market-positioning` (two tasks: a market analysis, then a customer profile and positioning) on the workbench's own case, from the terminal, on the reference model of the gate file. This file records what that run showed, question by question, and what each answer changes in the design.

It holds counts, kinds, durations, token counts and endings only: no content of the two documents, no answer the person typed and no path of the machine.

## The run in numbers

| Run | Task | Skill | Ending | Pending opened | Came back | Duration (ms) | Tokens | Skill loaded |
|---|---|---|---|---|---|---|---|---|
| 1 | market | biz-market-analysis | question | question | nothing | 22,292 | 126,525 | 1 |
| 2 | market | biz-market-analysis | draft_with_questions | question | document, state | 489,416 | 2,177,522 | 1 |
| 3 | market | biz-market-analysis | draft_with_questions | question | document, state | 17,259 | 256,401 | 1 |
| 4 | market | biz-market-analysis | draft_with_questions | question | document, state | 17,085 | 276,208 | 0 |
| 5 | market | biz-market-analysis | unclassified | review | nothing | 9,587 | 86,672 | 0 |
| 6 | positioning | biz-icp-positioning | question | question | nothing | 39,213 | 143,436 | 1 |
| 7 | positioning | biz-icp-positioning | draft_with_questions | review | document, state | 310,579 | 1,603,398 | 1 |

Runs 1 to 4 ran on the central branch before WP-1.10; runs 5 to 7 after it (see finding 1). Total: 7 runs, 905,431 ms of model time, 4,670,162 tokens. Every run ended `ok` on its first attempt. The request and both tasks ended `done`; two documents came back (the market analysis and the customer profile). The positioning document was not written, because the job the offer does is not decided and the skill writes positioning only once it is.

## Q1. Does the eval container run a skill on a run folder that is a copy of a project, not a case?

**Observed.** Yes. All 7 runs: `status` `ok`, no `failure`, `attempts` 1. No run folder holds a set-aside attempt (no `failed-<n>`, `early-end-<n>` or `paused-<n>`).

**Changes in the design:** nothing.

## Q2. Does the reference model load the one staged skill from a plain request followed by "For this task: ..."?

**Observed.** `skill_loaded` is 1 on 5 runs and 0 on 2 (runs 4 and 5). Both are short follow-up runs, made after an answer, on a task whose earlier runs had loaded the skill. Their replies follow the skill's reply template and report running the skill's own scripts, which only the staged skill carries. So the model worked with the skill, and the adapter's report of which skills were loaded did not show it.

**Changes in the design:** `skill_loaded` = 0 does not prove that a run went without its skill. A rule that reads it (stage 2's proof checks, a band computed on field evidence) treats 0 as "not reported", not as "not loaded", unless a second signal agrees. Finding 6.

## Q3. Does a run made after an answer treat the answers in its prompt as decisions?

**Observed.** 5 runs were made after an answer (runs 2, 3, 4, 5, 7).

| Run | Asked the same question again | Wrote the decisions into the state file |
|---|---|---|
| 2 | no | yes: 6 dated decisions, 7 open questions |
| 3 | no; its closing question was a point it had raised in run 1 and that the answer had left aside | yes: 1 dated decision |
| 4 | no | yes: 1 dated decision |
| 5 | no | no: the answer was "leave this open; nothing to add", and the run changed no file |
| 7 | no | yes: dated decisions and 4 open questions |

A point the person left open was kept as an open question, not decided (runs 2, 3, 7). One point was asked twice: raised in run 1, recorded as open by run 2, asked again as run 3's closing question; it was settled by a direct answer before run 4.

**Changes in the design:** nothing in the runtime. The prompt's rule ("each answer is the user's decision ... do not ask it again") held.

## Q4. Does the state file come back, and does the skill's change survive?

**Observed.** The state file came back (`returned`, class `state`) on the 4 runs that changed it (2, 3, 4, 7). It was never in `kept`. The 3 runs that changed nothing (1, 5, 6) returned nothing. After the acceptance, the state file holds both documents' rows as `draft`, the dated decisions of both skills and their open questions.

**Changes in the design:** nothing. The whole-file return of stage 1 was enough because nothing changed the state file at the origin during a run; stage 2's merge (L10) is still needed for the case where something does.

## Q5. Does the second task read the document the first one left?

**Observed.** Yes. The copy of run 6 held the market analysis and the state file. The positioning skill's first reply cites the market analysis's open question on the first audience and its segment scores, and its document compares the segments the analysis proposed.

**Changes in the design:** nothing.

## Q6. How did the first classifier name each ending, and was it right?

**Observed.**

| Run | Classifier | Reading of the reply |
|---|---|---|
| 1 | question | question: wrote nothing, asked 6 numbered questions |
| 2 | draft_with_questions | draft with questions: document written, one close call open, closes with a question |
| 3 | draft_with_questions | draft with questions: document updated, closes with a question |
| 4 | draft_with_questions | draft with questions: document updated; it holds an open question; the reply does not ask |
| 5 | unclassified | done: a summary of the delivered draft; it changed no file and asked nothing |
| 6 | question | question: wrote nothing, asked 7 numbered questions |
| 7 | draft_with_questions | draft with questions: document written, one close call left open |

`unclassified`: 1 (run 5). Every other ending matches the reading. Run 5 follows the classifier's own rule 2 (no file changed and no question), but the reply is a finished delivery: a run made after a "leave it open" answer has nothing left to write.

**Changes in the design:** the ending `draft_with_questions` opened a `question`, which cannot be released (finding 1, decided and built). A run that changes nothing and asks nothing after an answer is a case stage 2's classifier has to name (finding 2).

## Q7. What did a run leave that did not come back?

**Observed.** `kept` is empty on all 7 runs. Every run reports `left_out` = the project's `AGENTS.md`, "not copied in stage 1".

**Changes in the design:** nothing.

## Q8. Did the web runs work with the account's credential held outside the container?

**Observed.** All 7 runs had the open network (`web` 1). Both research runs (2 and 7) found and cited sources, and the skills' own source checks passed. No `auth` failure. The runtime does not store the number of redactions: the lab's result carries it, and neither the run's row nor the pending decision's payload keeps it. A search of every run folder for the redaction marker found none, so the count was 0.

**Changes in the design:** keep the redaction count of a run in the store (finding 7), so that L14 can be checked from the records.

## Q9. What does a run cost in time and tokens?

**Observed.** See the table above. The two research runs took 489,416 ms and 310,579 ms and 2,177,522 and 1,603,398 tokens. The five runs that only asked or recorded answers took between 9,587 and 39,213 ms and between 86,672 and 276,208 tokens. Wall-clock time per run was a few seconds above `duration_ms` (container start and the return of the copy). The reference model's `cost_usd` is recorded by the adapter but is not a real cost (backlog T23), so it is not used here.

**Changes in the design:** nothing. A task of this flow costs one question run (tens of seconds) plus one research run (five to eight minutes), plus about twenty seconds for each further answer.

## Q10. Was the image the evidence's?

**Observed.** Yes. `image_digest` is `sha256:4a446f8ae551e20ccca1728602c6fa8ce510b73db4b1fdb17cf87ad21351eb28` on all 7 rows, the digest of fact E13. The checkout names the image by a tag that follows its container definition, and that tag is not the one the plan's step quoted. The tag differed; the image id was the same (finding 3).

**Changes in the design:** nothing. The digest is what counts. The step's text was amended.

## Q11. What does the missing `AGENTS.md` change?

**Observed.** The project had an `AGENTS.md` (the workbench's own, with the workbench section added by the project's initialisation), and stage 1 left it out of every copy. All replies and both documents are in English. No reply says the file is missing.

**Changes in the design:** nothing seen in this case. A project whose instructions set another language, or rules a skill must follow, was not tested; stage 2's L5 brings the file in.

## Q12. Does the shell run on the system interpreter?

**Observed.** Yes. The system interpreter (Python 3.9.6) ran the shell's `status` on the configured project with exit 0, and printed the same output as the interpreter the runs used.

**Changes in the design:** nothing.

## Q13. Did anything need a step this plan does not have?

**Observed.**

- A read-only listing of the local images, to see why the image's tag differed from the step's (finding 3).
- Read-only queries of the store, to record the rows of the runs.
- A fix of the runtime in the middle of the acceptance (finding 1), then a move of the acceptance checkout to the commit that holds it.
- One extra answer and one extra run (run 5). Pending decision 4 had been opened as a `question` before the fix, so it could only be answered; it was answered "leave this open; nothing to add" and run again, and the new code opened a `review`. The run exists only because that row predates the fix.
- The acceptance ran from a second checkout used only for acceptance, detached on a commit of the central branch, and the project was another checkout of the workbench. Step 0's detection reported that checkout as "not a project root (no version control)", because a linked worktree's version-control entry is a file, not a folder (finding 4).

**Changes in the design:** see findings 1 and 4.

## Findings

| # | Finding | Kind | What it changes | Decided |
|---|---|---|---|---|
| 1 | A run that wrote its document and still asked (`draft_with_questions`) opened a `question`, which can only be answered. When the person leaves the open question open on purpose, every answer runs the skill again, and the draft can never be released | runtime design | A run that wrote a declared output opens a `review`, a draft with open questions included; a run that wrote nothing and asks opens a `question`. A review is released as it stands (the open questions stay in the document, its row stays `draft`) or answered. The store needs no new kind or resolution. Stage 6: an autonomy mode never releases by itself a review whose run ended `draft_with_questions` | Yes: decided by the supervisor on the maintainer's delegation on 2026-10-05 (the maintainer may undo it); built by WP-1.10, pull request #138, merged as `97858c0`; section F.3 of the plan amended first |
| 2 | After a final "leave it open" answer, a run changed nothing and asked nothing, and was named `unclassified` | classifier | Stage 2, which makes the classifier total, decides what this case is (a delivery with no change, or `unclassified` as now). Until then the person reads the reply and releases it | Decided by the supervisor on the maintainer's delegation on 2026-10-05, for stage 2's classifier (WP-2.2): when the task's declared output already exists in the project and the reply closes without a question, the ending is `done` |
| 3 | The plan's step quoted an image tag; the checkout's tag follows its container definition | plan | None in code. The step was amended: the digest is what counts | Amended in the plan |
| 4 | The project-initialisation script's detection does not recognise a linked git worktree as version control | skill script (`core-project-init`) | None in the runtime. A fix in the skill's script is a Y change of that skill, with its test | A backlog item for the maintainer (supervisor, 2026-10-05): `docs/backlog.md`, T29 |
| 5 | The skill asked a point a second time when the earlier answer left it aside instead of settling it | the skill working as written | Nothing: "never assume, ask" | n/a |
| 6 | `skill_loaded` was 0 on two follow-up runs that did use the skill | adapter report | A rule that reads `skill_loaded` treats 0 as "not reported" unless a second signal agrees | Decided by the supervisor on the maintainer's delegation on 2026-10-05: 0 is read as "not reported", never as "not loaded"; no rule of the runtime depends on the field until an adapter's report is reliable; it is stored as observed. The adapters' scripts are measurement files and are not edited: `docs/backlog.md`, R12 |
| 7 | The run's redaction count is not kept in the store | records | Stage 2 (L14) keeps the count on the run's row or in the payload | Decided by the supervisor on the maintainer's delegation on 2026-10-05: the count is stored on the run's row, by the package that builds L14 (WP-2.1b) |
