"""Grants of the channel policy (package POL-1): a channel restriction is a policy, the default is today's rule, and the person may widen
it one grant at a time. What these tests hold:

  * the DEFAULT is unchanged: for every row, channel, kind and policy that the tests of before the grants used, `permitted` answers as it
    did (a frozen copy of the earlier rule, written here, not read from the new code);
  * a grant is reached only from the project's own entry, per effect word; the umbrella `approve-effects` stays the page's; the MCP mode
    is granted plans, acceptances, reject-cancel and retry and never an effect, a networked plan or consent;
  * the configuration refuses what a channel may not take, each with its sentence, and warns where a grant does nothing;
  * accept-config accepts a file that adds a grant only with the sha256 of the widening list that `config` shows;
  * a granted write is approved on messaging only after that acceptance, executes once, and a `create` effect stays refused (per word);
  * an effect the whole of which cannot be on a card (an attachment, an image) is never approvable from one, the group granted or not;
  * the networked-plan rule (limit L36) is a grant of a messaging app and never of the conversation or the MCP mode.

The cards and the bridge are in test_channel_grants_cards.py, the e-mail and the post in test_channel_grants_send.py and
test_channel_grants_publish.py. Offline, no model, fictional names throughout.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_channel_grants.py
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import pytest

import standin_tree as st
from test_effects import gate_project, provider_calls, tree  # noqa: F401  (the effect fixture of test_effects.py)
from test_messaging_policy import decisions
from test_write_back import PATH as WRITE_PATH, SEED, opened as write_opened, writes, world  # noqa: F401  (the write-back world of test_write_back.py)

cards = st.load("messaging_cards")
effects = st.load("effects")
ops = st.load("ops")
ops_core = st.load("ops_core")
ops_waits = st.load("ops_waits")
ops_grants = st.load("ops_grants")
operations = st.load("operations")
policy_grants = st.load("policy_grants")
project_config = st.load("project_config")
mcp = st.load("mcp")

WAIT = 30
CHANNELS = ("terminal", "chat", "page", "mcp", "messaging", "bogus")
KINDS = (None, "plan", "acceptance", "effect")
BRAKES_BEFORE = ("cancel", "stop-task", "set-mode", "routine-pause", "routine-cancel")
NEW_GROUPS = ("approve-effect-create", "approve-effect-write", "approve-effect-send", "approve-effect-publish", "approve-networked-plans")
# The rule as it was before the grants, written out here (the default has to answer exactly so): a row lists the channel, the terminal is never
# narrowed, an effect only from the terminal and the page, a channel with no entry keeps its default or its ceiling, a group covers its kind.
OLD_GROUPS = {name: spec for name, spec in operations.GROUPS.items() if name not in NEW_GROUPS}
OLD_DEFAULT = {"messaging": ("read", "talk", "answer", "routine-brakes")}


def before_allows(op, channel, policy, kind):
    rows = [r for r in operations.OPERATIONS if r["name"] == op]
    if not rows or channel not in rows[0]["channels"]:
        return False
    if channel == "terminal":
        return True
    if op == "approve" and kind == "effect" and channel not in ("terminal", "page"):
        return False
    given = (policy or {}).get(channel)
    groups = tuple(given) if given is not None else OLD_DEFAULT.get(channel)
    if groups is None:
        return True
    return any(g in OLD_GROUPS and op in OLD_GROUPS[g]["operations"] and (OLD_GROUPS[g]["kind"] is None or kind is None or OLD_GROUPS[g]["kind"] == kind)
               for g in groups)


def before_permitted(op, channel, policy, kind):
    if channel == "page" and op in BRAKES_BEFORE and before_allows(op, channel, None, None):
        return True
    return before_allows(op, channel, policy, kind)


def accept(path, channels, **extra):
    """Write `channels` into the project's runtime.json and accept it as the person does: read `config`, and type the hash of the widening
    list it shows (when it shows one)."""
    file = Path(path) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(file.read_text())
    raw.pop("channels", None)
    if channels is not None:
        raw["channels"] = channels
    file.write_text(json.dumps(raw))
    shown = ops.config(path)
    return ops.accept_config(path, shown["sha256"], widen=shown["widening_sha256"], **extra)


# --- the default is unchanged ------------------------------------------------------------------------------------------------


def test_the_default_policy_answers_as_before_for_every_row_channel_kind_and_policy():
    policies = [None, {}, {"messaging": []}, {"messaging": ["read"]}, {"page": ["read", "approve-plans"]}]
    for group in OLD_GROUPS:
        for channel in ("page", "mcp", "messaging"):
            policies.append({channel: [group]})
            policies.append({channel: ["read", group]})
        policies.append({"messaging": [group], "mcp": ["read", group], "page": ["read", group]})
    policies.append({channel: ["read", *OLD_GROUPS] for channel in ("page", "mcp", "messaging")})
    # a policy that lists a group of GRANTS["mcp"] on the MCP mode was no valid file before (the ceiling had no such operation): that is the one
    # widening there is, and it is tested apart; every other policy is the default's and answers as before
    grants_on_mcp = [p for p in policies if set((p or {}).get("mcp") or ()) & set(operations.GRANTS["mcp"])]
    policies = [p for p in policies if p not in grants_on_mcp]
    assert grants_on_mcp and policies
    checked = 0
    for row in operations.OPERATIONS:
        for channel in CHANNELS:
            for kind in KINDS:
                for policy in policies:
                    assert operations.permitted(row["name"], channel, policy, kind) is before_permitted(row["name"], channel, policy, kind), \
                        (row["name"], channel, kind, policy)
                    checked += 1
    assert checked > 5000
    for policy in grants_on_mcp:      # and on the other channels they answer as before even so
        for row in operations.OPERATIONS:
            for channel in ("terminal", "chat", "page", "messaging", "bogus"):
                for kind in KINDS:
                    assert operations.permitted(row["name"], channel, policy, kind) is before_permitted(row["name"], channel, policy, kind), (row["name"], channel, kind)
    # the sentences and the lists the earlier tests read
    assert operations.refusal("approve", "messaging", None, "plan") == operations.not_enabled("approve", "messaging")
    assert operations.refusal("approve", "messaging", {"messaging": ["read", "approve-plans"]}, "effect") == operations.not_enabled("approve", "messaging")
    assert operations.EFFECT_CHANNELS == ("terminal", "page") and operations.PAGE_ONLY_GROUPS == ("approve-effects",)
    assert operations.DEFAULT_POLICY == OLD_DEFAULT and operations.BRAKES == BRAKES_BEFORE
    assert operations.NETWORKED_PLAN_CHANNELS == ("terminal", "page") and operations.INSTRUCTIONS_CHANNELS == ("terminal", "page")


def test_a_default_never_holds_a_grant_and_a_grant_is_found_only_in_the_projects_own_entry():
    held = {g for names in operations.DEFAULT_POLICY.values() for g in names}
    assert not held & {g for names in operations.GRANTS.values() for g in names}
    assert operations.grants(None) == [] and operations.grants({}) == []
    own = {"messaging": ["read", "approve-effect-write"], "mcp": ["read", "retry"], "page": ["read", "approve-effect-write"]}
    # the page's per-word group is a narrowing there, not a grant: only GRANTS counts
    assert operations.grants(own) == [("messaging", "approve-effect-write"), ("mcp", "retry")]
    assert operations.effective_groups("messaging", None) == operations.DEFAULT_POLICY["messaging"] == operations.policy_groups("messaging", None)
    assert operations.effective_groups("messaging", own) == ("read", "approve-effect-write")
    assert operations.effective_groups("page", None) is None and operations.effective_groups("messaging", own, "any-sender") == ("read", "approve-effect-write")


def test_the_invariants_of_the_grants():
    assert set(operations.GRANTS) == {"messaging", "mcp"} and not set(operations.NEVER_GRANTED) & set(operations.GRANTS)
    assert set(operations.NEVER_GRANTED) == {"chat", "terminal"}
    for channel, names in operations.GRANTS.items():
        for name in names:
            assert name in operations.GROUPS, name
            assert f"{channel}:{name}" in operations.GRANT_TEXT, name
    assert set(operations.GRANT_TEXT) == {f"{c}:{g}" for c, names in operations.GRANTS.items() for g in names}
    # the MCP mode (a model client) is granted no effect, no networked plan, no consent, no mode, no routine approval
    for name in operations.GRANTS["mcp"]:
        spec = operations.GROUPS[name]
        assert not operations.is_effect_kind(spec["kind"]) and spec["kind"] != "plan:networked", name
        assert not {"give-consent", "set-mode", "set-model", "routine-approve", "routine-resume", "accept-config", "approve-policy",
                    "execute-under-policy", "instructions-set", "instructions-add"} & set(spec["operations"]), name
    # nothing a grant reaches is the terminal's alone: accept-config, the standing approvals and the policy's execution list no grant
    for grant_names in operations.GRANTS.values():
        for name in grant_names:
            assert not {"accept-config", "approve-policy", "revoke-policy", "execute-under-policy"} & set(operations.GROUPS[name]["operations"])
    assert operations.grant_only_rows("mcp") == ("approve", "reject", "retry", "cancel") and operations.grant_only_rows("messaging") == ()


def test_every_effect_word_an_approval_path_opens_has_its_group_and_the_modules_name_it():
    opened = {}
    for word in effects.KINDS:
        module = effects.module_for(word)
        if getattr(module, "GATE", False) is True or getattr(module, "STEP", False) is True:
            opened[word] = module
    assert set(opened) == {"create", "write", "send", "publish"} == set(operations.EFFECT_APPROVAL_WORDS), "a new kind with an approval path adds its word and its group"
    assert "push" not in opened and not [g for g in operations.GROUPS if g == "approve-effect-push"], "a kind that never reaches approve has no group"
    for word, module in opened.items():
        group = operations.GROUPS[f"approve-effect-{word}"]
        assert group == {"operations": ("approve",), "kind": f"effect:{word}"} and f"approve-effect-{word}" in operations.GRANTS["messaging"]
        if hasattr(module, "APPROVAL_GROUP"):
            assert module.APPROVAL_GROUP == f"approve-effect-{word}"
    assert {g for g in operations.GROUPS if g.startswith("approve-effect-")} == {f"approve-effect-{w}" for w in opened}
    assert hasattr(effects.module_for("send"), "on_cards") and hasattr(effects.module_for("publish"), "on_cards")


# --- who is asked, by word --------------------------------------------------------------------------------------------------------


def test_a_word_is_granted_to_messaging_one_at_a_time_and_the_umbrella_never_counts_there():
    write = {"messaging": ["read", "approve-effect-write"]}
    for word in operations.EFFECT_APPROVAL_WORDS:
        assert operations.permitted("approve", "messaging", write, f"effect:{word}") is (word == "write"), word
    assert operations.permitted("approve", "messaging", write, "effect:write") and not operations.permitted("approve", "messaging", write, "effect")
    assert not operations.permitted("approve", "messaging", write, "plan") and not operations.permitted("approve", "messaging", write, "acceptance")
    # the umbrella and the other groups of messaging cover no effect there; the default holds none
    every = {"messaging": ["read", "approve-effects", "approve-plans", "approve-acceptances", "go-ahead"]}
    assert not any(operations.permitted("approve", "messaging", every, k) for k in ("effect", "effect:write", "effect:create", "effect:send", "effect:publish"))
    assert not any(operations.permitted("approve", "messaging", None, f"effect:{w}") for w in operations.EFFECT_APPROVAL_WORDS)
    # the other channels never: the conversation and the MCP mode have no grant of an effect, whatever the entry lists
    for channel in ("chat", "mcp"):
        listing = {channel: ["read", *operations.GROUPS]}
        assert not any(operations.permitted("approve", channel, listing, f"effect:{w}") for w in operations.EFFECT_APPROVAL_WORDS), channel
    # the terminal and the page keep approving every word, the page by the umbrella or by the word
    assert operations.permitted("approve", "terminal", {"terminal": []}, "effect:publish") and operations.permitted("approve", "page", None, "effect:send")
    assert operations.permitted("approve", "page", {"page": ["read", "approve-effects"]}, "effect:publish")
    assert operations.permitted("approve", "page", {"page": ["read", "approve-effect-send"]}, "effect:send")
    assert not operations.permitted("approve", "page", {"page": ["read", "approve-effect-send"]}, "effect:write")
    assert not operations.permitted("approve", "page", {"page": ["read", "approve-effect-send"]}, "effect"), "an effect with no word is covered by the umbrella alone"
    assert operations.permitted("approve", "page", {"page": ["read", "approve-effects"]}, "effect")


def test_the_pages_permissions_name_the_effect_words_it_may_approve():
    assert {"approve:effect", *(f"approve:effect:{w}" for w in operations.EFFECT_APPROVAL_WORDS)} <= set(operations.permissions("page", None))
    only = operations.permissions("page", {"page": ["read", "approve-effect-write"]})
    assert "approve:effect:write" in only and "approve:effect" in only and "approve:effect:create" not in only and "approve:plan" not in only
    assert "approve:effect" not in operations.permissions("page", {"page": ["read", "approve-plans"]})
    assert "approve:effect" in operations.permissions("page", {"page": ["read", "approve-effects"]})


def test_the_mcp_mode_is_granted_plans_acceptances_reject_cancel_and_retry_and_nothing_else():
    entry = {"mcp": ["read", "approve-plans", "approve-acceptances", "reject-cancel", "retry"]}
    for name, kind in (("approve", "plan"), ("approve", "acceptance"), ("reject", None), ("cancel", None), ("retry", None)):
        assert operations.permitted(name, "mcp", entry, kind) and not operations.permitted(name, "mcp", None, kind), name
        assert not operations.permitted(name, "mcp", {"mcp": ["read"]}, kind)
    assert not operations.permitted("approve", "mcp", {"mcp": ["read", "retry"]}, "plan") and not operations.permitted("retry", "mcp", {"mcp": ["read", "approve-plans"]})
    for name in ("approve", "reject", "cancel", "retry"):
        assert "mcp" not in operations.by_name(name)["channels"], "the row stays: a grant reaches it, the ceiling does not"
    for name in ("stop-task", "go-ahead", "set-mode", "accept-config", "give-consent", "routine-approve", "dispatch"):
        assert not operations.permitted(name, "mcp", {"mcp": ["read", *operations.GRANTS["mcp"]]}), name
    assert not operations.permitted("approve", "mcp", {"mcp": ["read", *operations.GRANTS["mcp"]]}, "plan:networked")
    assert not operations.permitted("approve", "mcp", entry, "effect:write") and not operations.permitted("approve", "mcp", entry, "effect")


# --- the configuration -----------------------------------------------------------------------------------------------------------


def refused(channels):
    with pytest.raises(project_config.ConfigError) as caught:
        project_config._channels(channels)
    return str(caught.value)


def test_the_configuration_accepts_a_grant_of_the_channel_and_refuses_the_rest_with_its_sentence():
    ok = project_config._channels
    assert ok({"messaging": ["read", "approve-effect-create", "approve-effect-write", "approve-effect-send", "approve-effect-publish"]})
    assert ok({"messaging": ["read", "approve-plans", "approve-networked-plans"]}) == {"messaging": ["read", "approve-plans", "approve-networked-plans"]}
    assert ok({"mcp": ["read", "approve-plans", "approve-acceptances", "reject-cancel", "retry"]})
    assert ok({"page": ["read", "approve-effect-write", "approve-effect-send"]}), "a word on the page narrows it"
    # the umbrella is the page's alone, and the sentence says which groups a messaging app takes
    text = refused({"messaging": ["read", "approve-effects"]})
    assert "valid on the page only" in text and "approve-effect-write" in text and "approve-effect-publish" in text
    assert "valid on the page only" in refused({"mcp": ["read", "approve-effects"]})
    # a model client approves no effect and no networked plan
    for group in ("approve-effect-create", "approve-effect-write", "approve-effect-send", "approve-effect-publish", "approve-networked-plans"):
        text = refused({"mcp": ["read", "approve-plans", group]})
        assert "not valid on the MCP mode" in text and "model client" in text, group
    # a networked plan is the messaging app's grant only, and needs approve-plans beside it
    assert "valid on a messaging app only" in refused({"page": ["read", "approve-networked-plans", "approve-plans"]})
    assert "needs 'approve-plans'" in refused({"messaging": ["read", "approve-networked-plans"]})
    # a group the table gives the channel no operation of is still refused, and the sentence names the channel's grants
    text = refused({"messaging": ["go-ahead"]})
    assert "never widens it, except by a grant" in text and "approve-effect-write" in text
    assert "(the grants of mcp: approve-plans, approve-acceptances, reject-cancel, retry)" in refused({"mcp": ["read", "go-ahead"]})
    assert "must list the group 'read'" in refused({"mcp": ["approve-plans"]})


def test_the_renamed_group_refuses_its_old_name_with_the_known_groups_and_no_alias_keeps_it():
    assert "instructions" not in operations.GROUPS and "instructions-write" in operations.GROUPS
    text = refused({"page": ["read", "instructions"]})
    assert "'instructions' is not a group (known: " in text and "instructions-write" in text and "approve-effect-write" in text
    assert project_config._channels({"page": ["read", "instructions-write"]}) == {"page": ["read", "instructions-write"]}
    assert operations.permitted("instructions-set", "page", {"page": ["read", "instructions-write"]})
    assert not operations.permitted("instructions-set", "page", {"page": ["read", "instructions"]}), "the old name covers nothing"
    assert operations.permitted("instructions", "page", {"page": ["read"]}), "`instructions`, the read operation, is the group read"
    assert not operations.permitted("instructions-add", "messaging", {"messaging": ["instructions-write"]}), "the writers stay the terminal's and the page's by default"


def test_the_widening_list_its_hash_and_the_warning_for_notices_that_carry_no_text():
    cfg = {"channels": {"messaging": ["read", "approve-plans", "approve-networked-plans", "approve-effect-write"], "mcp": ["read", "retry"]},
           "messaging": {"notices": "text"}}
    shown = policy_grants.grants(cfg["channels"])
    assert [(g["channel"], g["group"]) for g in shown] == [("messaging", "approve-effect-write"), ("messaging", "approve-networked-plans"), ("mcp", "retry")]
    assert all(g["means"] == operations.GRANT_TEXT[f"{g['channel']}:{g['group']}"] for g in shown)
    held = [("messaging", "approve-effect-write")]
    wide = policy_grants.widening(held, cfg["channels"])
    assert [(w["channel"], w["group"]) for w in wide] == [("messaging", "approve-networked-plans"), ("mcp", "retry")]
    expect = hashlib.sha256(b"messaging:approve-networked-plans\nmcp:retry\n").hexdigest()      # what a person can compute by hand
    assert policy_grants.widening_sha256(wide) == expect and policy_grants.widening_sha256([]) is None
    assert policy_grants.parse(policy_grants.dump(cfg["channels"])) == [("messaging", "approve-effect-write"), ("messaging", "approve-networked-plans"), ("mcp", "retry")]
    assert policy_grants.parse(None) == policy_grants.parse("not json") == policy_grants.parse('["nonsense", 3]') == []
    assert policy_grants.warnings(cfg) == []
    count = {**cfg, "messaging": {"notices": "count"}}
    [warning] = policy_grants.warnings(count)
    assert "notices is 'count'" in warning and "approve-effect-write" in warning and "approves nothing" in warning
    assert policy_grants.warnings({"channels": {"messaging": ["read", "retry"]}, "messaging": {"notices": "count"}}) == [], "no effect grant, nothing to warn"


# --- accept-config with the widening hash, and a granted write -------------------------------------------------------------------


def test_a_granted_write_is_approved_on_messaging_after_accept_config_with_the_widening_hash_and_refused_before(world):  # noqa: F811
    path = world["path"]
    task, item = write_opened(world)
    assert ops.pending(path, item["id"])["effect_word"] == "write" and ops.pending(path, item["id"])["effect_on_cards"] is True
    file = Path(path) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(file.read_text())
    raw["channels"] = {"messaging": ["read", "approve-effect-write"]}
    file.write_text(json.dumps(raw))
    shown = ops.config(path)
    assert shown["accepted"] is False and shown["warnings"] == []
    assert [(g["channel"], g["group"]) for g in shown["grants"]] == [("messaging", "approve-effect-write")] == [(g["channel"], g["group"]) for g in shown["widening"]]
    digest = hashlib.sha256(b"messaging:approve-effect-write\n").hexdigest()
    assert shown["widening_sha256"] == digest and "documents platform" in shown["grants"][0]["means"]
    # before the acceptance the same approval is refused, and nothing is written
    with pytest.raises(ops.OpsError) as before:
        ops.approve(path, item["id"], item["payload_sha256"], channel="messaging")
    assert before.value.code == 3 and writes(world) == []
    # accept-config without the hash, with another, with the file's hash: nothing is accepted until the widening list's hash is typed
    for wrong in (None, "0" * 64, shown["sha256"]):
        with pytest.raises(ops.OpsError) as refused_:
            ops.accept_config(path, shown["sha256"], widen=wrong)
        assert "widens what a channel may do" in str(refused_.value) and "messaging:approve-effect-write" in str(refused_.value)
        assert f"--widen {digest}" in str(refused_.value) and ops.config(path)["accepted"] is False
    done = ops.accept_config(path, shown["sha256"], widen=digest)
    assert [(w["channel"], w["group"]) for w in done["widened"]] == [("messaging", "approve-effect-write")] and ops.config(path)["accepted"] is True
    assert ops.config(path)["widening"] == [] and ops.config(path)["widening_sha256"] is None and len(ops.config(path)["grants"]) == 1
    # the same approval now runs once, from a messaging app, with the hash of the exact content
    with pytest.raises(ops.OpsError) as no_hash:
        ops.approve(path, item["id"], None, channel="messaging")
    assert "with --sha256" in str(no_hash.value) and writes(world) == []
    with pytest.raises(ops.OpsError) as wrong_hash:
        ops.approve(path, item["id"], "f" * 64, channel="messaging")
    assert "nothing was approved" in str(wrong_hash.value) and writes(world) == []
    done = ops.approve(path, item["id"], item["payload_sha256"], channel="messaging")
    assert done["task_state"] == "done" and done["result"]["written"] is True and len(writes(world)) == 1
    assert world["platform"].text(world["page"]).startswith("# Plan for the harbour market")
    ctx = ops_core.context(path)
    row = ctx["store"].approval_get(ctx["conn"], done["approval_id"])
    assert row["status"] == "executed" and row["scope"] == "action" and row["payload_sha256"] == item["payload_sha256"]
    assert ctx["store"].pending_get(ctx["conn"], item["id"])["status"] == "resolved"
    assert "state" in done, "the record of the executed approval is the state file's generated row"
    with pytest.raises(ops.OpsError):
        ops.approve(path, item["id"], item["payload_sha256"], channel="messaging")
    assert len(writes(world)) == 1, "approved once, executed once"


def test_a_write_grant_does_not_approve_another_word_the_conversation_the_mcp_mode_or_a_typed_line(world):  # noqa: F811
    path = world["path"]
    task, item = write_opened(world)
    accept(path, {"messaging": ["read", "approve-effect-create", "approve-effect-send", "approve-effect-publish"]})     # every word but the one this effect has
    for channel in ("messaging", "chat", "mcp", None, "bogus"):
        with pytest.raises(ops.OpsError) as no:
            ops.approve(path, item["id"], item["payload_sha256"], channel=channel)
        assert "an effect is approved in the terminal, with its hash" in str(no.value) and "approve-effect-write" in str(no.value), channel
    accept(path, {"messaging": ["read", "approve-effect-write"], "page": ["read", "approve-effect-create"]})
    for channel in ("chat", "mcp", None):
        with pytest.raises(ops.OpsError):
            ops.approve(path, item["id"], item["payload_sha256"], channel=channel)
    # a line typed into say never approves an effect, whatever the policy grants
    for channel in ("messaging", "chat", "page"):
        said = ops.say(path, f"/approve {item['id']} {item['payload_sha256']}", channel=channel)["reply"]
        assert said.startswith("error: "), (channel, said)
    assert writes(world) == [] and ops.pending(path, item["id"])["status"] == "open"
    # the page, under a policy that lists only another word, is refused for this one; under its own word it approves
    with pytest.raises(ops.OpsError) as page:
        ops.approve(path, item["id"], item["payload_sha256"], channel="page")
    assert "not enabled" in str(page.value) and writes(world) == []
    accept(path, {"page": ["read", "approve-effect-write"]})
    assert ops.approve(path, item["id"], item["payload_sha256"], channel="page")["task_state"] == "done" and len(writes(world)) == 1


def test_accept_config_asks_for_the_hash_only_of_a_grant_the_accepted_file_did_not_list(world):  # noqa: F811
    path = world["path"]
    first = accept(path, {"messaging": ["read", "approve-effect-write"]})
    assert [w["group"] for w in first["widened"]] == ["approve-effect-write"]
    file = Path(path) / "docs" / "workbench" / "runtime.json"
    # an unchanged grant, a narrower entry, and a change of another key need no flag
    raw = json.loads(file.read_text())
    raw["max_running"] = 2
    file.write_text(json.dumps(raw))
    assert ops.config(path)["widening"] == []
    assert ops.accept_config(path, ops.config(path)["sha256"])["widened"] == []
    raw["channels"] = {"messaging": ["read"]}
    file.write_text(json.dumps(raw))
    assert ops.accept_config(path, ops.config(path)["sha256"])["widened"] == [] and ops.config(path)["grants"] == []
    # the grant given up and asked for again is a new widening
    raw["channels"] = {"messaging": ["read", "approve-effect-write"]}
    file.write_text(json.dumps(raw))
    shown = ops.config(path)
    assert [w["group"] for w in shown["widening"]] == ["approve-effect-write"]
    with pytest.raises(ops.OpsError):
        ops.accept_config(path, shown["sha256"])
    # a second grant beside the first asks for the hash of the new one alone
    accept(path, {"messaging": ["read", "approve-effect-write"]})
    raw["channels"] = {"messaging": ["read", "approve-effect-write", "approve-effect-create"], "mcp": ["read", "retry"]}
    file.write_text(json.dumps(raw))
    shown = ops.config(path)
    assert [(w["channel"], w["group"]) for w in shown["widening"]] == [("messaging", "approve-effect-create"), ("mcp", "retry")]
    assert shown["widening_sha256"] == hashlib.sha256(b"messaging:approve-effect-create\nmcp:retry\n").hexdigest()
    assert shown["widening_sha256"] != hashlib.sha256(b"messaging:approve-effect-write\nmessaging:approve-effect-create\nmcp:retry\n").hexdigest()
    with pytest.raises(ops.OpsError):
        ops.accept_config(path, shown["sha256"], widen=hashlib.sha256(b"messaging:approve-effect-create\n").hexdigest())
    assert ops.accept_config(path, shown["sha256"], widen=shown["widening_sha256"])["widened"][1]["group"] == "retry"
    # the file edited by someone else: a grant added between the reading and the acceptance changes the list, and the old hash no longer fits
    raw["channels"]["messaging"].append("approve-effect-send")
    file.write_text(json.dumps(raw))
    again = ops.config(path)
    with pytest.raises(ops.OpsError):
        ops.accept_config(path, again["sha256"], widen=shown["widening_sha256"])
    assert ops.config(path)["accepted"] is False


def test_the_acceptance_that_set_mode_and_consent_make_does_not_widen_and_keeps_the_recorded_grants(world):  # noqa: F811
    path = world["path"]
    accept(path, {"messaging": ["read", "approve-effect-write"]})
    ctx = ops_core.context(path)
    assert json.loads(ctx["store"].cursor_get(ctx["conn"], policy_grants.CURSOR)) == ["messaging:approve-effect-write"]
    file = Path(path) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(file.read_text())
    raw["area_agents"] = {"planning": {"pack": "planning", "mode": "supervised"}}
    file.write_text(json.dumps(raw))
    ops.accept_config(path, ops.config(path)["sha256"])
    moved = ops.set_mode(path, "planning", "autonomous", accept=True, channel="terminal", consent=True)
    assert moved["accepted"] is True and moved["by"] == "person"
    assert ops.config(path)["widening"] == [] and len(ops.config(path)["grants"]) == 1
    ctx = ops_core.context(path)
    assert json.loads(ctx["store"].cursor_get(ctx["conn"], policy_grants.CURSOR)) == ["messaging:approve-effect-write"]
    # an edit that adds a grant to the file, then set-mode --accept: refused, since the file is not the accepted one
    raw = json.loads(file.read_text())
    raw["channels"]["messaging"].append("approve-effect-create")
    file.write_text(json.dumps(raw))
    with pytest.raises(ops.OpsError):
        ops.set_mode(path, "planning", "supervised", accept=True, channel="terminal")
    assert [w["group"] for w in ops.config(path)["widening"]] == ["approve-effect-create"] and ops.config(path)["accepted"] is False



# --- limit L44 -------------------------------------------------------------------------------------------------------------------


def test_limit_44_an_effect_is_approved_off_the_terminal_and_the_page_only_for_a_granted_word_from_a_whole_card_and_with_its_own_hash_never_from_the_mcp_mode_the_conversation_or_a_typed_line(world):  # noqa: F811
    path = world["path"]
    task, item = write_opened(world)
    digest = item["payload_sha256"]

    def refused(channel, sha=digest):
        with pytest.raises(ops.OpsError):
            ops.approve(path, item["id"], sha, channel=channel)
        assert writes(world) == [] and ops.pending(path, item["id"])["status"] == "open"

    # no grant: the default, every channel but the terminal and the page is refused before anything executes
    for channel in ("messaging", "chat", "mcp", None, "bogus"):
        refused(channel)
    # the word is granted by the accepted configuration, and the grant is not the umbrella and not another word
    accept(path, {"messaging": ["read", "approve-effect-create"]})
    refused("messaging")
    accept(path, {"messaging": ["read", "approve-effect-write"], "mcp": ["read", "approve-plans", "reject-cancel", "retry"]})
    # the conversation, the MCP mode and a typed line stay refused with the word granted; a hash that is not the effect's is refused too
    for channel in ("chat", "mcp", None, "bogus"):
        refused(channel)
    refused("messaging", "0" * 64)
    refused("messaging", None)
    for channel in ("messaging", "chat"):
        assert ops.say(path, f"/approve {item['id']} {digest}", channel=channel)["reply"].startswith("error: ")
    # a card that did not carry the whole text approves nothing: the card is built whole or not, and the bridge takes the hash from it
    full = ops.pending(path, item["id"])
    caps = {"buttons": True, "max_buttons": 6, "max_text": 4096, "documents": False}
    whole = cards.build("p", full, caps, ops.config(path)["channels"], "text", None, operations=operations)
    cut = cards.build("p", {**full, "body": "z" * 6000}, {**caps, "max_text": 1600}, ops.config(path)["channels"], "text", None, operations=operations)
    counted = cards.build("p", full, caps, ops.config(path)["channels"], "count", None, operations=operations)
    assert whole["whole"] is True and whole["approvable"] is True
    assert cut["whole"] is False and cut["approvable"] is False and counted["approvable"] is False
    # the granted channel, the right word, the exact hash: executes once
    assert ops.approve(path, item["id"], digest, channel="messaging")["task_state"] == "done" and len(writes(world)) == 1

# --- the facts of an effect -----------------------------------------------------------------------------------------------------------


def synthetic(tmp_path, doc):
    path, digest = effects.write(str(tmp_path), doc)
    return {"id": 9, "kind": "effect", "payload": {"effect_file": path}, "payload_sha256": digest}


def test_the_effects_word_and_whether_it_fits_on_a_card_come_from_the_document_read_by_the_decisions_own_hash(tmp_path):
    def made(name, doc):
        (tmp_path / name).mkdir()
        return synthetic(tmp_path / name, doc)

    nothing = {"word": None, "on_cards": False}
    assert ops_grants.effect_facts({}, made("a", {"effect": "send", "attachments": []})) == {"word": "send", "on_cards": True}
    assert ops_grants.effect_facts({}, made("b", {"effect": "send", "attachments": [{"name": "invoice.pdf"}]})) == {"word": "send", "on_cards": False}
    assert ops_grants.effect_facts({}, made("c", {"effect": "publish", "image": {"path": "docs/outputs/photo.png"}})) == {"word": "publish", "on_cards": False}
    assert ops_grants.effect_facts({}, made("d", {"effect": "publish", "image": None})) == {"word": "publish", "on_cards": True}
    assert ops_grants.effect_facts({}, made("e", {"effect": "write", "content": "# Plan\n"})) == {"word": "write", "on_cards": True}, "a page is on a card"
    assert ops_grants.effect_facts({}, made("e2", {"effect": "write", "operation": "create_page", "content": "# New\n"})) == {"word": "write", "on_cards": True}
    for operation in ("create_table", "append_rows"):       # a table's card is a preview (20 rows, the last 3, cells cut at 60): the hash covers every row
        assert ops_grants.effect_facts({}, made("t" + operation, {"effect": "write", "operation": operation, "content": {"columns": [], "rows": []}})) \
            == {"word": "write", "on_cards": False}, operation
    assert ops_grants.effect_facts({}, made("e3", {"effect": "write"})) == {"word": "write", "on_cards": False}, "a document without its content is not on a card"
    assert ops_grants.effect_facts({}, made("e4", {"effect": "create"})) == {"word": "create", "on_cards": False}, "a pull request card shows paths and hashes, not the code"
    # what cannot be read is no word and not on a card: a file edited after the gate, a word no kind has, no file, no hash
    edited = made("f", {"effect": "write"})
    Path(edited["payload"]["effect_file"]).write_text("{}")
    assert ops_grants.effect_facts({}, edited) == nothing
    assert ops_grants.effect_facts({}, made("g", {"effect": "teleport"})) == nothing
    assert ops_grants.effect_facts({}, {"id": 1, "payload": {"effect_file": str(tmp_path / "none")}, "payload_sha256": "a" * 64}) == nothing
    assert ops_grants.effect_facts({}, {"id": 1, "payload": {"effect_file": str(tmp_path / "a" / "effect.json")}, "payload_sha256": None}) == nothing
    assert ops_grants.effect_kind({"word": "send"}) == "effect:send" and ops_grants.effect_kind({"word": None}) == "effect" and ops_grants.effect_kind(None) == "effect"


def test_a_pull_request_effect_carries_its_word_and_no_card_approves_it_even_with_create_granted_the_terminal_and_the_page_do(tree):  # noqa: F811
    path, plan_id, digest, accept_id, effect = decisions(tree)
    full = ops.pending(path, effect["id"])
    assert full["effect_word"] == "create" and full["effect_on_cards"] is False, "the card shows paths and hashes, not the code the hash covers"
    assert "effect_word" not in ops.pending(path)["pending"][0], "the list does not read every effect document"
    # the default: refused before anything executes, and the sentence is the one it always was
    with pytest.raises(ops.OpsError) as no:
        ops.approve(path, effect["id"], effect["payload_sha256"], channel="messaging")
    assert "an effect is approved in the terminal, with its hash" in str(no.value) and provider_calls(tree) == []
    accept(path, {"messaging": ["read", "approve-effect-write"]})          # the wrong word
    with pytest.raises(ops.OpsError):
        ops.approve(path, effect["id"], effect["payload_sha256"], channel="messaging")
    assert provider_calls(tree) == [] and ops.pending(path, effect["id"])["status"] == "open"
    accept(path, {"messaging": ["read", "approve-effect-create"]})
    with pytest.raises(ops.OpsError) as no:      # the grant is there and approves nothing yet: a card does not show the change
        ops.approve(path, effect["id"], effect["payload_sha256"], channel="messaging")
    assert "more than a card can show" in str(no.value) and "the code of a change" in str(no.value)
    assert provider_calls(tree) == [] and ops.pending(path, effect["id"])["status"] == "open"
    done = ops.approve(path, effect["id"], effect["payload_sha256"], channel="terminal")
    assert done["pull_request"] and ops.pending(path, effect["id"])["status"] == "resolved"
    assert any(call for call in provider_calls(tree)), "the provider was called, once, by code"
    calls_after = len(provider_calls(tree))
    with pytest.raises(ops.OpsError):
        ops.approve(path, effect["id"], effect["payload_sha256"], channel="terminal")
    assert len(provider_calls(tree)) == calls_after


# --- an effect that cannot be on a card ----------------------------------------------------------------------------------------


def test_an_effect_whose_whole_cannot_be_on_a_card_is_refused_to_a_granted_channel_and_approved_by_the_terminal(tmp_path, monkeypatch):
    refused_by = ops_grants.effect_refusal
    ctx = {"cfg": {"project": str(tmp_path), "channels": {"messaging": ["read", "approve-effect-send", "approve-effect-publish"]}}}
    item = {"id": 3, "payload_sha256": "a" * 64}
    for word, fits in (("send", False), ("publish", False)):
        sentence = refused_by(ctx, item, "messaging", {"word": word, "on_cards": fits})
        assert sentence and "more than a card can show" in sentence and "approve" in sentence, word
        assert refused_by(ctx, item, "messaging", {"word": word, "on_cards": True}) is None, "granted and whole: allowed"
    for channel in ("terminal", "page"):
        assert refused_by(ctx, item, channel, {"word": "send", "on_cards": False}) is None, "the terminal and the page approve it with its hash"
    # a granted word of one kind does not cover another, and an unknown word is `effect` with no word
    assert "an effect is approved in the terminal" in refused_by(ctx, item, "messaging", {"word": "write", "on_cards": True})
    assert "an effect is approved in the terminal" in refused_by(ctx, item, "messaging", {"word": None, "on_cards": False})
    assert "an effect is approved in the terminal" in refused_by(ctx, item, "mcp", {"word": "send", "on_cards": True})
    assert "an effect is approved in the terminal" in refused_by(ctx, item, None, {"word": "send", "on_cards": True})


# --- the networked plan (limit L36) -----------------------------------------------------------------------------------------------


NETWORKED = {"id": 1, "kind": "plan", "payload": {"tasks": [{"key": "report", "step": "project-script", "args": {}}]}}


def test_a_networked_plan_is_a_grant_of_a_messaging_app_and_never_the_conversations_or_the_mcp_modes():
    assert ops_waits.networked_steps(NETWORKED) == [("report", "project-script")]
    plain = {"messaging": ["read", "approve-plans"]}
    granted = {"messaging": ["read", "approve-plans", "approve-networked-plans"]}
    for channel in ("messaging", "mcp", "chat", "bogus", None):
        with pytest.raises(ops.OpsError) as no:
            ops_waits.only_on_plans(NETWORKED, None, "a" * 64, channel, plain)
        assert "terminal or on the page by default" in str(no.value) and "approve-networked-plans" in str(no.value) and "Nothing was approved" in str(no.value)
    ops_waits.only_on_plans(NETWORKED, None, "a" * 64, "messaging", granted)                           # granted: allowed, with its hash
    with pytest.raises(ops.OpsError) as no_hash:
        ops_waits.only_on_plans(NETWORKED, None, None, "messaging", granted)
    assert "only with its hash" in str(no_hash.value)
    for channel in ("mcp", "chat", None, "bogus"):                                                    # every grant a policy can list, still no
        everything = {"mcp": ["read", *operations.GRANTS["mcp"]], "chat": ["read"], "messaging": granted["messaging"]}
        with pytest.raises(ops.OpsError):
            ops_waits.only_on_plans(NETWORKED, None, "a" * 64, channel, everything)
    # the grant is on top of approve-plans: alone it approves no plan
    with pytest.raises(ops.OpsError) as alone:
        ops_waits.only_on_plans(NETWORKED, None, "a" * 64, "messaging", {"messaging": ["read", "approve-networked-plans"]})
    assert "not enabled" in str(alone.value)
    for channel in ("terminal", "page"):
        ops_waits.only_on_plans(NETWORKED, None, "a" * 64, channel, plain)
    # a plan with no networked step is what it was
    ops_waits.only_on_plans({"id": 2, "kind": "plan", "payload": {"tasks": [{"key": "pull", "step": "ingest", "args": {}}]}}, None, "a" * 64, "messaging", plain)
    # the kind `plan:networked` is asked the page as a plan, and the other channels need the grant
    assert operations.permitted("approve", "page", {"page": ["read", "approve-plans"]}, "plan:networked")
    assert not operations.permitted("approve", "page", {"page": ["read"]}, "plan:networked")
    assert operations.permitted("approve", "messaging", granted, "plan:networked") and not operations.permitted("approve", "messaging", plain, "plan:networked")
    assert operations.permitted("approve", "terminal", None, "plan:networked") and not operations.permitted("approve", "chat", None, "plan:networked")


# --- the MCP mode ---------------------------------------------------------------------------------------------------------------


def tool(server, name, arguments=None):
    from test_mcp import tool as call  # noqa: E402  (the helper of test_mcp.py)
    return call(server, name, arguments)


def finished(server, answer):
    """The result of a tool call that may have started a job: the final text and whether it was a refusal or a failure."""
    assert "error" not in answer, answer
    content = answer["result"]["content"][0]["text"]
    if answer["result"]["isError"]:
        return True, content
    found = json.loads(content)
    deadline = time.monotonic() + WAIT
    while isinstance(found, dict) and found.get("state") == "running" and time.monotonic() < deadline:
        found = json.loads(tool(server, "job", {"job": found["job"]})["result"]["content"][0]["text"])
    if isinstance(found, dict) and found.get("state") == "failed":
        return True, found["error"]
    return False, found.get("result", found) if isinstance(found, dict) else found


def test_the_mcp_mode_lists_and_runs_the_granted_tools_for_a_plan_with_its_hash_and_never_for_an_effect(tree):  # noqa: F811
    path, plan_id, digest, accept_id, effect = decisions(tree)
    projects = [{"id": mcp.project_id(path), "name": "p", "path": path}]
    server = mcp.Server(ops, projects, log=lambda line: None, grace=WAIT)
    names = lambda: [t["name"] for t in server.tools()]  # noqa: E731
    base = ["request", "route", "status", "task", "flows", "flow-check", "progress", "pending", "answer", "release", "say", "agents", "conversation", "skills", "costs",
            "connections", "artifacts", "artifact", "version", "sources", "instructions", "routines", "projects", "job"]
    assert names() == base, "off by default: no approve, reject, cancel or retry tool"
    for name in ("approve", "reject", "retry", "cancel"):
        assert tool(server, name, {"pending_id": plan_id})["error"]["code"] == -32602
    accept(path, {"mcp": ["read", "talk", "approve-plans", "reject-cancel", "retry"]})
    listed = names()
    assert [n for n in listed if n in ("approve", "reject", "cancel", "retry")] == ["approve", "reject", "retry", "cancel"] and "stop-task" not in listed
    # a plan needs its hash, and only the plan's own
    refused_, text = finished(server, tool(server, "approve", {"pending_id": plan_id}))
    assert refused_ and "only with its hash" in text and ops.pending(path, plan_id)["status"] == "open"
    refused_, text = finished(server, tool(server, "approve", {"pending_id": plan_id, "sha256": "0" * 64}))
    assert refused_ and "nothing was approved" in text
    # an acceptance is not granted here, an effect never is, with the right hash or without
    refused_, text = finished(server, tool(server, "approve", {"pending_id": accept_id}))
    assert refused_ and "not enabled" in text and ops.pending(path, accept_id)["status"] == "open"
    refused_, text = finished(server, tool(server, "approve", {"pending_id": effect["id"], "sha256": effect["payload_sha256"]}))
    assert refused_ and "an effect is approved in the terminal, with its hash" in text
    assert provider_calls(tree) == [] and ops.pending(path, effect["id"])["status"] == "open"
    refused_, result = finished(server, tool(server, "approve", {"pending_id": plan_id, "sha256": digest}))
    assert not refused_ and ops.pending(path, plan_id)["status"] == "resolved"
    # reject and retry are what the entry lists; a project that does not list one refuses it
    refused_, text = finished(server, tool(server, "reject", {"pending_id": accept_id}))
    assert not refused_ and ops.pending(path, accept_id)["status"] == "resolved"
    # an effect is rejected from here too (nothing is sent by a rejection)
    # a typed line stays refused on this channel, whatever it grants
    failed, said = finished(server, tool(server, "say", {"text": f"/approve {effect['id']} {effect['payload_sha256']}"}))
    assert not failed and "is done in the terminal or on the page" in said["reply"] and ops.pending(path, effect["id"])["status"] == "open" and provider_calls(tree) == []


def test_no_effect_group_is_valid_on_the_mcp_mode_in_a_file_and_no_grant_makes_the_server_list_an_unrelated_tool(tree):  # noqa: F811
    path, plan_id, digest, accept_id, effect = decisions(tree)
    file = Path(path) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(file.read_text())
    for group in ("approve-effects", "approve-effect-write", "approve-networked-plans"):
        raw["channels"] = {"mcp": ["read", "approve-plans", group]}
        file.write_text(json.dumps(raw))
        with pytest.raises(ops.OpsError) as bad:
            ops.config(path)
        assert bad.value.code == 3 and "channels.mcp" in str(bad.value)
    projects = [{"id": mcp.project_id(path), "name": "p", "path": path}]
    accept(path, {"mcp": ["read", "retry"]})
    server = mcp.Server(ops, projects, log=lambda line: None, grace=WAIT)
    listed = [t["name"] for t in server.tools()]
    assert "retry" in listed and not {"approve", "reject", "cancel"} & set(listed)
