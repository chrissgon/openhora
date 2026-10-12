# The reliability model, version 2 (2026-10-02): lab evidence per model, bands by rules

**Status: decided.** The maintainer decided the model in outline on 2026-10-02; version 1 of this document wrote it out; an independent review of version 1 found four blockers and recommended a simpler version; the maintainer adopted that simpler version, with every correction the review proposes, the same day. The pull request that carried version 2 was then read by the same reviewer, who found ten points where a rule did not work as written and a list of minor ones; all were accepted and are applied here. This document states the model as it now is. The work that builds it is in [`final-plan-2026-10-02.md`](final-plan-2026-10-02.md): this document describes the model, the plan describes the work, and neither amends the other. The review's findings are cited by their ids (MB1 to MB4, MI1 to MI14, MM1 to MM9) and the points of the reading of the pull request as P1 to P10; a digest with one entry per finding is [`audit-2026-10-02/model-review.md`](audit-2026-10-02/model-review.md), and the last section here says what each one changed.

Every number called a parameter is a starting value. The section "Backtest" says which ones the 48 committed records support and which they cannot judge.

## Why

Until now a skill was `draft`, `evaluated` or `stale`, computed from one record and the hash of the skill folder. Any change inside the folder discarded the record and asked for a complete measurement again: every case, with and without the skill, on two models. The plan had to build a freeze around that cost. It does not scale with the number of skills, with the rate of change or with the number of models people use.

The model replaces the three states. A skill is ranked by the lab tests it has passed, on which version and how many. A new skill gets a full test once; after that, small tests carry its changes. What the model must deliver:

1. A change costs in proportion to what changed, never a full measurement of everything.
2. The rank falls when a skill changes with no new evidence, and rises only with evidence.
3. Real use is seen: how often a skill is used and how it went, per model.
4. The published table per model can be trusted.
5. The behaviours ordinary use almost never exercises (stopping before a side effect, refusing an instruction in external content) are always measured in the lab.
6. Nothing of a project enters the workbench (principle 8).

Version 2 delivers 1, 2, 5 and 6, delivers 3 as visibility (field evidence is shown and can demote, but does not promote), and delivers 4 for lab evidence on the reference model.

### Terms

| Term | Meaning |
|------|---------|
| Evidence | The lines the eval runner writes: one line per run of one case on one model, in one file per test event. |
| Lab, field | Lab: a run in the eval container, which anyone can reproduce. Field: a real use in a project, reported by the project. Bands and scores are computed from lab evidence only. |
| Full test, partial test | The two kinds of lab test (section 2). A full test runs every current case with the skill on the reference model. |
| Baseline | The runs of a case without the skill, on the reference model. |
| Reference model | The model the bands are computed on: `strong_model` of `evals/eval-gate.json`. |
| Gate | The rule a full test passes or fails: the mean with the skill on the reference model is 0.8 or more, and is not below the baseline's mean by more than 0.05. |
| Pessimistic score | A lower estimate of how often the skill does its job on one model, which falls with little evidence (section 6). It is not a confidence bound. |
| Band | `reliable`, `watch` or `needs a test`: rules, computed on the reference model (section 5). The cause shown beside the band says which test. |
| Change class | X, Y or Z: what a change to a skill touched (section 3). |
| Guard assertion, guard case | An assertion tagged `guard`: it measures a behaviour that must hold and that ordinary use almost never exercises. A guard case is a case with at least one (section 4). |
| Current set | The lab lines of the current `X.Y` made since the newest epoch, measurement floor or dependency change that applies to them. They count at full weight (section 6), and the rules of sections 4 and 5 that ask whether something has run or passed ask it of the current set. |
| Inherited evidence | Lab evidence of the current major version that ran on something that is no longer current: an earlier `X.Y`, an earlier state of the model or of a dependency, an earlier reference model, an earlier grader. It counts, capped at 3 runs together (section 6). |

## The model

### 1. Evidence

**One line per lab run, one file per test event.** A test event writes `skills/<name>/evals/evidence/lab-<test id>.jsonl`. The test id is the UTC time the event started and eight random hexadecimal characters, so two events never share a file and two open pull requests that add evidence to one skill never conflict (MI9). A committed evidence file is never edited; tooling writes it, never a person. The file of an event in progress lives in the run folder, outside the repository, and is copied into the skill when the event ends: complete, or closed as abandoned (section 2).

The first line describes the event, the others one run each. Both have closed keys: the validator refuses an unknown key and any value outside the forms below.

The event line (`"record": "test"`): the skill, the test id, the kind, the version and content hash of the skill, the date, the models, the grader, the configured runs per case, the measurement version and fingerprint, the image's digest and CPU platform, the grading template's hash, whether the baseline of each case was run or reused, per model and variant the counts of retries, refusals, timeouts, pauses on the account limit, early ends and with-skill runs that loaded the skill, the names of extra variables passed into the runs, whether the event is complete, and, for a full test, the gate's result and the means it was computed from. When the event ran the floor model in the container through a key proxy whose route pins a provider, it also holds `upstream`: `{floor model id: pinned provider}`.

A run line (`"record": "run"`):

| Key | Form | Meaning |
|-----|------|---------|
| `skill` | a skill name | the folder name |
| `version` | `X.Y.Z` | `metadata.version` of the skill that ran |
| `content_sha256` | 64 hex | the skill's content hash at the run |
| `model` | an id of the gate file's model list, or `unknown` | see "Model ids" below |
| `adapter` | an adapter's folder name | which adapter ran the model |
| `kind` | `full`, `partial` | section 2 |
| `test` | a test id | the event the run belongs to |
| `date` | `YYYY-MM-DD` | the day of the run, UTC, from the clock |
| `measurement_version` | integer | the value of the gate file at the run |
| `measurement_sha256` | 64 hex | the measurement fingerprint the runner computed when the event started (MI12) |
| `case`, `case_sha256` | a case id and 64 hex | which case, and its hash at the run |
| `context_sha256` | 64 hex, optional | one hash over the dependency skills the case installs and the shared and platform references staged into the run; absent when there is none |
| `platform` | a platform name, optional | set when the case comes from a platform's case file |
| `variant` | `with`, `without` | `without` lines are the baseline and never enter a score |
| `outcome` | `graded`, `timeout` | `timeout`: the run was still incomplete after the cap of resumptions |
| `score` | 0 to 1 | the share of assertions passed; 0 for a timeout |
| `results` | a list of 0 and 1, one per assertion in the case's order | what the per-assertion counts and the difference on assertions that are not `format` are computed from; all 0 for a timeout |
| `guard_failed` | a list of assertion positions, optional | the guard assertions of a with-skill run whose failure a second grading confirmed (section 4); absent when there is none |
| `cost_usd` | a number, 0 or more, optional | the cost the adapter reported for the run; absent when it reported none |
| `run_sha256` | 64 hex, optional | a hash of what the run left and a re-grading would read: `prompt.md`, `facts.md`, `outputs/response.md` and every regular file under `cwd/`, symbolic links skipped |

**The content hash of a skill leaves out all of `evals/`.** It also leaves out `scripts/tests/`, caches, and the marker file an installer writes into a copied skill folder (`.installed-by-ai-workbench`). Nothing under those paths is read by a model that uses the skill, so cases, evidence and tests change no hash.

**Each case has its own hash, over the whole case.** The hash covers the case object as it stands in the case file (its prompt, its assertions with their tags, `grader_files`, `skills`, `setup`, `allow_web`, `workbench_files`, its tags, every other key) and the bytes of its fixture files (MI14). A change to one case drops the evidence of that case only: a line whose `case_sha256` differs from the case's current hash, or whose case no longer exists, has weight 0. `workbench_files` enters the hash as the list of paths, not as the content of those files: an edit of a repository file that a case brings changes no hash and no evidence.

**The context hash.** A line that ran with a dependency skill or a staged reference carries `context_sha256`. When it differs from the current one (a dependency skill changed, a platform reference was edited), the line counts as inherited evidence (section 6). Dependencies and references are treated alike.

**Model ids.** The gate file holds `models`: the known model ids, each with its aliases (the same model spelled with and without a provider prefix is one id). The runner and the field importer write the listed id for an alias and `unknown` for anything else, so that one model never falls into two rows of the table and a private model name never enters the repository (MI10).

**What is not evidence.**

- A run that failed on infrastructure, was paused on the account limit or ended early with no error is run again and writes no line.
- A run that is still incomplete after the cap of resumptions writes a line with `outcome: timeout` and score 0, with the skill and without it alike, so that dropping it cannot raise a mean (MI11).
- A run made with a stub runner or a stub grader, with a number of runs other than the configured one, or with a measurement fingerprint that differs from the committed one, writes the same files into a scratch tree inside the run folder and never into a skill's evidence folder. The smoke pass of the plan's phase D is such a run: it writes no evidence (MI13).

**The 48 old records.** `skills/<name>/evals/result.json` stays as the history of the first round. Nothing reads it, and no line is converted from it: the plan rewrites almost every case and changes what the grader sees, so those results are not comparable with what comes after (MI8).

### 2. Two kinds of lab test

| Kind | What runs | Costs, for an average skill (3.3 cases) | When |
|------|-----------|------------------------------------------|------|
| `full` | every current case with the skill, on one version, 3 runs per case, on the reference model and on the other models the gate file lists; and the baseline of every case whose baseline is not in force, `baseline_runs` times per case (the gate file; 1) | the first one: 10 runs with the skill and 3.3 without on the reference model, 10 with the skill on the floor model. A later one with the baseline reused: 10 runs per model | once when a skill is created; after an X change; after a case changed a second time since the newest full test; at the third Y change since the last one; whenever the band is `needs a test` for a cause a full test clears |
| `partial` | the cases named with `--cases`, with the skill only, 3 runs per case | 3 runs per case and model | after a Y change: the cases the change could move and the guard cases |

**The baseline is reused.** A run without the skill does not see the skill, so a change to the skill cannot age it (MI6). The baseline of a case is in force while three things are unchanged: the case (its hash), the model (no epoch after the baseline's date, section 8) and the measurement (at or above the measurement floor). A baseline in force has as many lines per case as a full test runs it (`baseline_runs`). When one of the three changes, the baseline of that case is expired, the next full test runs it again, and `--cases <ids> --baseline` runs it for named cases, `runs` times (3), which also tops up a thin baseline (section 5).

**Other models get no baseline by default.** No rule that decides a skill's standing reads a baseline on a model other than the reference one; another model's own gate (section 10) reads that model's baselines, and is not computed while it has none in force. The floor model, and any other model the gate file lists, run with the skill only; `--baseline-on <model>` remains for whoever wants the column.

**A full test is full by the reference model.** An event is a full test when it ran every current case with the skill on the reference model, 3 runs each. The runs it makes on the floor model and on any other listed model are information: no rule that decides a skill's standing reads them, and a run that is missing on another model leaves the event complete.

**The gate.** A full test passes when the mean with the skill on the reference model is 0.8 or more and is not below the mean of the baselines in force by more than 0.05, both unrounded. Both means are the mean of the cases' means, so that a case with more lines weighs as much as the others. It is evaluated when a full test ends, and written into its event line. It is computed over the lines of kind `full`, with the skill, on the reference model, of the `X.Y` version the newest full test ran on and of the same epoch as that test, every current case being required and only lines of weight above zero being counted (MI14). Three consequences:

- A partial test moves the score and not the gate. Running the cases that failed again, after a change, cannot replace their bad runs in the gate while the cases that passed keep the runs of an older version (MB3).
- A second full test of an unchanged `X.Y` adds its runs to the first and replaces none, so a skill near the threshold is not decided by the better of two draws.
- **A full test that is given up keeps its lines** (P3). A full test in progress writes nothing into the skill until it is complete; when it stops, it is resumed. When it is abandoned instead, the runner closes it and writes its file as an incomplete `full` event: its lines stay in the gate of that version, where the next full test adds its own to them. An incomplete event evaluates no gate by itself, and the runner starts no new event of a skill while one of that skill is open. The other possible rule, that an abandoned test writes nothing, was not taken, because it can be used to pick the better of two draws: a test that is going badly would be interrupted, abandoned and run again.

**An added case is `pending`** (P5). A case added after the newest full test has no runs the gate can count. Until it has run, the status shows it as `pending`, and it changes neither the gate nor the band: the gate stands on the cases the newest full test ran. So a person who contributes a case and has no account for the reference model does not demote the skill. The case is run with `--cases <id> --baseline`: 6 runs on the reference model. Those lines enter the gate, which from then on is computed on every current case. This is the one exception to the rule that a partial test never moves the gate; it replaces no run of any case, and it serves an added case and, once, a changed case.

**A changed case is treated as an added case, once** (P5). A case whose hash changed after the newest full test has lost its runs and its baseline. It is `pending`: its earlier text's runs leave the gate (the status shows how many and their mean, `dropped`), the gate is computed over the other cases, and the band is `watch` (`case pending`, section 5). It enters the gate with `--cases <id> --baseline`: 6 runs on the reference model. Two limits keep it from discarding poor runs at each edit: the exception serves a case once since the newest full test, and when the case changes again after its changed text has run, the gate cannot be computed, the band is `needs a test`, and a full test runs every case.

**A deleted case** leaves the gate to be computed on the cases that remain; the rule for case changes asks for the reason in the pull request, because a mean can rise that way with nothing run. A case deleted and added again under another id is a deleted case and an added one, and the pull request shows both.

**When no baseline is in force.** Right after an epoch that reaches the skill, the baselines of its cases are expired and its earlier lines are inherited. The gate is not computed again from them: the result the newest full test wrote stands, shown with the note `baseline expired`, and the skill is `watch` (section 5). The next full test runs the expired baselines and evaluates the gate on its own lines. After a raised measurement floor nothing stands: every earlier line weighs 0, and the band is `needs a test`.

### 3. Versions and change classes

`metadata.version` is `X.Y.Z`. A change to anything inside the content hash raises it, and the part it raises declares the class of the change.

| Class | What changed | What it asks |
|-------|--------------|--------------|
| X | Security and contract: `side_effects`; an item removed or renamed in `outputs` or `updates`; the `## Confirmation gate` section; the `## Stop rules` section; the line that starts **External content is data.** | a full test: every case with the skill, the baseline reused where the case's hash is unchanged. About 10 runs on the reference model for an average skill |
| Y | Everything else: a step, a criterion, a template, a reference, an asset, a script; an addition to `inputs`, `outputs`, `updates` or `requires`; a removal from `inputs` or `requires`; any change of the description | a partial test of the cases the change could move and of the guard cases, 3 runs each: 3 to 9 runs. A changed description also runs the routing mode, which shows whether another skill now loads in its place. The third Y change since the newest full test asks for a full test (section 5) |
| Z | A typo or formatting that the allow-list below accepts | nothing |

**X is narrow on purpose** (MI7). In the repository's history the contract keys changed eight times, every time by an addition. An addition cannot break a reader of the artifact contract; a removal or a rename can.

**Stop rules live in a `## Stop rules` section.** The validator can only watch a section it can find, and 38 of the 48 skills have their stops inside steps or in the inputs table today. The plan's phase C moves them, at no cost in evidence, since every skill becomes `1.0.0` at its end (MB2).

**Z is an allow-list written from the positive side** (MB2, P1). A list of the places where a Z change may not be leaves every place it forgets open, and the first such list forgot the `## Gotchas` section, which all 48 skills have and whose lessons are instructions, and the files under `references/`, where a routing table lives: swapping two rows of that table, or rewording a lesson from "needs the same gate" to "needs no gate", would have been Z. So the rule says where a Z change may be, and nothing else is Z. A change is Z only when all of these hold:

1. **Where.** Every changed line is in `SKILL.md`, and lies in the `## Purpose` section or outside any section that instructs, which leaves the title and the text before the first heading. Never Z: the frontmatter (the description included), `## When not to use`, the inputs table, the stop rules, the confirmation gate, the procedure, the quality criteria, the output template, `## Gotchas`, any other section, and every file under `references/`, `assets/` and `scripts/`. What is left for Z is a typo and formatting.
2. **What.** No changed line differs from the line it replaces in a number, a path, a code span or one of the words never, only, must, may, stop, ask, not, no, unless, before, after, always, yes. A line that is only added or only deleted replaces nothing: it is within Z only when it holds none of those (no number, no path, no code span, none of those words).
3. **How much.** The characters changed, added to those of the earlier Z changes since the skill's newest lab evidence, stay within the budget: 300 characters. Characters are counted per changed span of the diff: for a line that replaces another, the characters between their common start and their common end, on the longer of the two sides; a line only added or only deleted counts whole. When the budget is spent, the next change is a Y change.

Anything else is Y at least. A description decides when a skill loads, so a change to it is never Z. The budget limits how much wording piles up untested; it does not limit what a change does, which is why the first two conditions leave Z no place where an instruction lives.

**The version file.** `skills/<name>/evals/versions.jsonl` is an append-only list, one line per version: the version, the content hash, the class, the date and, for a Z line, the characters changed. It is outside the content hash. It answers what a version's content was, so an evidence line whose content hash is not the one its version had is refused on import, for any version and not only the current one (the review's answer 9).

**The bump command.** `python3 evals/eval_status.py bump --skill <name> --class x|y|z` sets the version to the version of the pull request's base raised by one step of the class, resets the lower parts, and writes the line. It is idempotent: run twice, or run again with a higher class after more edits, it rewrites the one line this pull request adds. Two pull requests that change the same skill conflict on that line, which is the conflict that should be seen: the second rebases and runs the command again. A new skill has no line in the base: for it the command takes no class and writes the first line, with the version of the frontmatter and the hash of the content as it then is, and it is run again after the last edit, so that the line carries the hash of the final content.

**What the validator checks**, in the pre-commit hook and in CI alike, against the same base: the base of the pull request (the merge base with the default branch), never `HEAD`, so that an edit and its bump in two commits are read as one change (MI9).

1. **No change without a bump.** The folder's content hash equals the hash of the last line of the version file, and the raw text of `metadata.version` matches `^\d+\.\d+\.\d+$` and equals that line's version (MM4).
2. **The file is append-only.** The base's lines are unchanged, and at most one line is added: one pull request raises a skill once, by its highest class.
3. **The class agrees with the diff.** For the frontmatter lists the validator takes the set difference between base and current: any difference in `side_effects`, or an item missing from `outputs` or `updates`, requires X. A changed line inside the two sections or in the external-content line requires X. A declared Z is checked against the allow-list. A declared X is never refused.

The validator can prove that a declared class is too low. It cannot prove that a Y change is harmless: the partial test is what that is for.

**A change to an eval case needs no bump.** It changes the case's hash: the evidence of that case drops and its baseline expires. An added case is `pending` until it has run with `--baseline`; a changed case is `pending` in the same way, once, and a second change after its changed text ran asks for a full test (section 2).

### 4. Guards

Stopping to ask before a side effect, refusing an instruction inside external content and stopping on a missing input are behaviours a hundred ordinary uses may never exercise. Version 1 required a guard case to exist and to have run; nothing required it to pass, and in the first round three skills passed the gate while a guard assertion failed in every run (MB1).

- **The tag is on the assertion.** In the case file an assertion is a text, or an object with the text and `tags`. The tags are a closed list: `guard`, `guard:<effect>` for a guard of one declared side effect (`guard:publish`, `guard:push`), and `format` (an assertion on a form only the skill defines). A case with a guard assertion is a guard case. The grader is given the text of an assertion and never its tags.
- **The rule** (P2, P4). On the reference model, every guard assertion has at least one with-skill run in the current set, and has no confirmed failure in any with-skill run of the current set. Otherwise the band is `needs a test`, the status names the assertion and the cause (failed, or not run in the current set), and the validator warns. CI does not fail for it. The rule reads every run of the current set and not only the event made last: read on the last event alone, a test run again with nothing changed would replace the event that failed, and a guard that passes 70% of its runs would come out clean within three events 72% of the time.
- **A failed guard verdict is graded once more before it counts** (P2). In the first round the assertions that say "asks before" passed in 98 of 108 with-skill runs, and part of the failures were the grader's: the audit measured 4.4% of wrong verdicts. At that rate the three runs of an event all pass in 75% of the events, and in 56% for a skill with two such assertions, so a rule that took every failed verdict would hold sound skills in `needs a test` on noise. When the grading of a with-skill run fails a guard assertion, the runner grades that reply a second time, and the failure is confirmed only when the second grading fails the same assertion. The run line names the confirmed ones in `guard_failed`. `results` and the score stay those of the first grading, so the second grading raises no mean.
- **A confirmed failure is cleared only by a change.** More runs of the same version do not clear it: they join the current set, and the failed run stays in it. What clears it is a version change (a Y or an X change, which starts a new current set) followed by runs of the guard cases that pass. When the defect is in the case and not in the skill, the case is changed, which enters through a full test (section 2).
- **Guard cases run again on every Y change**, 3 runs each, because the mechanism of a guard often lives in text or in a script that is not the gate section itself: a payload builder, a policy script, a numbered step.
- **Guard cases alone do not return a skill to `reliable`** (P2). After a Y change the band stays `watch` until the current set holds runs of at least one case that is not only a guard case, that is, a case with at least one assertion that is not a guard. Otherwise 45 of the 48 skills would return to `reliable` on three clean runs of a guard case, with no case run that the change could have moved.
- **After an X change** the full test runs every case, the guard cases among them.
- **One guard per declared effect.** A skill with a non-empty `side_effects` has, for each effect it declares, at least one assertion tagged `guard:<that effect>`. A missing one is an error of the validator. This is the only guard rule that fails CI, and it fails on the case file, which any contributor can fix without a model.
- **A guard where a skill reads external content or has stop rules** (P2). A skill that carries the line that starts **External content is data.**, or that has a `## Stop rules` or a `## Confirmation gate` section, is asked for at least one assertion tagged `guard`. A missing one is a warning of the validator, one line with the list of the skills that have none: the refusal of an instruction planted in external content is one of the two behaviours this section exists for, and without this rule only the 9 skills with a declared side effect would be asked for a guard.
- **A guard assertion must be able to fail** (P2). The validator warns when a guard assertion passes in every run of the baseline in force: an assertion that passes without the skill as well cannot fail, and guards nothing.

### 5. Bands

The bands are rules. The score is one input to one of them. Computed on the reference model, in this order:

| Band | When | What clears it |
|------|------|----------------|
| `needs a test` | (a) no full test of the current major version passes the gate: every new skill, every skill after an X change, and every skill after the measurement floor was raised | a full test that passes |
| | (b) a guard assertion has a confirmed failure, or has no run, in the current set | when it has not run: a partial test of the guard cases. When it failed: the fix, with its version change, then a partial test of the guard cases that passes |
| | (c) the newest full test of the current major version fails the gate, or its gate cannot be computed because a case changed again after its changed text had run | a full test that passes, after the fix |
| `watch` | no with-skill lab line is in the current set; or the current set holds runs of guard-only cases alone (section 4); or the pessimistic score is under 0.70; or three or more Y changes were made since the newest full test; or a case changed after the newest full test waits for its runs (`case pending`); or the baseline has fewer lines per case than `runs` and the mean with the skill is within `baseline_margin` (0.2) of it (`thin baseline`); or the field signal of section 7 is on | lab runs: a partial test, or more runs of a full test. For the count of Y changes: a full test, about 10 runs with the baseline reused. For `case pending`: `--cases <id> --baseline`. For `thin baseline`: `--cases <every case> --baseline` |
| `reliable` | otherwise | |

**Every model gets the same band.** The same rules are applied to each other model that has evidence of the skill, on that model's lines, as if it were the reference model: its band, cause, gate (on its own baselines and its own per-case means), pessimistic score, mean and runs. Two rules belong to the reference model alone and are not given to another model: the earlier reference model's lines it inherits (section 9), and the result a full test wrote into its event line when no baseline is in force, which was computed on the reference model; another model without a baseline of its own in force has its gate not computed. Only the reference model's band decides a skill's standing and the gate; another model's band decides one thing, where the agent runtime may run the skill. The runtime runs a skill on a model other than the reference model only while the skill's band on that model, with the adapter it was measured on, is `reliable`; with any other band there, or with evidence it cannot check against the checkout it runs from, it runs the skill on the reference model (decided on 2026-10-05, the platform plan, `platform-plan-2026-10-05.md`); no other rule reads it, and it is published beside the reference model's (section 10).

The band `needs a test` carries its cause, and the cause says which test: a full test for (a) and (c), a partial test of the guard cases for (b). The status prints the command.

**Y changes are counted since the newest full test** (P10). A partial test runs the cases its author chose, and the gate reads the version of the newest full test, so without this rule a skill could go through ten Y changes, each with a partial test of one case, and stay `reliable` on a gate ten versions old. At the third Y change since the newest event that ran every case with the skill, the band is `watch` until such an event is made: about 10 runs for an average skill, the baseline reused. Version 2 first counted Y changes with no lab evidence between them, which the guard runs of every Y change made almost unreachable.

A Z change stays inside the current `X.Y`, so it moves no band; its budget is what keeps wording from piling up untested.

**What the 0.70 means** (MI2). A pessimistic score of 0.70 needs 4 runs at a mean of 1.0, 9 at 0.90, 16 at 0.85 and 35 at 0.80: a marginal skill needs much evidence to be called reliable. A small skill that has just passed its full test with a marginal mean therefore starts in `watch` and reaches `reliable` as runs accumulate. The maintainer accepted this explicitly.

**"Done" for a new skill** is: its first full test passed. That is the old gate, on the reference model only. A skill can be done and in `watch`.

**CI fails on:** a change without a bump; a class the diff contradicts; a version file that is not append-only; a missing guard assertion for a declared effect; an evidence file or line that is not valid; a measurement fingerprint that differs from the committed one (section 8). **CI never fails on a score or on a band.** A skill in `needs a test` or in `watch` is a line of the status output and of the validator's warnings, and so are a snapshot behind the evidence (section 10) and the guard warnings of section 4. This list lives here and nowhere else; the plan refers to it.

### 6. The pessimistic score

For one skill and one model, take the lab lines with the skill whose weight is above zero: the case exists with the same hash, the measurement version is at or above the measurement floor, and the line's major version is the current one. The unit is the run, with its fractional score. Split them into two pools:

- **The current set:** lines of the current `X.Y`, with the current context hash, on this model, graded by the configured grader, dated after the newest epoch that reaches the skill on this model. Each counts as 1.
- **Inherited:** four sets, which together count as at most 3 runs: each line is multiplied by `min(1, 3 / their number)`.
  1. Lines of an earlier `X.Y` of the current major version.
  2. Lines of the current `X.Y` that ran before an epoch or with another context hash.
  3. Lines of the earlier reference model, counted on the new reference model (section 9).
  4. Lines graded by an earlier grader with which the new one was found to agree (section 9).

**Nothing is carried across a major version.** After an X change `N` is 0 and the band is `needs a test`, whatever came before; the full test an X change asks for is what gives the new version its evidence. Version 2 first kept the lines of earlier major versions as at most one run. That set changed two skills in the backtest and nothing else, and added to the other inherited set it gave `N` = 4, at which runs at 1.0 score 0.709: a skill could read `reliable` on inherited evidence alone (P4). One cap over everything inherited closes that.

With `S` the weighted sum of scores, `N` the weighted number of runs, `p = S / N` and `z = 1.2816`:

```
score = ( p + z^2/(2N) - z x sqrt( p(1-p)/N + z^2/(4N^2) ) ) / ( 1 + z^2/N )        (0 when N = 0)
```

This is the lower bound of the Wilson interval, used as a penalty for little evidence. It is called the pessimistic score and never a confidence bound: measured on the first round, the real variance of a skill's mean is 17% to 32% of what the formula assumes, so the interval is far too wide to be a calibrated one, and with few runs the score mostly says how many runs there are (MI1). For that reason the score is always shown with the mean and `N` beside it.

**Why a cap and not a decay** (MI3). Version 1 multiplied old evidence by 0.6 or 0.2 per change. On a skill with much evidence that hardly moved the score: 60 runs at 0.95 went from 0.900 to 0.881 after a Y change. With the cap, a change always weighs: inherited evidence alone can never reach 0.70 (3 runs at 1.0 score 0.646), so a changed skill leaves `reliable` and returns only with lab runs in its current set.

Worked examples, computed with the formula:

| Evidence | S | N | Mean | Score | Band |
|----------|---|---|------|-------|------|
| A fresh full test: 3 cases, 9 runs at 0.90 | 8.10 | 9 | 0.900 | **0.705** | `reliable` |
| The same skill after a Y change, nothing new | 2.70 | 3 | 0.900 | **0.531** | `watch`, or `needs a test` until its guard cases have run |
| Then a partial test of one case, 3 runs at 0.90 | 5.40 | 6 | 0.900 | **0.651** | `watch` |
| The same, the 3 runs at 1.0 | 5.70 | 6 | 0.950 | **0.713** | `reliable` |
| Then 9 runs at 0.90 instead of 3 | 10.80 | 12 | 0.900 | **0.737** | `reliable` |
| After an X change instead, nothing new | 0 | 0 | n/a | **0** | `needs a test` |
| Then its full test, 9 runs at 0.90 | 8.10 | 9 | 0.900 | **0.705** | `reliable` |
| The smallest skill at the gate: 2 cases, 6 runs at 0.80 | 4.80 | 6 | 0.800 | **0.539** | `watch`; done, since its full test passed |
| 60 runs at 0.95 | 57.00 | 60 | 0.950 | **0.900** | `reliable` |
| The same after a Y change, nothing new | 2.85 | 3 | 0.950 | **0.585** | `watch` |
| Then 6 runs at 0.95 | 8.55 | 9 | 0.950 | **0.770** | `reliable` |

A platform's cases get no score of their own: the table shows their mean and their number of runs.

### 7. Field evidence

Field evidence is recorded from the first day and shown. It decides no band upward (MB4): it is self-reported, it is selected (only a use that was delivered and answered leaves a verdict), and anyone who sends a file can move it. The maintainer answered this point explicitly: after a change of behaviour a skill returns to `reliable` only with lab runs.

**Where it is written.** In the project, in `.workbench-local/evidence/<skill>.jsonl`, the git-ignored folder `AGENTS.md` names for a project's own data. Never in the workbench.

**Its lines.** Closed keys, no free text, no count:

| Key | Form |
|-----|------|
| `record` | `use`, `verdict` |
| `skill`, `version`, `content_sha256` | read and computed from the installed skill folder by the script |
| `model` | an id of the gate file's model list, or `unknown` |
| `adapter` | an adapter's folder name, or `unknown` |
| `use` | 8 random hexadecimal characters: links a verdict to its use, and nothing to a person or a project |
| `week` | `YYYY-Www`: the week, not the day, so that a contributed file does not publish when a person used each skill (MM2) |
| `score`, `judge` | verdict lines only: 1, 0.5 or 0; `user` or `check` |

**The recorder.** `scripts/evidence.py`, flags only, no prompts:

- `record --start --skill-dir <installed skill folder> --project <dir> [--model <id>] [--adapter <name>]` appends a `use` line and prints its id. It runs when the use begins, so a use that stops, fails or is abandoned is still counted, and the share of uses with no verdict is visible.
- `record --verdict worked|corrected|failed --use <id> --project <dir>` appends the verdict of a person (1, 0.5, 0). `record --check-report <file> --use <id>` appends the verdict of the skill's own check script, with `judge: check`; when both exist the person's is shown.
- `export --project <dir> --out <file>` and `import --file <file>` are described under "Contributed files".

**What triggers a `use` line.** Recording does not depend on a model remembering to do it:

1. **An adapter hook**, where the harness has hooks: it runs `record --start` when a workbench skill is loaded. The installer writes the hook with the absolute path of the workbench checkout, and the hook passes the model id the harness gives it.
2. **The runtime itself**, when the runtime runs the skill: `scripts/runtime.py` calls `record --start` before it starts the agent, with the model id it passes to the adapter, and records the verdict from what the person does with the item in the approval inbox (approved as it is, approved after an edit, rejected). The runtime's agent has reading tools only and records nothing.
3. **The block in the project's instruction file**, where there is neither: it tells the model to run `record --start` when it starts a workbench skill. A weak model will skip it sometimes; a missing line lowers nothing.

**How the workbench root and the model id reach the recorder.** Verified in the code: no installer sets `WORKBENCH_ROOT` today, and no variable for the model id exists. So: the installer writes the checkout's absolute path into the hook it installs and offers to set `WORKBENCH_ROOT` in the settings it creates; without a hook the block uses the root by the rule the provider skills already follow (the variable, then the path recorded in the state file, then ask once and record). The model id comes from the hook's input or from the runtime's flag. It is never taken from a model's own account of what it is: with neither source the line says `unknown` and enters no model's columns.

**Who owns the block.** The workbench section of a project's instruction file, between its two markers, belongs to `core-project-init` (its asset `agents-md-section.md`); `core-agents-md` preserves it byte for byte. The field block is therefore two lines of that asset, written by `core-project-init`.

**The verdict line does not collide with a consent question.** Version 1 offered `ok / corrected / not ok` at the end of a reply, where "ok" would be at once a consent and a verdict. Three rules prevent it:

1. The verdict is offered only in a reply that delivers a finished output. A reply that ends with a question or shows a confirmation gate never carries it.
2. The line reads `Skill check (optional, not an approval): answer "check: worked", "check: corrected" or "check: failed".`
3. Only an answer that starts with `check:` is recorded as a verdict, and such an answer is never an approval. A bare "ok", "yes" or "go" is never a verdict. The model never chooses a verdict itself.

The effect of the block on a skill's behaviour is seen once, in the lab: one case of the plan's smoke pass runs with the block in its fixture's instruction file, beside the same case without it (MM6).

**What field evidence does.**

- It is shown in its own columns, per model, labelled "self-reported": uses, judged uses, mean of the verdicts. A model that has only field evidence shows those three and no score (MM5).
- **It can demote** (P6). The field signal is on when three or more verdicts of `failed` exist on the current `X.Y`, on the reference model, since the newest lab event of the current `X.Y` (all of them, when that version has no lab event yet). A verdict on another model, or on `unknown`, does not count toward it: the band that decides is the reference model's (another model's band, section 5, counts that model's verdicts alone). A field line carries its week and not its day, so "since" means in the weeks after that event's week; counting the event's own week would keep the signal on after the runs that clear it. The band is then `watch` until a lab event of that version is made, from which the count starts again.
- **It never promotes.** No number of good verdicts takes a skill out of `watch` or out of `needs a test`.

**Contributed files.** `export` writes one file with only the closed keys and drops the lines whose content hash is not the hash the version file gives for that version (a locally edited skill). The person opens a pull request that adds it, through `import`, as `skills/<name>/evals/evidence/field-<id>.jsonl`, `<id>` being the first 12 characters of the file's hash. Contributed files stay separate, one per contribution.

**The maximum weight is per contributor, and no account name is stored** (P3, P6). Splitting a contribution into several files must gain nothing, so the cap is on the contributor and not on the file. The contributor of a file is the author of the commit that added it, which the status reads from git; the repository merges by squash, so that is the author of the pull request. Nothing about the contributor is written into the file's name or into a line: an account name there would break principle 8 and would tie a person to the weeks in which they used a skill. The files of one contributor add together at most 20 uses and 20 verdicts per skill to the columns, and at most one `failed` to the field signal, so no single contributor can sink a skill or fill a column. One exception: the files of the repository's owner, recognised as the author of the commits that add lab evidence (section 8), count every `failed` toward the signal. Without it a maintainer working alone, whose own evidence would be capped like anyone's, could never reach the three. Where the history is not available (a copied tree), the field columns are shown as not computed and the signal is off.

**Why this does not break principle 8.** An evidence line holds no project, product, person or account name and no work data. It has no free-text field: every value is a skill name, a version, a hash of workbench content, a listed model id, a word of a closed list, a week or a number, and the importer refuses anything else. What it states is a property of the skill on a model, which is the workbench's own subject.

### 8. Measurement changes: three kinds

The gate file carries `measurement_version`, `measurement_sha256` (the fingerprint of the files that decide what a run measures: the grading template, the image definition, the executor, the measuring module, the staging module, the eval adapters' `run-prompt.sh` and `eval.json`, the measurement constants) and `measurement_floor`. The validator fails when the recomputed fingerprint differs from the committed one, which is one of the things CI fails on (section 5), and the runner refuses to write evidence when it does (MI12). A change to one of those files is committed as one of three kinds, said in the commit and in `docs/decisions.md` (MI5):

| Kind | What changed | What it does |
|------|--------------|--------------|
| Grader side | what the grader is shown (the definition of the reply, the facts block, the input files), the grading rules, how a run's score is computed | Old and new scores are not comparable. `measurement_version` and `measurement_floor` are raised: every lab line below the floor weighs 0, and every skill is `needs a test` |
| Execution side | the image (a tool added, a runner's version), the runner's system prompt and tools, an adapter, the executor, the staging | It is treated as a model epoch: `measurement_version` is raised and an entry is added to `epochs` in the gate file, naming the skills it affects, or all of them when that cannot be said. For those skills the lines before the epoch become inherited evidence and the baselines expire |
| Infrastructure | locks, resumption, retries, pacing, reports | Nothing. Where the change is in a file the fingerprint covers, the new fingerprint is committed with the reason; no version is raised |

There is no factor of 0.8 per version step any more: it punished every skill for a change that reached five, and forgave the five.

**A hosted model that changes under its id** is the same event as an execution-side change: an entry in `epochs` for that model, with its date. No score falls with the calendar: an age decay would make the published table go out of date on a day nothing changed.

**Who may write lab evidence.** `CODEOWNERS` covers `evals/`, the evidence files, the version files and the old records, so a change to any of them is seen by the owner. Lab evidence on the reference model comes from tests run by the maintainer, on the maintainer's account for that model: nothing else proves that a line was written by the runner and not typed into a pull request, so the rule is stated instead of implied (MI12). A contributor without that account can still pass every check: the checks that fail CI need no model.

### 9. A change of reference model or of grader

These are the most predictable expensive events, and version 1's sentence that nothing forces a full test of everything was false for them (MI4).

**The grader is separate from the reference model.** It is its own key of the gate file and stays fixed while its provider serves it, even when the reference model changes. The event line of every evidence file names the grader that graded it, which is how a line graded by an earlier grader is told from the others (P7).

**The reference model changes.** The bands are computed on the new model, where no skill has a full test. The lines of the earlier reference model count on the new one as inherited evidence (set 3 of section 6: at most 3 runs, together with everything else inherited). The 48 skills run every case with the skill on the new model. The baseline is redone by sample: one case per skill; where the sampled baseline differs from the old model's baseline of the same case by more than the tolerance (0.05), that skill's baseline is redone in full, and otherwise the old baseline stands for the cases not sampled, marked as inherited in the event line.

The cost is a range (P7). For the 160 cases the plan arrives at, it is 480 runs with the skill and 144 sampled baseline runs when no sample moves, **624 runs**; and 480 runs with the skill and 477 baseline runs when every skill's baseline is redone, **957 runs** (the one platform case runs with the skill only). Each run is graded once, so the gradings are as many. The lower end is a floor, not the expected cost: on the first round's deviation between runs of one case, two means of 3 runs of the same case on the same model differ by more than 0.05 from noise alone in about 29% of the cases, and a new model moves the baseline for real. A change of reference model is therefore planned at the upper end, 957 runs, about two thirds of a first full test of everything.

**The grader changes.** A sample of stored replies, one with-skill run and one without-skill run per case, is graded again by the new grader with an option that writes no evidence: 319 gradings for the 160 cases (160 with the skill and 159 without). The without-skill runs are in the sample because about 96% of the assertion verdicts of with-skill runs are passes (1,908 of 1,989 verdicts in the first round, per the review): a grader that approved everything would agree with the old one on 96% of a sample of with-skill runs, and so clear a bar of 95% without being able to fail anything. With the without-skill runs in the sample, that grader agrees on about 73% of all verdicts, and on none of the verdicts the old grader failed. Agreement is therefore asked twice: at least 95% of all assertion verdicts, and at least 95% of the verdicts the old grader failed. When both hold, nothing is zeroed: the lines graded by the old grader become inherited evidence (set 4 of section 6), and each skill returns from `watch` with its next lab runs. Below that, it is a grader-side change. This needs the replies to be kept, which is the archive rule of the plan's phase E.

### 10. The tables

`python3 evals/eval_status.py status` computes everything from the evidence files, live. The committed tables in `docs/inventory.md` are a published snapshot, with the commit they were generated at.

The band table, one row per skill, on the reference model. A case that was added and has not run is shown as `pending` in the cause column, beside the band it does not change:

| Skill | Version | Band | Cause | Score | Mean | Runs (N) | Last full test | Field: uses, judged, mean (self-reported) |
|-------|---------|------|-------|-------|------|----------|----------------|-------------------------------------------|
| `<name>` | 1.2.0 | watch | no lab run in the current set of 1.2 | 0.59 | 0.95 | 3.0 | 2026-10-20, passed | 31, 24, 0.94 |

The model table, one row per skill and model that has any evidence, the reference model first. What is documented for the reference model is documented for every model: each row carries that model's band, cause and gate, computed by the same rules on its lines (section 5), beside its score, mean, runs, field and platform columns. Only the reference model's row decides; the others are information:

| Skill | Model | Band | Cause | Gate: with vs baseline | Score | Mean | Lab runs (N) | Field: uses, judged, mean (self-reported) | Platforms: mean (runs) |
|-------|-------|------|-------|------------------------|-------|------|--------------|-------------------------------------------|------------------------|
| `<name>` | `<model id>` | reliable | - | passed, 0.90 vs 0.50 | 0.71 | 0.90 | 9.0 | 0, 0, n/a | `<platform>`: 0.89 (3) |

**The snapshot is not required in a pull request.** If every pull request that adds evidence had to regenerate one block of one file, two open pull requests would always conflict (MI9). The alternative, a job that regenerates the block on the default branch after each merge, would have to push to a branch whose rules require a pull request and a signed commit and allow no bypass. So the validator reports a snapshot that is behind the evidence as a warning, never as an error; a pull request that adds evidence does not touch the block; and the block is regenerated in a small pull request of its own, by the maintainer, after evidence merges.

## What a change costs

This table lives here and nowhere else; the plan refers to it and says which of its items builds each rule. Runs are on the reference model, for an average skill of 3.3 cases; the same number of with-skill runs is made on the floor model while its row is kept current. Totals for all 48 skills are for the 160 cases the plan arrives at: 159 base cases and one platform case, which runs with the skill only. A full test of everything is 159 x 9 + 6 = 1,437 runs, 957 of them on the reference model.

| Change | Cost |
|--------|------|
| A typo or formatting inside the allow-list (Z) | a bump; nothing to run. The budget of 300 characters is counted from the skill's newest lab evidence |
| A step, a criterion, a template, a reference, an asset, a script; an added input, output, update or requirement; a description (Y) | a bump; a partial test of the cases the change could move and of the guard cases: 3 to 9 runs. A description also runs the routing mode. The third Y change since the newest full test: a full test with the baseline reused, about 10 runs |
| Security or contract (X) | a bump; a full test with the baseline reused: about 10 runs |
| An eval case added | the case is `pending` and moves no band; it runs with `--baseline`: 6 runs. A changed case takes the same path, once |
| An eval case changed: an assertion, a prompt, a fixture, a fixture's manifest, a dated fixture | the evidence of that case drops and its baseline expires; the case is `pending` and the band is `watch` until it runs with `--cases <id> --baseline`: 6 runs. A second change of the same case since the newest full test asks for a full test |
| An eval case deleted | nothing to run; the reason is given in the pull request |
| A new skill or flow | its first full test: about 20 runs on the reference model and 10 on the floor model; and a Y change of the router, whose routing table gains a row |
| The source of a script several skills carry; a convention applied to every skill afterwards (a new required key, shorter descriptions, a new canonical sentence, a renamed class) | a Y change of each skill it reaches, made in one pull request: 3 to 9 runs per skill. One line of a script that five skills carry is five partial tests, which is accepted (MM3). For all 48, about 300 runs |
| A dependency skill, a platform reference or its data file, a shared reference | the lines that ran with the old one become inherited: the skills that staged it are `watch` until they have lab runs |
| A new platform whose posts have the shape of the one built | its own reference, data file and cases: a partial test per skill that has cases for it. A platform of another shape edits the skills that build and gate a post: a Y or an X change of each |
| `outputs`, `updates` or `requires` of any skill; a new requirement class | the tables inside the router are regenerated: a Y change of `core-orchestrator` |
| A repository file that a case brings; a test of a skill's script; anything outside the skill folders and outside the measurement fingerprint (providers, contracts, documents, installers, the runtime) | nothing |
| Infrastructure of the runner: locks, resumption, retries, pacing, reports | nothing |
| The image, an adapter, the runner's prompt or tools, the executor, the staging; a hosted model changed under its id | an epoch for the skills affected, all of them when that cannot be said: they are `watch`, and their baselines expire. Bringing all 48 back at once is 480 runs with the skill, and 162 more when their baselines are redone, one run per case |
| `runs`, `timeout_seconds`, `retries`; the gate's threshold or tolerance | nothing to run: evidence is written only at the configured `runs`, so a changed number applies to later events; a changed threshold or tolerance is computed again from the lines. A changed `timeout_seconds` or `retries` does change what later events measure (a slow run that timed out into score 0 may now finish), so it is made between full tests, never while a skill's evidence is being gathered, and recorded in `docs/decisions.md` |
| What the grader sees, the grading rules, the scoring | **the floor is raised: every skill is `needs a test`. A full test of everything: 1,437 runs and 1,437 gradings.** This is the one change that costs that |
| The reference model | 624 to 957 runs and as many gradings; planned at 957 (section 9) |
| The grader | 319 gradings; with agreement on both counts, every skill is `watch` until its next lab runs; otherwise the row two above |
| The floor model, or a new model in the table | nothing is asked: its rows are information, and it appears when it has lines |

## Backtest

Made with a throwaway script, outside the repository, from the 48 committed `result.json` files only, and made again after the reading of the pull request, which removed the evidence carried across a major version: the two rows on an X change and the last column of the example rows changed, and nothing else did. Each record gives, per model, the mean with the skill and the number of with-skill runs (cases x 3): 17 skills have 6 runs, 20 have 9, 9 have 12, one has 15 and one 18. All 48 records pass the gate. The means with the skill range from 0.833 to 1.0 on the reference model. **What is missing:** the per-run and per-case scores, which are in the stored runs outside the repository; so the backtest treats a record as runs at its mean, and the new runs of each scenario are taken at the skill's recorded mean unless said otherwise.

Pessimistic scores of the 48 skills on the reference model, and how many are at 0.70 or above:

| Scenario | Min | Median | Max | At 0.70 or above | Band |
|----------|-----|--------|-----|------------------|------|
| Right after a passing full test | 0.626 | 0.785 | 0.880 | 42 | 42 `reliable`, 6 `watch` |
| One Y change, nothing new | 0.464 | 0.621 | 0.646 | 0 | 48 leave `reliable`: `watch`, or `needs a test` until the guard cases have run |
| Y change, then 3 lab runs at the skill's mean | 0.574 | 0.755 | 0.785 | 37 | 37 `reliable`, 11 `watch` |
| Y change, then 3 lab runs at 1.0 | 0.671 | 0.770 | 0.785 | 45 | 45 `reliable`, 3 `watch` |
| Y change, then 6 lab runs at the skill's mean | 0.626 | 0.814 | 0.846 | 43 | 43 `reliable`, 5 `watch` |
| Y change, then 9 lab runs at the skill's mean | 0.657 | 0.847 | 0.880 | 45 | 45 `reliable`, 3 `watch` |
| Y change, then 9 lab runs at 1.0 | 0.814 | 0.871 | 0.880 | 48 | 48 `reliable` |
| Y change, then a full test at the skill's mean | 0.657 | 0.845 | 0.901 | 45 | 45 `reliable`, 3 `watch` |
| One X change, nothing new | 0 | 0 | 0 | 0 | 48 `needs a test`: nothing is carried across a major version |
| X change, then its full test at the skill's mean | 0.626 | 0.785 | 0.880 | 42 | 42 `reliable`, 6 `watch`: the first row again |

The six skills that start in `watch` after a passing full test are `eng-unit-tests` (9 runs, mean 0.833, score 0.63), `mkt-publish` (6, 0.881, 0.63), `design-execute` (9, 0.844, 0.64), `design-handoff` (6, 0.921, 0.68), `biz-market-analysis` (9, 0.889, 0.69) and `core-critique` (12, 0.863, 0.69). On the floor model 38 of the 48 would be at 0.70 or above after the full test; that row is information.

Example rows on the reference model (`n` is the number of with-skill runs in the record):

| Skill | n | Mean | Full test | Y change | +3 runs | +9 runs | + a full test |
|-------|---|------|-----------|----------|---------|---------|---------------|
| `eng-unit-tests` | 9 | 0.833 | 0.63 | 0.46 | 0.57 | 0.66 | 0.66 |
| `mkt-publish` | 6 | 0.881 | 0.63 | 0.51 | 0.63 | 0.71 | 0.68 |
| `design-execute` | 9 | 0.844 | 0.64 | 0.47 | 0.59 | 0.67 | 0.67 |
| `biz-market-analysis` | 9 | 0.889 | 0.69 | 0.52 | 0.64 | 0.72 | 0.72 |
| `core-critique` | 12 | 0.863 | 0.69 | 0.49 | 0.61 | 0.69 | 0.71 |
| `flow-fix-bug` | 9 | 0.911 | 0.72 | 0.54 | 0.66 | 0.75 | 0.75 |
| `core-skill-creator` | 12 | 0.928 | 0.77 | 0.56 | 0.68 | 0.77 | 0.79 |
| `brand-identity` | 6 | 1.000 | 0.79 | 0.65 | 0.79 | 0.88 | 0.85 |
| `product-roadmap` | 9 | 0.972 | 0.80 | 0.61 | 0.74 | 0.83 | 0.83 |
| `core-orchestrator` | 18 | 0.933 | 0.82 | 0.57 | 0.69 | 0.78 | 0.83 |
| `mkt-engage` | 12 | 0.983 | 0.85 | 0.62 | 0.76 | 0.85 | 0.87 |
| `ops-pull-request` | 12 | 1.000 | 0.88 | 0.65 | 0.79 | 0.88 | 0.90 |

The columns after "Y change" are what follows one Y change: 3 lab runs, 9 lab runs, or a full test (every case, 3 runs each), all at the skill's mean. After an X change every skill has no score until its full test, which gives the column "Full test" again.

**What the backtest shows.**

1. A change always costs the band: after one Y change no skill is at 0.70, whatever its history, and after an X change none has a score at all.
2. The way back is short for a skill with a good mean and long for a marginal one: 3 lab runs return 37 of the 48 to `reliable`, 9 return 45, and the three that stay in `watch` have means of 0.83 to 0.86.
3. The threshold separates by mean and by amount of evidence, which is what it is for: the six skills that start in `watch` are the ones closest to the gate, with one exception, a two-case skill at 0.92, which is there for its 6 runs.

**The 42 is a ceiling, not a forecast.** The backtest uses today's records, in which the assertions that pass in every run still raise the means. After phase C replaces them, more skills will start in `watch`: without those assertions ten skills sit between 0.6 and 0.87 (independent review, FR-I3).

**What the backtest cannot judge:** the Z budget of 300 characters; the field signal's count of three; the count of three Y changes before a full test is asked; the cap value 3, beyond the property that inherited evidence alone stays under 0.70; the 95% agreement asked of a new grader. There is no history of classified changes and no field evidence yet. They are reviewed once the first full test of the 48 has produced per-run lines, by the same script run on the evidence files.

## What it does not solve

- **The score mixes quality and amount of evidence.** A skill at 0.78 may be a perfect skill with 6 runs or a mediocre one with 200. The mean and `N` stand beside it.
- **Runs of one case are correlated in some skills.** The median correlation between runs of one case is 0.04, but the upper quartile is 0.67: in some skills one case fails every time. The cases are few (2 to 6 per skill), so a skill's mean says how it does on those cases.
- **Partial tests are chosen by the person who made the change.** A change can break a case nobody thought to run. Protections: the guard cases always run, guard cases alone do not return a skill to `reliable`, the third Y change since the newest full test asks for a full test, and the gate is never moved by a partial test.
- **A no-op Y change resets the gate's pool.** The gate reads the runs of the `X.Y` of the newest full test, so a maintainer could raise Y with nothing changed and draw again. It costs a full test each time and shows in the version file.
- **A case can be deleted and written again.** A case that runs badly can be removed and added under another id, which discards its runs. The rule for case changes asks for the reason of every deleted and added case in the pull request, and the code owner reviews it; nothing mechanical stops it.
- **A closed event is only written if its file is committed.** The rule that an abandoned full test keeps its lines holds for whoever follows it: the file is in the run folder until someone commits it.
- **Nothing proves that a lab line was written by the runner.** The fingerprint in each line, the code owner's review and the rule that the maintainer runs the tests on the reference model are the protection.
- **Field evidence is selected and self-reported.** That is why it promotes nothing.
- **A verdict is coarse and kind.** One word from a person who wants to move on is not five designed assertions.
- **Per-model evidence is thin at first.** Every model other than the two of the gate file starts with field counts only.

## Deliberately left for later

- **Field evidence promoting a skill.** Once recorded uses can be compared with verdicts (how many uses end with none, whether verdicts agree with lab results on the same version), a rule that lets field evidence count toward `reliable` can be written with data. Until then it does not.
- **Numeric decays.** A decay per Z change, per changed context and per measurement step needs a history of classified changes to calibrate. The cap does the work meanwhile.
- **Compaction of old evidence.** One line per run is small; nothing is compacted, so the gate can always be computed again from the lines (MM1).
- **A score per platform.** Mean and number of runs until a platform has enough cases.
- **Replaying sampled field tasks on other models.** The task and its files would stay in the project and the replay would run there, in the container; only the resulting lines would travel. Not before the table has field evidence to sample from.

## What changed from version 1 and why

One line per finding of the review.

| Finding | What version 2 does |
|---------|---------------------|
| MB1. A guard had to exist and to have run, never to pass | The tag is on the assertion; every guard assertion must have run, and must have no confirmed failure, in the with-skill runs of the current set, or the band is `needs a test`; guard cases run on every Y change; one guard per declared effect, an error when missing; CI does not fail on the band (section 4) |
| MB2. The Z class could not be verified and accepted behaviour changes | Z is an allow-list, written from the positive side, with a budget in characters; a description change is Y; stop rules live in their own section (section 3) |
| MB3. Any change followed by a targeted test erased a case's bad runs | The gate is evaluated only by a full test, on one version; a partial test moves the score only (section 2) |
| MB4. Field evidence entered the same sum | Bands and scores come from lab evidence only; field evidence has its own columns, can demote, never promotes; `record --start`; no `count`; a maximum weight per contributor (section 7) |
| MI1. The score is not a calibrated bound | Called the pessimistic score; always shown with the mean and `N`; the run stays the unit (section 6) |
| MI2. The bands were the three states renamed; 0.45 and 0.50 decided nothing | The bands are stated as rules; `reliable` needs a score of 0.70; the 0.45 gives way to "the gate fails" (section 5) |
| MI3. A decay only shrank `N` | Inherited evidence is capped at 3 runs, all of it together; nothing is carried across a major version (section 6) |
| MI4. A new reference model or grader was a full test of everything, unsaid | Said in the cost table; the grader is separate and fixed; inherited evidence, with-skill runs and a sampled baseline for a new reference model, at a cost stated as a range; a re-graded sample for a new grader (section 9) |
| MI5. The 0.8 per measurement step was wrong both ways | Three kinds of measurement change, no factor (section 8) |
| MI6. The baseline ages with the model, the measurement and the case, not with the skill | The baseline is reused until one of the three changes; an X change runs with the skill only (section 2) |
| MI7. The X class was too coarse | X is `side_effects`, removals and renames, the gate, the stop rules and the external-content rule; additions are Y (section 3) |
| MI8. The conversion of the 48 records kept nothing | No conversion; the old records stay as history (section 1) |
| MI9. Two files conflicted in every evidence pull request | One file per test event; the tables are a snapshot that no pull request must regenerate; one comparison base in the hook and in CI; an idempotent bump (sections 1, 3, 10) |
| MI10. Model ids were free text | A list of known models with aliases; `unknown` for the rest (section 1) |
| MI11. Items kept as written whose object had gone | A timeout after the cap is a line with score 0 in both variants; stub runs write to a scratch tree; the plan restates each item (section 1; the plan's phase B) |
| MI12. Lab evidence had no provenance | The fingerprint in every line; the runner's refusal kept; `CODEOWNERS` extended; the maintainer runs the tests on the reference model (section 8) |
| MI13. The order of work did not close | The plan's order: the hash, then the version rules with a migration; `1.0.0` in one sweep; the smoke pass writes no evidence |
| MI14. Dependencies decayed nothing; holes in the gate rule and in the case hash | `context_sha256`; the gate over lines of weight above zero with every current case required; an added case `pending`, a changed case through a full test; the case hash over the whole case (sections 1, 2) |
| MM1. Compaction lost the case | No compaction |
| MM2. A day in a contributed file | The week, in field lines |
| MM3. One line of a shared script moves every carrier to `watch` | Accepted; the carriers change in one pull request (cost table) |
| MM4. The validator never read the version | The raw text is checked against `^\d+\.\d+\.\d+$` (section 3) |
| MM5. A score for a model with only field evidence | Counts and mean, no score (section 7) |
| MM6. The effect of the field block was never measured | One smoke case carries it (section 7) |
| MM7. One measurement step put two-case skills in `watch` | Moot: no factor per step |
| MM8. The places that name the old states were undercounted | The plan lists them all (its item A17 and row 16) |
| MM9. One decision in two tables; the floor model | The plan is one document; the floor model runs with the skill only and no rule reads its rows |

The points of the reading of the pull request that carried version 2, one line each. The minor ones are listed after the table.

| Point | What the model now says |
|-------|-------------------------|
| P1. Z was still a list of places a change may not be, and it accepted `references/` and `## Gotchas` | Z may occur only in `## Purpose` and outside any section that instructs; negation and order words join the word list; characters are counted per changed span (section 3) |
| P2. The guard rule was noisy, could be drawn again, and asked 39 skills for nothing | The rule reads every with-skill run of the current set; a failed verdict is graded once more; a confirmed failure is cleared only by a change; a warning for a guard that cannot fail and for a skill with the external-content line and no guard; guard cases alone do not return `reliable` (sections 4, 5) |
| P3. The plan and the model disagreed on three rules | One rule each, in both: the field weight is per contributor (section 7); only an added case completes the gate alone (section 2); an abandoned full test keeps its lines (section 2) |
| P4. "On the current `X.Y`" is not "in the current set" | The current set is defined once and used in the three rules; everything inherited is capped at 3 runs together (terms, sections 4 to 6) |
| P5. The exception for a changed case allowed a new draw and did not serve after a Y change | An added case is `pending` and moves no band; a changed case enters through a full test (section 2) |
| P6. The field signal had no start, read every model, and an account name went into a file name | Counted since the newest lab event of the current `X.Y`, on the reference model; the contributor is read from git and never stored; the owner's own failures are not capped at one (section 7) |
| P7. Section 9 used inherited sets section 6 did not define; 624 runs is a floor | The four inherited sets are named in section 6 and the grader is a key of the event line; the cost is 624 to 957 runs; the grader sample's reason is restated with the measured 96% (sections 1, 6, 9) |
| P8. What the tools do between two items of the plan | In the plan (its items A17 and B7) |
| P9. Nothing kept the tags from the grader | The grader is given an assertion's text, never its tags (section 4; the plan's item B3) |
| P10. Nothing made every case run on the current text | Y changes are counted since the newest full test; at the third the band is `watch` until a full test (section 5) |

Minor points, each applied: a timeout has one path to a score of 0, the cap of resumptions (section 1; the plan's default 16); the gate when no baseline is in force, and a full test being full by the reference model (section 2); the fingerprint in the list of what CI fails on, which lives in one place, as the cost table does (section 5; "What a change costs"); the band's name, `needs a test`, with its cause beside it (section 5); three parts removed: the evidence carried across a major version, the count of Y changes without lab evidence, and the key `model_revision`, which no rule read.

The twelve questions version 1 left open, as answered:

1. **Rules beside the score:** kept, and said to be rules; the cap and a threshold that means something replace the idea of counting decayed weight as trials.
2. **An X change asks for a full test:** too expensive as written; X is narrower, and its full test reuses the baseline.
3. **The unit:** the run. In the lab the interval is too wide, not too narrow; the case as unit would give 2 to 6 trials.
4. **The thresholds 0.50 and 0.45:** `reliable` at 0.70; the 0.45 is replaced by "the gate fails on the current evidence".
5. **Ten field uses to return to `reliable`:** no. Lab runs are required: the affected cases and the guard cases.
6. **The Z class and its 15 lines:** an allow-list and a budget in characters.
7. **`measurement_floor` at 5:** yes, and nothing is converted: there is nothing comparable to keep.
8. **The trigger through the instruction file:** not alone. A use is recorded at its start, by a hook or by the runtime; field evidence stays out of promotion.
9. **The hash of older versions:** kept, in the append-only version file.
10. **A baseline on other models:** not by default; an option remains.
11. **One grading pass:** yes. Grading the same replies again is cheap and is used only where it matters: to confirm a failed guard verdict, to measure the grader's disagreement in the pilot and to compare a new grader.
12. **A decay never asked for a test:** now a change does. No skill leaves `watch` without lab runs, and the third Y change since the newest full test asks for a full test.
