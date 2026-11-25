## 2026-11-25: CI-1b, the renderer and hyperframes jobs split into legs balanced by measured time (CI-1; no model call, no lab run, fingerprint unchanged)

**Context.** CI-1a (`docs/decisions/2026-11-24-ci-1a-selection-everywhere.md`, merged as b97d101d) moved the live jobs into `.github/workflows/live-jobs.yml` and made both live steps print every test's duration (`-rA --durations=0`). On its own run (45537114876, 2026-11-25) `live / hyperframes` took 18.3 minutes (pytest: 8 passed, 19 skipped in 961.9 s) and `live / renderer` 603.3 s of tests (15 passed, 17 skipped), so the `hyperframes` job was the critical path of a video pull request. The maintainer approved item 1 of CI-1 on 2026-11-24: split the live tests of both jobs into parallel jobs, balanced by measured time.

**Decision.** `renderer` becomes a matrix of 3 legs (`k_r` = 3) and `hyperframes` a matrix of 5 legs (`k_h` = 5), `k_r + k_h` = 8, the concurrency budget. `fail-fast` is off. Each leg checks out, names its own state folder, builds its own images through `scripts/ci_retry.py` with the same command lines as before, and runs `pytest -q -rA --durations=0 $TARGETS ${LEGS:+-k "$LEGS"}` with the same environment variable as the unsplit job (`WB_RENDERER_DOCKER_TESTS=1`, `WB_HYPERFRAMES_DOCKER_TESTS=1`), so which parameter runs in which job does not change. Only the renderer leg whose targets hold `test_transcriber_docker_live.py` builds the transcriber image. Every `-k` word ends with `_`, so `test_f1_` never matches `test_f10_`.

**Measured durations (call phase, seconds; no setup or teardown line reached 2 s), from run 45537114876.**

| Job | Test | s |
|---|---|---|
| hyperframes | F3 | 255.8 |
| hyperframes | F9 | 197.8 |
| hyperframes | F1 | 127.3 |
| hyperframes | F2 | 112.3 |
| hyperframes | F5 | 86.5 |
| hyperframes | F6 | 86.2 |
| hyperframes | F8 | 84.2 |
| hyperframes | F7 | 11.7 |
| renderer | preview of a 60 s render (renderer file) | 88.5 |
| renderer | F4 | 84.8 |
| renderer | F3 [ffmpeg] | 84.5 |
| renderer | F10 [ffmpeg] | 82.6 |
| renderer | composed recording (renderer file) | 52.2 |
| renderer | F9 [ffmpeg] | 49.5 |
| renderer | two-stage encode (renderer file) | 49.0 |
| renderer | F1 [ffmpeg] | 48.3 |
| renderer | F2 [ffmpeg] | 33.2 |
| renderer | F7 [ffmpeg] | 10.9 |
| renderer | F5 [ffmpeg] | 10.5 |
| renderer | proxy 1080x1920 (renderer file) | 4.6 |
| renderer | host check (renderer file) | 3.8 |

Estimates, not measured on CI (supervisor's figures from the maintainer's Mac, for the changes of PF-a4a, #840): `test_f11_` [ffmpeg] 60 s and the new `test_f5_` [ffmpeg] 45 s (it was 10.5 s as a refusal), `test_f5_` [hyperframes] unchanged near 86 s. The PR's own run replaces them. Fixed costs of a leg, measured: hyperframes about 132 s (checkout, common image 74 s, HyperFrames image 47 s, `--check`, setup); renderer about 126 s with the transcriber image (90 s) and about 36 s without. The target is the larger of 7 minutes and the longest `tests shard k of 6` (1.8 minutes), that is 420 s.

**The groups (LPT, longest unit first into the group with the smallest total).** The provisional groups of the spec were not kept: they differ from the measured assignment by far more than 15 percent (the provisional renderer group 3 alone would hold about 371 s of tests, once F11 is counted).

| Job | Group | Targets | `-k` | Estimated tests, s | With the leg's fixed cost, s |
|---|---|---|---|---|---|
| renderer | 1 | the renderer docker file and the transcriber file | none | 198.1 | about 324 |
| renderer | 2 | the contract file | `test_f4_ or test_f11_ or test_f9_ or test_f5_ or test_f7_` | 250.2 (F4 84.8, F11 60 est., F9 49.5, F5 45 est., F7 10.9) | about 286 |
| renderer | 3 | the contract file | `not (...)` the words of group 2: F1, F2, F3, F6, F10 and whatever is added later | 250.6 (F3 84.5, F10 82.6, F1 48.3, F2 33.2, F6 under 2) | about 287 |
| hyperframes | 1 | the contract file | `test_f1_ or test_f3_` | 383.1 (F3 reuses F1's renders, so they stay together) | about 515 |
| hyperframes | 2 | the contract file | `test_f8_` | 84.2, plus F1's render 127.3 made again = 211.5 | about 344 |
| hyperframes | 3 | the contract file | `test_f9_` | 197.8 | about 330 |
| hyperframes | 4 | the contract file | `test_f2_ or test_f7_` | 124.0 | about 256 |
| hyperframes | 5 | the contract file and `test_hf_docker_live.py` | `not (...)` the words of groups 1 to 4: F5, F6 and whatever is added later | 172.7 | about 305 |

The renderer file group stands alone because a `-k` expression applies to every file of a command, so a group that mixes whole files with selected legs would drop the whole files.

**The 7-minute target is met by the renderer legs and not by `hyperframes` group 1.** F3 (255.8 s) is only that cheap after F1 has made its renders (127.3 s); apart from F1 it would cost the same sum, so no `k` shortens the group: F1 and F3 together are about 383 s plus 132 s of builds, about 8.6 minutes, against 420 s. Rule 4 of the spec (when the target cannot be met, take `k_r + k_h` = 8 and report) was followed: `k_h` = 5, though the makespan would be the same at `k_h` = 3, so legs 4 and 5 buy only shorter siblings. Splitting F3 itself would need an edit of the live module (E8) and is left to PF-b, which deletes the `hyperframes` job. The expected critical path of a video pull request is therefore about 8.6 minutes plus queue (estimate; section 11 step 4 of the spec measures the real one), against 18.3 minutes before.

**The coverage oracle.** `test_the_live_legs_together_collect_exactly_what_one_job_collected` in `scripts/tests/test_checks_wiring.py` collects, offline and at the same time, the items of the unsplit job (the files of the old step, written literally in the test) and of every leg, and asserts that the union of the legs equals the unsplit collection, that no item is in two legs, that every leg holds an item it can run, that the transcriber image is built exactly by the leg that holds its file, and that the job names say the real number of legs. Its vacuity test plants a dropped `-k` word, an item in two groups, a dropped file, a wrong transcriber flag, a wrong count and a complement that no longer complements, and each is caught. A change to the live module selects that test, so a new test or a new leg is checked on the pull request that adds it. The last group of each job is the complement of the others, so a test added later (F11 of PF-a4a, F12 and so on) lands there and is never lost.

**No image cache.** Each leg builds its images from the pinned definition (a real build, 0.4 to 1.5 minutes each). A cache or a hand-off of images would need the providers' build verbs to change (the tests read the build's record in the state folder, which a loaded image lacks), outside CI-1's files, and a cache shared across pull requests is an input a pull request could poison. What it would save is 0.5 to 1.4 minutes per leg, which does not clearly exceed that (principle 13). What this accepts: about 3 to 4 times more requests to the snapshot archive per run, which `ci_retry.py` (3 attempts, 120 s) absorbs.

**Saving and loss.** Saving: a video pull request waits for the longest leg instead of the whole job, about 8.6 minutes instead of 18.3 (estimate). Loss: more runner jobs per run (8 legs instead of 2 jobs), a first leg that may wait up to about 2 minutes behind the 20-job limit, more archive requests, and more steps to read when a leg fails.

**What PF-b deletes.** The `hyperframes:` job (its matrix included) and its input in `live-jobs.yml`; the matching lines of `checks.yml` and `nightly.yml`; `"hyperframes"` in `DOCKER_JOBS` and `UNSPLIT` of `test_checks_wiring.py`. The renderer groups need no edit: their last group is a complement, so the `[hyperframes]` items it collects and skips go with the parameter, and the oracle confirms the union.

**Not changed.** The required checks `validate` and `tests`, the branch protection, which parameter runs in which job, `test_hf_tier_a_live.py` (never run), the timeouts (60 and 90 minutes).

**Verified.** The oracle and its plants pass offline; the whole `test_checks_wiring.py` passes. **Not verified.** The real time of each leg, the queue under the 20-job limit, the sums of passed and skipped over the legs (renderer 15 and 17, hyperframes 8 and 19, before PF-a4a's items) and the set of passed node ids against CI-1a's run: only this pull request's own run shows them.
