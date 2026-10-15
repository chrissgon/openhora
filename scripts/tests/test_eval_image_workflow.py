"""A text test over .github/workflows/eval-image.yml, the workflow that publishes the eval image. The workflow
cannot run before it is on main, so what makes it safe is checked as text: who holds the identity token, that every
action is pinned, that nothing is cached, that nothing publishes off main and that both platforms are built natively.

Run: uv run --with pytest==9.1.1 pytest scripts/tests/test_eval_image_workflow.py
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TEXT = (REPO / ".github" / "workflows" / "eval-image.yml").read_text()


def jobs():
    """{job name: its block of text}, from the two-space-indented keys under `jobs:`."""
    body = TEXT[re.search(r"^jobs:\s*$", TEXT, re.M).end():]
    names = re.findall(r"^  ([\w-]+):\s*$", body, re.M)
    blocks = re.split(r"^  [\w-]+:\s*$", body, flags=re.M)[1:]
    assert names and len(names) == len(blocks)
    return dict(zip(names, blocks))


def code(text):
    """The text without comment lines and trailing comments (a `uses:` line keeps its version comment out of it)."""
    return "\n".join(re.sub(r"(^|\s)#.*$", "", line) for line in text.splitlines())


def test_the_identity_token_is_minted_in_the_attestation_job_alone():
    found = {name: block for name, block in jobs().items() if re.search(r"^\s+id-token: write\s*$", code(block), re.M)}
    assert list(found) == ["attest"]
    assert not re.search(r"id-token", code(TEXT.split("jobs:")[0]))  # not at the top
    attest = code(found["attest"])
    assert re.search(r"^\s+attestations: write\s*$", attest, re.M)
    others = {n: b for n, b in jobs().items() if n != "attest"}
    assert not any("attestations: write" in code(b) for b in others.values())


def test_the_attestation_job_receives_digests_only_and_runs_nothing_of_the_repository():
    attest = code(jobs()["attest"])
    assert "actions/checkout" not in attest and "run:" not in attest
    assert "needs.merge.outputs" in attest
    assert "actions/attest-build-provenance@" in attest


def test_the_top_permissions_are_read_only_and_packages_write_is_only_where_an_image_is_pushed():
    top = code(TEXT.split("jobs:")[0])
    assert re.search(r"^permissions:\n  contents: read\s*$", top, re.M)
    assert "write" not in top
    pushing = {name for name, block in jobs().items() if re.search(r"^\s+packages: write\s*$", code(block), re.M)}
    assert pushing == {"build", "merge", "attest"}


def test_every_action_is_pinned_by_a_40_character_commit_sha():
    uses = re.findall(r"^\s*-?\s*uses:\s*(\S+)", code(TEXT), re.M)
    assert len(uses) >= 8
    for ref in uses:
        assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", ref), ref
    # a pinned action says its version in a comment, as checks.yml does
    assert all(re.search(r"@[0-9a-f]{40} # v\d", line) for line in TEXT.splitlines() if re.search(r"^\s*-?\s*uses:", line))


def test_nothing_is_cached():
    text = code(TEXT)
    assert not re.search(r"actions/cache|cache-from|cache-to|type=gha|type=registry|^\s+cache:", text, re.M)
    assert re.search(r"^\s+no-cache: true\s*$", text, re.M)


def test_the_workflow_runs_on_main_only():
    assert re.search(r"^on:\n  push:\n    branches: \[main\]\n    paths:\n      - \"evals/container/\*\*\"\n"
                     r"      - \".github/workflows/eval-image\.yml\"\n  workflow_dispatch:", TEXT, re.M)
    for name, block in jobs().items():
        assert re.search(r"^    if: github\.ref == 'refs/heads/main'\s*$", block, re.M), name
    assert "pull_request" not in code(TEXT)


def test_both_platforms_are_built_natively_each_on_a_runner_of_its_architecture():
    build = jobs()["build"]
    assert "runs-on: ${{ matrix.runner }}" in build
    pairs = re.findall(r"- platform: (linux/\w+)\n\s+runner: (\S+)", build)
    assert pairs == [("linux/amd64", "ubuntu-24.04"), ("linux/arm64", "ubuntu-24.04-arm")]
    assert "platforms: ${{ matrix.platform }}" in build
    assert "setup-qemu" not in TEXT and "qemu" not in code(TEXT)


def test_the_image_is_pushed_by_digest_from_the_pinned_definition_and_signed_per_digest():
    text = code(TEXT)
    assert "push-by-digest=true" in text and "context: evals/container" in text
    assert "ghcr.io/${OWNER,,}/openhora-eval" in text
    assert text.count("actions/attest-build-provenance@") == 3  # the index and both manifests
    assert re.search(r"password: \$\{\{ secrets\.GITHUB_TOKEN \}\}", text)
    assert not re.search(r"secrets\.(?!GITHUB_TOKEN)", text)


def test_every_job_has_a_timeout_and_a_value_from_the_run_never_lands_inside_a_script():
    for name, block in jobs().items():
        assert re.search(r"^    timeout-minutes: [1-9]\d*\s*$", block, re.M), name
    for run in re.findall(r"run: \|\n((?:\s{10,}.*\n)+)", TEXT):
        assert "${{" not in run  # values reach a script through env, never by being pasted into it


def test_the_index_digest_is_the_one_the_create_command_produced_never_resolved_from_a_tag():
    merge = code(jobs()["merge"])
    assert "imagetools create --metadata-file" in merge and "containerimage.digest" in merge
    assert "imagetools inspect \"${repository}:" not in merge  # the tag is not read back


LOCK_WORKFLOW = (REPO / ".github" / "workflows" / "image-lock.yml").read_text()


def test_the_lock_is_verified_by_a_read_only_job_on_every_change_of_it():
    text = code(LOCK_WORKFLOW)
    assert re.search(r"^permissions:\n  contents: read\s*$", text, re.M) and "write" not in text
    assert "push:" in text and "pull_request:" in text and "pull_request_target" not in text
    assert text.count('"evals/image-lock.json"') == 2  # a push and a pull request
    assert 'python3 scripts/image_lock.py --check --verify-provenance --source-repo "$SOURCE_REPOSITORY"' in text
    assert "GH_TOKEN: ${{ github.token }}" in text and "SOURCE_REPOSITORY: ${{ github.repository }}" in text
    assert re.search(r"^    timeout-minutes: [1-9]\d*\s*$", text, re.M)
    for ref in re.findall(r"^\s*-?\s*uses:\s*(\S+)", text, re.M):
        assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", ref), ref
    assert "${{" not in "".join(re.findall(r"run: (.*)", text))  # values reach the script through env
