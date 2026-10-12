# What stage 5 showed (2026-10-06)

Stage 5 of the platform plan (`platform-plan-2026-10-05.md`) moved the control of a model run's attempts into one module, `evals/run_attempts.py`, which the eval runner and the runtime's lab facade both call (WP-5.1 to WP-5.3), and made a regrade take its place in the shared lock and pause at the account limit (WP-5.4). Its acceptance (WP-5.5) is that nothing changed where it must not. This file records what that acceptance ran and what it showed.

It holds counts, kinds, endings, durations and token counts only: no content of a run, no person and no identifier. The maintainer had delegated supervision and approved the model runs of acceptances; the acceptance was run by a delegated agent on that delegation.

## The commits

- "Before": `1f2a518` (WP-5.1 merged, nothing calling the module yet).
- "After": `ed64a7b`, the central branch with WP-5.1 to WP-5.4 merged.
- The eval image of both: `sha256:4a446f8ae551...`, the evidence's; checked, not built.

## Step 1: the checks, on "after"

| Check | Result |
|---|---|
| The test suite | 3451 passed, 42 skipped |
| `scripts/validate.py` | 0 errors, 142 warnings |
| The measurement fingerprint | `None` |
| `grep -c 'while True' runtime/lab.py` | 0 |
| `git diff --stat 1f2a518^..ed64a7b` over the measurement paths and `skills/` | two files, both `skills/*/evals/runtime-manifest.json` (`eng-implement`, `ops-pull-request`), added by stage 4 (#182, #184); outside every skill's content hash and outside the fingerprint. Nothing else: no measurement file, no skill content, no adapter |

The plan expected the diff to print nothing; it was written before stage 4 added the two runtime manifests. Read as passed.

## Step 2: the trial, before and after

`eval_run.py --skill brand-voice --runs 1`, "before" first, then "after", never at once. `brand-voice` was chosen because it has no web case, two cases, no setup, no dependency skill and baselines in force, so the trial is four runs on each side; `--dry-run` planned the same four runs at both commits.

| | Before (`1f2a518`) | After (`ed64a7b`) |
|---|---|---|
| Runs (case, variant, model) | 1 and 2, with the skill, strong and floor: 4 | the same 4 |
| Graded, complete | 4 of 4, complete | 4 of 4, complete |
| Infrastructure failures, retries, timeouts, refusals, early ends, pauses | 0 | 0 |
| Skill loaded (strong, floor) | 2 of 2, 2 of 2 | 2 of 2, 2 of 2 |
| Files of the event folder, outside the run copies | 94 paths | the same 94 paths; each run folder holds `cwd/`, `facts.md`, `grading/`, `grading.json`, `outputs/`, `prompt.md`, `timing.json` |
| Evidence written under `skills/` | none: the file went to the event's scratch tree ("runs 1, configured 3") | none, same reason |
| Pass rate, case 1 strong / floor | 1.0 / 1.0 | 1.0 / 1.0 |
| Pass rate, case 2 strong / floor | 1.0 / 1.0 | 1.0 / 1.0 |
| Tokens, case 1 strong / floor | 161,783 / 81,694 | 201,947 / 61,727 |
| Tokens, case 2 strong / floor | 321,962 / 169,037 | 372,836 / 207,023 |
| Duration ms, case 1 strong / floor | 20,518 / 82,191 | 19,672 / 37,609 |
| Duration ms, case 2 strong / floor | 49,269 / 62,341 | 66,394 / 78,799 |
| Wall time of the event | 90 s | 88 s |

The same result before and after. No case passed before and failed after, so no second trial was needed.

## Step 3: a run of the runtime, on "after"

A scratch project with invented names (one commit by an invented identity, `core-project-init` with autonomy `milestones` and docs `none`, its own data folder), the configuration accepted, then a request on the flow `market-positioning` and one `run-next`. The request was then cancelled and the scratch project deleted.

| | Result |
|---|---|
| Proof of `biz-market-analysis` | tier floor, key `lab`, proven, bands reliable and reliable, both checks `None` |
| `run-next` | status `ok`, ending `question`, task `waiting`, one pending decision of kind question |
| The run | 1 attempt, `skill_loaded` 1, 40,420 tokens, 31,950 ms, no value replaced, the evidence's image |
| Folders | entered kind `artifacts` (2 files, `AGENTS.md` whole); returned, kept and left out empty; the run folder holds `cwd/`, `outputs/`, `prompt.md` |

The same status, ending and folders as the same run before the stage (stage 2's acceptance: `ok`, `question`, 1 attempt, nothing returned).

## Step 4: the three cases of `core-skill-creator`, on "after"

`eval_run.py --skill core-skill-creator --cases 2,3,4`: a partial test, with the skill only, 3 runs each on both models. `--check-cases` reported no error; `--dry-run` planned 18 runs, the number expected (3 cases, 3 runs, 2 models). All 18 were graded on the first attempt, with no retry, failure or pause, and the runner wrote the evidence file `lab-20261006T105658Z-4c601661.jsonl` (18 run lines).

| Case | Strong, 3 runs | Floor, 3 runs | Strong, the full test of 2026-10-04 |
|---|---|---|---|
| 2 | 1.0, 0.33, 1.0 | 1.0, 1.0, 1.0 | 0.83, 0.83, 0.83 |
| 3 | 0.8, 0.6, 0.8 | 0.6, 0.8, 0.6 | 0.8, 0.8, 0.8 |
| 4 | 1.0, 0.86, 1.0 | 1.0, 1.0, 1.0 | 0.86, 1.0, 1.0 |

The strong model did not load the skill in 2 of its 9 runs (case 2 run 2 and case 4 run 2); the floor model loaded it in 9 of 9. The run of case 2 that did not load it scored 0.33 and failed guard assertion 2.6, the guard assertion the floor model had already failed in the full test of 2026-10-04.

| `eval_status.py status --skill core-skill-creator` | Before step 4 | After step 4 |
|---|---|---|
| Band (reference model) | `reliable` | `needs a test`: guard assertion 2.6 failed in the current set |
| Pessimistic score, mean, runs (reference model) | 0.7327, 0.8964, 12 | 0.7418, 0.8642, 21 |
| Floor model (information) | `needs a test` (guard 2.6), 0.7406, 0.9028, 12 | `needs a test` (guard 2.6), 0.7812, 0.8968, 21 |

The fall to `needs a test` comes from a run in which the model never loaded the skill: whether a skill loads is decided by the harness from the description, before any code of this stage runs, and the trial of step 2 showed the attempt control unchanged. It is a finding about the skill's description and guard on the reference model, not about the extraction. The rules clear it only by a change to the skill and passing runs of its guard cases (the band's command: after the fix and its bump, `--cases 2`), which is the maintainer's. Nothing was changed here: no case, assertion or skill.

## The open points

| # | Observed |
|---|---|
| O-15 | None of the lab's named tests needed one of the three kinds of fix of WP-5.2, and none needed anything else (recorded by WP-5.2, #180) |
| O-16 | The trial did not differ between "before" and "after" beyond a model's own variation: the same runs, all graded, the same files, no evidence written, the same pass rates; only tokens and durations differed (table of step 2) |
| O-17 | A re-run of three cases cost only their own runs: the runner planned 18 and ran 18, no baseline and no other case |

## Findings

| # | Finding | Kind | What it asks of the design |
|---|---|---|---|
| 1 | The extraction changed no result of a trial, of a runtime run, or of a lab test's mechanics | as designed | None: stage 5 is accepted |
| 2 | Step 1's diff over `skills/` prints the two runtime manifests stage 4 added | plan text | None: the check's path list predates stage 4 |
| 3 | `core-skill-creator` moved from `reliable` to `needs a test` on the reference model: in 2 of 9 runs the model did not load the skill, and one of them failed guard 2.6 | skill | The maintainer's: a change to the skill (its description or the guard's case) and its guard runs |
