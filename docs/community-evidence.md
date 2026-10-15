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
- The **keys as secrets of the fork** (Settings, Secrets and variables, Actions): the key of the model's provider, and the token of the grader's account, because every run is graded by the configured grader. The gate file (`evals/eval-gate.json`) names them: `pass_env` of the model's entry and `strong_pass_env`. The workflow declares `OPENROUTER_API_KEY` and `CLAUDE_CODE_OAUTH_TOKEN`; a key never enters a run, each run's key proxy holds it. A request for a key that is not set is refused before anything runs, and only the name is printed.
- A **model of the gate file with a route**: a community run tests a listed model whose key a key proxy holds. A model that is not listed is added to the gate file in a pull request first.
- A **commit of this repository's `main`**: the workflow is referenced by its full commit sha. A commit that is not in the history of `main` is refused by the workflow and, later, by the check.

## The caller

Add this file to your fork as `.github/workflows/lab.yml` (any one file name, kept for good: see "Every completed run"). Replace `<owner>/<repo>` with the official repository and `<sha>` with the 40-character commit of its `main` you chose.

```yaml
name: lab
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
    # only its attestation job uses the other two.
    permissions:
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

The workflow's other input is `arch` (`amd64`, the default, or `arm64`; evidence from either is accepted) and `adapter`, which only makes the run refuse an adapter other than the one the model's entry names. You can run it from the Actions tab, or with `gh workflow run lab.yml -f skill=<name> -f model=<id> -f full=true`.

## What the workflow does

Two jobs, and the line between them is the point:

1. **`run`** has `contents: read` and nothing else. It checks out **this** repository, never the caller's code, at the commit of the reusable workflow file itself, which is `github.job_workflow_sha`: inside a reusable workflow the `github` context is the caller's, so `github.sha` and `github.workflow_sha` name your fork's commit and would run your code under the official identity; `job_workflow_sha` is the commit you wrote after `@`, the same value as the Build Signer Digest of the certificate. The repository to check out is a literal in the attested file. It checks the checkout is exactly that commit and that the commit is in the history of `main`, checks the request and the keys, pulls the published eval image by the digest of the lock file (`python3 scripts/image_lock.py pull`), runs `python3 evals/eval_run.py` for one skill and one model, and packs the evidence file and a manifest (`scripts/community_pack.py`). There is no actions cache and no setup action.
2. **`attest`** is the only job with `id-token: write` and `attestations: write`. It checks out nothing and runs no code of any repository: it downloads the two files, compares their sha256 with what `run` reported, and attests both by digest in one bundle. It never runs the model.

You get the artifact `community-evidence`: three files named after the run, `community-<repository id>-<run id>-<attempt>.jsonl` (the evidence), `.manifest.json` (the repository, the run id and number, the caller's workflow path, the official commit, the skill, the model and the evidence's sha256: no free text) and `.sigstore.json` (the bundle). The event line of the evidence file carries `"source": "community"`.

## Submitting

1. Download the artifact and copy the three files into `skills/<skill>/evals/evidence/` of a branch of your fork, and open a pull request to this repository. Do not edit them: a file that differs from what was attested fails the check, and a committed community file is never edited.
2. `python3 evals/eval_status.py evidence --file skills/<skill>/evals/evidence/community-<...>.jsonl` checks the shape and the agreement of the three files, offline. `python3 scripts/verify_community.py --root . --official-repo <owner>/<repo> --files skills/<skill>/evals/evidence/community-<...>.jsonl` runs the whole check, with the GitHub CLI, as CI does.
3. **Every completed run of your fork's workflow is submitted.** The run number of a workflow counts up from 1, so a number that no file carries is a run that was not submitted, and the check flags it: a warning in the pull request and a count of `gaps` in the status. A gap is never a refusal (a run that failed before it wrote anything leaves one too), and a reviewer can look at the fork's Actions page. Keep one caller file and do not delete runs: another caller file has a count of its own, and a deleted run is a gap. Submitting only the runs that came out well is the cherry-picking this rule exists to show.

## What the check verifies

`.github/workflows/community-verify.yml` runs on every pull request, under `pull_request` (never `pull_request_target`), with `contents: read` and no secret. The pull request's files are data. The script that reads them, `scripts/verify_community.py`, is the **base commit's**, read with `git show`, and the evidence validators it loads come from a checkout of the base commit, so a change cannot weaken its own check. For each added community file:

1. The shape, with the evidence validators read strictly: the three files agree (the name's ids, the manifest, the sha256), the event is a community event of one model that is listed with a route, through its entry's adapter, with the configured number of runs, from the published image; the skill's version file gives the event's content hash for its version.
2. The signing commit is in the history of `main` (`git merge-base --is-ancestor`).
3. `gh attestation verify` of the evidence file and of the manifest against the bundle, with `--cert-identity https://github.com/<owner>/<repo>/.github/workflows/community-eval.yml@<commit>`, `--signer-digest <commit>`, `--deny-self-hosted-runners` and `--repo <the fork the manifest names>`: the signer is the official workflow at exactly that commit, on a GitHub-hosted runner, in that fork, and each file's digest is a subject of the bundle.

A community file that is edited, deleted or renamed after it is merged is refused.

## The cap and the other protections

- One contributor (the author of the commit that added a file, read from git and stored nowhere) adds at most `COMMUNITY_CAP` (30, in `evals/eval_status.py`) lines with the skill to the community column of one skill and one model: the newest are kept; the status says how many were `capped`.
- The pessimistic score falls with little evidence, so a few runs never make a pair `reliable`.
- Three `failed` field verdicts demote a pair.
- The provider and the model's pin live in the attested code (the key proxy's route of the model's entry), so a fake server cannot produce an attested line.

What the design cannot remove: running a model several times and submitting one run (the gaps flag it; the cap and the score limit it), and the provider's honesty about the model it served (not checkable, and published as such).

## For the maintainer

These steps cannot be done from a pull request, and the workflows cannot be exercised end to end before they are on `main`:

- The first publication of the eval image (`eval-image.yml`) and the lock file it produces (`scripts/image_lock.py`). The package must be public so that a fork's runner can pull it; until then the workflow stops at its pull step.
- Mark the `community-verify` check as required before a merge. It has no path filter so that it can be.
- `OFFICIAL_REPOSITORY` at the top of `community-eval.yml` is the repository the workflow checks out. If the repository moves, change it in the same pull request.
- Until a grader has an entry of its own in the gate file, every grading goes through the strong slot's adapter, so a community run of a model whose adapter is not the grader's is a trial and writes no evidence; the workflow then stops at the pack step with "found 0". The package that gives the grader its own entry lifts this.
- A first real run decides the points this repository could not verify: that `github.job_workflow_sha` has the value the text above says, and the shape of the certificate that `gh attestation verify` checks.
