"""Tests of a task whose skill has a confirmation gate, run up to it, and of the recovery of the payload it wrote
there (runtime/lab.py tmp_in_run, runtime/effects.py, runtime/ops.py). Offline: the stand-in skill demo-gate of
runtime/tests/standin_tree.py writes payload.md under its temporary folder and replies in the pull-request skill's
form; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_gate_payload.py
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

import standin_tree as st

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
effects = st.load("effects")
effect_pull_request = st.load("effect_pull_request")
manifest = st.load("manifest")

GIT = ["git", "-c", "user.name=Demo", "-c", "user.email=demo@example.test", "-c", "commit.gpgsign=false"]
CODE = {"provider": "github", "repo": "example-org/web", "base": "main"}
PAYLOAD = ("```text\nRepository: example-org/web\nBase ← head: main ← wb/request-1\nCommits:\n- 1a2b3c4 Carry the providers\n"
           "Title: feat(installer): carry the providers\nBody:\nWhat changes.\n\nWhy it changes.\n```\n")


@pytest.fixture
def tree(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    return built


def git(folder, *args) -> str:
    return subprocess.run(GIT + ["-C", str(folder), *args], check=True, capture_output=True, text=True).stdout


def gate_project(tree, code=CODE) -> str:
    project = tree["project"]
    (project / "src").mkdir()
    (project / "src" / "app.py").write_text("v1\n")
    (project / ".gitignore").write_text(".workbench-local/\n")
    config = project / "docs" / "workbench" / "runtime.json"
    data = json.loads(config.read_text())
    if code is not None:
        data["code"] = code
    config.write_text(json.dumps(data))
    git(project, "init", "-q")
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "start")
    path = str(project)
    ops.accept_config(path, ops.project_config.load(path)["sha256"])
    return path


def to_the_gate(tree, path, change="echo v2 > src/app.py\n") -> dict:
    (tree["adapter"] / "code.sh").write_text(change)
    ops.request(path, "Carry the providers a skill needs.", "gate-demo", title="Carry the providers")
    first = ops.run_next(path)
    ops.release(path, first["pending_id"])
    return ops.run_next(path)


def run(tree, tmp_path, **more):
    with lab.session():
        return lab.run_skill("demo-gate", "prepare it\n", [], str(tmp_path / "data" / "run-1"), **more)


def test_the_temporary_folder_of_a_run_is_inside_its_run_folder_and_comes_back(tree, tmp_path):
    out = run(tree, tmp_path, tmp_in_run=True)
    assert out["status"] == "ok" and out["tmp"] == os.path.join(out["outputs"], "tmp")
    made = [p for p in Path(out["tmp"]).rglob("payload.md")]
    assert len(made) == 1 and made[0].read_text().startswith("Repository: example-org/web")
    assert not [p for p in os.listdir(tmp_path) if p.startswith("eval-")]
    without = run(tree, tmp_path)
    assert without["tmp"] is None and not (Path(without["outputs"]) / "tmp").exists()


def test_the_path_of_the_temporary_folder_is_never_replaced_as_a_secret(tree, tmp_path, monkeypatch):
    monkeypatch.setenv("STANDIN_KEY", "invented-value-0123456789")
    out = run(tree, tmp_path, tmp_in_run=True, pass_env=["STANDIN_KEY"])
    told = (Path(out["outputs"]) / "gate-tmpdir.txt").read_text().strip()
    assert told and told.endswith(os.sep + "tmp") and f"Temporary folder: {told}" in out["response"]
    assert "[redacted" not in out["response"] and "invented-value-0123456789" not in out["response"]


def test_the_payload_is_recovered_only_when_its_hash_is_the_one_the_reply_states(tmp_path):
    tmp = tmp_path / "tmp"
    (tmp / "tmp.a1").mkdir(parents=True)
    (tmp / "tmp.a1" / "payload.md").write_text(PAYLOAD)
    digest = hashlib.sha256(PAYLOAD.encode()).hexdigest()
    reply = f"Nothing was pushed or created yet.\n\nPayload file: `/eval/tmp/tmp.a1/payload.md`, sha256 `{digest}`\n\nProceed? (yes/no)"
    found = effects.recover_payload(reply, str(tmp), lab.readable)
    assert found["recovered"] is True and found["text"] == PAYLOAD and found["sha256"] == digest
    wrong = effects.recover_payload(reply.replace(digest, "0" * 64), str(tmp), lab.readable)
    assert wrong == {"recovered": False, "why": "the file is not the one the reply hashed"}
    (tmp / "tmp.b2").mkdir()
    (tmp / "tmp.b2" / "payload.md").write_text("Repository: other\n")
    elsewhere = reply.replace("/eval/tmp/tmp.a1/payload.md", "/somewhere/else/payload.md")
    assert effects.recover_payload(elsewhere, str(tmp), lab.readable)["recovered"] is True  # the one whose hash it is
    assert effects.recover_payload(elsewhere.replace(digest, "1" * 64), str(tmp), lab.readable)["recovered"] is False
    assert effects.recover_payload(reply, str(tmp_path / "missing"), lab.readable)["recovered"] is False


def test_a_reply_without_the_payload_line_or_with_two_is_not_recovered(tmp_path):
    tmp = tmp_path / "tmp"
    (tmp / "d").mkdir(parents=True)
    (tmp / "d" / "payload.md").write_text(PAYLOAD)
    line = f"Payload file: `/eval/tmp/d/payload.md`, sha256 `{hashlib.sha256(PAYLOAD.encode()).hexdigest()}`"
    assert effects.recover_payload("Proceed? (yes/no)", str(tmp), lab.readable)["why"] == "the reply names no payload file"
    two = effects.recover_payload(f"{line}\n{line}\nProceed? (yes/no)", str(tmp), lab.readable)
    assert two == {"recovered": False, "why": "the reply names more than one payload file"}


def test_a_link_named_payload_md_is_never_read(tmp_path):
    tmp, outside = tmp_path / "tmp", tmp_path / "outside"
    outside.mkdir()
    (outside / "payload.md").write_text(PAYLOAD)
    (tmp / "d").mkdir(parents=True)
    os.symlink(outside / "payload.md", tmp / "d" / "payload.md")
    os.symlink(outside, tmp / "e")
    digest = hashlib.sha256(PAYLOAD.encode()).hexdigest()
    for stated in ("/eval/tmp/d/payload.md", "/eval/tmp/e/payload.md"):
        found = effects.recover_payload(f"Payload file: `{stated}`, sha256 `{digest}`", str(tmp), lab.readable)
        assert found == {"recovered": False, "why": "no payload.md was found under the run's temporary folder"}


def test_a_payload_in_the_skills_form_parses_and_any_other_form_does_not():
    parsed = effect_pull_request.parse(PAYLOAD)
    assert parsed == {"repository": "example-org/web", "base": "main", "head": "wb/request-1",
                      "title": "feat(installer): carry the providers", "body": "What changes.\n\nWhy it changes."}
    bare = PAYLOAD.replace("```text\n", "").replace("```\n", "").replace("Commits:\n- 1a2b3c4 Carry the providers\n", "")
    assert effect_pull_request.parse(bare)["head"] == "wb/request-1"
    for broken in (PAYLOAD.replace("Repository:", "Repo:"), PAYLOAD.replace("Base ← head: main ← wb/request-1", "Base: main"),
                   PAYLOAD.replace("Title: ", "Subject: "), PAYLOAD.replace("Body:\n", "Body: inline\n"),
                   "Some text before\n" + PAYLOAD, PAYLOAD.replace("What changes.\n\nWhy it changes.\n", "")):
        assert effect_pull_request.parse(broken) is None, broken


def test_a_gate_task_sees_the_change_set_as_one_commit_on_a_branch_over_its_base(tree):
    path = gate_project(tree)
    out = to_the_gate(tree, path)
    outputs = Path(out["run_dir"]) / "outputs"
    assert (outputs / "gate-branches.txt").read_text().split() == ["main", "wb/request-1"]
    assert (outputs / "gate-log.txt").read_text().split("\n")[:2] == ["Carry the providers", "fixture"]
    assert (outputs / "gate-status.txt").read_text() == ""  # the change is committed, nothing is left uncommitted
    assert out["ending"] == "gate" and out["status"] == "ok"
    item = ops.pending(path, out["pending_id"])
    gate = item["payload"]["gate"]
    assert gate["recovered"] is True and gate["parsed"] is True
    kept = Path(out["run_dir"]) / "payload.md"
    assert gate["payload_file"] == str(kept) and hashlib.sha256(kept.read_bytes()).hexdigest() == gate["payload_sha256"]
    assert [t["name"].rsplit("/", 1)[-1] for t in gate["tmp_left"]] == ["payload.md"]
    assert not (outputs / "tmp").exists()  # only the recovered payload is kept
    assert (tree["project"] / "src" / "app.py").read_text() == "v1\n"


def test_a_gate_task_with_no_change_set_fails_before_any_model_call(tree):
    path = gate_project(tree)
    out = to_the_gate(tree, path, change="true\n")
    assert out["status"] == "failed" and out["failure"]["reason"] == "there is no change to open a pull request for"
    assert st.calls(tree["adapter"]) == ["demo-code 1"]
    config = tree["project"] / "docs" / "workbench" / "runtime.json"
    data = json.loads(config.read_text())
    del data["code"]
    config.write_text(json.dumps(data))
    git(tree["project"], "commit", "-q", "-am", "no code host")
    ops.accept_config(path, ops.project_config.load(path)["sha256"])
    out = to_the_gate(tree, path)
    assert out["status"] == "failed" and "has no code" in out["failure"]["reason"]
    assert [c.split()[0] for c in st.calls(tree["adapter"])] == ["demo-code", "demo-code"]  # never demo-gate


def test_the_manifest_opening_is_the_first_line_of_the_skills_asking_reply():
    text = (st.REPO / "skills" / "ops-pull-request" / "SKILL.md").read_text(encoding="utf-8")
    loaded = manifest.load(str(st.REPO), "ops-pull-request")
    assert loaded["asking_openings"] == manifest.asking_openings_of(text)
    first = text.split("Reply that asks for approval", 1)[1].split("\n````markdown\n", 1)[1].split("\n", 1)[0]
    assert first.startswith(loaded["asking_openings"][0]) and first.startswith("Nothing was pushed or created yet")
    assert loaded["gate"] == {"effect": "create", "payload_file": "<tmp>/payload.md"}
