"""Tests of R4-C6 (A-71): the kind of effect a skill's confirmation gate names is chosen by the skill's own
requirement, not by the side-effect word alone. `create` is "open a pull request" for the pull-request skill (it
requires integration:vcs) and "create something in a design tool" for the design skills (they require
integration:design-tool): a design skill's task needs no `code` in the configuration, opens no effect, and its gate,
when a reply reaches it, opens a review. A code skill's `create` is still the pull request and still needs `code`; an
effect is still executed only with its approval. Offline; invented names for the stand-ins, the real manifests for the
unit tests.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_gate_kind_by_requirement.py
"""
from __future__ import annotations

import json
import os

import pytest

import standin_tree as st

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
effects = st.load("effects")
effect_pull_request = st.load("effect_pull_request")
effect_reply = st.load("effect_reply")
manifest = st.load("manifest")
skill_meta = st.load("skill_meta")


@pytest.fixture
def tree(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    (built["tree"] / "flows" / "design-demo.json").write_text(json.dumps({"flow": "design-demo", "title": "Design demo", "tasks": [
        {"key": "system", "skill": "demo-design", "title": "Visual foundations", "text": "write the design system."}]}),
        encoding="utf-8")  # this file's own flow: the shared stand-in tree lists no more flows than before
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    return built


def design_project(tree) -> str:
    """A project with no `code` key at all, as the maintainer's site project is."""
    path = str(tree["project"])
    assert "code" not in json.loads((tree["project"] / "docs" / "workbench" / "runtime.json").read_text())
    ops.accept_config(path, ops.project_config.load(path)["sha256"])
    return path


def request_design(path):
    return ops.request(path, "Write the design system.", "design-demo", title="Visual foundations")


# --- the bug: a design skill's task ran as a pull-request task --------------------------------------------------------


def test_a_design_skill_with_create_runs_with_no_code_key_and_writes_its_document(tree):
    path = design_project(tree)
    request_design(path)
    out = ops.run_next(path)
    assert out["status"] == "ok", out.get("failure")
    assert out["ran"] and out["skill"] == "demo-design"
    assert st.calls(tree["adapter"]) == ["demo-design 1"]  # the model was called: the task did not fail before it
    assert (tree["project"] / "docs" / "design" / "design-system.md").read_text().startswith("# Design system")
    item = ops.pending(path, out["pending_id"])
    assert item["kind"] != "effect" and "effect_file" not in item["payload"]  # no effect is opened for a document


def test_a_design_skill_that_reaches_its_gate_opens_a_review_and_never_an_effect(tree):
    (tree["adapter"] / "design-gate").write_text("1\n")
    path = design_project(tree)
    request_design(path)
    out = ops.run_next(path)
    assert out["status"] == "ok" and out["ending"] == "gate"
    item = ops.pending(path, out["pending_id"])
    assert item["kind"] == "review"
    assert item["payload"]["effect"]["opened"] is False and "names no kind of effect" in item["payload"]["effect"]["why"]
    assert "effect_file" not in item["payload"] and item["payload_sha256"] is None  # nothing to approve by a hash
    assert item["payload"]["gate"]["recovered"] is True  # the person still reads exactly what the skill showed
    assert not [p for p in os.listdir(tree["data"]) if "effect" in p]
    assert not (tree["adapter"].parent.parent / "providers" / "vcs" / "calls.txt").exists()  # no provider was called


# --- the rule: a kind applies to a skill that declares the class of provider that executes it ------------------------


def test_the_kind_of_a_gate_is_chosen_by_the_skills_requirement(tree):
    gate = {"effect": "create", "payload_file": "<tmp>/payload.md"}
    assert ops._effect_kind(gate, ["integration:vcs"]) is effect_pull_request
    assert ops._effect_kind(gate, ["integration:design-tool"]) is None
    assert ops._effect_kind(gate, ["integration:design-tool", "generator:image"]) is None
    assert ops._effect_kind(gate, []) is None  # a skill that declares nothing gets no effect: fail closed
    assert ops._effect_kind(None, ["integration:vcs"]) is None
    with pytest.raises(TypeError):
        ops._effect_kind(gate)  # the requirement is required: a caller that forgets it raises, it never silently gets no kind
    with pytest.raises(TypeError):
        ops._effect_or_review({}, {}, {}, "", {}, {}, None, None, "create")
    assert ops._effect_kind({"effect": "publish", "payload_file": "x"}, ["publisher:<platform>"]) is None  # a policy kind: GATE is false
    assert ops._effect_kind({"effect": "nothing-known", "payload_file": "x"}, ["integration:vcs"]) is None


def test_the_real_skills_that_declare_a_gate_get_the_kind_they_mean():
    root = str(st.REPO)
    got = {}
    for name in sorted(os.listdir(os.path.join(root, "skills"))):
        folder = os.path.join(root, "skills", name)
        if not os.path.isfile(os.path.join(folder, "evals", "runtime-manifest.json")):
            continue
        gate = json.load(open(os.path.join(folder, "evals", "runtime-manifest.json"), encoding="utf-8")).get("gate")
        if gate:
            got[name] = ops._effect_kind(gate, skill_meta.declared(folder)["requires"])
    assert set(got) == {"design-system", "design-execute", "ops-pull-request", "mkt-engage", "product-backlog"}
    assert got["ops-pull-request"] is effect_pull_request  # a code skill's create is still the pull request
    assert got["design-system"] is None and got["design-execute"] is None and got["mkt-engage"] is None
    assert got["product-backlog"] is None  # its create is a ticket in an issue tracker, no pull request: the task stops at its gate and opens a review


def test_a_kind_module_names_the_class_that_executes_it():
    for word in effects.KINDS:
        assert isinstance(effects.module_for(word).PROVIDER_CLASS, str), word


# --- what stays: a code skill's create is the pull request, with its refusals, and an effect needs its approval --------


def test_a_pull_request_skill_still_needs_code_and_a_change_set():
    assert effect_pull_request.refusal({}, None) == "the configuration has no code (provider, repo, base): a task with a confirmation gate needs it"
    assert effect_pull_request.refusal({"code": {"base": "main"}}, None) == "there is no change to open a pull request for"
    assert effect_reply.GATE is False and effect_pull_request.GATE is True and effect_pull_request.POLICY is False
