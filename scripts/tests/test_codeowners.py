"""The code owners file covers what decides what a run measures and what moves a skill's standing (the
reliability model, section 8; item B11 of docs/architecture/final-plan-2026-10-02.md), and every pattern in it
matches something of the repository.

Run: uv run --with pytest pytest scripts/tests/test_codeowners.py
"""
import fnmatch
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CODEOWNERS = REPO / ".github" / "CODEOWNERS"

# What item B11 asks the file to gain, besides the rules and checks it already covered.
REQUIRED = ["/evals/", "/adapters/claude-code/run-prompt.sh", "/adapters/claude-code/adapter.json",
            "/adapters/agents-dir/run-prompt.sh", "/adapters/agents-dir/adapter.json", "/adapters/claude-code/eval.json",
            "/adapters/agents-dir/eval.json", "/adapters/*/install.sh",
            "/scripts/stage_skills.py", "/scripts/redact.py", "/scripts/test_dirs.py", "/scripts/evidence.py",
            "/.security-scan-allow", "/shared/", "/skills/*/evals/evidence/", "/skills/*/evals/versions.jsonl",
            "/skills/*/evals/result.json", "/AGENTS.md", "/scripts/validate.py", "/.github/", "/runtime/", "/interface/", "/flows/", "/skills/*/evals/runtime-manifest.json"]


def patterns():
    return [line.split()[0] for line in CODEOWNERS.read_text().splitlines() if line.strip() and not line.startswith("#")]


def test_every_line_names_an_owner():
    for line in CODEOWNERS.read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            assert len(line.split()) >= 2 and line.split()[1].startswith("@"), line


def test_the_measurement_the_evidence_and_the_checks_are_covered():
    missing = [p for p in REQUIRED if p not in patterns()]
    assert not missing, f"CODEOWNERS lacks {missing}"


def test_every_pattern_matches_a_tracked_path_or_one_that_tooling_writes():
    tracked = subprocess.run(["git", "-C", str(REPO), "ls-files"], capture_output=True, text=True, check=True).stdout.split()
    written = {"/skills/*/evals/evidence/"}  # evidence folders are created by the runner and the importer
    for pattern in patterns():
        if pattern in written:
            continue
        body = pattern.lstrip("/")
        glob = body + "*" if body.endswith("/") else body
        assert any(fnmatch.fnmatchcase(path, glob) for path in tracked), f"{pattern} matches no tracked path"


def test_every_eval_adapter_is_covered():
    """An eval adapter (one with a run-prompt.sh) is in the measurement fingerprint: its run-prompt.sh and its
    eval.json are owned, and so is its adapter.json."""
    for script in sorted(REPO.glob("adapters/*/run-prompt.sh")):
        name = script.parent.name
        assert f"/adapters/{name}/run-prompt.sh" in patterns() and f"/adapters/{name}/adapter.json" in patterns(), name
        assert f"/adapters/{name}/eval.json" in patterns(), name
