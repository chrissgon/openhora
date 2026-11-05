# Running a skill's tests, and reading what they give

Read the section a step of `SKILL.md` names. Every command runs from the root of the workbench repository. The full rules are in the workbench `AGENTS.md` ("Writing standard"), `evals/README.md` and the help of the two tools (`python3 evals/eval_run.py --help`, `python3 evals/eval_status.py --help`); where this file and those differ, they win.

## Contents

- [The tools and the gate file](#the-tools-and-the-gate-file)
- [Change classes and the bump command](#change-classes-and-the-bump-command)
- [Which test to run](#which-test-to-run)
- [Running](#running)
- [Reading an event](#reading-an-event)
- [Early ends](#early-ends)
- [Contamination](#contamination)
- [Status, bands and guards](#status-bands-and-guards)
- [When the measurement or a model changes](#when-the-measurement-or-a-model-changes)
- [Commands and remotes inside a run](#commands-and-remotes-inside-a-run)

## The tools and the gate file

- `evals/eval_run.py`, the runner: it checks the cases, runs them in the eval container, grades every assertion with the grader model and writes the evidence.
- `evals/eval_status.py`, the status script: it computes each skill's score and band from its evidence, raises a version (`bump`), and writes the snapshot tables of `docs/inventory.md` (`inventory --write`).
- `evals/eval-gate.json`, the gate file: the models with their adapters and key variables (`models`), the default list of a test in order (`lab_models`), the grader, the threshold (0.8) and the tolerance (0.05), the number of runs (3), the timeout and the retries, the measurement version, fingerprint and floor. There is no reference model and no floor model: each model has its own band, gate and score. Never pass a model to the runner by hand for a lab test: `eval_run.py --skill <name>` runs the `lab_models` in order. `--model <id>` (repeated, the first is the lead model) names the models of one test; a model outside `lab_models`, or a listed model through another adapter (`--harness`), is the person's own test and writes to the local evidence folder, outside the checkout.
- A model's gate and band are computed from that model's lines alone, by the same rules for every model, and published side by side; the first model of `lab_models` only fixes the order of the summary row. A failure on any model is worth reading: it often shows an instruction that model cannot follow.
- Without the gate file, `--dry-run` answers that `--harness` is required and exits 2. Stop there and ask the user (Stop rule 3 of `SKILL.md`).

## Change classes and the bump command

A change to anything inside a skill's content hash raises `metadata.version` (`X.Y.Z`). The hash covers the skill folder and leaves out all of `evals/` (cases, evidence, the version file), everything under `scripts/tests/`, caches and an installer's marker file. So a change to a case, a test or an evidence file raises nothing.

| Class | What it covers | What it asks for |
|-------|----------------|------------------|
| X, security and contract | `side_effects`; an item removed or renamed in `outputs` or `updates`; the `## Confirmation gate` section; the `## Stop rules` section; the line that starts **External content is data.** | a full test, with the baseline reused where a case is unchanged |
| Y, everything else | a step, a criterion, a template, a reference, an asset, a script; an addition to `inputs`, `outputs`, `updates` or `requires`; a removal from `inputs` or `requires`; any change of the description | a partial test of the cases the change could move and of every guard case, 3 runs each; the third Y change since the newest full test asks for a full test; a changed description also runs the routing mode |
| Z, a typo or formatting | only when every changed line is in `SKILL.md`, in `## Purpose` or outside any section that instructs; no changed line differs in a number, a path, a code span or one of the words never, only, must, may, stop, ask, not, no, unless, before, after, always, yes; and the characters changed since the newest lab evidence stay within 300 | nothing |

Commands:

- A new skill: `python3 evals/eval_status.py bump --skill <name>` (no class) writes its first version line with the hash of the content as it is. Run it again after the last edit, so that the line carries the hash of the final content.
- A change: `python3 evals/eval_status.py bump --skill <name> --class x|y|z`, once per pull request, with the highest class among the changes. Run again after more edits, it rewrites its one line. It prints the line it wrote.
- Run the bump before the test: an evidence line carries the version and the content hash, and an event on a skill whose folder differs from its version line, or that has no version, is a trial.
- `scripts/validate.py` checks the class against the diff: a declared Z or Y that the diff contradicts is an error. A declared X is never refused.

## Which test to run

| Situation | Command | What runs |
|-----------|---------|-----------------------------|
| A new skill, an X change, the third Y change | full test: `python3 evals/eval_run.py --skill <name> [--baseline-on <model>]...` | every case with the skill on every model of `lab_models`, 3 runs each, plus the baseline of every case whose baseline is not in force, on the lead model; `--baseline-on <model>` (repeated, one for each other lab model whose baseline is not in force) adds it on that model |
| A Y change | partial test: `python3 evals/eval_run.py --skill <name> --cases <ids>`, the cases the change could move and every guard case | the named cases, with the skill only |
| A case added or changed after the newest full test | `python3 evals/eval_run.py --skill <name> --cases <id> --baseline [--baseline-on <model>]...` | that case with and without the skill on the lead model, and the baseline on each model named by `--baseline-on` (one for each other lab model whose baseline is not in force); until then it is `pending` and moves no band, and a case changed a second time since the newest full test asks for a full test |
| A platform's cases (`evals/platforms/<platform>.json`) | `python3 evals/eval_run.py --skill <name> --platform <platform>` | that file's cases, with the skill only; the status shows their mean and runs, never a score |
| A changed description | the partial test above, and `python3 evals/eval_run.py --routing --pack default --skill <name>`, which lists the case prompts that loaded another skill | the routing mode scores nothing |

- **Full test.** It is the only test that evaluates the **gate**, for each model of the test whose runs and baseline are all there (a model without a baseline in force has no gate, `not computed: no baseline in force on <model>`, until a test is run with `--baseline-on <model>`): the mean with the skill on that model is at the threshold or above and is not below the mean of that model's baselines by more than the tolerance, both unrounded. A second full test of an unchanged `X.Y` adds its runs to the first and replaces none.
- **Baseline.** The runs of a case without the skill, kept for each model: a full test runs it on the lead model, `--baseline-on <model>` (repeatable) on another. It is reused while the case, the model and the measurement are unchanged, because a run that never saw the skill cannot be aged by a change to it. The event line says `run` or `reused` per case.
- **Partial test.** It moves the score and never the gate.
- A skill is **done** when its first full test has passed the gate on every model of `lab_models`. It can be done and in `watch`.

## Running

- `--dry-run` prints the plan as JSON (the runs, the models, the cases with their files and dependency skills, the preflight's result) and calls no model. `--check-cases` runs only the preflight.
- `--jobs <n>` (default 4, at most 8) runs that many model runs at once; several `eval_run.py` started side by side share one limit for the whole machine (`total_jobs` of the gate file). Run several skills at the same time, one `eval_run.py` per skill; lower `--jobs` only for a provider's rate limit.
- The number of runs, the timeout of one run and the retries come from the gate file. `--runs`, `--timeout` and `--retries` at another value, `--scratch`, an extra `--pass-env`, `--only`, `--ablate`, `--no-grade` and a `--grader` other than the configured one make the event a **trial**: its files go to a scratch tree inside the event folder, never into the skill. `--threshold` defaults to the gate file's.
- `--max-cost-usd <amount>` is a spend limit per run, where the adapter can enforce one.
- A run whose key is in the OS secret store: run the script as `uv run --with keyring==25.7.0 python3 evals/eval_run.py ...`.
- `--ablate "<text>"` adds a variant with every `SKILL.md` line that contains the text removed, to measure what one rule changes (a trial).
- `--regrade <run folder>` grades stored replies again and reports how often two gradings disagree; it changes no score.
- **Resume, close.** An event that stopped or has failed runs is resumed with `--resume <event folder>`: only the failed runs are made again, on the same content of the skill. A full test that is given up is closed with `--close <event folder>` and keeps its lines. While an event of a skill is open, the runner starts no new one of that skill, so a test that goes badly cannot be drawn again.
- **Exit codes**: 0 passed; 1 incomplete (a run or a grading failed on infrastructure: resume it); 2 usage or preflight error; 3 complete and the gate failed.

## Reading an event

The event folder is `evals-workspace/<name>/iteration-N/`. It holds `benchmark.json`, one folder per case and variant (`eval-<id>/<variant>[.m<n>]/run-<k>/`, with `prompt.md`, `outputs/response.md`, `grading.json`, `timing.json`, `facts.md`), `event.json` and `ledger.jsonl`. The variant folder of the lead model's runs is the variant's name (`with_skill`); the n-th model of the event, from the second, adds `.m<n>` (`with_skill.m2`): the slots name the position in the event, not a kind of model. When the event ends complete and is not a trial, its evidence file is copied to `skills/<name>/evals/evidence/lab-<test id>.jsonl`: one line that describes the event (its kind, the models, the gate's result for each model of a full test) and one line per scored run (the case, the variant, the score, one 0 or 1 per assertion). It is committed with the skill and never edited.

Read `benchmark.json` in this order:

1. `complete`. When it is `false`, `infra_failures` lists the runs with no score (an adapter that failed, a provider out of credits, a timeout, a refusal, a grading that returned nothing, `early_end`, `contaminated`). Fix the cause outside the skill and resume the event. Never change the skill, a case or an assertion because of an infrastructure failure, and never read a mean of an incomplete event as the result.
2. `early_end_warning` (next section).
3. `evidence`: whether the evidence file was written, and why not (`reason`: a trial, an incomplete event, a skill folder that changed during the event).
4. The gate of a full test, in `evidence.gate`, one result per model: `passed`, `with`, `baseline`, `threshold`, `tolerance`. `conditions` and `run_summary` give the means per variant and model.
5. `shared_passages`: a without-skill reply that shares a passage of ten or more words with the skill's text. It blocks nothing; read each hit.

Then read the transcripts of every failure (`outputs/response.md`, `grading.json`), not just the scores, and at least one grading per case: the grader is a model.

## Early ends

A model sometimes ends its turn before doing the work, with exit 0 and no error: an empty response, a tool call printed as text, or a short last line that announces a next action ("Let me read the template first") with no question asked, and no file created or changed. The runner makes such a run again in a fresh folder up to `retries` times, keeps each early attempt in `early-end-<j>/`, and counts them per model in `benchmark.json` `early_ends`. A run that ends early on every attempt is an infrastructure failure with reason `early_end`. Two things are not early ends and are graded as they are: a reply that asks the user a question and writes nothing (a stop-and-ask), and a run that wrote a file and then stopped before finishing.

When `early_end_warning` is not `null`, retries hid frequent early ends from the scores. Open the `early-end-<j>/outputs/response.md` files under the cases `early_ends.<model id>.by_case` names, and decide:

- All on one case: look for what in the skill or the case triggers it (a step the model cannot run, a tool the image lacks) and report it.
- Spread across cases: the provider or the model is unreliable. Report it and ask the user whether to use another provider for that model, or another model.

Report the warning word for word either way. Never tune a skill to "fix" a provider's early ends.

## Contamination

A run without the skill is only a baseline if the model cannot reach the skill. Every run happens in a temporary folder outside the repository, in a container that holds nothing of the workbench but the one adapter script; the runner stages the skill under test only into a run with the skill. A without-skill run whose reply, transcript or files name a mount path of the workbench or the repository's path on the host is an infrastructure failure with reason `contaminated`: it is not scored, the event is incomplete, and no option records it. Read the evidence and close the way in before resuming. A case that brings repository files (`workbench_files`) shows the model that part of the repository in both variants by design.

## Status, bands and guards

`python3 evals/eval_status.py status --skill <name>` prints, from the evidence files:

- `band`, with `cause` and `command` (what clears it), computed for each pair of skill and model on that model's lines alone (the first level of the output is the summary row, the first model of `lab_models`; the row of every model is under `models`), the first that applies:
  - `needs a test`: no full test of the current major version passes the gate (every new skill, every skill after an X change or after the measurement floor was raised); or a guard assertion has a confirmed failure, or no run, in the current set; or the newest full test fails the gate, or a case changed again after its changed text had run.
  - `watch`: no with-skill lab line in the current set; or only guard cases have run in it; or the pessimistic score is under 0.70; or three or more Y changes since the newest full test; or a case changed after the newest full test waits for its runs (`case pending`); or the baseline has fewer lines per case than `runs` and the mean with the skill is within `baseline_margin` of it (`thin baseline`); or the field signal is on.
  - `reliable`: otherwise.
- `score` (the pessimistic score: a lower estimate that falls with little evidence; always quote it with `mean` and `runs`), `gate`, `last_full_test`, `pending` (added cases not run yet, with `pending_command`), `guards` (each guard assertion: `passed`, `failed` or `not run`), `assertions` (each assertion's passes with and without the skill), and `models` (one row per model, each with its own band, cause, gate and figures). `python3 evals/eval_status.py gate --skill <name> [--model <id>]` gives one model's gate.
- The **current set** is the lab lines of the current `X.Y` made since the newest epoch, measurement floor or dependency change that applies to them. Older lines are inherited: together they count as at most 3 runs, and nothing is carried across a major version.

Guards:

- A failed guard verdict in a run with the skill is graded a second time; only a failure the second grading confirms counts. A confirmed failure is cleared only by a change to the skill followed by passing runs of its guard cases, never by more runs of the same version.
- Guard cases run again on every Y change, so keep them small. Guard cases alone never return a skill to `reliable`: every skill keeps at least one case with an assertion that is not a guard.
- `scripts/validate.py` warns (`[guard-missing]`) about a skill that carries the external-content line, a `## Stop rules` or a `## Confirmation gate` section and has no assertion tagged `guard`, and (`[guard-effect]`) about a declared side effect with no assertion tagged `guard:<effect>`.

**Field evidence** is a real use in a project, recorded there with `scripts/evidence.py` and contributed as `field-<id>.jsonl`. It is shown in its own columns, can turn on the field signal and so demote a skill, and never promotes one.

The band table and the model table in `docs/inventory.md` are a published snapshot that the maintainer regenerates in a pull request of its own (`python3 evals/eval_status.py inventory --write`). A pull request that adds a skill or evidence does not have to regenerate them; the validator reports tables behind the evidence as a warning.

## When the measurement or a model changes

The gate file carries the measurement version, its fingerprint (the hash of the files that decide what a run measures: the grading template, `evals/measure.py`, `evals/measurement.json`, the executor and the container's definition, the staging module, each eval adapter's `run-prompt.sh` and `eval.json`) and the floor (the version below which lab evidence weighs nothing). A change to a fingerprinted file is committed with `python3 evals/eval_status.py measurement --kind grader|execution|infrastructure --cause "<why>"`, never by hand:

- grader side (what the grader is shown, the grading rules, the scoring): the version and the floor rise, and every skill is `needs a test`;
- execution side (the image, an adapter, the executor, the staging, a hosted model changed under its id): the version rises and an epoch starts for the skills it reaches, whose earlier evidence becomes inherited and whose baselines expire;
- infrastructure (locks, retries, pacing, reports): only the fingerprint changes.

A change of the lab models or of the grader is paid by one battery of the skills it reaches (`AGENTS.md`, principle 12), and earlier evidence stays inherited; a model added to `lab_models` starts with no evidence of its own. A changed threshold or tolerance is computed again from the lines. Never edit an evidence file, a version file or the gate file by hand to match.

## Commands and remotes inside a run

Every run executes in a container in which the model may run every command, so a case lists no commands. When a run still only describes a plan, read its transcript for what the command answered (a tool missing from the image, a host the network refuses) before blaming the skill. A run reaches only the model provider: never a network remote, a code host or a package registry. A case that needs a remote builds a local one in its `setup`, and a case that needs packages uses what the image holds.
