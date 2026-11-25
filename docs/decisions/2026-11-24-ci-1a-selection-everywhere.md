## 2026-11-24: CI-1a, the selected tests on every pull request and push, the whole suite once a day and on demand, six shards, and the live jobs in one reusable workflow (CI-1; amends TESTSEL 2026-10-20, T2b 2026-10-24, T4 and TEST-SPEED 2026-10-27; no model call, no lab run, fingerprint unchanged)

**Authority.** The maintainer's decision, 2026-11-24:

> "Vamos fazer do 1 ao 4. Porém no 4, vamos marcar uma rotina 1 vez por dia para rodar todos os testes. Se algo falhar, no maximo iremos identificar em 24hrs. Assim cada PR roda apenas os testes afetados" (validate: allow english-only -- the maintainer's own words, quoted)

In English: let's do 1 to 4; but in 4, a routine once a day runs all the tests; if something fails, at most we find it within 24 hours; that way each pull request runs only the affected tests. The four items: (1) split the live tests of the `hyperframes` and `renderer` jobs into parallel legs balanced by measured time (CI-1b, a later pull request); (2) go from 3 to 6 shards in `tests-shard` and `python39`; (3) leave the removal of the `hyperframes` job to PF-b; (4) the selection on every pull request, into `main` included, and the whole suite once a day.

His answer to the question M1, whether the live jobs run on a push to `main`:

> "Não, só PR e noite (Recomendado)" (validate: allow english-only -- the maintainer's own words, quoted)

That is option (a): no live job on a push to `main`; a live job runs on a pull request by path, and every one runs in the nightly run.

**What changes.**

| Event | Shards before | Shards after | Live jobs before | Live jobs after |
|---|---|---|---|---|
| Pull request into `main` | whole suite + full fuzz | selection | all five | by path |
| Pull request into another branch | selection | selection | by path | by path |
| Push to `main` | whole | selection (against the commit before the push) | all five | none |
| Manual run | whole | whole | all | all |
| Label `full-suite` | whole | whole | all | all |
| Draft pull request | none; `tests` red on purpose | unchanged | none | none |
| Nightly run, 06:17 UTC | whole list in 3 shards + python39 list | unchanged | none | all five |

`tests-shard` and `python39` run in six shards (`tests shard k of 6`, `python39 shard k of 6`). The five path-gated jobs (`container`, `converter`, `renderer`, `hyperframes`, `go`) moved, unchanged except for what the move needs, into `.github/workflows/live-jobs.yml`: `checks.yml` calls it with what the job `changes` found, `nightly.yml` calls it with every input true (`nightly-live`). The two live steps print every test's duration (`-rA --durations=0`) so that CI-1b can balance its legs from measured times. The `python39` choose step runs the whole list when its base is not in the clone (a force-pushed `main`), as the selector already does for every test folder. The `changes` job no longer reads a pull request into `main` as "everything".

**What it amends.** TESTSEL: the whole suite is no longer run "at the end of a delivery" but every night and on demand. T4: the whole `python39` list runs at the nightly run, on a manual run and with `full-suite`, no longer on a pull request into `main` or a push to `main`. T2b: the rule of the slow meta-tests is unchanged, but a pull request into `main` that touches no wiring no longer runs them by default (the nightly does). TEST-SPEED part B: three shards become six.

**Saving and loss (principle 13).**
- Saving: a pull request that touches no renderer path no longer waits for the live jobs (about 17.5 minutes before, estimated at 6 to 7 minutes now); the six shards halve the per-shard share. Runner minutes cost nothing on a public repository.
- Loss: a regression the selection cannot see (a dynamic import, a call chain beyond the reach depth, a Python 3.9-only break in unselected code) reaches `main` and is found by the next nightly run, up to about 24 hours after the merge. A live failure caused by a file outside the path filters, or by two pull requests merged close together, is found by the nightly run. The three slow meta-tests run on a pull request only when it touches the wiring. The release-time whole `python39` list goes.
- Accepted by the maintainer in the words above. Hard limits (principle 11) do not depend on the test selection.

**Measured before the change** (runs 45525988550, 45528301051 and 45511274647, from the `gh` job timings): `hyperframes` 17.3 to 17.4 minutes, `renderer` 11.3 to 12.4, `tests shard k of 3` 9.4 to 14.1, `python39 shard k of 3` 7.3 to 12.2; the run took 17.5 to 17.9 minutes. The six-shard and per-leg times are not measured yet: this pull request's own run prints them.

**Not changed.** The required checks (`validate`, `tests`), the branch protection and every repository setting; `WB_GENERATED_BLOCKS` (still strict on a push, a manual run, a pull request into `main` and a `batch/` branch); the nightly's three shards; the guards; the `renderer` and `hyperframes` jobs themselves (CI-1b splits them).

**Verified here.** Offline only: `scripts/tests/test_checks_wiring.py` (its oracle reads the new conditions, the six-shard matrix and launchers, the caller of `live-jobs.yml`, the nightly's `nightly-live`, the `changes` script on real repositories and the `python39` choose script with an unknown base, each with planted failures), the validator, the strict security scan and the selected tests.

**Not verified here.** That GitHub accepts `live-jobs.yml` as written (boolean inputs from `needs` outputs, `if: inputs.<x>` on a called job); that `gh attestation verify` in the `container` job works inside a called workflow and from the nightly's schedule; the live jobs' counts, durations and queue times under the 20-job limit; the six-shard times; the label paths (`nightly`, `full-suite`) with the reusable workflow. The pull request's own run shows these.
