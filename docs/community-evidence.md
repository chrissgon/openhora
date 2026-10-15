# Community evidence

A contributor can test a skill on a model the maintainer has not tested, with the contributor's own keys, and have the result count for everyone's choice of a model. The result is not trusted because a person says so: it is produced by the official workflow of this repository, running in the contributor's fork, and GitHub attests the file it wrote. This repository's CI verifies the attestation with no model call. The plan's decisions D19 and D36 and the review finding S5 are the reasons; `evals/README.md` ("Community evidence") states the rules in the project's words.

## What it is, and what it is not

- It is **evidence of the same kind as a lab test**, in a column of its own: `python3 evals/eval_status.py status` prints a `community` section, per skill and model, with the runs, the mean, the pessimistic score, the band and its cause, computed by the same rules on the community lines alone. It is never added to a lab figure, a band or a gate.
- It **ranks**: the runtime reads it for a person's choice of a model and for `auto`.
- It **never releases unattended work by itself** (decision D36). A pair that is `reliable` in the community column and not in the lab's carries `"community_only": true` in that section. The runtime chooses and uses such a pair, and holds its output for review, until the person's own tests or the lab prove it.
- It is **demoted** like any pair: three `failed` field verdicts on the current version put the pair in `watch`.
- It is **not** a way to run the maintainer's tests for the maintainer: the maintainer's tests stay lab evidence. They may move to the same attested workflow later.

## What you need

- A **public fork** of this repository (attestations of a public repository are free on every plan), with GitHub Actions enabled.
- The **keys as secrets of the fork** (Settings, Secrets and variables, Actions): the key of the model's provider, and the token of the grader's account, because every run is graded by the configured grader. The gate file (`evals/eval-gate.json`) names them: `pass_env` of the model's entry and `pass_env` of the grader's own entry. The workflow declares `OPENROUTER_API_KEY` and `CLAUDE_CODE_OAUTH_TOKEN`; a key never enters a run, each run's key proxy holds it. A request for a key that is not set is refused before anything runs, and only the name is printed.
- A **model of the gate file with a route**: a community run tests a listed model whose key a key proxy holds. A model that is not listed is added to the gate file in a pull request first.
- A **commit of this repository's `main`**: the workflow is referenced by its full commit sha. A commit that is not in the history of `main` is refused by the workflow and, later, by the check.

## The caller

Add this file to your fork as `.github/workflows/openhora-community.yml`, the one file name the check expects (the run numbers of a workflow count per file, so one file keeps the count whole; a fork that used another is flagged, and the manifest records the path). Keep it for good: see "Submitting". The caller workflow holds only the call to the reusable workflow, as below: any other job in it is read by the attestation job like the rest and must be on GitHub's own runners. Replace `<owner>/<repo>` with the official repository and `<sha>` with the 40-character commit of its `main` you chose.

```yaml
name: openhora-community
on:
  workflow_dispatch:
    inputs:
      skill:
        required: true
      model:
        required: true
      cases:
        description: "Case ids separated by commas, for a partial test"
        required: false
        default: ""
      full:
        description: "A full test: every case"
        type: boolean
        default: false
permissions:
  contents: read
jobs:
  test:
    # The called workflow cannot hold more than this job gives. Its model-running job asks for contents: read only;
    # only its attestation job uses the other three (actions: read, to read which runner the model-running job had).
    permissions:
      actions: read
      contents: read
      id-token: write
      attestations: write
    uses: <owner>/<repo>/.github/workflows/community-eval.yml@<sha>
    with:
      skill: ${{ inputs.skill }}
      model: ${{ inputs.model }}
      cases: ${{ inputs.cases }}
      full: ${{ inputs.full }}
    secrets:
      OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
      CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
```

The workflow's other input is `arch` (`amd64`, the default, or `arm64`; evidence from either is accepted) and `adapter`, which only makes the run refuse an adapter other than the one the model's entry names. You can run it from the Actions tab, or with `gh workflow run openhora-community.yml -f skill=<name> -f model=<id> -f full=true`.

## What the workflow does

Two jobs, and the line between them is the point:

1. **`run`** has `contents: read` and nothing else. It checks out **this** repository, never the caller's code, at the commit of the reusable workflow file itself, which is `job.workflow_sha` ("the commit SHA of the workflow file that defines the current job", in the contexts reference): inside a reusable workflow the `github` context is the caller's, so `github.sha` and `github.workflow_sha` name your fork's commit and would run your code under the official identity; `job.workflow_sha` is the commit you wrote after `@`, the same value as the `job_workflow_sha` claim of the identity token and the Build Signer Digest of the certificate. (`github.job_workflow_sha` is not a property of the `github` context and reads as an empty string.) The repository to check out is a literal in the attested file. It checks the checkout is exactly that commit and that the commit is in the history of `main`, checks the request and the keys, pulls the published eval image by the digest of the lock file (`python3 scripts/image_lock.py pull`), runs `python3 evals/eval_run.py` for one skill and one model, and packs the evidence file and a manifest (`scripts/community_pack.py`). There is no actions cache and no setup action.
2. **`attest`** is the only job with `id-token: write` and `attestations: write`. It checks out nothing and runs no code of any repository: it downloads the two files, compares their sha256 with what `run` reported, and reads this run attempt's jobs through the API (`actions: read`). The certificate of the attestation shows only the runner of the attest job itself, so it requires **every** job of this run attempt to have run in GitHub's own runner group (the group's name is `GitHub Actions` and its id is `0`: a self-hosted runner is in a group of its own, and a job with no runner fails the check too), and the job that ran the model (`lab test`) to be there once and to have succeeded. A decoy job of the caller on a self-hosted group therefore fails the run. The labels the API reports are the requested ones, not the runner's, so they are not read. It adds `"run_runner_group": "GitHub Actions"` to the manifest and attests both files by digest in one bundle. It never runs the model.

You get the artifact `community-evidence`: three files named after the run, `community-<repository id>-<run id>-<attempt>.jsonl` (the evidence), `.manifest.json` (the repository, the run id, attempt and number, the caller's workflow path, the official commit, the skill, the model, the evidence's sha256 and the runner group: no free text) and `.sigstore.json` (the bundle). The event line of the evidence file carries `"source": "community"`.

## Submitting

1. Download the artifact and copy the three files into `skills/<skill>/evals/evidence/` of a branch of your fork, and open a pull request to this repository. Do not edit them: a file that differs from what was attested fails the check, and a committed community file is never edited.
2. `python3 evals/eval_status.py evidence --file skills/<skill>/evals/evidence/community-<...>.jsonl` checks the shape and the agreement of the three files, offline. `python3 scripts/verify_community.py --root . --official-repo <owner>/<repo> --files skills/<skill>/evals/evidence/community-<...>.jsonl` runs the whole check, with the GitHub CLI, as CI does.
3. **Every completed run of your fork's workflow is submitted, with every attempt.** The run number of a workflow counts up from 1, so a number that no file carries is a run that was not submitted; a run that was re-run has several attempts, so an attempt below the highest one submitted that no file carries is flagged too (re-running until a run comes out well and submitting that attempt alone is cherry-picking by re-run). The check flags both: a warning in the pull request and a count of `gaps` in the status (`run_gaps` and `attempt_gaps` apart). A caller workflow other than `.github/workflows/openhora-community.yml` is flagged as well (`other_callers`). A gap is never a refusal (a run that failed before it wrote anything leaves one too), and a reviewer can look at the fork's Actions page. Keep one caller file and do not delete runs: a deleted run is a gap, and a new fork starts its numbering again from 1 (residual: see below). Submitting only the runs that came out well is the cherry-picking this rule exists to show.

## What the check verifies

`.github/workflows/community-verify.yml` runs on every pull request, under `pull_request` (never `pull_request_target`), with `contents: read` and no secret. The pull request's files are data. The script that reads them, `scripts/verify_community.py`, is the **base commit's**, read with `git show`, and the evidence validators it loads, the gate file, the version files and `evals/community.json` come from a checkout of the base commit, so a change cannot weaken its own check or the rules its own files are read by. Where the base has no verifier, a pull request that adds any community file fails, even one that adds the verifier (a script and the files it would judge never arrive together); the pull request that adds the verifier alone runs its own copy. For each added community file:

1. The shape, with the evidence validators read strictly: the three files agree (the name's ids, the manifest, the sha256), the manifest carries `"run_runner_group": "GitHub Actions"`, the event is a community event of one model that is listed with a route, through its entry's adapter, with the configured number of runs, from the published image; the skill's version file gives the event's content hash for its version (the gate file and the version file of the base commit).
2. The signing commit is in the history of `main` (`git merge-base --is-ancestor`) and, when `evals/community.json` of the base names a `min_signing_commit`, on `main`'s first-parent line at that commit or after it. The maintainer raises the minimum to retire a workflow found faulty: evidence signed by an older one is refused.
3. `gh attestation verify` of the evidence file and of the manifest against the bundle, with `--cert-identity https://github.com/<owner>/<repo>/.github/workflows/community-eval.yml@<commit>`, `--signer-digest <commit>`, `--deny-self-hosted-runners` and `--repo <the fork the manifest names>`: the signer is the official workflow at exactly that commit, on a GitHub-hosted runner, in that fork, and each file's digest is a subject of the bundle.

A community file that is edited, deleted or renamed after it is merged is refused.

## The cap and the other protections

- One contributor (the owner of the fork the manifest names, which the attestation binds; not the author of a commit) adds at most `COMMUNITY_CAP` (30, in `evals/eval_status.py`) lines with the skill to the community column of one skill and one model: the newest are kept; the status says how many were `capped`.
- The pessimistic score falls with little evidence, so a few runs never make a pair `reliable`.
- Three `failed` field verdicts demote a pair.
- The provider and the model's pin live in the attested code (the key proxy's route of the model's entry), so a fake server cannot produce an attested line.

What the design cannot remove, stated and not hidden:

- Running a model several times and submitting one run (the gaps in run numbers flag it; the cap and the score limit it), or re-running one run and submitting the best attempt (the gaps in attempts flag it).
- A new fork resets the numbering: a contributor who abandons a fork with unfavourable runs and starts another begins at run 1 again with nothing to compare. Several accounts and several forks of one person are several contributors to the cap.
- The contributor controls both accounts, the model's provider account and the grader's, and their account-level settings (what the provider serves, rate limits, a cheaper model behind an alias). The provider's honesty about the model it served is not checkable, and is published as such.
- Today only the reference model can produce evidence that is not a trial: every grading goes through the strong slot's adapter until the grader has an entry of its own in the gate file (the package that gives it one lifts this).

## For the maintainer

These steps cannot be done from a pull request, and the workflows cannot be exercised end to end before they are on `main`:

- The first publication of the eval image (`eval-image.yml`) and the lock file it produces (`scripts/image_lock.py`). The package must be public so that a fork's runner can pull it; until then the workflow stops at its pull step.
- Mark the `community-verify` check as required before a merge. It has no path filter so that it can be.
- `OFFICIAL_REPOSITORY` at the top of `community-eval.yml` is the repository the workflow checks out. If the repository moves, change it in the same pull request.
- Until a grader has an entry of its own in the gate file, every grading goes through the strong slot's adapter, so a community run of a model whose adapter is not the grader's is a trial and writes no evidence; the workflow then stops at the pack step with "found 0". The package that gives the grader its own entry lifts this.
- `evals/community.json` holds `min_signing_commit`, `null` at first. After the workflow is merged and a first real run has shown it right, set it to the merge commit of the workflow; raise it whenever a workflow is found faulty. The caller must grant `actions: read` for the attestation job to read the run job's runner group.
- A first real run decides the points this repository could not verify: that `job.workflow_sha` has the value the text above says, the shape of the jobs answer of the API (`runner_group_name`, `labels`, `conclusion`) and the certificate that `gh attestation verify` checks.
