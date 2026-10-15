"""The hard limit of the routines (limit L33, finding S10): a routine whose workflow holds a networked script, or that a standing effect
policy covers, is made and changed only from the terminal or the page, whatever `channels.messaging` grants; the brakes (list, pause,
cancel) are the only routine verbs that reach messaging by default; the MCP mode lists routines and nothing else. Enforced in code
like EFFECT_CHANNELS: the operation refuses by the channel it is told it was called from, computed from the workflow and the store.
On the stand-in tree. Offline; invented names only.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_routines_limit.py
"""
from __future__ import annotations

import ast
import datetime

import pytest

import standin_tree as st
from test_ops_flows import ops, ops_core, plan, world, write_flow  # noqa: F401
from test_ops_routines import AT, clock, make  # noqa: F401

operations = st.load("operations")
steps = st.load("steps")
ops_routines = st.load("ops_routines")

GRANT = {"messaging": ["read", "talk", "answer", "routine-brakes", "routine-edit"]}
REFUSAL = "is made and changed only in the terminal or on the page, whatever the project's policy grants"


def literal(name: str):
    tree = ast.parse((st.RUNTIME / "operations.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(name)


def networked_flow(world, monkeypatch, name="with-script"):
    kind = steps.Kind(name="net-script", order=("go",), executors={"go": lambda ctx, state: {}}, networked=True)
    monkeypatch.setitem(steps.REGISTRY, "net-script", kind)
    write_flow(world, name, {"flow": name, "title": "A script", "tasks": [{"key": "run", "step": "net-script", "title": "Run it", "args": {}}]})
    return name


def standing_flow(world, monkeypatch):
    """A workflow of a skill with a side effect, in the pack of an agent that holds an active standing approval."""
    monkeypatch.setattr(plan, "resolve_pack", lambda pack, root: ["demo-gate", "demo-code", "demo-asks", "demo-writes"])
    path = world["project"] / "docs" / "workbench" / "runtime.json"
    raw = __import__("json").loads(path.read_text(encoding="utf-8"))
    raw["area_agents"] = {"delivery": {"pack": "ops", "mode": "autonomous-with-policy", "max_runs_per_day": 50}}
    path.write_text(__import__("json").dumps(raw), encoding="utf-8")
    ops.accept_config(world["path"], ops.project_config.load(world["path"])["sha256"])
    ctx = ops_core.context(world["path"])
    until = (datetime.date.today() + datetime.timedelta(days=30)).isoformat() + "T23:59:59Z"
    ctx["store"].approval_standing_add(ctx["conn"], what="pull requests", by="user", policy_sha256="a" * 64,
                                       bounds={"policy": "pull-requests", "agent": "delivery"}, expires_at=until)
    write_flow(world, "ships", {"flow": "ships", "title": "Ships", "tasks": [{"key": "change", "skill": "demo-gate", "title": "Ship", "text": "Prepare it."}]})
    return "ships"


def test_limit_33_a_routine_with_a_networked_script_or_under_a_standing_policy_is_made_and_changed_only_in_the_terminal_or_on_the_page(
        world, clock, monkeypatch):
    # the channels are a literal of the table, like EFFECT_CHANNELS
    assert literal("ROUTINE_LOCAL_CHANNELS") == operations.ROUTINE_LOCAL_CHANNELS == ("terminal", "page")
    assert "messaging" not in operations.ROUTINE_LOCAL_CHANNELS and "mcp" not in operations.ROUTINE_LOCAL_CHANNELS
    # the policy grants creating and changing to messaging: the shell lets the call through ...
    for verb in ("routine-create", "routine-change"):
        assert operations.permitted(verb, "messaging", GRANT) is True
    net = networked_flow(world, monkeypatch)
    # ... and the operation still refuses, by the channel it is told it came from
    with pytest.raises(ops_core.OpsError, match=REFUSAL + ".*net-script"):
        make(world, flow=net, channel="messaging")
    made = make(world, flow=net, name="from-terminal", channel="terminal")
    assert made["state"] == "draft"
    assert make(world, flow=net, name="from-page", channel="page")["state"] == "draft"
    with pytest.raises(ops_core.OpsError, match=REFUSAL):
        ops.routine_change(world["path"], made["id"], at="01:00", channel="messaging")
    # a routine whose CURRENT workflow is such a one is not changed from messaging either, whatever the new workflow is
    plain = make(world, flow="demo", name="plain", channel="messaging")
    assert plain["state"] == "draft", "a plain workflow may be made from messaging when the project grants it"
    with pytest.raises(ops_core.OpsError, match=REFUSAL):
        ops.routine_change(world["path"], made["id"], flow="demo", channel="messaging")
    assert ops.routine_change(world["path"], plain["id"], at="02:00", channel="messaging")["schedule"]["at"] == "02:00"
    # a standing effect policy that covers the workflow's agent
    ships = standing_flow(world, monkeypatch)
    with pytest.raises(ops_core.OpsError, match=REFUSAL + ".*demo-gate.*a standing approval of delivery covers"):
        make(world, flow=ships, name="ship", channel="messaging")
    assert make(world, flow=ships, name="ship", channel="terminal")["state"] == "draft"


def test_the_brakes_are_the_only_routine_verbs_that_reach_messaging_by_default_and_the_mcp_mode_only_lists(world):
    default = lambda verb, channel="messaging", policy=None: operations.permitted(verb, channel, policy)           # noqa: E731
    assert default("routines") and default("routine-pause") and default("routine-cancel")
    for verb in ("routine-create", "routine-change", "routine-approve", "routine-resume"):
        assert default(verb) is False, verb
    assert operations.permitted("routine-create", "messaging", GRANT) and not operations.permitted("routine-approve", "messaging", GRANT)
    every = {"messaging": list(operations.GROUPS)}
    assert not operations.permitted("routine-approve", "messaging", every) and not operations.permitted("routine-resume", "messaging", every), \
        "approving a routine by the hash of its content, and resuming it, are the terminal's and the page's"
    mcp = [r["name"] for r in operations.OPERATIONS if "mcp" in r["channels"] and r["name"].startswith("routine")]
    assert mcp == ["routines"]
    assert all(r["channels"] == ("terminal", "page") for r in operations.OPERATIONS if r["name"] in ("routine-approve", "routine-resume"))
    assert {r["name"] for r in operations.OPERATIONS if r.get("channel_arg")} >= {"routine-create", "routine-change"}
    assert "routine-pause" in operations.BRAKES and "routine-cancel" in operations.BRAKES
    assert operations.permitted("routine-pause", "page", {"page": ["read"]}) and operations.permitted("routine-cancel", "page", {"page": ["read"]})
