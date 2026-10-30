"""Test of the hash chain at a skill's gate (44-C4a, OPEN-C4-4; principle 11, limits L15, L16, L17): the payload a skill showed,
the effect document that carries its hash, and the pending decision that carries the document's hash. A wrong
`payload_file_sha256` in the effect document passed every other test of the runtime (2,423 tests of 65 files, planted by the
44-C4 spec writer); the run's start and body moved to runtime/ops_task_run.py in this package, and this file is the test that
holds the chain while code moves. Offline: the stand-in skill demo-gate and the stand-in code provider of
runtime/tests/standin_tree.py. Every name is invented.

The oracle (`chain_problems`) recomputes each hash from the bytes of a file with hashlib; it reads no hash that the code under
test computed. Its vacuity cases plant a wrong hash in the two places the chain can break (the document's payload hash; the
decision's document hash) and require the oracle to fail.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_gate_hash_chain.py
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest

import standin_tree as st

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
effects = st.load("effects")
effect_pull_request = st.load("effect_pull_request")

GIT = ["git", "-c", "user.name=Demo", "-c", "user.email=demo@example.test", "-c", "commit.gpgsign=false"]
CODE = {"provider": "github", "repo": "example-org/web", "base": "main"}
HEX64 = re.compile(r"[0-9a-f]{64}")


@pytest.fixture
def tree(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    return built


def git(folder, *args) -> str:
    return subprocess.run(GIT + ["-C", str(folder), *args], check=True, capture_output=True, text=True).stdout


def provider_calls(tree) -> list:
    path = tree["tree"] / "providers" / "vcs" / "calls.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []


def gate_run(tree) -> dict:
    """One request of the stand-in flow gate-demo, run up to its gate: the person's project holds a git repository, the change
    the stand-in skill makes, and the configuration accepted. Returns the project, the run's result and the pending decision."""
    project = tree["project"]
    (project / "src").mkdir()
    (project / "src" / "app.py").write_text("v1\n")
    (project / ".gitignore").write_text(".workbench-local/\n")
    config = project / "docs" / "workbench" / "runtime.json"
    config.write_text(json.dumps({**json.loads(config.read_text()), "code": CODE}))
    git(project, "init", "-q")
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "start")
    path = str(project)
    ops.accept_config(path, ops.project_config.load(path)["sha256"])
    (tree["tree"] / "providers" / "vcs" / "answers.json").write_text(
        json.dumps({"base_commit": git(project, "rev-parse", "HEAD").strip(), "branch_exists": False}))
    (tree["adapter"] / "code.sh").write_text("echo v2 > src/app.py\n")
    ops.request(path, "Carry the providers a skill needs.", "gate-demo", title="Carry the providers")
    first = ops.run_next(path)
    ops.release(path, first["pending_id"])
    out = ops.run_next(path)
    return {"path": path, "out": out, "item": ops.pending(path, out["pending_id"])}


def sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def chain_problems(case: dict) -> list:
    """What breaks the chain, from the files' own bytes: the decision's hash is the sha256 of the effect document's file, the
    document's payload_file_sha256 is the sha256 of the payload the run kept (payload.md), and so is the gate's hash the decision
    carries. An empty list is a whole chain."""
    item, out = case["item"], case["out"]
    problems = []
    if item["kind"] != "effect":
        return [f"the decision is a {item['kind']!r}, not an effect"]
    effect_file = Path(item["payload"]["effect_file"])
    shown = Path(out["run_dir"]) / "payload.md"
    if item["payload_sha256"] != sha(effect_file):
        problems.append("the decision's payload_sha256 is not the sha256 of the effect document's file")
    doc = json.loads(effect_file.read_text())
    if doc.get("payload_file_sha256") != sha(shown):
        problems.append("the document's payload_file_sha256 is not the sha256 of the payload the skill showed")
    if item["payload"]["gate"]["payload_sha256"] != sha(shown):
        problems.append("the gate's payload_sha256 in the decision is not the sha256 of the payload the skill showed")
    if Path(item["payload"]["payload_file"]).read_bytes() != shown.read_bytes():
        problems.append("the payload file the decision names is not the payload the skill showed")
    return problems


def test_the_hash_of_the_payload_the_skill_showed_is_in_the_document_and_the_hash_of_the_document_is_the_decisions(tree):
    case = gate_run(tree)
    item = case["item"]
    assert case["out"]["ending"] == "gate" and item["kind"] == "effect"
    assert chain_problems(case) == []
    shown_hash = sha(Path(case["out"]["run_dir"]) / "payload.md")
    assert HEX64.fullmatch(shown_hash) and HEX64.fullmatch(item["payload_sha256"])
    assert shown_hash != item["payload_sha256"], "two files, two hashes: the document is not the payload"
    assert json.loads(Path(item["payload"]["effect_file"]).read_text())["payload_file_sha256"] == shown_hash
    assert provider_calls(tree) == []  # nothing was sent: the skill stopped at its gate


def test_an_approval_with_the_hash_of_the_payload_instead_of_the_documents_executes_nothing(tree):
    case = gate_run(tree)
    item = case["item"]
    shown_hash = sha(Path(case["out"]["run_dir"]) / "payload.md")
    for wrong in (shown_hash, shown_hash[::-1], "0" * 64):
        with pytest.raises(ops.OpsError):
            ops.approve(case["path"], item["id"], wrong, channel="terminal")
    assert provider_calls(tree) == [] and ops.pending(case["path"], item["id"])["status"] == "open"
    done = ops.approve(case["path"], item["id"], item["payload_sha256"], channel="terminal")
    assert done["task_state"] == "done" and [c["argv"][0] for c in provider_calls(tree)][-1] == "open-pr"


def test_vacuity_a_wrong_payload_hash_in_the_document_fails_the_oracle(tree, monkeypatch):
    real = effect_pull_request.document

    def planted(effect, cfg, request, payload, changeset, task, payload_file_sha256):
        return real(effect, cfg, request, payload, changeset, task, payload_file_sha256[::-1])
    monkeypatch.setattr(effect_pull_request, "document", planted)
    problems = chain_problems(gate_run(tree))
    assert problems == ["the document's payload_file_sha256 is not the sha256 of the payload the skill showed"]


def test_vacuity_a_wrong_document_hash_in_the_decision_fails_the_oracle(tree, monkeypatch):
    real = effects.write

    def planted(run_dir, doc):
        path, digest = real(run_dir, doc)
        return path, digest[::-1]
    monkeypatch.setattr(effects, "write", planted)
    problems = chain_problems(gate_run(tree))
    assert problems == ["the decision's payload_sha256 is not the sha256 of the effect document's file"]


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
