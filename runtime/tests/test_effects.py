"""Tests of the effect: a pull request a skill prepared up to its confirmation gate, approved by the hash of its exact
content and executed by code through the code provider (runtime/effects.py, runtime/ops.py, runtime/state_merge.py;
limits L15, L16, L17). Offline: the stand-in skills demo-code and demo-gate and the stand-in code provider of
runtime/tests/standin_tree.py, which records its arguments and answers as the real one prints; no network, no push.
Every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_effects.py
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
state_merge = st.load("state_merge")

GIT = ["git", "-c", "user.name=Demo", "-c", "user.email=demo@example.test", "-c", "commit.gpgsign=false"]
CODE = {"provider": "github", "repo": "example-org/web", "base": "main"}


@pytest.fixture
def tree(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    return built


def git(folder, *args) -> str:
    return subprocess.run(GIT + ["-C", str(folder), *args], check=True, capture_output=True, text=True).stdout


def provider(tree) -> Path:
    return tree["tree"] / "providers" / "vcs"


def answers(tree, **values) -> None:
    (provider(tree) / "answers.json").write_text(json.dumps(values))


def provider_calls(tree) -> list:
    path = provider(tree) / "calls.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []


def gate_project(tree, change="echo v2 > src/app.py\nrm src/old.py\necho '#!/bin/sh' > src/run.sh\nchmod +x src/run.sh\n",
                 gate=None) -> dict:
    project = tree["project"]
    (project / "src").mkdir()
    (project / "src" / "app.py").write_text("v1\n")
    (project / "src" / "old.py").write_text("old\n")
    (project / ".gitignore").write_text(".workbench-local/\n")
    config = project / "docs" / "workbench" / "runtime.json"
    config.write_text(json.dumps({**json.loads(config.read_text()), "code": CODE}))
    git(project, "init", "-q")
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "start")
    path = str(project)
    ops.accept_config(path, ops.project_config.load(path)["sha256"])
    answers(tree, base_commit=git(project, "rev-parse", "HEAD").strip(), branch_exists=False)
    (tree["adapter"] / "code.sh").write_text(change)
    if gate is not None:
        (tree["adapter"] / "gate.sh").write_text(gate)
    ops.request(path, "Carry the providers a skill needs.", "gate-demo", title="Carry the providers")
    first = ops.run_next(path)
    ops.release(path, first["pending_id"])
    out = ops.run_next(path)
    return {"path": path, "out": out, "item": ops.pending(path, out["pending_id"]) if out.get("pending_id") else None}


def test_limit_16_a_skill_with_a_gate_runs_up_to_the_gate_and_what_it_showed_is_what_the_person_approves(tree):
    case = gate_project(tree)
    item, out = case["item"], case["out"]
    assert out["ending"] == "gate" and item["kind"] == "effect" and item["title"] == "Pull request: Carry the providers"
    effect_file = Path(item["payload"]["effect_file"])
    assert item["payload_sha256"] == hashlib.sha256(effect_file.read_bytes()).hexdigest()
    doc = json.loads(effect_file.read_text())
    shown = (Path(out["run_dir"]) / "payload.md").read_text()
    parsed = effect_pull_request.parse(shown)
    assert (doc["title"], doc["body"]) == (parsed["title"], parsed["body"])  # what it showed is what is approved
    assert (doc["repo"], doc["base"], doc["head"]) == ("example-org/web", "main", "wb/request-1")
    assert item["payload_sha256"] in item["body"] and parsed["body"].rstrip("\n") in item["body"]
    assert provider_calls(tree) == []  # nothing was sent: the skill stopped at its gate


def test_limit_15_the_effect_is_executed_by_code_with_exactly_the_approved_content(tree):
    case = gate_project(tree)
    item = case["item"]
    doc = json.loads(Path(item["payload"]["effect_file"]).read_text())
    done = ops.approve(case["path"], item["id"], item["payload_sha256"], channel="terminal")
    assert done["pull_request"] == {"number": 7, "url": "https://code.example/example-org/web/pull/7"}
    assert done["task_state"] == "done" and done["commit"] == "c" * 40
    calls = provider_calls(tree)
    assert [c["argv"][0] for c in calls] == ["commit-files", "commit-files", "open-pr"]
    real = calls[1]
    assert real["files"] == {f["path"]: f["sha256"] for f in doc["files"]}  # every file has the document's hash
    argv = real["argv"]
    assert "--confirmed" in argv and argv[argv.index("--branch") + 1] == "wb/request-1"
    assert argv[argv.index("--from-branch") + 1] == "main" and argv[argv.index("--repo") + 1] == "example-org/web"
    assert [argv[i + 1] for i, a in enumerate(argv) if a == "--delete"] == ["src/old.py"]
    assert "src/run.sh=755" in argv and "src/app.py=644" in argv
    title = Path(calls[2]["argv"][calls[2]["argv"].index("--title-file") + 1]).read_text()
    assert title == doc["title"] + "\n"
    assert ops.status(case["path"])["requests"][0]["state"] == "done"


def test_an_approval_with_another_hash_executes_nothing(tree):
    case = gate_project(tree)
    for wrong, code in (("0" * 64, 1), (None, 2)):
        with pytest.raises(ops.OpsError) as refused:
            ops.approve(case["path"], case["item"]["id"], wrong, channel="terminal")
        assert refused.value.code == code
    assert provider_calls(tree) == [] and ops.pending(case["path"], case["item"]["id"])["status"] == "open"


def test_a_file_changed_after_the_gate_is_a_deviation_and_nothing_is_sent(tree):
    case = gate_project(tree)
    stored = Path(case["item"]["payload"]["changeset_dir"]) / "files" / "src" / "app.py"
    stored.write_text("edited after the gate\n")
    with pytest.raises(ops.OpsError, match="nothing was sent"):
        ops.approve(case["path"], case["item"]["id"], case["item"]["payload_sha256"], channel="terminal")
    assert provider_calls(tree) == []
    effect_file = Path(case["item"]["payload"]["effect_file"])
    stored.write_text("v2\n")
    effect_file.write_text(effect_file.read_text().replace("Carry the providers", "Something else"))
    with pytest.raises(ops.OpsError, match="its hash changed"):
        ops.approve(case["path"], case["item"]["id"], case["item"]["payload_sha256"], channel="terminal")
    assert provider_calls(tree) == [] and ops.pending(case["path"], case["item"]["id"])["status"] == "open"


def test_a_base_that_moved_or_a_branch_that_already_exists_is_a_deviation_and_nothing_is_sent(tree):
    case = gate_project(tree)
    item = case["item"]
    answers(tree, base_commit="d" * 40, branch_exists=False)
    with pytest.raises(ops.OpsError, match="the base branch moved"):
        ops.approve(case["path"], item["id"], item["payload_sha256"], channel="terminal")
    answers(tree, base_commit=git(tree["project"], "rev-parse", "HEAD").strip(), branch_exists=True)
    with pytest.raises(ops.OpsError, match="already exists on the remote"):
        ops.approve(case["path"], item["id"], item["payload_sha256"], channel="terminal")
    assert all("--dry-run" in c["argv"] for c in provider_calls(tree))  # only dry runs: nothing committed or opened


def test_limit_17_the_approval_lives_in_the_table_and_the_state_file_row_is_a_generated_copy(tree):
    case = gate_project(tree)
    item = case["item"]
    done = ops.approve(case["path"], item["id"], item["payload_sha256"], channel="terminal")
    assert done["state"] == {"written": True}
    ctx = ops_core.context(case["path"])
    rows = ctx["store"].approvals_list(ctx["conn"])
    assert [(r["scope"], r["status"], r["payload_sha256"], r["pending_id"]) for r in rows] == [
        ("action", "executed", item["payload_sha256"], item["id"])]
    state = (tree["project"] / "docs" / "workbench" / "state.md").read_text()
    approvals = state.split("## Approvals", 1)[1].split("## ", 1)[0]
    row = [line for line in approvals.splitlines() if item["payload_sha256"] in line]
    assert len(row) == 1 and row[0].startswith("| action | pull request wb/request-1 into main")
    assert row[0].endswith(f"| sha256:{item['payload_sha256']} | {rows[0]['approved_at'][:10]} | after execution | executed |")
    again = state_merge.write_generated(state, [effects.approval_row(rows[0], json.loads(
        Path(item["payload"]["effect_file"]).read_text()))])
    assert again == state  # the same row is replaced, never doubled
    refused = state_merge.merge_report(state, state, state.replace("after execution | executed", "after execution | revoked"),
                                       "demo-gate")
    assert refused["text"] == state  # a run never writes an approval row


def test_the_commit_is_one_made_by_the_code_provider_and_no_module_of_the_runtime_pushes(tree):
    allowed = {"changeset.py": ("SCRIPT", "AS_BRANCH")}
    for path in sorted((st.REPO / "runtime").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for name in allowed.get(path.name, ()):
            text = re.sub(name + r' = """.*?"""', "", text, flags=re.S)  # the literal scripts of the copy
        code = "\n".join(line for line in text.split('"""')[0::2])
        # the one closed table that maps the effect words to their kinds (CONS-3): a word of the side-effect
        # vocabulary as a dictionary key, no git command
        if path.name == "effects.py":  # only the registry's own module may spell the word, never another one
            code = re.sub(r"^KINDS = \{.*$", "", code, flags=re.M)
        assert not re.search(r"""["']push["']|git[^\n]{0,40}\bpush\b""", code), path.name
        assert not re.search(r"""["']git["'][^\n]*["']commit["']""", code), path.name
    case = gate_project(tree)
    ops.approve(case["path"], case["item"]["id"], case["item"]["payload_sha256"], channel="terminal")
    assert [c["argv"][0] for c in provider_calls(tree)].count("commit-files") == 2  # one dry run, one commit


def test_the_pull_request_is_opened_only_after_the_commit_succeeded(tree):
    case = gate_project(tree)
    item = case["item"]
    answers(tree, base_commit=git(tree["project"], "rev-parse", "HEAD").strip(), fail={"commit-files": [1, "the push was rejected"]})
    with pytest.raises(ops.OpsError, match="the push was rejected"):
        ops.approve(case["path"], item["id"], item["payload_sha256"], channel="terminal")
    assert "open-pr" not in [c["argv"][0] for c in provider_calls(tree)]


def test_a_provider_failure_leaves_the_pending_decision_open_and_approving_again_uses_the_same_keys(tree):
    case = gate_project(tree)
    item = case["item"]
    head = git(tree["project"], "rev-parse", "HEAD").strip()
    answers(tree, base_commit=head, fail={"open-pr": [1, "a server error"]})
    with pytest.raises(ops.OpsError, match="a server error"):
        ops.approve(case["path"], item["id"], item["payload_sha256"], channel="terminal")
    assert ops.pending(case["path"], item["id"])["status"] == "open"
    ctx = ops_core.context(case["path"])
    assert [r["status"] for r in ctx["store"].approvals_list(ctx["conn"])] == ["pending-execution"]
    answers(tree, base_commit="moved-but-committed", branch_exists=True)
    done = ops.approve(case["path"], item["id"], item["payload_sha256"], channel="terminal")  # the key already committed: no check
    assert done["task_state"] == "done" and len(ctx["store"].approvals_list(ctx["conn"])) == 1
    keys = [c["argv"][c["argv"].index("--idempotency-key") + 1] for c in provider_calls(tree)]
    assert len(set(k for k in keys if k.endswith("-commit"))) == 1 and len(set(k for k in keys if k.endswith("-pr"))) == 1
    assert re.fullmatch(r"wb-[0-9a-f]{12}-p\d+-commit", keys[0])


def test_a_payload_that_does_not_parse_or_disagrees_with_the_configuration_opens_a_review_never_an_effect(tree):
    gate = ('d=$(mktemp -d "${TMPDIR:-/tmp}/tmp.XXXXXXXX"); '
            "printf 'Repository: example-org/web\\nBase ← head: develop ← wb/request-1\\nTitle: T\\nBody:\\nB\\n' > \"$d/payload.md\"; "
            "sha=$( (sha256sum \"$d/payload.md\" 2>/dev/null || shasum -a 256 \"$d/payload.md\") | cut -d' ' -f1); "
            "printf 'Nothing was pushed or created yet. This is what will be sent:\\n\\nPayload file: `%s/payload.md`, sha256 `%s`\\n\\nProceed? (yes/no)\\n' \"$d\" \"$sha\" > \"$1/response.md\"\n")
    case = gate_project(tree, gate=gate)
    item = case["item"]
    assert case["out"]["ending"] == "gate" and item["kind"] == "review"
    assert item["body"].startswith("No effect was opened: the payload's base and head (develop ← wb/request-1)")
    assert item["payload_sha256"] is None and provider_calls(tree) == []


def test_a_blocked_change_set_never_becomes_an_effect(tree):
    case = gate_project(tree, change="echo v2 > src/app.py\n")
    # A second request whose first task leaves a blocked change set: its review cannot be released, so the gate task
    # never runs on it; and an effect is never opened from a blocked one.
    (tree["adapter"] / "code.sh").write_text("echo 'KEY=AKIA" + "Q" * 16 + "' > leak.txt\n")
    ops.approve(case["path"], case["item"]["id"], case["item"]["payload_sha256"], channel="terminal")
    ops.request(case["path"], "Another change.", "gate-demo", title="Another change")
    first = ops.run_next(case["path"])
    assert first.get("pending_id"), first
    assert ops.pending(case["path"], first["pending_id"])["payload"]["changeset"]["blocked"] is True
    with pytest.raises(ops.OpsError, match="blocked"):
        ops.release(case["path"], first["pending_id"])
    assert [p["kind"] for p in ops.pending(case["path"])["pending"]] == ["review"]


def test_answering_an_effect_with_only_an_approval_word_is_refused(tree):
    case = gate_project(tree)
    item = case["item"]
    for word in ("yes", "Y", "ok", "Okay.", "APPROVED", "approve", "proceed", "go."):
        with pytest.raises(ops.OpsError, match="approve --id"):
            ops.answer(case["path"], item["id"], word)
    out = ops.answer(case["path"], item["id"], "Yes, but shorten the title.")
    assert out["task_state"] == "ready" and provider_calls(tree) == []


def test_rejecting_an_effect_cancels_the_task_and_sends_nothing(tree):
    case = gate_project(tree)
    out = ops.reject(case["path"], case["item"]["id"], "Not now.")
    assert out["task_state"] == "cancelled" and provider_calls(tree) == []
    assert ops.pending(case["path"], case["item"]["id"])["resolution"] == "rejected"


def test_the_provider_is_found_by_its_class_never_by_a_path_built_here(tree):
    # the operations layer is ops.py and its siblings ops_*.py (CONS-1B)
    names = ["effects.py", "effect_pull_request.py", "ops.py", *sorted(p.name for p in (st.REPO / "runtime").glob("ops_*.py"))]
    text = "".join((st.REPO / "runtime" / name).read_text(encoding="utf-8") for name in names)
    assert "vcs/github.py" not in text and '"vcs"' not in text
    assert effect_pull_request.PROVIDER_CLASS == "integration:vcs" and "resolve.resolve(cls, root=core.ROOT" in text
    case = gate_project(tree)
    found = ops._provider_path(ops_core.context(case["path"])["cfg"], effect_pull_request.PROVIDER_CLASS)
    assert found == str(provider(tree) / "github.py")


def test_a_kind_is_a_module_and_a_row_of_the_registry_and_ops_py_names_none(tree, monkeypatch):
    import sys
    import types
    calls = []
    kind = types.ModuleType("standin_effect_kind")
    real = effect_pull_request
    kind.PROVIDER_CLASS = real.PROVIDER_CLASS
    kind.GATE = True  # a kind the gate path may open (the contract at the head of runtime/effects.py)
    for name in ("refusal", "head", "prepare", "parse", "mismatch", "document", "body", "title", "describe", "verify",
                 "unconfigured", "summary"):
        setattr(kind, name, getattr(real, name))
    kind.document = lambda effect, *rest: real.document("standin", *rest)
    kind.execute = lambda doc, changeset_dir, work_dir, provider, key_prefix, run=None: (
        calls.append((doc["effect"], provider, key_prefix)) or
        {"commit": "e" * 40, "pushed": True, "pull_request": {"number": 9, "url": "https://code.example/p/9"}, "replayed": False})
    monkeypatch.setitem(sys.modules, "standin_effect_kind", kind)
    monkeypatch.setitem(effects.KINDS, "create", "standin_effect_kind")  # no edit of ops.py
    case = gate_project(tree)
    item = case["item"]
    assert item["kind"] == "effect" and json.loads(Path(item["payload"]["effect_file"]).read_text())["effect"] == "standin"
    monkeypatch.setitem(effects.KINDS, "standin", "standin_effect_kind")
    done = ops.approve(case["path"], item["id"], item["payload_sha256"], channel="terminal")
    assert done["pull_request"]["number"] == 9 and len(calls) == 1 and calls[0][0] == "standin"
    assert provider_calls(tree) == []  # the stand-in kind executed it, not the code provider


def test_a_gate_word_with_no_kind_opens_a_review_never_an_effect(tree, monkeypatch):
    monkeypatch.setattr(effects, "KINDS", {})
    case = gate_project(tree)
    item = case["item"]
    assert case["out"]["ending"] == "gate" and item["kind"] == "review"
    assert item["body"].startswith("No effect was opened: the gate's effect 'create' names no kind of effect")
    assert item["payload_sha256"] is None and provider_calls(tree) == []
    with pytest.raises(effects.EffectError) as unknown:
        effects.module_for("nothing")
    assert unknown.value.kind == "usage"


def test_ops_py_names_no_effect_kind():
    code = []
    import ast
    # the operations layer is ops.py and the siblings it re-exports from, ops_*.py (CONS-1B)
    for name in ["ops.py", *sorted(p.name for p in (st.REPO / "runtime").glob("ops_*.py"))]:
        tree_ = ast.parse((st.REPO / "runtime" / name).read_text(encoding="utf-8"))
        docstrings = {id(n.body[0].value) for n in ast.walk(tree_)
                      if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.body
                      and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        for node in ast.walk(tree_):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                code.append(node.value)
    assert not [t for t in code if "open-pr" in t or re.search(r"pull request|pull-request", t)], "ops.py spells an effect kind"


# --- the one registry, keyed by the side-effect vocabulary (CONS-3) ------------------------------------------------


def vocabulary() -> tuple:
    """The side-effect words, read from their one source the way ops._effect_words reads them."""
    found = ops.SIDE_EFFECTS_LINE.search((st.REPO / "scripts" / "validate.py").read_text(encoding="utf-8"))
    return tuple(word.strip().strip('"') for word in found.group(1).split(",") if word.strip())


def test_the_registry_holds_every_kind_keyed_by_a_word_of_the_side_effect_vocabulary():
    assert set(effects.KINDS) <= set(vocabulary())
    assert effects.KINDS == {"create": "effect_pull_request", "push": "effect_commit", "publish": "effect_reply"}


def test_every_kind_exposes_describe_and_the_policy_names_when_it_may_run_under_a_policy():
    for word in effects.KINDS:
        kind = effects.module_for(word)
        assert callable(kind.describe), word
        assert isinstance(kind.POLICY, bool) and isinstance(kind.PROVIDER_CLASS, str), word
        if kind.POLICY:
            for name in ("policy_platform", "policy_effect", "policy_argv"):
                assert callable(getattr(kind, name)), f"{word} runs under a policy and lacks {name}"
    assert effects.module_for("create").POLICY is False and effects.module_for("push").POLICY is True
    assert effects.module_for("publish").POLICY is True and effects.module_for("publish").GATE is False
    assert effects.policy_kinds() == ["publish", "push"]


@pytest.mark.parametrize("word", ["nothing", "schedule", "", None, 7])
def test_a_word_with_no_kind_is_a_usage_error_naming_the_kinds(word):
    with pytest.raises(effects.EffectError) as unknown:
        effects.module_for(word)
    assert unknown.value.kind == "usage" and "create, publish, push" in unknown.value.reason


def test_the_shape_of_a_handed_over_document_and_the_operations_own_flags_live_in_the_registry_module():
    assert effects.EFFECT_KEYS == ("policy", "kind", "target", "files", "items", "idempotency_key", "payload_sha256", "args")
    assert effects.RESERVED_FLAGS == ("--confirmed", "--dry-run", "--allow", "--idempotency-key")
    text = "".join((st.REPO / "runtime" / name).read_text(encoding="utf-8")
                   for name in ["ops.py", *sorted(p.name for p in (st.REPO / "runtime").glob("ops_*.py"))])
    assert not re.search(r"^(EFFECT_KEYS|RESERVED_FLAGS|[A-Z_]*_CALLS) =", text, re.M)  # no table of kinds beside the registry
    assert not [name for name in dir(ops) if name.endswith("_CALLS")]


def test_a_gate_naming_a_kind_that_only_the_policy_path_uses_opens_a_review_never_an_effect(tree):
    manifest = tree["tree"] / "skills" / "demo-gate" / "evals" / "runtime-manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    manifest.write_text(json.dumps({**data, "gate": {**data["gate"], "effect": "push"}}), encoding="utf-8")
    skill_file = manifest.parent.parent / "SKILL.md"
    skill_file.write_text(skill_file.read_text(encoding="utf-8").replace("side_effects: [create]", "side_effects: [push]"),
                          encoding="utf-8")
    assert effects.module_for("push").GATE is False and effects.module_for("create").GATE is True
    case = gate_project(tree)
    item = case["item"]
    assert case["out"]["ending"] == "gate" and item["kind"] == "review"
    assert item["body"].startswith("No effect was opened: the gate's effect 'push' names no kind of effect")
    assert item["payload_sha256"] is None and provider_calls(tree) == []
