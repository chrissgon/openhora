"""The channel `messaging` against the real operations layer: the rows of the table that list it, the channel policy
(decision M-8: groups, the ceiling, the closed default, operations.permitted), the approve rule (a plan only with its hash,
an acceptance allowed, an effect never) and the typed commands of `say`. Offline, no model.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_policy.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import standin_tree as st
from test_effects import gate_project, provider_calls, tree  # noqa: F401  (the effect fixture of test_effects.py)

ops = st.load("ops")
ops_core = st.load("ops_core")
operations = st.load("operations")
project_config = st.load("project_config")

ON_MESSAGING = ["status", "progress", "pending", "task", "agents", "costs", "skills", "artifacts", "artifact", "say", "answer",
                "release", "approve", "reject", "retry", "cancel", "stop-task", "ask", "sources", "instructions", "routines", "routine-create", "routine-change", "routine-pause",
                "routine-cancel", "attachments", "attachment-hold", "attachment-add", "attachment-discard", "remind", "reminders", "reminder-forget",
                "event-create", "event-change", "event-cancel",
                "file-create", "file-replace", "file-save"]
ALL_GROUPS = list(operations.GROUPS)
NOT_ENABLED = "is not enabled for this channel; the project's configuration (channels.messaging) turns it on"


def set_policy(path, groups):
    """Write channels.messaging into the project's runtime.json and accept the new hash, as the person does."""
    file = Path(path) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(file.read_text())
    if groups is None:
        raw.pop("channels", None)
    else:
        raw["channels"] = {"messaging": groups}
    file.write_text(json.dumps(raw))
    ops.accept_config(path, project_config.load(path)["sha256"], widen=ops.config(path)["widening_sha256"])


def decisions(tree):  # noqa: F811
    """(path, plan id, plan hash, acceptance id, effect) of a project with all three kinds open."""
    case = gate_project(tree)
    path, effect = case["path"], case["item"]
    ctx = ops_core.context(path)
    store, conn = ctx["store"], ctx["conn"]
    tasks = [{"key": "market", "skill": "demo-asks", "title": "Market", "text": "Do it.", "depends_on": [], "milestone": False}]
    digest = ops.plan.plan_hash(tasks)
    plan_id = store.plan_open(conn, ops.request(path, "Plan this.")["request"], title="Plan", body="The plan.",
                              payload={"tasks": tasks, "plan_sha256": digest, "flow": "demo"})["pending_id"]
    made = ops.request(path, "A request that waits on an acceptance.", "demo")
    accept_id = store.acceptance_open(conn, task_id=made["request"], what="deliveries", title="Accept", body="Accept them.",
                                      payload={})["pending_id"]
    return path, plan_id, digest, accept_id, effect


# --- the table -------------------------------------------------------------------------------------------------------


def test_messaging_is_listed_on_exactly_the_rows_of_the_specification():
    listed = [r["name"] for r in operations.OPERATIONS if "messaging" in r["channels"]]
    assert sorted(listed) == sorted(ON_MESSAGING)
    for name in ("request", "route", "route-queued", "set-mode", "accept-config", "go-ahead", "config", "dispatch", "deps",
                 "run-next", "approve-policy", "revoke-policy", "standing", "execute-under-policy", "contained-run", "sync",
                 "hand-over", "handler", "pin", "proof", "verdict", "stop-runs", "service-check", "flows", "connections",
                 "conversation", "artifact-raw", "version", "commands"):
        assert "messaging" not in operations.by_name(name)["channels"], name
    assert "messaging" not in ops.EFFECT_CHANNELS and "messaging" not in ops.ops_say.QUEUING_CHANNELS


def test_permitted_follows_the_groups_the_ceiling_and_the_closed_default():
    rows = {r["name"]: r for r in operations.OPERATIONS}
    for group, spec in operations.GROUPS.items():
        if group in operations.PAGE_ONLY_GROUPS:  # an effect is approved on no messaging channel, by any group (asserted below)
            continue
        for name in rows:
            kinds = [None] if spec["kind"] is None else [spec["kind"]]
            for kind in kinds:
                expected = name in spec["operations"] and "messaging" in rows[name]["channels"]
                assert operations.permitted(name, "messaging", {"messaging": [group]}, kind) is expected, (group, name)
    assert operations.GROUPS["approve-plans"]["kind"] == "plan" and operations.GROUPS["approve-acceptances"]["kind"] == "acceptance"
    plans, acceptances = {"messaging": ["approve-plans"]}, {"messaging": ["approve-acceptances"]}
    assert operations.permitted("approve", "messaging", plans, "plan") and not operations.permitted("approve", "messaging", plans, "acceptance")
    assert operations.permitted("approve", "messaging", acceptances, "acceptance") and not operations.permitted("approve", "messaging", acceptances, "plan")
    assert not operations.permitted("approve", "messaging", plans, "effect") and not operations.permitted("approve", "messaging", {"messaging": ALL_GROUPS}, "effect")
    # the ceiling: a row that does not list the channel is refused whatever the policy says
    assert not operations.permitted("set-mode", "messaging", {"messaging": ALL_GROUPS}) and not operations.permitted("nothing", "messaging", None)
    # the closed default: read, talk, answer
    for name in rows:
        expected = name in ON_MESSAGING and name not in ("release", "approve", "reject", "retry", "cancel", "stop-task", "ask", "sources", "routine-create", "routine-change", "attachments", "attachment-hold", "attachment-add", "attachment-discard", "remind", "reminders", "reminder-forget", "event-create", "event-change", "event-cancel", "file-create", "file-replace", "file-save")  # the calendar writes are in no default policy (W1); reminders are in no default policy (RM-1); an answer from the full text of the sources is turned on by a group, never by default (AQ-1); files from a messaging app are taken only on the group add-sources (ATT-1); a routine is made and changed only on a grant (P6b); # the catalog holds the person's data: its group is turned on, never by default
        assert operations.permitted(name, "messaging", None) is expected, name
        assert operations.permitted(name, "messaging", {}, "plan") is expected, name
    assert operations.permitted("approve", "messaging", {"messaging": []}) is False
    # the terminal is never narrowed; a channel with no entry keeps its ceiling
    for name, row in rows.items():
        for policy in (None, {"messaging": []}, {"terminal": [], "messaging": ["read"]}):
            assert operations.permitted(name, "terminal", policy) is ("terminal" in row["channels"]), name
        assert operations.permitted(name, "page", {"messaging": []}) is ("page" in row["channels"]), name
        assert operations.permitted(name, "mcp", None) is ("mcp" in row["channels"]), name


# --- approve from messaging -------------------------------------------------------------------------------------------


def test_a_plan_with_its_hash_and_an_acceptance_are_approved_and_the_rest_is_refused(tree):  # noqa: F811
    path, plan_id, digest, accept_id, effect = decisions(tree)
    set_policy(path, ["read", "approve-plans", "approve-acceptances"])
    for hash_ in (None, "0" * 64):
        with pytest.raises(ops.OpsError) as refused:
            ops.approve(path, plan_id, hash_, channel="messaging", sender="telegram:4242")
        assert ("only with its hash" in str(refused.value)) if hash_ is None else ("nothing was approved" in str(refused.value))
    assert ops.pending(path, plan_id)["status"] == "open"
    ops.approve(path, plan_id, digest, channel="messaging", sender="telegram:4242")
    assert ops.pending(path, plan_id)["status"] == "resolved"
    ops.approve(path, accept_id, channel="messaging", sender="telegram:4242")
    assert ops.pending(path, accept_id)["status"] == "resolved"
    with pytest.raises(ops.OpsError) as refused:
        ops.approve(path, effect["id"], effect["payload_sha256"], channel="messaging", sender="telegram:4242")
    assert "an effect is approved in the terminal, with its hash" in str(refused.value)
    assert ops.pending(path, effect["id"])["status"] == "open" and provider_calls(tree) == []


def test_a_policy_with_approve_plans_does_not_approve_an_acceptance_and_the_default_approves_nothing(tree):  # noqa: F811
    path, plan_id, digest, accept_id, effect = decisions(tree)
    set_policy(path, ["approve-plans"])
    with pytest.raises(ops.OpsError) as refused:
        ops.approve(path, accept_id, channel="messaging", sender="telegram:4242")
    assert NOT_ENABLED in str(refused.value) and ops.pending(path, accept_id)["status"] == "open"
    set_policy(path, None)  # no entry: the closed default
    with pytest.raises(ops.OpsError) as refused:
        ops.approve(path, plan_id, digest, channel="messaging", sender="telegram:4242")
    assert NOT_ENABLED in str(refused.value) and ops.pending(path, plan_id)["status"] == "open"
    # the terminal, the page and the conversation are not narrowed by it
    ops.approve(path, plan_id, digest, channel="terminal")
    assert ops.pending(path, plan_id)["status"] == "resolved"
    ops.approve(path, accept_id, channel="page")
    assert ops.pending(path, accept_id)["status"] == "resolved"


# --- typed into say ---------------------------------------------------------------------------------------------------


def test_typed_commands_follow_the_policy_and_the_default_allows_reads_talk_and_answer_only(tree):  # noqa: F811
    path, plan_id, digest, accept_id, effect = decisions(tree)
    set_policy(path, None)
    before = (ops.status(path), ops.pending(path))
    for command in (f"/approve {plan_id} {digest}", f"/approve {accept_id}", f"/approve {effect['id']} {effect['payload_sha256']}",
                    f"/reject {plan_id}", "/retry 2", "/cancel 1", "/stop-task 1", "/release 1"):
        reply = ops.say(path, command, channel="messaging", sender="telegram:4242")["reply"]
        assert reply == f"error: /{command[1:].split()[0]} {NOT_ENABLED}", command
    assert (ops.status(path), ops.pending(path)) == before and provider_calls(tree) == []
    assert ops.say(path, "/pending", channel="messaging", sender="telegram:4242")["reply"].lstrip().startswith("{")
    assert ops.say(path, "/status", channel="messaging", sender="telegram:4242")["reply"]
    answered = ops.say(path, "/answer 99999 text", channel="messaging", sender="telegram:4242")["reply"]  # allowed, and the layer's own sentence
    assert NOT_ENABLED not in answered


def test_a_typed_approve_with_the_policy_on_needs_the_hash_and_a_command_the_table_does_not_give_is_refused(tree):  # noqa: F811
    path, plan_id, digest, accept_id, effect = decisions(tree)
    set_policy(path, ["read", "talk", "approve-plans"])
    reply = ops.say(path, f"/approve {plan_id}", channel="messaging", sender="telegram:4242")["reply"]
    assert "as the whole line" in reply and ops.pending(path, plan_id)["status"] == "open"
    reply = ops.say(path, f"/approve {effect['id']} {effect['payload_sha256']}", channel="messaging", sender="telegram:4242")["reply"]
    assert "as the whole line" in reply and provider_calls(tree) == []
    reply = ops.say(path, f"/approve {accept_id}", channel="messaging", sender="telegram:4242")["reply"]
    assert "as the whole line" in reply and ops.pending(path, accept_id)["status"] == "open"
    sha = ops.config(path)["sha256"]
    reply = ops.say(path, "/set-mode autonomous", channel="messaging", sender="telegram:4242")["reply"]
    assert reply.startswith(operations.HELP_HEAD) and ops.config(path)["sha256"] == sha  # no such command here: the help
    reply = ops.say(path, f"/approve {plan_id} {digest}", channel="messaging", sender="telegram:4242")["reply"]
    assert "as the whole line" in reply and ops.pending(path, plan_id)["status"] == "open"


def test_the_terminal_is_unaffected_by_any_policy(tree):  # noqa: F811
    path, plan_id, digest, accept_id, effect = decisions(tree)
    set_policy(path, [])
    reply = ops.say(path, f"/approve {accept_id}", channel="terminal")["reply"]
    assert NOT_ENABLED not in reply and ops.pending(path, accept_id)["status"] == "resolved"
    ops.approve(path, plan_id, digest, channel="terminal")
    assert ops.pending(path, plan_id)["status"] == "resolved"


# --- the configuration ------------------------------------------------------------------------------------------------


def test_channels_are_checked_against_the_groups_and_the_ceiling(monkeypatch):
    assert project_config._channels(None) == {}
    assert project_config._channels({"messaging": ["read", "read", "talk"]}) == {"messaging": ["read", "talk"]}
    for bad in ({"messaging": ["everything"]}, {"messaging": "read"}, {"messaging": [1]}, {"terminal": ["read"]},
                {"chat": ["read"]}, {"page": ["talk"]}, {"mcp": ["answer"]}, {"messaging": ["approve-effects"]}, {"page": ["go-ahead"]}, ["read"]):
        with pytest.raises(project_config.ConfigError):
            project_config._channels(bad)
    with pytest.raises(project_config.ConfigError) as unknown:
        project_config._channels({"messaging": ["everything"]})
    assert "read" in str(unknown.value) and "reject-cancel" in str(unknown.value)
    row = operations.by_name("release")  # a group that goes above the channel's ceiling
    monkeypatch.setitem(row, "channels", tuple(c for c in row["channels"] if c != "messaging"))
    with pytest.raises(project_config.ConfigError) as above:
        project_config._channels({"messaging": ["release"]})
    assert "ceiling" in str(above.value) and "never widens" in str(above.value)


def test_the_messaging_section_is_read_and_each_wrong_value_is_a_sentence():
    good = {"senders": {"telegram": ["4242", "4243"]}, "notices": "count", "page_url": "https://page.example/open"}
    assert project_config._messaging(good) == {**good, "sender_profiles": {}}      # POL-2: the entries that name a profile, none here
    assert project_config._messaging(None) == {"senders": {}, "sender_profiles": {}, "notices": "text", "page_url": None}
    assert project_config._messaging({"senders": {"telegram": ["4242"]}}) == {
        "senders": {"telegram": ["4242"]}, "sender_profiles": {}, "notices": "text", "page_url": None}
    for bad in ({"notices": "loud"}, {"senders": {"telegram": "4242"}}, {"senders": {"telegram": [4242]}},
                {"senders": {"telegram": [""]}}, {"senders": {"Telegram": ["1"]}}, {"senders": []},
                {"page_url": "ftp://page.example"}, {"page_url": "javascript:alert(1)"}, {"page_url": 5}, {"colour": "red"}, []):
        with pytest.raises(project_config.ConfigError):
            project_config._messaging(bad)


def test_a_valid_section_is_loaded_with_the_project_and_reaches_the_config_operation(tree):  # noqa: F811
    path = str(tree["project"])
    file = Path(path) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(file.read_text())
    raw["messaging"] = {"senders": {"telegram": ["4242"]}, "notices": "count"}
    raw["channels"] = {"messaging": ["read", "talk"]}
    file.write_text(json.dumps(raw))
    shown = ops.config(path)
    assert shown["accepted"] is False  # a change takes effect only after accept-config
    assert shown["messaging"]["senders"] == {"telegram": ["4242"]} and shown["channels"] == {"messaging": ["read", "talk"]}


def test_a_typed_approve_is_refused_outright_from_messaging_even_with_the_policy_on(tree):  # noqa: F811
    path, plan_id, digest, accept_id, effect = decisions(tree)
    set_policy(path, ["read", "talk", "approve-plans", "approve-acceptances"])
    for line in (f"/approve {accept_id}", f"/approve {plan_id} {digest}"):
        assert ops.say(path, line, channel="messaging", sender="telegram:4242")["reply"] == "error: use the card's button, or /approve <id> as the whole line"
    assert ops.pending(path, accept_id)["status"] == "open" and ops.pending(path, plan_id)["status"] == "open"
    ops.approve(path, accept_id, channel="messaging", sender="telegram:4242")  # the bridge's own call, after its binding, still works
    assert ops.pending(path, accept_id)["status"] == "resolved"
