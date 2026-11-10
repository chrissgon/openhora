## 2026-11-09: HyperFrames in CI, the `hyperframes` job and the paths of the docker jobs (V3c-2; no measurement change, no skill changed, no lab run)

**What.** `.github/workflows/checks.yml` gains a job `hyperframes` (D7 of the V3c spec, as recommended) and a `changes` output of the same name. The job runs on
`ubuntu-24.04` with a 90-minute bound; it builds the common image (`ffmpeg.py build --confirmed --platform linux64`, 900 s per attempt) and the HyperFrames image
(`hyperframes.py build --confirmed`, 1800 s per attempt, no `--arch`: a build is for the daemon's own architecture), each through `scripts/ci_retry.py --attempts 3
--delay 120`, then `hyperframes.py --check` (the amd64 selfcheck), then `WB_HYPERFRAMES_DOCKER_TESTS=1` over `test_engine_contract_live.py` and
`test_hf_docker_live.py`. `test_hf_tier_a_live.py` is never run there (it fails without its survey variables).

**The paths.** `hyperframes` is true for `providers/renderer/`, `providers/*.py`, `shared/references/video-presets.json`, `shared/references/platforms/instagram.json`,
`skills/mkt-social-copy/scripts/check_script.py`, `scripts/ci_retry.py` and the workflow itself, and in the four whole-suite cases; false on a draft. `renderer`
gains the three shared files every render reads (they were in no docker path) and, through a new `touched_but` helper, no longer starts for a change inside
`providers/renderer/hyperframes-image/` alone (the V1a OPEN-9 hand-off: that change built the common image for nothing). `scripts/tests/test_checks_wiring.py` covers
the new job (needs, condition, build order, retry bounds, state folder, no survey test) and every row of the changes table. Departure from the spec text: the
patterns write `.` where the spec wrote `[.]`, because `test_every_path_a_workflow_names_exists` reads a path ending in `[.]json` as a path that does not exist;
`.` matches the same files.

**Gate (STOP 1).** The job's first run is the first amd64 build of the HyperFrames image. It downloads, on GitHub's runner: the base image by digest; Debian
packages from `snapshot.debian.org` (dated `20261006T000000Z`); the amd64 static ffmpeg from `github.com/BtbN/FFmpeg-Builds` (size `null` in `pins.json`, sha256
`26d2ecd0...fca5b0`, copied from HyperFrames' own Dockerfile and never downloaded); the linux64 headless shell from `storage.googleapis.com` (124,203,329 bytes,
sha256 `39dcb8c4...278786`); the npm packages of the lockfile from `registry.npmjs.org`; the registry's `LICENSE` from `raw.githubusercontent.com` at the pinned
commit. A sha256 mismatch stops the build; nothing is re-pinned. The pull request stays a draft (a draft runs no docker job) until the maintainer says yes.

**First amd64 build (run 42721633048, ubuntu-24.04 amd64, at head 36073413).**

- The `hyperframes` job was green.
- The common image built in 66 s and the HyperFrames image in 45 s, both through `ci_retry`.
- `hyperframes.py --check` (the selfcheck) was ok.
- The HyperFrames legs took 14.7 minutes.
- In the same run the `renderer` job failed F3[ffmpeg]: nondeterminism at 4 frame threads, found here and fixed by V3c-3 (`2026-11-09-v3c-3-x264-one-thread-compose.md`).
- The run after the merge of V3c-3 into this branch is the first of the `hyperframes` job with sliced threads: its result is (see the PR's checks).

**Cost (principle 13).** Saved: the HyperFrames image is built and its legs run in CI, so the amd64 items V3a-image left open can close; a change inside its folder
stops building the ffmpeg image. Given up: up to 90 CI minutes of a docker job per change to the renderer paths, and a docker job on a change of the three shared
files that previously ran none. No measurement change, no skill changed, no lab run.
