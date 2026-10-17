"""Policies per sender (package POL-2): a policy is a named set of groups (a profile), a channel has a default profile and, on a messaging app, each
listed sender may have their own. The schema and its refusals (runtime/project_config.py), the resolution (operations.effective_groups), the
widening of a sender (runtime/policy_widening.py, accept-config --widen), the actor that the store keeps with a decision and that no file of the
project shows (runtime/ops_actor.py, providers/store/sqlite.py migration 17), what a limited reader sees (`read-limited`) and the brakes of the page. What
the bridge does with a sender (the card, the tap, the chat check) is in test_sender_profiles_bridge.py. Offline, no model; invented ids.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_sender_profiles.py
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
from pathlib import Path

import pytest

import standin_tree as st
from test_board_mirror import planned as board_planned, tree as board_tree  # noqa: F401  (the board world of test_board_mirror.py, under another name)
from test_effects import tree  # noqa: F401  (the stand-in tree fixture)
from test_messaging_policy import decisions
from test_write_back import PATH as WRITE_PATH, opened as write_opened, writes, world  # noqa: F401  (the write-back world)

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_actor = st.load("ops_actor")
operations = st.load("operations")
policy_grants = st.load("policy_grants")
policy_widening = st.load("policy_widening")
project_config = st.load("project_config")
progress = st.load("progress")

OWNER = "55119000000001"
STAFF = "55119000000002"
OWNER_KEY = f"telegram:{OWNER}"
STAFF_KEY = f"telegram:{STAFF}"
POLICIES = {
    "owner": ["read", "talk", "answer", "release", "approve-plans", "approve-acceptances", "reject-cancel", "retry", "routine-brakes",
              "approve-effect-write"],
    "staff": ["read-limited", "talk", "answer"],
}
SENDERS = {"telegram": [{"id": OWNER, "policy": "owner"}, {"id": STAFF, "policy": "staff"}]}


def write_config(path, **keys):
    """Replace the given keys of the project's runtime.json (a None removes the key) and return the file."""
    file = Path(path) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(file.read_text())
    for key, value in keys.items():
        if value is None:
            raw.pop(key, None)
        else:
            raw[key] = value
    file.write_text(json.dumps(raw))
    return file


def accept(path, **keys):
    """Write the keys and accept the file as the person does: read `config`, and type the hash of the widening list it shows."""
    write_config(path, **keys)
    shown = ops.config(path)
    return ops.accept_config(path, shown["sha256"], widen=shown["widening_sha256"])


def loaded(raw_policies=None, channels=None, messaging=None):
    """The three keys through the loader's own functions, as project_config.load puts them together."""
    policies = project_config._policies(raw_policies)
    messaging_out = project_config._messaging(messaging, policies)
    out = project_config._channels(channels, policies)
    senders = project_config.sender_policy(messaging_out, policies)
    if senders:
        out[operations.SENDERS_KEY] = senders
    return policies, messaging_out, out


# --- today's files resolve unchanged ---------------------------------------------------------------------------------------


def old_resolution(channel, channels):
    """The rule before the profiles, written out here: the project's entry, else the default of the channel, else the whole ceiling (None)."""
    given = (channels or {}).get(channel)
    return tuple(given) if given is not None else operations.DEFAULT_POLICY.get(channel)


def test_today_s_files_resolve_unchanged_for_every_channel_and_every_sender():
    files = [{}, {"page": ["read"]}, {"page": ["read", "approve-plans"], "mcp": ["read", "talk"], "messaging": ["read", "talk", "answer", "release"]},
             {"messaging": []}, {"messaging": ["read-limited", "talk"]}]
    for raw in files:
        channels = project_config._channels(raw)                       # a flat list, with no `policies`: the form of today
        messaging = project_config._messaging({"senders": {"telegram": [OWNER, STAFF], "whatsapp": ["55119000000003"]}})
        assert operations.SENDERS_KEY not in channels and messaging["sender_profiles"] == {}
        for channel in (*operations.POLICY_CHANNELS, "chat", "terminal", "bogus"):
            assert operations.effective_groups(channel, channels) == old_resolution(channel, channels)
            for platform, ids in messaging["senders"].items():
                for sender in ids:                                      # a string sender gets the channel's groups, whatever the sender is
                    key = operations.sender_key(platform, sender)
                    assert operations.effective_groups(channel, channels, key) == old_resolution(channel, channels), (raw, channel, key)
                    for row in operations.OPERATIONS:
                        for kind in (None, "plan", "acceptance", "effect:write"):
                            assert operations.permitted(row["name"], channel, channels, kind, key) is operations.permitted(row["name"], channel, channels, kind)
    # and the loader puts nothing new into a file that has no profile
    assert project_config._policies(None) == {} and project_config.channel_profiles({"page": ["read"]}) == {}


def test_a_profile_replaces_the_channels_groups_for_that_sender_and_a_string_sender_gets_the_channels():
    policies, messaging, channels = loaded(POLICIES, {"messaging": "staff"}, {"senders": {"telegram": [{"id": OWNER, "policy": "owner"}, STAFF]}})
    assert channels["messaging"] == ["read-limited", "talk", "answer"]          # the channel's profile is its default groups
    assert operations.effective_groups("messaging", channels) == ("read-limited", "talk", "answer")
    assert operations.effective_groups("messaging", channels, OWNER_KEY) == tuple(POLICIES["owner"])
    assert operations.effective_groups("messaging", channels, STAFF_KEY) == ("read-limited", "talk", "answer")   # no profile of their own: the channel's
    assert operations.effective_groups("messaging", channels, "telegram:55119000000099") == ("read-limited", "talk", "answer")
    # replaces, never adds: a sender may be NARROWER than the channel default
    _, _, narrow = loaded({"all": ["read", "talk", "answer", "release"], "view": ["read"]}, {"messaging": "all"},
                          {"senders": {"telegram": [{"id": STAFF, "policy": "view"}, OWNER]}})
    assert operations.permitted("release", "messaging", narrow, None, OWNER_KEY) and not operations.permitted("release", "messaging", narrow, None, STAFF_KEY)
    assert not operations.permitted("say", "messaging", narrow, None, STAFF_KEY) and operations.permitted("say", "messaging", narrow, None, OWNER_KEY)
    # the profile applies to the messaging channel only: another channel never reads a sender
    assert operations.effective_groups("page", channels, OWNER_KEY) == old_resolution("page", channels)


def test_a_grant_counts_only_from_the_senders_own_profile_or_the_channels_explicit_entry_never_from_a_default():
    policies, messaging, channels = loaded(POLICIES, {"messaging": ["read", "talk"]}, {"senders": {"telegram": [{"id": OWNER, "policy": "owner"}, STAFF]}})
    assert operations.permitted("approve", "messaging", channels, "effect:write", OWNER_KEY)
    assert not operations.permitted("approve", "messaging", channels, "effect:write", STAFF_KEY)
    assert not operations.permitted("approve", "messaging", channels, "effect:write")
    assert operations.sender_grants(channels) == [(OWNER_KEY, "approve-effect-write")] and operations.grants(channels) == []
    assert not operations.permitted("approve", "messaging", {}, "effect:write", OWNER_KEY), "a sender unknown to the mapping is the default's: no grant"


# --- the refusals of the schema, each with its sentence ----------------------------------------------------------------------


def refusal(policies=None, channels=None, messaging=None):
    with pytest.raises(project_config.ConfigError) as refused:
        loaded(policies, channels, messaging)
    return str(refused.value)


def test_every_refusal_of_the_schema_names_what_is_wrong():
    ok = {"p": ["read", "talk"]}
    assert "'Bad' is not a profile name" in refusal({"Bad": ["read"]})
    assert "'" + "x" * 33 + "' is not a profile name" in refusal({"x" * 33: ["read"]})
    assert "'default' is the label of a sender with no profile" in refusal({"default": ["read"]})
    assert "policies.p: 'nonsense' is not a group (known: read" in refusal({"p": ["read", "nonsense"]})
    assert "policies.p must be a list of group names" in refusal({"p": "read"})
    assert "lists both 'read' and 'read-limited'" in refusal({"p": ["read", "read-limited"]})
    assert "an object profile has the keys groups, notices" in refusal({"p": {"groups": ["read"], "colour": "red"}})
    assert "policies.p.notices must be one of all, actionable" in refusal({"p": {"groups": ["read"], "notices": "loud"}})
    assert "policies must be an object" in refusal([])
    # an unknown profile, at a channel and at a sender
    assert "channels.messaging: 'nobody' is not a profile of policies (known: p)" in refusal(ok, {"messaging": "nobody"})
    assert "messaging.senders.telegram: 'nobody' is not a profile of policies (known: p)" in refusal(
        ok, None, {"senders": {"telegram": [{"id": OWNER, "policy": "nobody"}]}})
    # a profile assigned to a channel that does not take one of its groups: the sentence names the profile AND the channel
    wide = {"owner": ["read", "approve-effects"], "reader": ["read-limited"], "net": ["read", "approve-plans", "approve-networked-plans", "approve-effect-write"]}
    text = refusal(wide, {"messaging": "owner"})
    assert "channels.messaging: profile 'owner': the group 'approve-effects' is valid on the page only" in text
    text = refusal(wide, {"mcp": "net"})
    assert "channels.mcp: profile 'net':" in text and "not valid on the MCP mode" in text
    text = refusal(wide, {"page": "reader"})
    assert "channels.page: profile 'reader': the group 'read-limited' is valid on a messaging app only" in text
    text = refusal(wide, None, {"senders": {"telegram": [{"id": STAFF, "policy": "owner"}]}})
    assert "messaging.senders.telegram: profile 'owner': the group 'approve-effects' is valid on the page only" in text
    assert "channels.page: profile 'p': must list the group 'read'" in refusal({"p": ["talk"]}, {"page": "p"})
    assert "profile 'q': 'approve-networked-plans' needs 'approve-plans' beside it" in refusal({"q": ["approve-networked-plans"]}, {"messaging": "q"})
    # a sender id listed twice on one platform, in either form
    assert "a sender is listed once on a platform" in refusal(ok, None, {"senders": {"telegram": [OWNER, OWNER]}})
    assert "a sender is listed once on a platform" in refusal(ok, None, {"senders": {"telegram": [OWNER, {"id": OWNER, "policy": "p"}]}})
    assert loaded(ok, None, {"senders": {"telegram": [OWNER], "whatsapp": [OWNER]}}), "the same id on another platform is another sender"
    # an id that is not a string without spaces, an entry object with other keys
    for bad in (5, "", " ", "55 11", None, {"id": 5, "policy": "p"}, "x" * 65):
        assert "must list sender ids" in refusal(ok, None, {"senders": {"telegram": [bad]}}), bad
    for bad in ({"id": OWNER}, {"id": OWNER, "policy": "p", "extra": 1}, {"policy": "p"}, {}):
        assert "an entry object has the keys id and policy, and no other" in refusal(ok, None, {"senders": {"telegram": [bad]}}), bad
    # a `policy` on the conversation or the terminal
    for name in ("chat", "terminal"):
        assert f"channels.{name}: the {name} is never narrowed" in refusal(ok, {name: "p"})
        assert f"channels.{name}: the {name} is never narrowed" in refusal(ok, {name: ["read"]})
    assert "has no policy; the channels with one are page, mcp, messaging" in refusal(ok, {"nobody": "p"})
    assert "must be a list of group names or the name of a profile" in refusal(ok, {"page": 5})
    # the profile that is fine at a channel and at a sender
    policies, messaging, channels = loaded({"p": ["read", "talk"], "reader": {"groups": ["read-limited", "talk"], "notices": "actionable"}},
                                           {"page": "p"}, {"senders": {"telegram": [{"id": OWNER, "policy": "reader"}]}})
    assert policies["reader"] == {"groups": ["read-limited", "talk"], "notices": "actionable"} and policies["p"]["notices"] == "all"
    assert channels["page"] == ["read", "talk"] and channels[operations.SENDERS_KEY] == {OWNER_KEY: ["read-limited", "talk"]}
    assert messaging["senders"] == {"telegram": [OWNER]} and messaging["sender_profiles"] == {"telegram": {OWNER: "reader"}}


def test_the_file_is_loaded_with_its_profiles_and_the_closed_set_of_keys_has_policies(tree):  # noqa: F811
    path = str(tree["project"])
    write_config(path, policies=POLICIES, channels={"messaging": "staff", "page": ["read", "approve-plans"]},
                 messaging={"senders": SENDERS, "notices": "text"})
    cfg = project_config.load(path)
    assert cfg["policies"]["staff"] == {"groups": ["read-limited", "talk", "answer"], "notices": "all"}
    assert cfg["channel_profiles"] == {"messaging": "staff"} and cfg["messaging"]["senders"] == {"telegram": [OWNER, STAFF]}
    assert cfg["messaging"]["sender_profiles"] == {"telegram": {OWNER: "owner", STAFF: "staff"}}
    assert cfg["channels"][operations.SENDERS_KEY] == {OWNER_KEY: POLICIES["owner"], STAFF_KEY: POLICIES["staff"]}
    assert "policies" in project_config.TASK_RUNTIME_KEYS
    shown = ops.config(path)
    assert shown["policies"] == cfg["policies"] and shown["channel_profiles"] == {"messaging": "staff"} and shown["messaging"]["sender_profiles"]
    write_config(path, policies={"staff": ["read-limited", "nonsense"]})
    with pytest.raises(project_config.ConfigError, match="policies.staff: 'nonsense' is not a group"):
        project_config.load(path)


def test_the_warnings_a_profile_nobody_uses_and_a_sender_profile_with_effect_grants_while_the_notices_carry_no_text():
    policies, messaging, channels = loaded({**POLICIES, "spare": ["read"]}, None, {"senders": {"telegram": SENDERS["telegram"]}, "notices": "count"})
    cfg = {"policies": policies, "messaging": messaging, "channels": channels, "channel_profiles": {}}
    found = policy_grants.warnings(cfg)
    assert any("the profile spare is assigned to no channel and no sender" in w for w in found)
    assert any("notices is 'count'" in w and "approve-effect-write" in w for w in found), "the owner's profile grants a write; a card of `count` holds no text"
    cfg["messaging"] = {**messaging, "notices": "text"}
    assert [w for w in policy_grants.warnings(cfg) if "notices" in w] == []
    assert [g for g in policy_grants.grants(cfg) if g.get("sender")] == [
        {"channel": "messaging", "sender": OWNER_KEY, "group": "approve-effect-write", "means": operations.GRANT_TEXT["messaging:approve-effect-write"]}]


# --- the widening: any group a place did not effectively have --------------------------------------------------------------


def lines_of(shown):
    return [f"{w['place']}:{w['group']}" for w in shown["widening"]]


def test_a_group_inside_a_channels_ceiling_is_a_widening_too_with_its_text_and_the_hash_of_the_list(tree):  # noqa: F811
    path = str(tree["project"])
    first = ops.config(path)
    assert first["widening"] == [] and first["widening_sha256"] is None, "no entry: the defaults, nothing beyond them"
    write_config(path, channels={"messaging": ["read", "talk", "answer", "release", "approve-plans", "reject-cancel", "retry", "brakes", "routine-edit"]})
    shown = ops.config(path)
    assert lines_of(shown) == [f"messaging:{g}" for g in ("release", "approve-plans", "reject-cancel", "brakes", "retry", "routine-edit")]   # the order of GROUPS
    assert all(w["means"] == operations.GROUP_TEXT[w["group"]] for w in shown["widening"]), "a group inside the ceiling says what it gives"
    expect = hashlib.sha256("".join(line + "\n" for line in lines_of(shown)).encode()).hexdigest()      # what a person can compute by hand
    assert shown["widening_sha256"] == expect
    for wrong in (None, "0" * 64, shown["sha256"]):
        with pytest.raises(ops.OpsError) as refused:
            ops.accept_config(path, shown["sha256"], widen=wrong)
        text = str(refused.value)
        assert "widens what a channel may do or what a listed sender may do" in text and f"--widen {expect}" in text
        assert "messaging:release: " + operations.GROUP_TEXT["release"] in text and ops.config(path)["accepted"] is False
    done = ops.accept_config(path, shown["sha256"], widen=expect)
    assert [w["group"] for w in done["widened"]][:2] == ["release", "approve-plans"] and ops.config(path)["accepted"] is True
    assert ops.config(path)["widening"] == [] and ops.config(path)["widening_sha256"] is None
    # narrower, or the same, needs nothing; removing one group and adding another asks for the new one only
    write_config(path, channels={"messaging": ["read", "talk", "release"]})
    assert ops.config(path)["widening"] == [] and ops.accept_config(path, ops.config(path)["sha256"])["widened"] == []
    write_config(path, channels={"messaging": ["read", "talk", "retry"]})
    assert lines_of(ops.config(path)) == ["messaging:retry"]
    # the page and the MCP mode are compared with their ceiling: an entry, then a wider one
    accept(path, channels={"page": ["read"], "messaging": ["read"]})
    write_config(path, channels={"page": ["read", "approve-plans", "request"], "messaging": ["read"]})
    assert lines_of(ops.config(path)) == ["page:request", "page:approve-plans"]
    accept(path, channels={"page": ["read", "approve-plans", "request"]})
    write_config(path, channels=None)       # the entry removed: the page then holds its whole ceiling again, and that is a widening
    assert "page:set-mode" in lines_of(ops.config(path)) and "page:read" not in lines_of(ops.config(path))
    accept(path, channels=None)
    write_config(path, channels={"page": ["read"]})
    assert ops.config(path)["widening"] == [], "from the ceiling to an entry is a narrowing"


def test_every_group_has_a_one_line_text_and_a_grants_text_is_its_own():
    assert set(operations.GROUP_TEXT) == set(operations.GROUPS), "every group has a line of text"
    for name, text in operations.GROUP_TEXT.items():
        assert isinstance(text, str) and text.strip() == text and text and "\n" not in text and len(text) < 220, name
    assert set(operations.GRANT_TEXT) == {f"{c}:{g}" for c, gs in operations.GRANTS.items() for g in gs}
    for place, text in (("messaging", "approve-effect-write"), ("messaging", "release"), ("mcp", "retry"), ("page", "set-mode")):
        assert policy_widening.means(place, text) == (operations.GRANT_TEXT.get(f"{place}:{text}") or operations.GROUP_TEXT[text])
    assert policy_widening.means("messaging", "approve-effect-write") == operations.GRANT_TEXT["messaging:approve-effect-write"]
    assert policy_widening.means("messaging", "release") == operations.GROUP_TEXT["release"]


def test_a_project_accepted_before_the_record_of_what_a_file_has_confirms_what_it_lists_beyond_the_defaults_once(tree):  # noqa: F811
    path = str(tree["project"])
    write_config(path, channels={"messaging": ["read", "talk", "answer", "release", "retry", "approve-effect-write"]})
    ctx = ops_core.context(path, check_config=False)
    # an older store: accepted with POL-1's record of the grants alone (or with none at all), and no record of what the file effectively had
    ctx["store"].cursor_set(ctx["conn"], policy_widening.LEGACY, json.dumps(["messaging:approve-effect-write"]))
    ctx["store"].cursor_set(ctx["conn"], project_config.ACCEPTED, project_config.load(path)["sha256"])
    shown = ops.config(path)
    assert shown["accepted"] is True, "the file stays in force: a record that was never written cannot take an accepted file away"
    assert lines_of(shown) == ["messaging:release", "messaging:retry"], "the grant was confirmed once (POL-1); the groups inside the ceiling were not"
    # the person runs accept-config with --widen, once, on the same hash
    done = ops.accept_config(path, shown["sha256"], widen=shown["widening_sha256"])
    assert [w["group"] for w in done["widened"]] == ["release", "retry"] and ops.config(path)["widening"] == []
    # with no record at all: the defaults, so every group beyond them is listed
    ctx = ops_core.context(path, check_config=False)
    with ctx["conn"]:
        ctx["conn"].execute("DELETE FROM cursors WHERE name IN (?, ?)", (policy_widening.EFFECTIVE, policy_widening.LEGACY))
    assert lines_of(ops.config(path)) == ["messaging:release", "messaging:approve-effect-write", "messaging:retry"]


def test_a_sender_moved_to_a_wider_profile_or_listed_with_one_is_a_widening_asked_by_the_hash_of_the_list(tree):  # noqa: F811
    path = str(tree["project"])
    accept(path, policies=POLICIES, channels={"messaging": "staff"}, messaging={"senders": {"telegram": [STAFF]}})
    # a new sender listed with a profile that is not a subset of the channel's groups
    write_config(path, messaging={"senders": {"telegram": [STAFF, {"id": OWNER, "policy": "owner"}]}})
    shown = ops.config(path)
    # the channel gave read-limited, talk and answer; the owner's profile adds `read` (which holds read-limited), and the rest of its groups
    assert lines_of(shown) == [f"{OWNER_KEY}:{g}" for g in operations.GROUPS if g in POLICIES["owner"] and g not in ("talk", "answer")]
    assert all(w["place"] == OWNER_KEY and w["channel"] == "messaging" for w in shown["widening"])
    assert f"{OWNER_KEY}:approve-effect-write" in lines_of(shown) and f"{OWNER_KEY}:release" in lines_of(shown)
    assert f"{OWNER_KEY}:talk" not in lines_of(shown), "a group the channel already gave is not a widening"
    with pytest.raises(ops.OpsError) as refused:
        ops.accept_config(path, shown["sha256"])
    assert OWNER_KEY + ":approve-effect-write" in str(refused.value) and "--widen " + shown["widening_sha256"] in str(refused.value)
    done = ops.accept_config(path, shown["sha256"], widen=shown["widening_sha256"])
    assert {w["place"] for w in done["widened"]} == {OWNER_KEY} and ops.config(path)["widening"] == []
    # a sender moved from a narrow profile to a wider one: the new groups only
    write_config(path, messaging={"senders": {"telegram": [{"id": STAFF, "policy": "owner"}, {"id": OWNER, "policy": "owner"}]}})
    moved = ops.config(path)
    assert {w["place"] for w in moved["widening"]} == {STAFF_KEY} and f"{STAFF_KEY}:release" in lines_of(moved)
    with pytest.raises(ops.OpsError):
        ops.accept_config(path, moved["sha256"])
    with pytest.raises(ops.OpsError):
        ops.accept_config(path, moved["sha256"], widen=shown["widening_sha256"])           # another list's hash
    assert ops.accept_config(path, moved["sha256"], widen=moved["widening_sha256"])["accepted"]
    # a sender moved to a subset of what they had, or to the channel's own groups, asks for nothing
    write_config(path, messaging={"senders": {"telegram": [{"id": STAFF, "policy": "staff"}, {"id": OWNER, "policy": "owner"}]}})
    assert ops.config(path)["widening"] == [] and ops.accept_config(path, ops.config(path)["sha256"])["accepted"]
    # a group added to a profile that is assigned: the senders that use it widen; a profile nobody uses widens nobody
    policies = {**POLICIES, "staff": [*POLICIES["staff"], "release"], "spare": ["read", "retry"]}
    write_config(path, policies=policies)
    added = ops.config(path)
    assert sorted(lines_of(added)) == sorted([f"{STAFF_KEY}:release", "messaging:release"]), "the channel names the profile too, so it widens too"
    assert not any(w["group"] == "retry" for w in added["widening"]), "the profile `spare` is assigned to nobody"
    assert ops.accept_config(path, added["sha256"], widen=added["widening_sha256"])["accepted"]
    # the file accepted by hand-edited hash only never widens: set-mode --accept refuses a file that is not the accepted one
    write_config(path, policies={**policies, "staff": [*policies["staff"], "retry"]})
    assert f"{STAFF_KEY}:retry" in lines_of(ops.config(path))
    assert ops.config(path)["accepted"] is False


def test_a_widening_confirms_with_the_hash_of_the_list_not_of_the_file_and_the_list_is_deterministic(tree):  # noqa: F811
    path = str(tree["project"])
    write_config(path, policies=POLICIES, channels={"messaging": "staff"}, messaging={"senders": SENDERS})
    one, two = ops.config(path), ops.config(path)
    assert one["widening"] == two["widening"] and one["widening_sha256"] == two["widening_sha256"] and one["widening_sha256"] != one["sha256"]
    text = "".join(f"{w['place']}:{w['group']}\n" for w in one["widening"])
    assert one["widening_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert one["widening"][0]["channel"] == "messaging" and any(w["place"] == OWNER_KEY for w in one["widening"])
    with pytest.raises(ops.OpsError):
        ops.accept_config(path, one["sha256"], widen=one["sha256"])


# --- the actor: in the store, and in no file of the project ---------------------------------------------------------------


def seed(path, sender_groups):
    accept(path, policies=POLICIES, channels={"messaging": "staff"}, messaging={"senders": SENDERS})


def test_the_actor_is_in_the_store_with_the_sender_and_the_profile_and_absent_from_the_state_file_and_the_project(world):  # noqa: F811
    path = world["path"]
    task, item = write_opened(world)
    seed(path, None)
    with pytest.raises(ops.OpsError) as staff:     # staff's profile grants no write: refused at the operations layer, for THAT sender, nothing is written
        ops.approve(path, item["id"], item["payload_sha256"], channel="messaging", sender=STAFF_KEY)
    assert "is not in the terminal" in str(staff.value) or "approved in the terminal" in str(staff.value)
    assert writes(world) == [] and ops.pending(path, item["id"])["status"] == "open"
    with pytest.raises(ops.OpsError):               # and with no sender at all the channel's groups answer: the default is staff's, no grant
        ops.approve(path, item["id"], item["payload_sha256"], channel="messaging")
    done = ops.approve(path, item["id"], item["payload_sha256"], channel="messaging", sender=OWNER_KEY)
    assert done["task_state"] == "done" and len(writes(world)) == 1
    ctx = ops_core.context(path)
    row = ctx["store"].approval_get(ctx["conn"], done["approval_id"])
    decision = ctx["store"].pending_get(ctx["conn"], item["id"])
    assert row["actor"] == decision["actor"] == f"messaging:telegram:owner:{OWNER}"
    assert row["approved_by"] == "user" and decision["resolved_by"] == "user", "the kind of actor it always was"
    # the project's versioned files get the channel and the profile only
    state = (Path(path) / "docs" / "workbench" / "state.md").read_text()
    assert "approved on telegram, profile owner" in state and OWNER not in state and STAFF not in state
    for current, _folders, files in os.walk(path):
        for name in files:
            if ".workbench-local" in current or name.endswith((".db", ".sqlite")):
                continue
            blob = (Path(current) / name).read_bytes()
            assert OWNER.encode() not in blob or name == "runtime.json", (current, name)      # the only file that names a sender is the configuration
    # what a shell reads shows who acted, never the id
    shown = ops.pending(path, item["id"])
    assert "actor" not in shown and shown["acted_by"] == "owner on telegram" and OWNER not in json.dumps(shown)
    assert ops_actor.public(row["actor"]) == "owner on telegram" and ops_actor.public(None) is None and ops_actor.public("page") == "page"


def test_the_terminal_the_page_and_the_mcp_mode_record_their_own_name_and_a_release_shows_by_whom_in_progress(tree):  # noqa: F811
    path, plan_id, digest, accept_id, effect = decisions(tree)
    ops.approve(path, plan_id, digest, channel="page")
    ops.approve(path, accept_id, channel="terminal")
    ctx = ops_core.context(path)
    assert ctx["store"].pending_get(ctx["conn"], plan_id)["actor"] == "page" and ctx["store"].pending_get(ctx["conn"], accept_id)["actor"] == "terminal"
    assert ops.pending(path, plan_id)["acted_by"] == "page"
    accept(path, policies=POLICIES, channels={"messaging": "staff"}, messaging={"senders": SENDERS})
    question = ops.run_next(path)                     # the stand-in skill asks before it writes
    assert ctx["store"].pending_get(ctx["conn"], question["pending_id"])["kind"] == "question"
    ops.answer(path, question["pending_id"], "The harbour market first.", channel="messaging", sender=STAFF_KEY)
    assert ctx["store"].pending_get(ctx["conn"], question["pending_id"])["actor"] == f"messaging:telegram:staff:{STAFF}"
    review = ops.run_next(path)
    assert ctx["store"].pending_get(ctx["conn"], review["pending_id"])["kind"] == "review"
    ops.release(path, review["pending_id"], channel="messaging", sender=OWNER_KEY)
    assert ctx["store"].pending_get(ctx["conn"], review["pending_id"])["actor"] == f"messaging:telegram:owner:{OWNER}"
    found = ops.progress(path)
    assert "released by owner on telegram" in found["text"] and OWNER not in json.dumps(found) and STAFF not in json.dumps(found)
    asked_task = ctx["store"].pending_get(ctx["conn"], question["pending_id"])["task_id"]
    assert ops.task(path, asked_task)["pending"][0]["acted_by"] == "staff on telegram" and "actor" not in ops.task(path, asked_task)["pending"][0]


def test_a_resolution_of_every_kind_records_the_actor_a_reject_an_answer_a_release_and_a_plan(tree):  # noqa: F811
    path, plan_id, digest, accept_id, effect = decisions(tree)
    accept(path, policies=POLICIES, channels={"messaging": "staff"}, messaging={"senders": SENDERS})
    ctx = ops_core.context(path)
    ops.reject(path, accept_id, channel="messaging", sender=OWNER_KEY)
    assert ctx["store"].pending_get(ctx["conn"], accept_id)["actor"] == f"messaging:telegram:owner:{OWNER}"
    with pytest.raises(ops.OpsError) as refused:                  # staff's profile lacks reject-cancel: the layer refuses for that sender
        ops.reject(path, plan_id, channel="messaging", sender=STAFF_KEY)
    assert "is not enabled for this channel" in str(refused.value) and ops.pending(path, plan_id)["status"] == "open"
    with pytest.raises(ops.OpsError) as refused:
        ops.approve(path, plan_id, digest, channel="messaging", sender=STAFF_KEY)
    assert "is not enabled for this channel" in str(refused.value) and ops.pending(path, plan_id)["status"] == "open"
    ops.approve(path, plan_id, digest, channel="messaging", sender=OWNER_KEY)
    assert ctx["store"].pending_get(ctx["conn"], plan_id)["actor"] == f"messaging:telegram:owner:{OWNER}"
    assert ops.pending(path, plan_id)["acted_by"] == "owner on telegram"


def test_a_sender_without_the_group_is_refused_for_release_retry_cancel_and_answer_by_the_layer_itself(tree):  # noqa: F811
    path, plan_id, digest, accept_id, effect = decisions(tree)
    accept(path, policies=POLICIES, channels={"messaging": "staff"}, messaging={"senders": SENDERS})
    for call in (lambda: ops.release(path, plan_id, channel="messaging", sender=STAFF_KEY),
                 lambda: ops.retry(path, 1, channel="messaging", sender=STAFF_KEY),
                 lambda: ops.cancel(path, 1, channel="messaging", sender=STAFF_KEY),
                 lambda: ops.stop_task(path, 1, channel="messaging", sender=STAFF_KEY)):
        with pytest.raises(ops.OpsError) as refused:
            call()
        assert "is not enabled for this channel" in str(refused.value)
    # staff may answer (their profile lists it); the owner may not stop a task (no `brakes`), the page's brakes are another channel's
    with pytest.raises(ops.OpsError) as refused:
        ops.stop_task(path, 1, channel="messaging", sender=OWNER_KEY)
    assert "is not enabled for this channel" in str(refused.value)


# --- what a limited reader sees; the brakes of the page ---------------------------------------------------------------------


def test_read_limited_hides_the_spend_the_agents_the_connections_and_the_configuration_and_read_shows_them():
    limited, full = {"messaging": ["read-limited"]}, {"messaging": ["read"]}
    for name in ("costs", "agents", "connections", "config", "task", "progress"):
        assert not operations.permitted(name, "messaging", limited), name
    for name in ("status", "pending", "skills", "artifacts", "routines", "instructions"):
        assert operations.permitted(name, "messaging", limited), name
    for name in ("costs", "agents", "task", "progress", "status", "pending"):
        assert operations.permitted(name, "messaging", full), name
    assert "read-limited" not in operations.GROUPS["read"]["operations"] and set(operations.GROUPS["read-limited"]["operations"]) < set(operations.GROUPS["read"]["operations"])
    assert not set(operations.GROUPS["read-limited"]["operations"]) & {"costs", "agents", "connections", "config", "task", "progress"}
    # per sender: the owner reads the spend, staff does not, on one platform
    policies, messaging, channels = loaded(POLICIES, {"messaging": "staff"}, {"senders": SENDERS})
    assert operations.permitted("costs", "messaging", channels, None, OWNER_KEY) and not operations.permitted("costs", "messaging", channels, None, STAFF_KEY)
    assert operations.permitted("pending", "messaging", channels, None, STAFF_KEY) and operations.permitted("agents", "messaging", channels, None, OWNER_KEY)
    assert "read-limited" in operations.permissions("messaging", limited) or "status" in operations.permissions("messaging", limited)
    assert "costs" not in operations.permissions("messaging", limited) and "costs" in operations.permissions("messaging", full)


def test_a_typed_costs_command_is_refused_to_the_limited_reader_and_answered_to_the_owner(tree):  # noqa: F811
    path = str(tree["project"])
    accept(path, policies=POLICIES, channels={"messaging": "staff"}, messaging={"senders": SENDERS})
    refused = ops.say(path, "/progress", channel="messaging", sender=STAFF_KEY)["reply"]      # progress carries a run's cost
    assert "is not enabled for this channel" in refused
    allowed = ops.say(path, "/progress", channel="messaging", sender=OWNER_KEY)["reply"]
    assert "is not enabled" not in allowed and "cost known" in allowed
    assert "is not enabled" not in ops.say(path, "/status", channel="messaging", sender=STAFF_KEY)["reply"]
    # status shows no spend either: nothing of a run's cost is in it
    body = json.dumps({k: v for k, v in ops.status(path).items() if k != "config"}).lower()      # the config entry holds the test's path
    assert "cost" not in body and "usd" not in body


def test_the_brakes_of_the_page_are_unchanged_by_profiles_and_a_page_profile_works(tree):  # noqa: F811
    for page in (["read"], None):
        policy = {"page": page} if page else {}
        for brake in operations.BRAKES:
            assert operations.permitted(brake, "page", policy) is ("page" in operations.by_name(brake)["channels"]), brake
    policies, messaging, channels = loaded({"viewer": ["read"], "owner": ["read", "approve-plans"]}, {"page": "viewer"}, None)
    assert channels["page"] == ["read"] and operations.permitted("cancel", "page", channels) and operations.permitted("set-mode", "page", channels)
    assert not operations.permitted("approve", "page", channels, "plan") and operations.policy_allows("approve", "page", channels, "plan") is False
    assert operations.permitted("stop-task", "page", channels) and operations.permitted("routine-pause", "page", channels)
    assert operations.permitted("approve", "page", loaded({"owner": ["read", "approve-plans"]}, {"page": "owner"}, None)[2], "plan")


# --- nothing a sender sends can name a profile ---------------------------------------------------------------------------------


def test_nothing_a_sender_sends_names_a_profile_the_profile_is_read_from_the_accepted_configuration_by_the_senders_id(tree):  # noqa: F811
    path, plan_id, digest, accept_id, effect = decisions(tree)
    accept(path, policies=POLICIES, channels={"messaging": "staff"}, messaging={"senders": SENDERS})
    # no operation takes a profile or a policy as an argument, from any channel
    for row in operations.OPERATIONS:
        names = {a["name"] for a in row["args"]}
        assert not names & {"profile", "profiles", "groups", "actor", "sender"}, row["name"]        # a shell passes no sender or profile: the bridge and the layer do
        assert "policy" not in names or row["name"] in ("approve-policy", "standing", "execute-under-policy"), row["name"]      # a standing approval's file, nothing else
        params = set(inspect.signature(getattr(ops, row["call"])).parameters)
        assert not params & {"profile", "profiles", "groups"}, row["name"]
    # a sender key that carries a profile name is only a key nobody is listed under: the channel's groups answer
    for forged in (f"telegram:{STAFF}:owner", f"telegram:{OWNER}:staff", "owner", "telegram:", ":", "", f"telegram:{OWNER} ", "telegram:owner"):
        with pytest.raises(ops.OpsError) as refused:
            ops.approve(path, plan_id, digest, channel="messaging", sender=forged)
        assert "is not enabled for this channel" in str(refused.value), forged
    assert ops.pending(path, plan_id)["status"] == "open"
    # the text of a line is not read as a profile: a command with the profile's name is a command that is checked for the sender
    reply = ops.say(path, f"/approve {plan_id} {digest} profile owner", channel="messaging", sender=STAFF_KEY)["reply"]
    assert ops.pending(path, plan_id)["status"] == "open" and reply
    ctx = ops_core.context(path)
    assert ctx["store"].pending_get(ctx["conn"], plan_id)["actor"] is None


def test_the_labels_of_an_actor_are_built_from_the_loaded_configuration_and_parse_back(tree):  # noqa: F811
    path = str(tree["project"])
    accept(path, policies=POLICIES, channels={"messaging": "staff"}, messaging={"senders": {"telegram": [{"id": OWNER, "policy": "owner"}, STAFF]}})
    cfg = project_config.load(path)
    assert ops_actor.label(cfg, "messaging", OWNER_KEY) == f"messaging:telegram:owner:{OWNER}"
    assert ops_actor.label(cfg, "messaging", STAFF_KEY) == f"messaging:telegram:staff:{STAFF}", "a plain entry gets the profile the channel names"
    assert ops_actor.label(cfg, "page") == "page" and ops_actor.label(cfg, "terminal") == "terminal" and ops_actor.label(cfg, None) is None
    assert ops_actor.label(cfg, "messaging") == "messaging" and ops_actor.label(cfg, "messaging", "nonsense") == "messaging"
    assert ops_actor.profile_of(cfg, OWNER_KEY) == "owner" and ops_actor.profile_of(cfg, "telegram:55119000000077") == "staff"
    plain = project_config.load(path)
    plain["channel_profiles"] = {}
    assert ops_actor.profile_of(plain, "telegram:55119000000077") == "default"
    assert ops_actor.split(OWNER_KEY) == ("telegram", OWNER) and ops_actor.split("a:b:c") == ("a", "b:c") and ops_actor.split("x") == ("", "")
    assert operations.actor_text(f"messaging:telegram:owner:{OWNER}") == "owner on telegram" and OWNER not in operations.actor_text(f"messaging:telegram:owner:{OWNER}")
    assert operations.actor_text("messaging:broken") == "messaging" and operations.actor_text("mcp") == "mcp" and operations.actor_text("") is None


def test_a_sender_removed_or_narrowed_loses_the_act_at_once_the_layer_reads_the_configuration_of_that_call(tree):  # noqa: F811
    path, plan_id, digest, accept_id, effect = decisions(tree)
    accept(path, policies=POLICIES, channels={"messaging": "staff"}, messaging={"senders": SENDERS})
    other, other_digest = plan_id, digest
    # narrowed: the owner's profile loses approve-plans (a narrowing needs no hash)
    accept(path, policies={**POLICIES, "owner": ["read", "talk"]})
    with pytest.raises(ops.OpsError) as refused:
        ops.approve(path, other, other_digest, channel="messaging", sender=OWNER_KEY)
    assert "is not enabled for this channel" in str(refused.value) and ops.pending(path, other)["status"] == "open"
    # an edited file that is not accepted refuses everything, whoever asks
    write_config(path, policies=POLICIES)
    with pytest.raises(ops.OpsError):
        ops.approve(path, other, other_digest, channel="messaging", sender=OWNER_KEY)
    write_config(path, policies={**POLICIES, "owner": ["read", "talk"]})        # the accepted bytes again
    assert ops.pending(path, other)["status"] == "open"


# --- the board, the project, and the bounds of the record ------------------------------------------------------------------------


def test_a_cancel_from_a_messaging_app_names_the_profile_and_neither_the_board_nor_the_project_holds_the_senders_id(board_tree):
    project = str(board_tree["project"])
    ids = board_planned(board_tree)
    accept(project, policies={**POLICIES, "owner": [*POLICIES["owner"], "brakes"]}, channels={"messaging": "staff"}, messaging={"senders": SENDERS})
    ops.sync(project)
    done = ops.cancel(project, ids["request"], channel="messaging", sender=OWNER_KEY)
    assert done["request"] == ids["request"] and ids["market"] in done["cancelled"]
    ctx = ops_core.context(project)
    assert ctx["store"].task_get(ctx["conn"], ids["request"])["stop_requested_by"] == "user from messaging, profile owner"
    with pytest.raises(ops.OpsError) as refused:                  # the employee has no brakes: the layer itself refuses them
        ops.cancel(project, ids["request"], channel="messaging", sender=STAFF_KEY)
    assert "is not enabled for this channel" in str(refused.value)
    ops.sync(project)
    seen = 0
    for home in (project, str(board_tree["board"])):
        for current, _folders, files in os.walk(home):
            for name in files:
                if ".workbench-local" in current or name == "runtime.json":
                    continue
                seen += 1
                blob = (Path(current) / name).read_bytes()
                assert OWNER.encode() not in blob and STAFF.encode() not in blob, (current, name)
    assert seen > 2, "the board and the project were really walked"


def test_the_record_of_what_a_file_gives_fits_a_cursor_for_as_many_senders_as_a_file_may_list_and_holds_no_sender():
    senders = [{"id": f"{n:064d}", "policy": "owner" if n % 2 else "staff"} for n in range(project_config.SENDERS_MAX)]
    policies, messaging, channels = loaded(POLICIES, {"messaging": "staff", "page": ["read"], "mcp": ["read"]}, {"senders": {"telegram": senders}})
    text = policy_widening.dump(policy_widening.snapshot({"channels": channels, "messaging": messaging}))
    assert len(text.encode()) < 4 * 1024, "a cursor holds 4 KiB"
    assert not any(s["id"] in text for s in senders) and "telegram" not in text, "the record names no sender: places are one-way ids"
    back = policy_widening.parse(text)
    assert len(back["sender_ids"]) == project_config.SENDERS_MAX and back["senders"] == {}
    with pytest.raises(project_config.ConfigError, match="more than 100 senders in all"):
        project_config._messaging({"senders": {"telegram": [f"{n}" for n in range(60)], "whatsapp": [f"{n}" for n in range(41)]}})
    assert policy_widening.place_id(OWNER_KEY) == policy_widening.place_id(OWNER_KEY) != policy_widening.place_id(STAFF_KEY)
    assert len(policy_widening.place_id(OWNER_KEY)) == 12
    # a sender in the file is compared with the record by that id, and a sender moved to a wider profile still shows
    old = policy_widening.parse(policy_widening.dump({"channels": {}, "senders": {OWNER_KEY: ["read-limited"]}}))
    new = {"channels": {}, "senders": {OWNER_KEY: ["read"]}}
    assert [(w["place"], w["group"]) for w in policy_widening.widening(old, new)] == [(OWNER_KEY, "read")], "read holds read-limited: one line"


def test_a_group_that_holds_another_is_one_line_and_the_pairs_are_the_tables():
    assert set(operations.IMPLIED["read"]) == {"read-limited"} and set(operations.GROUPS["read-limited"]["operations"]) < set(operations.GROUPS["read"]["operations"])
    assert set(operations.IMPLIED["approve-effects"]) == {g for g in operations.GROUPS if g.startswith("approve-effect-")}
    old = {"channels": {"page": ["read"]}, "senders": {}}
    assert [w["group"] for w in policy_widening.widening(old, {"channels": {"page": ["read", "approve-effects"]}, "senders": {}})] == ["approve-effects"]
    held = {"channels": {"page": ["read", "approve-effects"]}, "senders": {}}
    assert policy_widening.widening(held, {"channels": {"page": ["read", "approve-effect-write"]}, "senders": {}}) == []
