"""The channel policy for the page and the MCP mode, on the server (MSG-3b; decisions M-8, M-12, M-13): the groups and
their validity, the pure helper `operations.refusal`, the page's 409 before anything runs, the brakes, a typed line under
the channel that carries it (and never an effect), the MCP per-call check, the queue's re-check at the drain, the
`permissions` field of GET /projects and the filtered `commands`. Offline, no model.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_channel_policy.py
"""
from __future__ import annotations

from phone_literals import PLAIN_REFUSAL  # noqa: E402

import json
import os
import threading
import types
from pathlib import Path

import pytest

import standin_tree as st
from test_effects import gate_project, provider_calls, tree  # noqa: F401  (the effect fixture of test_effects.py)
from test_messaging_policy import decisions
from test_service import PORT, TOKEN, WAIT, Standin, api, call, wait_job, world  # noqa: F401  (the stand-in world of test_service.py)

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_say = st.load("ops_say")
operations = st.load("operations")
project_config = st.load("project_config")
service = st.load("service")
mcp = st.load("mcp")

AGENTS = {"planning": {"pack": "planning", "mode": "supervised"}, "brand": {"pack": "brand", "mode": "autonomous", "max_runs_per_day": 3}}


def sentence(op, channel="page"):
    return f"/{op} is not enabled for this channel; the project's configuration (channels.{channel}) turns it on"


def set_channels(path, channels, agents=None):
    """Write `channels` (and, with agents, area_agents) into the project's runtime.json and accept the new hash, as the person does."""
    file = Path(path) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(file.read_text())
    raw.pop("channels", None)
    if channels is not None:
        raw["channels"] = channels
    if agents is not None:
        raw["area_agents"] = agents
    file.write_text(json.dumps(raw))
    ops.accept_config(path, project_config.load(path)["sha256"], widen=ops.config(path)["widening_sha256"])


def real_world(path):
    projects = [{"id": service.project_id(path), "name": "p", "path": path}]
    return types.SimpleNamespace(svc=service.Service(ops, projects, TOKEN, PORT, None, log=lambda line: None), projects=projects)


# --- the groups --------------------------------------------------------------------------------------------------------


def test_every_row_of_the_page_the_mcp_mode_and_messaging_is_in_exactly_one_group_and_each_approve_kind_too():
    for row in operations.OPERATIONS:
        if not {"page", "mcp", "messaging"} & set(row["channels"]):
            continue
        owners = [(g, s["kind"]) for g, s in operations.GROUPS.items() if row["name"] in s["operations"] and g not in operations.MESSAGING_ONLY_GROUPS]
        if row["name"] == "approve":
            # the umbrella and one group for each word of an effect (POL-1), and the networked plans beside the plans
            assert sorted(k for _, k in owners) == ["acceptance", "effect", "effect:calendar", "effect:create", "effect:files", "effect:mailbox", "effect:publish", "effect:send", "effect:send-own", "effect:write",
                                                     "plan", "plan:networked"], owners
        elif row["name"] == "cancel":   # R18: the one operation in two groups, so that a policy written with reject-cancel stays valid
            assert sorted(g for g, _ in owners) == ["brakes", "reject-cancel"] and {k for _, k in owners} == {None}, owners
        elif row["name"] == "attachment-hold":   # ATT-1: the group of the files, and the grant that adds them without a card (kind "direct")
            assert sorted(owners, key=str) == [("add-sources", None), ("add-sources-direct", "direct")], owners
        else:
            assert len(owners) == 1 and owners[0][1] is None, (row["name"], owners)
    # POL-2: `read-limited` is a subset of `read` (the one group beside `brakes`/`reject-cancel` that shares operations), valid on a messaging app alone
    assert set(operations.GROUPS["read-limited"]["operations"]) < set(operations.GROUPS["read"]["operations"])
    assert operations.MESSAGING_ONLY_GROUPS == ("read-limited", "ask-mail", "interpret")
    for group, spec in operations.GROUPS.items():  # every operation a group names is a row of the table
        for name in spec["operations"]:
            operations.by_name(name)
    assert operations.GROUPS["go-ahead"] == {"operations": ("go-ahead",), "kind": None}
    assert operations.GROUPS["approve-effects"] == {"operations": ("approve",), "kind": "effect"}
    assert "reject-cancel-retry" not in operations.GROUPS and operations.GROUPS["reject-cancel"]["operations"] == ("reject", "cancel")
    assert operations.GROUPS["retry"]["operations"] == ("retry",)
    assert operations.DEFAULT_POLICY == {"messaging": ("read", "talk", "answer", "routine-brakes")}
    assert ops.EFFECT_CHANNELS is operations.EFFECT_CHANNELS == ("terminal", "page")


def test_a_group_is_valid_on_a_channel_with_one_operation_in_its_ceiling_and_the_page_and_mcp_list_read():
    ok = project_config._channels
    assert ok({"page": ["read", "approve-effects", "go-ahead", "documents", "set-mode", "retry", "dispatch", "verdict"]})
    assert ok({"mcp": ["read", "talk", "request"]}) == {"mcp": ["read", "talk", "request"]}
    assert ok({"messaging": ["read", "reject-cancel", "retry"]}) == {"messaging": ["read", "reject-cancel", "retry"]}  # reject and cancel are both on it
    assert ok({"messaging": []}) == {"messaging": []}                        # the closed default is not a "must list read" channel
    assert ok({"page": ["read", "reject-cancel"], "mcp": ["read"]})
    assert ok({"mcp": ["read", "retry"]}) == {"mcp": ["read", "retry"]}      # POL-1: a grant of the MCP mode (it was invalid before: the ceiling has no retry), valid because the project's own entry lists it
    for bad in ({"page": ["talk"]}, {"mcp": []}, {"mcp": ["talk"]},           # page and mcp list read
                {"mcp": ["read", "approve-effects"]}, {"messaging": ["approve-effects"]},   # approve-effects is for the page alone
                {"mcp": ["read", "go-ahead"]}, {"messaging": ["go-ahead"]},  # no operation of the group in the ceiling
                {"messaging": ["verdict"]}, {"messaging": ["documents"]},
                {"chat": ["read"]}, {"terminal": ["read"]}, {"nobody": ["read"]}):
        with pytest.raises(project_config.ConfigError):
            ok(bad)
    with pytest.raises(project_config.ConfigError, match="never narrowed"):
        ok({"chat": ["read"]})
    with pytest.raises(project_config.ConfigError, match="page only"):
        ok({"mcp": ["read", "approve-effects"]})


def test_the_group_flow_write_covers_saving_a_flow_and_handing_a_file_over_and_neither_workflows_nor_flows_is_a_group():
    assert operations.GROUPS["flow-write"] == {"operations": ("flow-save", "stage-file"), "kind": None}
    assert "workflows" not in operations.GROUPS and "flows" not in operations.GROUPS, "no alias: the group exists under one name"
    assert project_config._channels({"page": ["read", "flow-write"]}) == {"page": ["read", "flow-write"]}
    assert operations.permitted("flow-save", "page", {"page": ["read", "flow-write"]}) and operations.permitted("stage-file", "page", {"page": ["read", "flow-write"]})
    assert not operations.permitted("flow-save", "page", {"page": ["read"]}) and not operations.permitted("stage-file", "page", {"page": ["read"]})
    for stale in ("workflows", "flows"):      # `flows` is the read operation of the group `read`, never a group: narrowing to it must not grant a write
        with pytest.raises(project_config.ConfigError, match=rf"'{stale}' is not a group \(known: .*\bflow-write\b"):
            project_config._channels({"page": ["read", stale]})


def test_defaults_page_and_mcp_keep_their_ceiling_and_messaging_stays_closed():
    for row in operations.OPERATIONS:
        for channel in ("page", "mcp"):
            expected = channel in row["channels"]
            assert operations.permitted(row["name"], channel, None) is expected, (row["name"], channel)
            assert operations.permitted(row["name"], channel, {}) is expected
            assert (operations.refusal(row["name"], channel, None) is None) is expected
    for kind in ("plan", "acceptance", "effect"):
        assert operations.permitted("approve", "page", None, kind) and operations.permitted("approve", "page", {"mcp": ["read"]}, kind)
    assert not operations.permitted("approve", "mcp", None, "plan")
    assert operations.policy_groups("messaging", None) == ("read", "talk", "answer", "routine-brakes") and operations.policy_groups("page", None) is None


def test_refusal_is_a_pure_sentence_and_the_terminal_and_the_conversation_are_never_refused():
    policy = {"page": ["read", "approve-plans"]}
    assert operations.refusal("approve", "page", policy, "plan") is None
    assert operations.refusal("approve", "page", policy, "acceptance") == sentence("approve")
    assert operations.refusal("approve", "page", policy, "effect") == sentence("approve")
    assert operations.refusal("approve", "page", policy, "plan", go_ahead=True) == sentence("go-ahead")
    assert operations.refusal("approve", "page", {"page": ["read", "approve-plans", "go-ahead"]}, "plan", go_ahead=True) is None
    assert operations.refusal("approve", "page", {"page": ["read", "go-ahead"]}, "plan") == sentence("approve")
    assert operations.refusal("say", "page", policy) == sentence("say")
    assert operations.refusal("say", "mcp", {"mcp": ["read"]}) == sentence("say", "mcp")
    assert operations.refusal("status", "page", {"page": ["read"]}) is None
    assert operations.refusal("approve", "terminal", {"terminal": []}, "effect", True) is None
    assert operations.refusal("status", "chat", policy) is None and operations.refusal("approve", "chat", policy, "plan") is None
    assert operations.refusal("nothing", "page", policy) == sentence("nothing")


def test_permissions_are_names_and_pairs_in_the_tables_order():
    everything = operations.permissions("page", None)
    assert "approve" not in everything and "set-mode" not in everything
    assert {"approve:plan", "approve:acceptance", "approve:effect", "approve:go-ahead", "set-mode:down", "set-mode:up", "cancel", "go-ahead"} <= set(everything)
    assert operations.permissions("page", {"page": ["read", "approve-plans", "go-ahead"]}) == [
        "status", "task", "flows", "flow-check", "config", "progress", "pending", "approve:plan", "approve:go-ahead", "go-ahead", "cancel", "stop-task", "set-mode:down",
        "agents", "conversation", "skills", "costs", "connections", "artifacts", "artifact", "artifact-raw", "version", "commands", "items", "instructions", "routines", "routine-pause", "routine-cancel"]
    only_read = operations.permissions("page", {"page": ["read"]})
    assert only_read == ["status", "task", "flows", "flow-check", "config", "progress", "pending", "cancel", "stop-task", "set-mode:down", "agents", "conversation",
                         "skills", "costs", "connections", "artifacts", "artifact", "artifact-raw", "version", "commands", "items", "instructions", "routines", "routine-pause", "routine-cancel"]  # the brakes are there
    assert "set-mode:up" in operations.permissions("page", {"page": ["read", "set-mode"]})
    assert operations.permissions("page", {"page": ["read", "approve-effects", "approve-acceptances"]}).count("approve:effect") == 1


def test_the_brakes_are_for_the_page_alone_and_do_not_leak_to_messaging_or_mcp():
    assert operations.BRAKES == ("cancel", "stop-task", "set-mode", "routine-pause", "routine-cancel")
    assert operations.permitted("cancel", "page", {"page": ["read"]}) and operations.permitted("set-mode", "page", {"page": ["read"]})
    assert not operations.permitted("cancel", "messaging", {"messaging": ["read"]})   # a written policy that leaves the group out narrows it
    assert not operations.permitted("cancel", "messaging", None) and not operations.permitted("stop-task", "messaging", None)   # R18: every channel is restrictive by default, `brakes` is a grant
    assert operations.permitted("cancel", "messaging", {"messaging": ["reject-cancel"]})
    assert operations.permitted("cancel", "messaging", {"messaging": ["brakes"]}) and not operations.permitted("stop-task", "messaging", {"messaging": ["reject-cancel"]})
    assert not operations.permitted("cancel", "mcp", None) and not operations.permitted("set-mode", "mcp", None)
    assert not operations.policy_allows("set-mode", "page", {"page": ["read"]})   # the move up is not a brake


# --- the page: a route is refused before anything runs ------------------------------------------------------------------


def stand_in(world, groups, kind="plan"):  # noqa: F811
    world.fake.answers["config"] = {"path": "x", "sha256": "a" * 64, "accepted": True, "data_dir": str(world.tmp / "data"),
                                    "channels": {"page": groups}}
    world.fake.answers["pending"] = {"kind": kind}


def test_a_policy_without_the_group_makes_each_matching_route_a_409_before_a_job_or_a_byte_exists(world):  # noqa: F811
    stand_in(world, ["read"])
    posts = [("approve", "/pending/7/approve", {"sha256": "a" * 64}), ("go-ahead", "/tasks/7/go-ahead", {}), ("retry", "/tasks/7/retry", {}),
             ("sync", "/sync", {}), ("dispatch", "/dispatch", {}), ("request", "/requests", {"text": "x"}),
             ("answer", "/pending/7/answer", {"text": "x"}), ("release", "/pending/7/release", {}), ("reject", "/pending/7/reject", {}),
             ("verdict", "/runs/7/verdict", {"word": "worked"}), ("say", "/conversation", {"text": "hello"}),
             ("route", "/requests/7/route", {})]
    for kind in ("effect", "acceptance", "plan"):
        world.fake.answers["pending"] = {"kind": kind}
        status, _, body = call(world, "POST", api(world, "/pending/7/approve"), {"sha256": "a" * 64})
        assert (status, body["error"], body["message"]) == (409, "refused", sentence("approve")), kind
    for name, tail, given in posts:
        status, _, body = call(world, "POST", api(world, tail), given)
        assert (status, body["error"], body["message"]) == (409, "refused", sentence(name)), name
    upload = {"name": "brief.md", "content_base64": "aGVsbG8="}
    assert call(world, "POST", api(world, "/tasks/7/files"), upload)[2]["message"] == sentence("hand-over")
    assert not os.path.exists(world.tmp / "data" / "uploads"), "the bytes of a refused upload are never written"
    assert world.svc.jobs == {} and [c[0] for c in world.fake.calls] == ["pending"] * 4, "no job, and no operation ran"
    # the reads, the brakes and the mode's own check
    assert call(world, "GET", api(world, "/status"))[0] == 200
    assert call(world, "POST", api(world, "/requests/7/cancel"), {})[0] == 200
    assert call(world, "POST", api(world, "/agents/writer/mode"), {"mode": "supervised"})[0] == 200   # the direction is the operation's to check
    # a group opens only its own routes
    for groups, opens in ((["read", "retry"], "retry"), (["read", "documents"], "sync"), (["read", "dispatch"], "dispatch"),
                          (["read", "request"], "request"), (["read", "talk"], "say"), (["read", "answer"], "answer")):
        stand_in(world, groups)
        for name, tail, given in posts:
            status = call(world, "POST", api(world, tail), given)[0]
            assert (status != 409) == (name == opens or (name == "route" and opens == "request")), (groups, name)
    stand_in(world, ["read", "documents"])
    assert call(world, "POST", api(world, "/tasks/7/files"), upload)[0] != 409


def test_an_unaccepted_configuration_is_left_to_the_operation_and_a_read_asks_nothing_of_the_configuration(world):  # noqa: F811
    world.fake.answers["config"] = {"path": "x", "sha256": "a" * 64, "accepted": False, "data_dir": str(world.tmp), "channels": {"page": ["read"]}}
    assert call(world, "POST", api(world, "/requests"), {"text": "x"})[0] == 200      # the operation answers (412 in the real one)
    world.fake.config_reads.clear()
    assert call(world, "GET", api(world, "/status"))[0] == 200 and world.fake.config_reads == []


def test_a_page_policy_without_dispatch_leaves_the_services_own_dispatch_loop_running(world):  # noqa: F811
    stand_in(world, ["read"])
    seen, done = [], threading.Event()

    def dispatch(project, wait=None):
        seen.append(wait)
        done.set()
        return {"stopped": "no task is ready"}

    world.fake.answers["dispatch"] = dispatch
    assert call(world, "POST", api(world, "/dispatch"), {})[0] == 409     # the person's request is refused
    stop = threading.Event()
    runner = threading.Thread(target=service.dispatch_loop, args=(world.svc, 0.01, stop))
    runner.start()
    assert done.wait(WAIT)                                                 # the loop the person started with the service runs
    stop.set()
    runner.join(WAIT)
    assert seen and set(seen) == {False}


def test_the_page_commands_leave_out_what_its_policy_refuses_and_new_follows_talk(world):  # noqa: F811
    rows = [{"command": c["usage"].split(" ", 1)[0], "arguments": "", "help": c["help"]} for c in operations.chat_commands()]
    world.fake.answers["commands"] = {"commands": rows}
    names = lambda: [c["command"] for c in call(world, "GET", api(world, "/commands"))[2]["commands"]]  # noqa: E731
    stand_in(world, ["read", "approve-plans"])
    world.fake.answers["commands"] = {"commands": rows}
    assert names() == ["/help", "/status", "/progress", "/pending", "/approve", "/cancel", "/stop-task"]
    stand_in(world, ["read", "talk", "answer", "release", "reject-cancel", "retry", "approve-effects"])
    world.fake.answers["commands"] = {"commands": rows}
    assert names() == ["/help", "/status", "/progress", "/pending", "/answer", "/release", "/approve", "/reject", "/retry", "/cancel", "/stop-task", "/new"]
    world.fake.answers["config"] = {"path": "x", "sha256": "a" * 64, "accepted": True, "data_dir": str(world.tmp), "channels": {}}
    assert names() == [r["command"] for r in rows]                          # no policy: the ceiling, whole


# --- the page: the real operations ----------------------------------------------------------------------------------------


def test_the_terminal_still_does_what_a_page_policy_withholds_and_the_page_does_it_when_the_group_is_listed(tree):  # noqa: F811
    path, plan_id, digest, accept_id, effect = decisions(tree)
    set_channels(path, {"page": ["read"]})
    world = real_world(path)
    for item, given in ((accept_id, {}), (plan_id, {"sha256": digest}), (effect["id"], {"sha256": effect["payload_sha256"]})):
        status, _, body = call(world, "POST", api(world, f"/pending/{item}/approve"), given)
        assert (status, body["message"]) == (409, sentence("approve")), item
    assert world.svc.jobs == {} and provider_calls(tree) == []
    assert all(ops.pending(path, i)["status"] == "open" for i in (plan_id, accept_id, effect["id"]))
    ops.approve(path, accept_id, channel="terminal")
    assert ops.pending(path, accept_id)["status"] == "resolved"
    set_channels(path, {"page": ["read", "go-ahead"]})                      # a go-ahead group does not approve a plan
    assert call(world, "POST", api(world, f"/pending/{plan_id}/approve"), {"sha256": digest})[0] == 409
    set_channels(path, {"page": ["read", "approve-plans"]})
    status, _, body = call(world, "POST", api(world, f"/pending/{plan_id}/approve"), {"sha256": digest, "go_ahead": ["market"]})
    assert (status, body["message"]) == (409, sentence("go-ahead"))         # task keys need the group go-ahead as well
    set_channels(path, {"page": ["read", "approve-plans", "go-ahead"]})
    status, _, body = call(world, "POST", api(world, f"/pending/{plan_id}/approve"), {"sha256": digest})
    assert status == 202 and wait_job(world, body["job"])["state"] == "done"
    assert ops.pending(path, plan_id)["status"] == "resolved"
    set_channels(path, {"page": ["read", "approve-effects"]})               # the page approves an effect with its hash once the group is on
    status, _, body = call(world, "POST", api(world, f"/pending/{effect['id']}/approve"), {"sha256": effect["payload_sha256"]})
    assert status == 202 and wait_job(world, body["job"])["state"] == "done" and provider_calls(tree) != []


def test_the_brakes_cancel_and_a_move_down_work_under_a_page_that_lists_read_only_and_a_move_up_needs_set_mode(tree):  # noqa: F811
    path = str(tree["project"])
    set_channels(path, {"page": ["read"]}, AGENTS)
    world = real_world(path)
    request = ops.request(path, "Something to cancel.")["request"]
    assert call(world, "POST", api(world, f"/requests/{request}/cancel"), {})[0] == 200
    status, _, body = call(world, "POST", api(world, "/agents/brand/mode"), {"mode": "supervised"})   # down: autonomous -> supervised
    assert status == 200 and body["accepted"] is True and body["by"] == "code:narrowing"
    sha = ops.config(path)["sha256"]
    status, _, body = call(world, "POST", api(world, "/agents/brand/mode"), {"mode": "autonomous"})   # up
    assert (status, body["message"]) == (409, sentence("set-mode"))
    assert ops.config(path)["sha256"] == sha, "nothing was written"
    assert call(world, "POST", api(world, "/agents/brand/mode"), {"mode": "supervised"})[0] == 200      # the same mode: nothing to widen
    set_channels(path, {"page": ["read", "set-mode"]})
    status, _, body = call(world, "POST", api(world, "/agents/brand/mode"), {"mode": "autonomous"})
    assert status == 200 and body["accepted"] is False and "accept-config" in body["next"]


def test_a_move_up_is_checked_by_the_operation_for_the_page_and_not_for_the_terminal(tree):  # noqa: F811
    path = str(tree["project"])
    set_channels(path, {"page": ["read"]}, AGENTS)
    with pytest.raises(ops.OpsError) as refused:
        ops.set_mode(path, "planning", "autonomous", channel="page")
    assert refused.value.code == 1 and str(refused.value) == sentence("set-mode")
    ops.set_mode(path, "planning", "autonomous", channel="terminal")
    assert json.loads((tree["project"] / "docs" / "workbench" / "runtime.json").read_text())["area_agents"]["planning"]["mode"] == "autonomous"


# --- a line carries its own channel ----------------------------------------------------------------------------------------


def test_a_typed_approve_on_the_page_follows_the_page_policy_and_never_approves_an_effect(tree):  # noqa: F811
    path, plan_id, digest, accept_id, effect = decisions(tree)
    set_channels(path, {"page": ["read", "talk", "approve-plans"]})
    reply = ops.say(path, f"/approve {accept_id}", channel="page")["reply"]
    assert reply == "error: " + sentence("approve") and ops.pending(path, accept_id)["status"] == "open"
    assert ops.say(path, "/reject " + str(plan_id), channel="page")["reply"] == "error: " + sentence("reject")
    assert ops.say(path, "/cancel 9999", channel="page")["reply"] != "error: " + sentence("cancel")      # the brake
    ops.say(path, f"/approve {plan_id} {digest}", channel="page")
    assert ops.pending(path, plan_id)["status"] == "resolved"
    set_channels(path, {"page": ["read", "talk", "approve-effects", "approve-acceptances"]})
    reply = ops.say(path, f"/approve {effect['id']} {effect['payload_sha256']}", channel="page")["reply"]
    assert reply.startswith("error: an effect is approved in the terminal, with its hash") and provider_calls(tree) == []
    assert ops.pending(path, effect["id"])["status"] == "open"
    for channel in ("terminal", "mcp", "messaging", None):
        said = ops.say(path, f"/approve {effect['id']} {effect['payload_sha256']}", channel=channel, sender=("telegram:4242" if channel == "messaging" else None))["reply"]
        assert (said == PLAIN_REFUSAL if channel == "messaging" else said.startswith("error: ")) and provider_calls(tree) == [], channel
    ops.say(path, f"/approve {accept_id}", channel="page")
    assert ops.pending(path, accept_id)["status"] == "resolved"
    set_channels(path, {"page": ["read"]})                                 # a line needs talk to be said at all, on the page route
    status, _, body = call(real_world(path), "POST", api(real_world(path), "/conversation"), {"text": "/status"})
    assert (status, body["message"]) == (409, sentence("say"))


def test_a_typed_command_on_the_mcp_mode_is_checked_under_mcp(tree):  # noqa: F811
    path, plan_id, digest, accept_id, effect = decisions(tree)
    set_channels(path, {"mcp": ["read", "talk"]})
    assert ops.say(path, "/release 1", channel="mcp")["reply"] == "error: " + sentence("release", "mcp")
    assert ops.say(path, "/answer 1 text", channel="mcp")["reply"] == "error: " + sentence("answer", "mcp")
    assert ops.say(path, "/status", channel="mcp")["reply"]
    assert ops.say(path, "/cancel 1", channel="mcp")["reply"] == "error: /cancel is done in the terminal or on the page"
    set_channels(path, {"mcp": ["read", "talk", "answer", "release"]})
    assert "not enabled" not in ops.say(path, "/release 1", channel="mcp")["reply"]
    assert "not enabled" not in ops.say(path, "/answer 99999 text", channel="mcp")["reply"]


# --- the MCP mode: the policy is checked at each call, per project -----------------------------------------------------------


def second_project(tmp_path, tree, name="second"):  # noqa: F811
    folder = tmp_path / name
    (folder / "docs" / "workbench").mkdir(parents=True)
    (folder / "docs" / "workbench" / "runtime.json").write_text(json.dumps(
        {"workbench": str(tree["tree"]), "data_dir": str(tmp_path / f"{name}-data"), "store_db": str(tmp_path / f"{name}-store" / "tasks.sqlite"),
         "sources_dir": str(tmp_path / f"{name}-sources")}))
    (folder / "docs" / "workbench" / "state.md").write_text((tree["project"] / "docs" / "workbench" / "state.md").read_text())
    (folder / "AGENTS.md").write_text("# Project\n")
    ops.accept_config(str(folder), project_config.load(str(folder))["sha256"])
    return str(folder)


def test_a_policy_for_the_mcp_mode_refuses_the_calls_it_withholds_per_project(tree, tmp_path):  # noqa: F811
    first = str(tree["project"])
    second = second_project(tmp_path, tree)
    set_channels(first, {"mcp": ["read", "talk"]})
    set_channels(second, {"mcp": ["read", "request", "release"]})
    projects = [{"id": mcp.project_id(p), "name": n, "path": p} for n, p in (("first", first), ("second", second))]
    server = mcp.Server(ops, projects, log=lambda line: None, grace=WAIT)
    ids = [p["id"] for p in projects]
    assert [t["name"] for t in server.tools()] == [t["name"] for t in mcp.Server(ops, projects, log=lambda line: None).tools()]
    assert "release" in [t["name"] for t in server.tools()], "tools/list is the ceiling's list; the per-call check enforces"

    def text(name, project, **given):
        out = mcp.call_tool(server, name, {"project": project, **given})
        return out["isError"], out["content"][0]["text"]

    assert text("release", ids[0], pending_id=1) == (True, sentence("release", "mcp"))
    assert text("request", ids[0], text="x") == (True, sentence("request", "mcp"))
    assert text("route", ids[0], request_id=1) == (True, sentence("route", "mcp"))
    assert text("answer", ids[0], pending_id=1, text="x") == (True, sentence("answer", "mcp"))
    assert text("status", ids[0])[0] is False
    assert text("request", ids[1], text="a request")[0] is False
    assert text("answer", ids[1], pending_id=1, text="x") == (True, sentence("answer", "mcp"))
    refused, said = text("release", ids[1], pending_id=99999)
    assert said != sentence("release", "mcp")                              # allowed there: the layer's own sentence about the pending id
    set_channels(first, None)                                              # no entry: the ceiling again
    refused, said = text("release", ids[0], pending_id=99999)
    assert said != sentence("release", "mcp")


# --- the queue ---------------------------------------------------------------------------------------------------------------


def queued_line(path, text="Please plan the launch."):
    ctx = ops_core.context(path)
    with ops_core._route_lock(ctx["cfg"]):
        out = ops.say(path, text, channel="page")
    assert out["queued"] is True
    return ctx, out["message_id"]


def test_a_queued_line_is_checked_again_at_the_drain_under_the_page_policy_and_gets_a_stored_reply(tree):  # noqa: F811
    path = str(tree["project"])
    set_channels(path, {"page": ["read", "talk"]})
    ctx, line = queued_line(path)
    assert [(e["kind"], e["id"], e.get("group")) for e in ops_say._queue_read(ctx, peek=True)] == [("line", line, "talk")]
    set_channels(path, {"page": ["read"]})                                  # talk is turned off and accepted while it waits
    out = ops.route_queued(path)
    assert out["dropped"] == {"kind": "line", "id": line} and out["queued"] == 0
    reply = [m for m in ops.conversation(path)["messages"] if m["role"] == "assistant"][-1]["text"]
    assert reply == "A queued line was not answered: " + sentence("say") and ops_say._queue_read(ops_core.context(path), peek=True) == []


def test_an_entry_queued_before_groups_were_stored_is_checked_as_a_line_or_a_route_under_the_page(tree):  # noqa: F811
    path = str(tree["project"])
    set_channels(path, {"page": ["read", "talk"]})
    ctx, line = queued_line(path)
    entries = [{k: v for k, v in e.items() if k != "group"} for e in ops_say._queue_read(ctx)]
    ops_say._queue_write(ctx, entries)                                      # as an older version left it: no group
    assert ops_say._drain_refusal(ctx, entries[0]) is None
    set_channels(path, {"page": ["read", "request"]})
    ctx = ops_core.context(path)
    assert ops_say._drain_refusal(ctx, entries[0]) == sentence("say") and ops_say._drain_refusal(ctx, {"kind": "route", "id": 1}) is None
    set_channels(path, {"page": ["read", "talk"]})
    assert ops_say._drain_refusal(ops_core.context(path), {"kind": "route", "id": 1}) == sentence("route")
    assert ops_say._drain_refusal(ops_core.context(path), {"kind": "route", "id": 1, "group": "nonsense"}) == sentence("route")
    request = ops.request(path, "A request to route.")["request"]
    ctx = ops_core.context(path)
    ops_say._queue_write(ctx, [])                                           # the line above is dropped by hand: the drain below takes the route
    ops_say.queue_route(ctx, request)
    assert [e.get("group") for e in ops_say._queue_read(ctx)] == ["request"]
    ops_say._retag(ctx, "route", request, "talk")
    assert [e.get("group") for e in ops_say._queue_read(ctx)] == ["talk"]
    ops_say._queue_write(ctx, [{k: v for k, v in e.items() if k != "group"} for e in ops_say._queue_read(ctx)])
    out = ops.route_queued(path)                                            # page has talk but not request: refused, and the request is told
    assert out["dropped"] == {"kind": "route", "id": request}
    note = [m for m in ops.conversation(path)["messages"] if m["task_id"] == request][-1]["text"]
    assert sentence("route") in note


def test_a_line_that_routes_a_request_already_queued_by_the_page_keeps_the_group_request(tree, monkeypatch):  # noqa: F811
    path = str(tree["project"])
    set_channels(path, {"page": ["read", "talk", "request"]})
    request = ops.request(path, "A request to route.")["request"]
    ctx = ops_core.context(path)
    answer_to = ctx["store"].acceptance_open(ctx["conn"], task_id=request, what="deliveries", title="Q", body="b", payload={})["pending_id"]
    monkeypatch.setattr(ops_say, "_planning_may_start", lambda c: (True, ""))
    monkeypatch.setattr(ops_say, "_ops", lambda: types.SimpleNamespace(answer=lambda *a, **k: None, route=ops.route))
    with ops_core._route_lock(ctx["cfg"]):
        ops_say.queue_route(ctx, request)                                   # the page asked for the route: group request
        ops_say._say_route(path, ctx, "same request", 10**6, "page", answer_to=answer_to)   # a line routes the same request
    assert [e["group"] for e in ops_say._queue_read(ctx)] == ["request"]
    set_channels(path, {"page": ["read", "talk"]})
    ctx = ops_core.context(path)
    assert ops_say._drain_refusal(ctx, ops_say._queue_read(ctx)[0]) == sentence("route")


# --- GET /projects ------------------------------------------------------------------------------------------------------------


def test_get_projects_carries_the_pages_permissions_per_project_and_null_when_not_accepted(tree, tmp_path):  # noqa: F811
    first = str(tree["project"])
    second = second_project(tmp_path, tree)
    unaccepted = second_project(tmp_path, tree, "third")
    with open(project_config.path(unaccepted), "ab") as f:
        f.write(b" ")
    set_channels(first, {"page": ["read", "approve-plans", "go-ahead"]})
    set_channels(second, None)
    projects = [{"id": service.project_id(p), "name": os.path.basename(p), "path": p} for p in (first, second, unaccepted)]
    world = types.SimpleNamespace(svc=service.Service(ops, projects, TOKEN, PORT, None, log=lambda line: None), projects=projects)
    status, _, body = call(world, "GET", "/api/v1/projects")
    assert status == 200 and set(body) == {"projects", "messaging"}
    [one, two, three] = body["projects"]
    assert one["permissions"] == {"channel": "page", "allowed": [
        "status", "task", "flows", "flow-check", "config", "progress", "pending", "approve:plan", "approve:go-ahead", "go-ahead", "cancel", "stop-task", "set-mode:down",
        "agents", "conversation", "skills", "costs", "connections", "artifacts", "artifact", "artifact-raw", "version", "commands", "items", "instructions", "routines", "routine-pause", "routine-cancel"]}
    assert set(one["permissions"]) == {"channel", "allowed"}
    assert two["permissions"] == {"channel": "page", "allowed": operations.permissions("page", None)}
    assert {"approve:plan", "approve:acceptance", "approve:effect", "approve:go-ahead", "set-mode:down", "set-mode:up"} <= set(two["permissions"]["allowed"])
    assert three["permissions"] is None and three["config"]["accepted"] is False
    shown = mcp.Server(ops, projects, log=lambda line: None).projects_list()["projects"]
    assert all("permissions" not in entry for entry in shown), "the MCP projects tool keeps the kit's shape"
    # the page's commands, through the real operations layer
    set_channels(first, {"page": ["read", "approve-plans"]})
    got = [c["command"] for c in call(world, "GET", f"/api/v1/projects/{projects[0]['id']}/commands")[2]["commands"]]
    assert got == ["/help", "/status", "/progress", "/pending", "/approve", "/cancel", "/stop-task"]


# --- messaging keeps its behaviour with the new names ------------------------------------------------------------------------


def test_messaging_keeps_its_closed_default_and_the_split_groups_turn_reject_cancel_and_retry_on_separately():
    for name in ("reject", "cancel", "stop-task", "retry", "release", "approve"):
        assert not operations.permitted(name, "messaging", None)
    assert not operations.permitted("stop-task", "messaging", None) and operations.permitted("stop-task", "messaging", {"messaging": ["brakes"]})   # R18: a grant, not a default
    assert operations.permitted("reject", "messaging", {"messaging": ["reject-cancel"]}) and operations.permitted("cancel", "messaging", {"messaging": ["reject-cancel"]})
    assert not operations.permitted("retry", "messaging", {"messaging": ["reject-cancel"]})
    assert operations.permitted("retry", "messaging", {"messaging": ["retry"]}) and not operations.permitted("cancel", "messaging", {"messaging": ["retry"]})
