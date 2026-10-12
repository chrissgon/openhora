# What the acceptance of stage 2 showed (2026-10-05)

Stage 2 of the platform plan (`platform-plan-2026-10-05.md`) hardened the task runtime: what enters a run and what comes back under limits L1 to L8, L10, L12 and L14; a classifier of endings that is total against its corpus; the choice of a model by the skill's proof; the hash of the project's configuration; a use and a verdict recorded with the existing recorder. Its acceptance ran stage 1's case again, the flow `market-positioning` on the workbench's own case, from the terminal, under those limits. This file records what that run showed and what each finding asks of the design. The effect of a project's `AGENTS.md` in the two adapters is recorded apart, in [agents-md-effect-2026-10-05.md](agents-md-effect-2026-10-05.md).

It holds counts, kinds, endings, durations and token counts only: no content of the two documents, no answer the person typed and no path of the machine.

## Before any model call

| Check | Observed |
|---|---|
| A configuration not accepted yet | `status` refused, exit 3, naming the file's hash and "none" |
| `accept-config` with that hash | accepted; `status` then showed stage 1's request `done`, exit 0 |
| One byte added to the configuration | `status` refused, exit 3, naming both hashes; restored, exit 0 |
| `proof` (no model call) | both business skills: tier `floor`, `proven` true, bands `reliable` on both models, both checks passing (`measurement` and `image` null), `web` true, key `lab` |
| The eval image | the evidence's digest (`docs/decisions.md`) |
| `test_limit_*` passing | 11 |
| The classifier's corpus test | passed |
| The store | migrated to version 3 by the first command of the advanced checkout |

## The runs

A new request on the same flow, after stage 1's request. The documents of stage 1 were in the project, with the decisions of stage 1 in its state file. `protected_paths` named `AGENTS.md`, so only the workbench section entered.

| Run | Task | Skill | Tier | Key | Proven | `agents_md` | Ending | Right? | Pending | Came back | State lines accepted / refused | Duration (ms) | Tokens |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 8 | market | biz-market-analysis | floor | lab | yes | section | draft_with_questions | yes | review, released | document, state | 0 / 1 | 498,980 | 2,536,476 |
| 9 | positioning | biz-icp-positioning | floor | lab | yes | section | unclassified | no: `question` | review, answered | state | 0 / 2 | 376,837 | 541,899 |
| 10 | positioning | biz-icp-positioning | floor | lab | yes | section | done | yes | review, released | nothing | none | 174,209 | 157,069 |

Total: 3 runs, 1,050,026 ms of model time, 3,235,444 tokens, every run `ok` on its first attempt, `skill_loaded` 1, no value replaced in what it left, a use recorded for each, the image the evidence's. `kept` and `left_out` were empty on every run. The request and both tasks ended `done`. The market analysis was updated in place (its sources kept, both of its checkers passing); the customer profile was already there and unchanged; the positioning document was not written, as in stage 1, because the job the offer does is not decided. The project's `AGENTS.md` kept its hash, and the runtime's checkout stayed clean. The person's verdict on runs 8 and 10 was recorded as a `verdict` line with the floor model's id and `judge` `user`.

**The floor model ran these tasks.** The proof gave the floor tier for both skills and every run went there: the run rows name the gate file's floor model and adapter, the streams are the floor adapter's, and the adapter's own cost figures are about two orders of magnitude below a reference-model run of the same length. The key was the lab's (WP-2.11): the maintainer decided on 2026-10-05 that the runtime uses the key already stored for the lab's floor model, and the routing named it as `key: "lab"`.

## Findings

| # | Finding | Kind | What it asks of the design |
|---|---|---|---|
| 1 | The merge refuses a new open question that is not in the checkbox form `- [ ] ...` of `contracts/state.md`. Run 8 added `- OPEN-2 (...) ...`, the form its skill writes, and the project's earlier open questions are all plain `- ...` lines; the line was refused, and the question is in the document but not in the state file. The reason printed, "a run may add an open question, never close or remove one", is the reason for closing or removing one and does not describe this refusal | runtime defect (the reason); a gap between the skills' form and the contract | The merge gives its own reason for a line in another form. Whether it accepts the `- OPEN-<n>` and plain forms as new open questions, or the skills write the checkbox form, is a decision for the maintainer: a merge change is a runtime package; a skill change is a Y change with its lab test |
| 2 | A run whose only change is the state file, and which closes with numbered questions, is `unclassified` (run 9: "files changed, none of them a declared output of the skill"). The person's reading is `question`: it wrote no declared output and asks | runtime defect (classifier) | The rule for "wrote nothing and asks" treats a run that changed only the state file (a file the skill `updates`) as one that wrote nothing. Added to the classifier's labels; a change of rule is a package of its own |
| 3 | Because run 9 opened a `review`, answering it did not write the answer into the state file: `ops.answer` writes the person's decision only for a `question`. The next run got the answer through its prompt only | consequence of finding 2 | Fixed with finding 2; until then a person who answers a `review` whose reply asked should know the answer is not recorded as a decision |
| 4 | The finding-2 rule of WP-2.2 named run 10 `done`: nothing changed, the declared output was there, and the reply named its remaining decision without a question mark. Right in this case | as designed | None. The supervisor's rule for stage 6 stands: no autonomy mode releases such a `done` by itself |
| 5 | Run 8 ended `draft_with_questions` where step 3 of the acceptance script expected `question` or `done`: with stage 1's decisions in the state file it did not ask the scope again and updated its draft, keeping the close call open | plan gap | Step 3 lists `draft_with_questions` among the expected endings of a project whose documents exist |
| 6 | Run 9 changed an existing open question (it added its own attribution and a second blocker to it); the merge refused both the changed line and the removal of the original, as its rules say | as designed | None |
| 7 | Every run of this acceptance went to the floor model on the lab's key. Without WP-2.11 every run would have stayed on the reference model, because no key of the runtime's own was stored | plan gap, closed by WP-2.11 | None further: a key of the runtime's own still wins when it is stored |

## Open points of part 2 that this run answered

| # | Open point | Observed |
|---|---|---|
| O1 | What the system interpreter does when the credential is only in the secret store | No model call made. On the system's Python 3.9, `proof` routes to the reference model: the resolver imports but, without the store library, finds nothing, so a stored key is reported as "not stored" (the reason should say the store could not be read). Read in code, not run: `run-next` there starts the run, then the facade refuses it (the credential is neither set nor found), and the task ends `failed`. Stage 6 (item 6.3) decides how a scheduled run gets its credential |
| O2 | Whether the key proxy is restarted when a run arrives with another value | Read in `evals/executor.py`, no docker command: the proxy's container is labelled with a hash of the value it was started with, and a call with another value replaces it. With WP-2.11 the runtime and the lab use one key, so the label is the same and the proxy is not replaced when both run; with a key of the runtime's own stored, a lab test and a floor run of the runtime must not run at once |
| O5 | Whether a skill re-asks because the merge refused its own line | No. The merge refused one line of run 8 and two of run 9; neither the line nor its question came back as a question in the next run |
| O6 | Whether `lab.standing` is fast enough | The first `proof` of this acceptance, on a data folder with no proof file, took 0.60 s of wall time for both business skills |
| O9 | Whether both business skills are `reliable` on the floor model at the runtime's checkout | Yes: `reliable` on both models, both checks passing |

## What was not run

- No lab test, no `eval_run.py`, no docker build, removal or `ensure`.
- `run-next` on the system's Python 3.9 (O1): read in code only, because it would fail a task of the acceptance project.
- No answer was written into the state file by code in this acceptance (finding 3), so the check "one more `(user)` decision line" of step 4 did not apply. It ran after the two fixes below.

## The two defects, fixed

Decided by the supervisor on the maintainer's delegation on 2026-10-05; no skill was edited.

| Finding | Fix | Pull request |
|---|---|---|
| 1: a new open question not in the checkbox form was refused, with the reason for closing or removing one | The merge reads tolerantly and writes strictly: a new list item of `## Open questions`, in any list form, is written as `- [ ] <text>`, its text kept (an `OPEN-<n>` mark stays part of it). Closing, rewording or removing a question the project has, a question attributed to the person or to another skill, and a line that is not a list item are each refused with their own reason. A test binds the written form to `contracts/state.md` | #153 |
| 2 and 3: a run that changed only the state file and asked was `unclassified`, so the answer was not written into the state file | For telling `question` from the other endings, a change limited to the state file counts as having written nothing: such a run that asks ends `question`, and its answer is written by code. One that asks nothing follows the rules already there; `draft_with_questions` still needs a declared output written. One corpus line moved from `unclassified` to `question` and is labelled | #154 |

**Step 4, run after both fixes.** On a scratch project with invented names (not the workbench's own case), from the acceptance checkout advanced to the central branch holding #153 and #154: one run of `biz-market-analysis`, floor tier by proof, key `lab`, first attempt, 111,968 ms, 39,108 tokens, the image the evidence's. It changed no file and asked six numbered questions: ending `question`. The answer gave `"state": {"written": true}`, and the state file had one more decision line ending `(user)`, the last of `## Decisions`, in the form `- <date>: Answer to <skill> (pending decision <n>): <text> (user)`. The request was cancelled and the scratch project deleted. This run wrote nothing at all, so it did not exercise the state-only path of #154 in a real run; that path is covered by the classifier's tests and one corpus line.
