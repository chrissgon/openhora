"""The widening list against what a configuration can DO (package POL-2; runtime/policy_widening.py): the repros of the independent review of PR #449
and a differential fuzz. For random pairs of an old and a new `runtime.json` the capability of every place (the page, the MCP mode, messaging, each
listed sender: which operation, for which kind of decision) is computed through operations.permitted, and whatever the new file can do that the old
could not must be covered by a line of the widening list. Three baselines: the record of a file accepted by this version (known), a file accepted before
the record existed (unknown: only POL-1's grants were confirmed), and a project that never accepted a file. A sender the old file did not list is
compared with nothing. Offline, deterministic (fixed seeds), invented ids.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_widening_fuzz.py
"""
from __future__ import annotations

import json
import random

import standin_tree as st

operations = st.load("operations")
project_config = st.load("project_config")
policy_widening = st.load("policy_widening")

KINDS = {"approve": ["plan", "acceptance", "plan:networked"] + ["effect:" + w for w in operations.EFFECT_APPROVAL_WORDS]}
OPS = [(row["name"], kind) for row in operations.OPERATIONS for kind in KINDS.get(row["name"], [None])]
IDS = ["111", "222", "333", "444"]
PLATFORMS = ["telegram", "whatsapp-cloud"]


def load(raw):
    """The three keys through the loader's own functions, as project_config.load puts them together."""
    policies = project_config._policies(raw.get("policies"))
    messaging = project_config._messaging(raw.get("messaging"), policies)
    channels = project_config._channels(raw.get("channels"), policies)
    senders = project_config.sender_policy(messaging, policies)
    if senders:
        channels[operations.SENDERS_KEY] = senders
    return {"policies": policies, "messaging": messaging, "channels": channels}


def capability(channel, cfg, sender=None):
    return {(op, kind) for op, kind in OPS if operations.permitted(op, channel, cfg["channels"], kind, sender)}


def listed(base, new):
    found = {}
    for item in policy_widening.widening(base, policy_widening.snapshot(new)):
        found.setdefault(item["place"], set()).add(item["group"])
    return found


# --- the repros of the review -----------------------------------------------------------------------------------------------


def test_an_old_project_that_removes_its_entries_gains_the_whole_default_or_ceiling_only_with_the_hash():
    unknown = policy_widening.baseline(None, "[]", accepted_before=True)
    new = load({"messaging": {"senders": {"telegram": ["111"]}}})
    lines = policy_widening.widening(unknown, policy_widening.snapshot(new))
    places = {(i["place"], i["group"]) for i in lines}
    assert ("page", "set-mode") in places and ("mcp", "request") in places and ("messaging", "talk") in places and ("telegram:111", "talk") in places
    # the same edit against a record of a file accepted by this version: the entries were narrow, so the same lines
    old = load({"channels": {"mcp": ["read"], "page": ["read"], "messaging": ["read"]}, "messaging": {"senders": {"telegram": ["111"]}}})
    known = policy_widening.parse(policy_widening.dump(policy_widening.snapshot(old)))
    assert {(i["place"], i["group"]) for i in policy_widening.widening(known, policy_widening.snapshot(new))} >= {("page", "set-mode"), ("mcp", "request")}


def test_an_old_project_that_gives_a_sender_a_profile_lists_the_whole_profile_for_that_sender():
    new = load({"policies": {"staff": ["read", "talk", "answer"]}, "channels": {"messaging": ["reject-cancel"]},
                "messaging": {"senders": {"telegram": [{"id": "111", "policy": "staff"}]}}})
    unknown = policy_widening.baseline(None, "[]", accepted_before=True)
    assert listed(unknown, new)["telegram:111"] == {"read", "talk", "answer"}
    old = load({"channels": {"messaging": ["reject-cancel"]}, "messaging": {"senders": {"telegram": ["111"]}}})
    known = policy_widening.parse(policy_widening.dump(policy_widening.snapshot(old)))
    assert listed(known, new)["telegram:111"] == {"read", "talk", "answer"}


def test_a_new_sender_added_in_the_first_edit_after_the_upgrade_inherits_no_grant_unseen():
    base = policy_widening.baseline(None, json.dumps(["messaging:approve-effect-write"]), accepted_before=True)
    new = load({"channels": {"messaging": ["read", "approve-effect-write"]}, "messaging": {"senders": {"telegram": ["111", "999"]}}})
    assert operations.permitted("approve", "messaging", new["channels"], "effect:write", "telegram:999")
    assert listed(base, new)["telegram:999"] == {"read", "approve-effect-write"}, "the new id names the grant as well as the read"


# --- the differential fuzz --------------------------------------------------------------------------------------------------


def valid_groups(channel):
    return [g for g in operations.GROUPS if operations.group_refusal(channel, g) is None]


def random_groups(channel, rng):
    groups = valid_groups(channel)
    out = rng.sample(groups, rng.randint(0, min(6, len(groups))))
    if channel in operations.MUST_READ and "read" not in out:
        out.append("read")
    if "approve-networked-plans" in out and "approve-plans" not in out:
        out.append("approve-plans")
    if "read" in out and "read-limited" in out:
        out.remove("read-limited")
    if "files-trash" in out and "read-files" not in out:
        out.append("read-files")      # the configuration refuses the trash without the right to see names (R2-A), as it refuses send-files without read-files
    return out


def random_raw(rng):
    raw, profiles = {}, {}
    for name in rng.sample(["owner", "staff", "lim"], rng.randint(0, 3)):
        profiles[name] = random_groups("messaging", rng)
    if profiles:
        raw["policies"] = profiles
    channels = {}
    for channel in ("page", "mcp", "messaging"):
        roll = rng.random()
        if roll < 0.4:
            continue
        channels[channel] = rng.choice(list(profiles)) if channel == "messaging" and profiles and roll < 0.6 else random_groups(channel, rng)
    if channels:
        raw["channels"] = channels
    senders = {}
    for platform in PLATFORMS:
        entries = []
        for sender in rng.sample(IDS, rng.randint(0, 3)):
            entries.append({"id": sender, "policy": rng.choice(list(profiles))} if profiles and rng.random() < 0.5 else sender)
        if entries:
            senders[platform] = entries
    if senders:
        raw["messaging"] = {"senders": senders}
    return raw


def pol1_raw(rng):
    """A file as POL-1 knew it: no policies, flat lists, plain ids."""
    raw = random_raw(rng)
    raw.pop("policies", None)
    channels = raw.get("channels") or {}
    for channel in [c for c in channels if isinstance(channels[c], str)]:
        del channels[channel]
    if raw.get("messaging"):
        raw["messaging"]["senders"] = {p: [e if isinstance(e, str) else e["id"] for e in v] for p, v in raw["messaging"]["senders"].items()}
    return raw


def places(cfg):
    out = {"page": ("page", None), "mcp": ("mcp", None), "messaging": ("messaging", None)}
    for platform, ids in cfg["messaging"]["senders"].items():
        for sender in ids:
            key = operations.sender_key(platform, sender)
            out[key] = ("messaging", key)
    return out


def misses(old, new, base, fresh=False):
    """(place, operation, kind) that the new file can do, that the old could not, and that no line of the widening list covers. The oracle is strict
    for a sender the old file did not list (nothing); because nobody can tell who an old file listed, the list may name more, never less."""
    lines = listed(base, new)
    old_places = places(old)
    found = []
    for place, (channel, sender) in places(new).items():
        after = capability(channel, new, sender)
        before = capability(channel, old, old_places[place][1]) if place in old_places and not fresh else set()
        if sender is None and fresh:
            before = capability(channel, load({}), None)
        groups = set(lines.get(place, ()))
        if sender is not None and place in old_places:
            plain_new = sender not in (new["channels"].get(operations.SENDERS_KEY) or {})
            plain_old = sender not in (old["channels"].get(operations.SENDERS_KEY) or {})
            if plain_new and plain_old:
                groups |= lines.get("messaging", set())      # a sender that follows the channel in both files: the channel's line
        for group in list(groups):
            groups.update(operations.IMPLIED.get(group, ()))
        for op, kind in sorted(after - before, key=str):
            as_kind = "plan" if (kind == "plan:networked" and channel in operations.NETWORKED_PLAN_CHANNELS) else kind
            covered = [g for g in groups if op in operations.GROUPS[g]["operations"] and operations._covers(operations.GROUPS[g]["kind"], as_kind)]
            if channel == "page" and op in operations.BRAKES:
                covered = covered or ["brake"]      # the brakes are the page's whatever its policy says
            if not covered:
                found.append((place, op, kind))
    return found


def run(mode, seed, rounds):
    rng = random.Random(seed)
    checked = 0
    for _ in range(rounds):
        a, b = (pol1_raw(rng) if mode == "unknown" else random_raw(rng)), random_raw(rng)
        if rng.random() < 0.3:
            b = json.loads(json.dumps(a))
        try:
            old, new = load(a), load(b)
        except project_config.ConfigError:
            continue
        if mode == "known":
            base = policy_widening.parse(policy_widening.dump(policy_widening.snapshot(old)))
        elif mode == "unknown":
            grants = json.dumps([f"{c}:{g}" for c, g in operations.grants(old["channels"])])
            base = policy_widening.baseline(None, grants, True)
        else:
            base, old = policy_widening.baseline(None, None, False), load({})
        found = misses(old, new, base, fresh=(mode == "fresh"))
        assert found == [], (mode, a, b, found[:5])
        checked += 1
    return checked


def test_nothing_a_new_file_can_do_that_the_old_could_not_is_missing_from_the_widening_list_known_record():
    assert run("known", 11, 500) > 300


def test_nothing_is_missing_when_the_old_file_was_accepted_before_the_record_existed():
    assert run("unknown", 5, 500) > 300


def test_nothing_is_missing_for_a_project_that_never_accepted_a_file():
    assert run("fresh", 7, 500) > 300
