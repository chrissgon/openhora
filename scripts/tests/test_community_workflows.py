"""Text tests over .github/workflows/community-eval.yml (the official reusable workflow) and community-verify.yml (the check
of a pull request that adds community evidence). Neither can run before it is on main, so what makes them safe is checked as
text, as test_eval_image_workflow.py does for the image workflow: who holds the identity token, that every action is pinned,
that nothing is cached, which code is checked out and at which commit, where a secret may appear, and that the verifier is
the base commit's.

Run: uv run --with pytest pytest scripts/tests/test_community_workflows.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EVAL = (REPO / ".github" / "workflows" / "community-eval.yml").read_text()
VERIFY = (REPO / ".github" / "workflows" / "community-verify.yml").read_text()


def code(text):
    """The text without comment lines and trailing comments (a `uses:` line keeps its version comment out of it)."""
    return "\n".join(re.sub(r"(^|\s)#.*$", "", line) for line in text.splitlines())


def jobs(text):
    """{job name: its block of text}, from the two-space-indented keys under `jobs:`."""
    body = text[re.search(r"^jobs:\s*$", text, re.M).end():]
    names = re.findall(r"^  ([\w-]+):\s*$", body, re.M)
    blocks = re.split(r"^  [\w-]+:\s*$", body, flags=re.M)[1:]
    assert names and len(names) == len(blocks)
    return dict(zip(names, blocks))


def run_scripts(text):
    """The bodies of the `run:` steps (block scalars and one-liners)."""
    blocks = re.findall(r"run: \|\n((?:\s{10,}.*\n|\n)+)", text)
    return blocks + re.findall(r"run: ([^|\n].*)", text)


# --- the reusable workflow ----------------------------------------------------------------------------------

def test_it_is_a_reusable_workflow_and_nothing_else():
    text = code(EVAL)
    assert re.search(r"^on:\n  workflow_call:", text, re.M)
    assert not re.search(r"^\s+(push|pull_request|pull_request_target|workflow_dispatch|schedule):", text, re.M)
    assert [n for n in jobs(EVAL)] == ["run", "attest"]


def test_the_identity_token_is_minted_in_the_attestation_job_alone():
    found = {n for n, b in jobs(EVAL).items() if re.search(r"^\s+id-token: write\s*$", code(b), re.M)}
    assert found == {"attest"}
    top = code(EVAL.split("jobs:")[0])
    assert "id-token" not in top and "write" not in top
    assert re.search(r"^permissions:\n  contents: read\s*$", top, re.M)
    assert {n for n, b in jobs(EVAL).items() if "attestations: write" in code(b)} == {"attest"}
    run = code(jobs(EVAL)["run"])
    assert re.search(r"^    permissions:\n      contents: read\s*\n    outputs:", run, re.M)  # exactly that, and nothing else
    assert "id-token" not in run.replace("retention-days", "") and "attest-build-provenance" not in run and "attestations:" not in run


def test_the_attestation_job_checks_out_nothing_and_runs_no_model_and_no_code_of_a_repository():
    attest = code(jobs(EVAL)["attest"])
    assert "actions/checkout" not in attest
    for needle in ("python3", "scripts/", "evals/", "eval_run", "image_lock", "community_pack", "docker", "git "):
        assert needle not in attest, needle
    assert "needs.run.outputs.name" in attest and "needs.run.outputs.evidence_sha256" in attest
    assert "needs.run.outputs.manifest_sha256" in attest
    assert "sha256sum" in attest and "actions/attest-build-provenance@" in attest
    assert "subject-checksums:" in attest  # by subject digest, never by a path it would hash itself
    assert "subject-path" not in attest
    assert "secrets." not in attest


def test_the_attestation_job_proves_the_run_job_ran_on_githubs_own_runners_and_records_it_in_the_attested_manifest():
    """Its own certificate shows only its own runner: the job that ran the model is read from the API."""
    attest, run = code(jobs(EVAL)["attest"]), code(jobs(EVAL)["run"])
    assert re.search(r"^      actions: read\s*$", attest, re.M) and "actions: read" not in run  # the caller grants it; only attest asks
    assert "GH_TOKEN: ${{ github.token }}" in attest
    assert 'gh api --paginate "repos/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}/attempts/${GITHUB_RUN_ATTEMPT}/jobs"' in attest
    # EVERY job of the attempt is read (a decoy job of the caller on a self-hosted group must fail the run), by the group's name
    # and its id; the labels the API reports are the requested ones and are not read
    assert ".jobs[] | [.name, .runner_group_name, (.runner_group_id | tostring), .conclusion] | @tsv" in attest and "select(" not in attest
    assert "$2 != \"GitHub Actions\" || $3 != \"0\"" in attest and ".labels" not in attest and "ubuntu-24.04" not in attest[attest.index("jobs_tsv="):attest.index("group=\"GitHub Actions\"")]
    assert re.search(r"^    name: lab test\s*$", jobs(EVAL)["run"], re.M)  # the name the one job that must succeed is found by
    assert '$1 == "lab test" || $1 ~ / \\/ lab test$/' in attest and '[ "$lab" = "success" ]' in attest
    # the group is added to the manifest BEFORE the digests are taken and attested, so the attestation covers it
    assert attest.index("run_runner_group: $group") < attest.index("manifest_sha=") < attest.index("checksums.txt") < attest.index("attest-build-provenance")
    assert attest.index('[ -z "$outside" ]') < attest.index("run_runner_group: $group")


def test_every_action_is_pinned_by_a_40_character_commit_sha_with_its_version_in_a_comment():
    uses = re.findall(r"^\s*-?\s*uses:\s*(\S+)", code(EVAL), re.M)
    assert len(uses) >= 5
    for ref in uses:
        assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", ref), ref
    assert all(re.search(r"@[0-9a-f]{40} # v\d", line) for line in EVAL.splitlines() if re.search(r"^\s*-?\s*uses:", line))
    for other in (VERIFY,):
        for ref in re.findall(r"^\s*-?\s*uses:\s*(\S+)", code(other), re.M):
            assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", ref), ref


def test_nothing_is_cached_and_no_setup_action_brings_a_cache_in():
    text = code(EVAL)
    assert not re.search(r"actions/cache|cache-from|cache-to|type=gha|^\s+cache:|cache-dependency|enable-cache|setup-(python|node|uv|go|java|buildx)",
                         text, re.M)
    assert not re.search(r"actions/cache|enable-cache|^\s+cache:", code(VERIFY), re.M)


def test_the_official_repository_is_checked_out_at_the_commit_of_the_workflow_itself_never_the_callers_code():
    text = code(EVAL)
    checkouts = re.findall(r"uses: actions/checkout@[0-9a-f]{40}[ \t]*\n((?: {8,}.*\n)+)", text + "\n")
    assert len(checkouts) == 1
    step = checkouts[0]
    assert "repository: ${{ env.OFFICIAL_REPOSITORY }}" in step
    assert "ref: ${{ job.workflow_sha }}" in step
    assert "persist-credentials: false" in step and "fetch-depth: 0" in step
    # The literal is owner/name, in the text of the attested file; nothing of the caller names what is checked out.
    literal = re.search(r"^env:\n  OFFICIAL_REPOSITORY: (\S+)\s*$", text, re.M).group(1)
    assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+", literal)
    assert "github.sha" not in text and "github.workflow_sha" not in text and "github.head_ref" not in text
    # job.workflow_sha is the property of the job context that holds the workflow file's commit; github.job_workflow_sha is
    # not a property of the github context (it reads as an empty string, and the checkout would take the default branch).
    assert "github.job_workflow_sha" not in text and text.count("job.workflow_sha") == 3
    assert "github.event" not in text and "github.ref" not in text
    # The commit is checked, not trusted: 40 hexadecimal characters, HEAD equal to it, and an ancestor of main.
    assert "^[0-9a-f]{40}$" in text and 'git rev-parse HEAD' in text and "merge-base --is-ancestor" in text
    # Only the official code runs: the scripts named are the checkout's, and the pack is told the same commit.
    assert "python3 scripts/image_lock.py pull --source-repo \"$OFFICIAL_REPOSITORY\"" in text
    assert "python3 evals/eval_run.py" in text and '--commit "$WORKFLOW_SHA"' in text


def test_the_runner_is_a_github_hosted_one_and_the_caller_cannot_name_another():
    labels = re.findall(r"runs-on: (.+)", code(EVAL))
    assert labels and all(re.fullmatch(r"\$\{\{ inputs\.arch == 'arm64' && 'ubuntu-24\.04-arm' \|\| 'ubuntu-24\.04' \}\}|ubuntu-24\.04", l) for l in labels)
    assert "self-hosted" not in code(EVAL)
    assert "runs-on: ${{ inputs." not in code(EVAL).replace("runs-on: ${{ inputs.arch ==", "")


def test_a_value_from_the_context_reaches_a_script_through_env_only():
    for text in (EVAL, VERIFY):
        for script in run_scripts(text):
            assert "${{" not in script, script
        scripted = "".join(re.findall(r"^\s+(?:python3|if|set|checker|echo|fi|else|git|code|verifier|mkdir|cp|cd) .*$", code(text), re.M))
        assert "${{" not in scripted


def test_a_secret_appears_only_as_an_environment_variable_of_the_two_steps_that_need_it():
    lines = [l for l in code(EVAL).splitlines() if "secrets." in l]
    assert lines and all(re.fullmatch(r"\s+([A-Z_]+): \$\{\{ secrets\.\1 \}\}", l) for l in lines), lines
    run = jobs(EVAL)["run"]
    steps = re.split(r"\n      - ", run)
    holders = [s.splitlines()[0] for s in steps if "secrets." in code(s)]
    assert holders == ["name: Check the request and that the keys are set (names only, never a value)", "name: Run the lab test"]
    assert "secrets." not in code(VERIFY)
    # Every key variable the gate file passes into a model's runs, and the grader's, is a secret the workflow declares.
    gate = json.loads((REPO / "evals" / "eval-gate.json").read_text())
    needed = set()
    for entry in gate["models"].values():
        needed |= set(entry.get("pass_env", []))
    declared = set(re.findall(r"^      ([A-Z_]+):\n        description", EVAL.split("permissions:")[0], re.M))
    assert needed <= declared, f"the workflow declares {sorted(declared)} and the gate file passes {sorted(needed)}"


def test_the_inputs_cannot_choose_the_provider_the_model_or_the_code():
    inputs = re.search(r"workflow_call:\n    inputs:\n(.*?)\n    secrets:", EVAL, re.S).group(1)
    assert set(re.findall(r"^      (\w+):\n", inputs, re.M)) == {"skill", "model", "adapter", "cases", "full", "quick", "arch"}
    text = code(EVAL)
    # One model per community file: the run names the one model it was asked for with --model, so the gate file's lab models
    # (the default of an event that names none) do not run beside it. The option --floor-model no longer exists in the runner.
    assert "preflight" in text and '(--skill "$SKILL" --model "$MODEL")' in text and "--floor-model" not in text
    assert "--pass-env" not in text and "--scratch" not in text and "--no-grade" not in text and "--runs" not in text
    assert "base_url" not in text.lower() and "endpoint" not in text.lower()


def test_quick_is_an_input_exclusive_with_cases_and_full_and_reaches_the_runner_as_a_flag_alone():
    inputs = re.search(r"workflow_call:\n    inputs:\n(.*?)\n    secrets:", EVAL, re.S).group(1)
    assert re.search(r"^      quick:\n(?:        .*\n)*?        type: boolean\n        required: false\n        default: false$", inputs, re.M)
    assert "Give one of cases, full or quick" in inputs
    steps = re.split(r"\n      - ", jobs(EVAL)["run"])
    check = next(s for s in steps if s.startswith("name: Check the request"))
    lab = next(s for s in steps if s.startswith("name: Run the lab test"))
    # The request check hands every choice made to the preflight, which refuses anything but exactly one of the three.
    assert 'QUICK: ${{ inputs.quick }}' in check and '[ "$QUICK" != "true" ] || args+=(--quick)' in code(check)
    assert '[ "$FULL" != "true" ] || args+=(--full)' in code(check) and '[ -z "$CASES" ] || args+=(--cases "$CASES")' in code(check)
    # The run itself: a quick test is the flag alone (no case list, no run count), else a full test or the named cases.
    assert 'QUICK: ${{ inputs.quick }}' in lab
    assert 'if [ "$QUICK" = "true" ]; then args+=(--quick); elif [ "$FULL" != "true" ]; then args+=(--cases "$CASES"); fi' in code(lab)


def test_every_job_has_a_timeout_and_the_files_move_between_jobs_as_artifacts_of_the_same_run():
    for name, block in jobs(EVAL).items():
        assert re.search(r"^    timeout-minutes: [1-9]\d*\s*$", block, re.M), name
    assert jobs(EVAL)["run"].count("actions/upload-artifact@") == 1
    assert "actions/download-artifact@" in jobs(EVAL)["attest"]
    assert "name: community-evidence-files" in EVAL and "name: community-evidence\n" in EVAL


# --- the check of a pull request ----------------------------------------------------------------------------

def test_the_verifier_job_runs_on_pull_request_never_on_pull_request_target_and_holds_no_secret():
    text = code(VERIFY)
    assert re.search(r"^on:\n  pull_request:\s*$", text, re.M)
    assert "pull_request_target" not in text and "workflow_run" not in text
    assert re.search(r"^permissions:\n  contents: read\s*$", text, re.M) and "write" not in text
    assert "paths:" not in text  # a check required before a merge runs on every pull request
    assert "GH_TOKEN: ${{ github.token }}" in text
    assert re.search(r"^    timeout-minutes: [1-9]\d*\s*$", text, re.M)


def test_the_script_that_verifies_is_the_base_commits_read_with_git_show_and_the_checkout_is_data():
    text = code(VERIFY)
    assert 'BASE_SHA: ${{ github.event.pull_request.base.sha }}' in text
    assert 'git show "$BASE_SHA":scripts/verify_community.py > "$RUNNER_TEMP/verify_community.py"' in text
    assert 'git archive "$BASE_SHA" evals scripts' in text
    assert 'verifier="$RUNNER_TEMP/verify_community.py"' in text and 'code="$RUNNER_TEMP/base"' in text
    run = text[text.index("python3 \"$verifier\""):]
    assert '--root "$GITHUB_WORKSPACE"' in run and '--code-root "$code"' in run and '--base "$BASE_SHA"' in run
    assert "--main-ref origin/main" in run
    # the checkout's own script runs only when the base has none yet (the pull request that adds it), and the job says so
    assert text.index('verifier="$RUNNER_TEMP/verify_community.py"') < text.index('python3 "$verifier"')
    assert "note: this pull request adds the community verifier and no community file" in text
    assert "python3 scripts/verify_community.py" not in text  # never run by its path in the checkout
    # the gate file, the minimum signing commit (evals/) and the version files the files are read by are the base's
    assert "git archive \"$BASE_SHA\" evals scripts 'skills/*/evals/versions.jsonl'" in text
    # the fallback to the pull request's own verifier is for the pull request that adds it AND adds no community file: where the
    # base has no verifier, any added community file is refused, even in a pull request that adds the verifier, so a script and
    # the files it would judge never arrive together
    refuse = text.index("elif [ -n \"$(git diff --name-only \"$BASE_SHA\" HEAD -- 'skills/*/evals/evidence/community-*')\" ]; then")
    own = text.index('elif [ -n "$(git diff --name-only --diff-filter=A "$BASE_SHA" HEAD -- scripts/verify_community.py)" ]; then')
    assert refuse < own  # the refusal is decided first
    refusal, fallback = text[refuse:own], text[own:]
    assert "exit 1" in refusal and "::error::" in refusal and "exit 1" not in fallback
    assert "note: this pull request adds the community verifier and no community file" in fallback and "exit 0" in fallback
    assert "pip install" not in text and "setup-python" not in text
