"""The shell script of the attestation job of .github/workflows/community-eval.yml, run for real against a fake `gh`:
it must add GitHub's runner group to the manifest only when the API shows that EVERY job of the run attempt ran in that
group (its name and its id, 0) and the job that ran the model succeeded; it must refuse files that changed on the way; and the digests it
writes for the attestation must be those of the manifest as it is after the group was added. The API call itself (the
shape of the jobs answer) is the one thing a first real run decides.

Run: uv run --with pytest pytest scripts/tests/test_community_attest_script.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EVAL = (REPO / ".github" / "workflows" / "community-eval.yml").read_text()
STEM = "community-111-222-1"
# what the --jq filter prints: name, runner group name, runner group id, conclusion (the fake gh prints it whatever it is asked)
LAB = "test / lab test\tGitHub Actions\t0\tsuccess\n"
ATTEST = "test / attest\tGitHub Actions\t0\t\n"
HOSTED = LAB + ATTEST


def attest_script():
    """The `run:` block of the step that reads the run job's runner from the API, as the shell receives it."""
    jobs = EVAL[re.search(r"^jobs:\s*$", EVAL, re.M).end():]
    block = jobs[jobs.index("\n  attest:"):]
    start = block.index("- name: The run job ran on GitHub's own runners")
    body = block[start:]
    lines = body[body.index("run: |\n") + len("run: |\n"):].splitlines()
    out = []
    for line in lines:
        if line.strip() and not line.startswith(" " * 10):
            break
        out.append(line[10:])
    return "\n".join(out)


def run_attest(tmp_path, api_output, edit=None, name=None):
    bin_dir, temp = tmp_path / "bin", tmp_path / "runner-temp"
    files = temp / "files"
    bin_dir.mkdir(parents=True)
    files.mkdir(parents=True)
    fake = bin_dir / "gh"
    fake.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$FAKE_GH_LOG"\nprintf "%s" "$FAKE_GH_OUTPUT"\n')
    fake.chmod(0o755)
    evidence = b'{"record": "test"}\n'
    (files / f"{STEM}.jsonl").write_bytes(evidence)
    evidence_sha = hashlib.sha256(evidence).hexdigest()
    manifest = json.dumps({"record": "community-manifest", "evidence_sha256": evidence_sha}).encode()
    (files / f"{STEM}.manifest.json").write_bytes(manifest)
    if edit:
        edit(files)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "RUNNER_TEMP": str(temp), "GH_TOKEN": "a-stand-in",
           "GITHUB_REPOSITORY": "ana/openhora", "GITHUB_REPOSITORY_ID": "111", "GITHUB_RUN_ID": "222", "GITHUB_RUN_ATTEMPT": "1",
           "NAME": name or STEM, "EVIDENCE_SHA256": evidence_sha, "MANIFEST_SHA256": hashlib.sha256(manifest).hexdigest(),
           "FAKE_GH_OUTPUT": api_output, "FAKE_GH_LOG": str(tmp_path / "gh.log")}
    result = subprocess.run(["bash", "-c", attest_script()], env=env, capture_output=True, text=True)  # security-scan: allow shell-string -- the script is the committed workflow's own text, run in a temp folder with a fake gh
    return result, temp


def test_the_script_adds_the_runner_group_and_attests_the_new_manifest_digest(tmp_path):
    result, temp = run_attest(tmp_path / "a", HOSTED)
    assert result.returncode == 0, result.stderr
    manifest = temp / "files" / f"{STEM}.manifest.json"
    assert json.loads(manifest.read_text())["run_runner_group"] == "GitHub Actions"
    evidence = temp / "files" / f"{STEM}.jsonl"
    assert (temp / "checksums.txt").read_text().splitlines() == [
        f"{hashlib.sha256(evidence.read_bytes()).hexdigest()}  {STEM}.jsonl",
        f"{hashlib.sha256(manifest.read_bytes()).hexdigest()}  {STEM}.manifest.json"]
    assert "repos/ana/openhora/actions/runs/222/attempts/1/jobs" in (tmp_path / "a" / "gh.log").read_text()
def test_the_script_refuses_what_is_not_a_hosted_successful_run_job_and_leaves_nothing_to_attest(tmp_path):
    outside = "a job of this run attempt was not on GitHub's own runners"
    cases = [
        (LAB + ATTEST + "test / decoy\tDefault\t1\tsuccess\n", outside),  # a decoy job of the caller on a self-hosted group
        ("test / lab test\tDefault\t1\tsuccess\n" + ATTEST, outside),  # the job that ran the model itself
        ("test / lab test\tGitHub Actions\t7\tsuccess\n" + ATTEST, outside),  # a group that took GitHub's name has another id
        (LAB + "test / other\t\tnull\t\n", outside),  # a job with no runner at all
        (LAB + "test / attest\tself-hosted\t0\t\n", outside),
        ("test / lab test\tGitHub Actions\t0\tfailure\n" + ATTEST, "expected exactly one job named lab test, and that it succeeded"),
        (ATTEST, "expected exactly one job named lab test, and that it succeeded"),
        (LAB + LAB + ATTEST, "expected exactly one job named lab test, and that it succeeded"),
        ("", "listed no job"),
    ]
    for n, (output, said) in enumerate(cases):
        result, temp = run_attest(tmp_path / str(n), output)
        assert result.returncode != 0 and said in result.stderr, (output, result.stderr)
        assert not (temp / "checksums.txt").exists()
        assert "run_runner_group" not in (temp / "files" / f"{STEM}.manifest.json").read_text()


def test_the_script_refuses_files_that_changed_on_the_way(tmp_path):
    result, _ = run_attest(tmp_path / "a", HOSTED, edit=lambda files: (files / f"{STEM}.jsonl").write_bytes(b"x"))
    assert result.returncode != 0 and "evidence file changed" in result.stderr
    result, _ = run_attest(tmp_path / "b", HOSTED, name="community-1-2-3")
    assert result.returncode != 0 and "this run is community-111-222-1" in result.stderr
    result, _ = run_attest(tmp_path / "c", HOSTED, edit=lambda files: (files / "extra.txt").write_text("x"))
    assert result.returncode != 0 and "unexpected files" in result.stderr


def test_the_labels_of_a_job_are_not_read_because_the_api_reports_the_requested_ones():
    assert ".labels" not in attest_script() and "ubuntu-24.04" not in attest_script()
