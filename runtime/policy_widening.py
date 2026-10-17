#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""What a configuration WIDENS, and the hash a person types to accept it (packages POL-1 and POL-2), pure.

A channel restriction is a policy: the default is today's restrictive rule, and the person may widen it in the project's configuration.
Narrowing needs no ceremony; a widening needs one step more: `accept-config` stops, prints the list and takes its hash (`--widen`).

The unit is a place and a group. A place is a channel (`page`, `mcp`, `messaging`) or one listed sender (`<platform>:<sender id>`). The
groups a place EFFECTIVELY has come from its entry: a sender's profile, else the channel's entry (a list, or a profile), else what the
channel holds with no entry (messaging: operations.DEFAULT_POLICY; the page and the MCP mode: their whole ceiling). A WIDENING is a group
that a place has in the file being accepted and did not effectively have in the file accepted before, which covers all of these at once:

  * a group added to the entry of a channel: a grant of operations.GRANTS, and also a group inside the channel's ceiling (release, approve-plans,
    reject-cancel, retry, brakes, routine-edit, ...), since the default is the restrictive rule and the person may widen it, knowing what they widen;
  * a group added to a profile that is assigned somewhere (the places that use it have more);
  * a sender moved to a profile whose groups are not a subset of the groups that sender had;
  * a new sender listed with a profile that is not a subset of the channel's groups;
  * a channel's entry removed, when the channel then holds more than it did (the page's whole ceiling).

What the earlier file effectively had is a record of the store, written when a configuration is accepted (the cursor `config:effective`, a JSON
snapshot; outside git, since it names senders). A project accepted before this record existed has only the grants of POL-1 (the cursor
`config:grants`) or nothing: the missing record is read as the defaults plus those grants, so a group it lists beyond them is a widening, confirmed
once with `accept-config --widen` (`config` shows the list). The hash proves no reading: whoever can run accept-config can compute it. It binds
exactly the list that was shown, and nobody types a phone number.

  snapshot(cfg)              the record of a loaded configuration: {"channels": {channel: [groups] or None}, "senders": {key: [groups] or None}}
  dump(snapshot), parse(text)   the cursor's text, and the snapshot it holds (None when the text is not one)
  baseline(effective, grants) the snapshot the next acceptance compares with, from the two cursors' texts
  widening(old, new)         [{"place", "channel", "group", "means"}], channels in the order of ORDER, then senders by key
  widening_sha256(list)      the sha256 of the list written one `<place>:<group>` per line, a newline after each; None for an empty list

No module here calls the store or a provider. Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import operations  # noqa: E402

ORDER = ("messaging", "mcp", "page")   # the order of the widening list: the channel that reaches a person's phone first, then the MCP mode, then the page
EFFECTIVE = "config:effective"   # the store's cursor that holds the snapshot of the file the person accepted last
LEGACY = "config:grants"         # POL-1's cursor: the grants of that file, as a JSON list of "<channel>:<group>" (read when EFFECTIVE is absent)


def line_of(place: str, group: str) -> str:
    return f"{place}:{group}"


def means(channel: str, group: str) -> str:
    """What the person gives away by this group at a place of this channel: operations.GRANT_TEXT for a grant, else operations.GROUP_TEXT."""
    return operations.GRANT_TEXT.get(line_of(channel, group)) or operations.GROUP_TEXT.get(group, group)


def place_id(key: str) -> str:
    """The short, one-way name under which a sender is recorded: the first 12 hexadecimal characters of the sha256 of its key. The record of the
    store holds no phone number or account id, and fits the 4 KiB of a cursor for as many senders as project_config allows."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def snapshot(cfg: dict) -> dict:
    """The record of a loaded configuration: for each channel with an entry its groups (None: no entry), for each listed sender, by its key, the
    groups of its profile (None: the sender has no profile of its own and follows the channel)."""
    channels = cfg.get("channels") or {}
    named = channels.get(operations.SENDERS_KEY) or {}
    out = {"channels": {c: list(channels[c]) if channels.get(c) is not None else None for c in operations.POLICY_CHANNELS if c in channels},
           "senders": {}}
    for platform, ids in ((cfg.get("messaging") or {}).get("senders") or {}).items():
        for sender in ids:
            key = operations.sender_key(platform, sender)
            out["senders"][key] = list(named[key]) if key in named else None
    return out


def dump(snap: dict) -> str:
    """The cursor's text: the groups in the order of operations.GROUPS now, and each place as a bit mask over that list (a sender by place_id). Compact
    on purpose: a cursor holds 4 KiB."""
    names = list(operations.GROUPS)
    mask = lambda groups: None if groups is None else format(sum(1 << names.index(g) for g in groups if g in names), "x")   # noqa: E731
    senders = {place_id(k): mask(v) for k, v in snap["senders"].items()}
    senders.update({k: mask(v) for k, v in (snap.get("sender_ids") or {}).items()})
    return json.dumps({"v": 2, "groups": names, "channels": {c: mask(v) for c, v in snap["channels"].items()}, "senders": senders},
                      sort_keys=True, separators=(",", ":"))


def parse(text):
    """The snapshot a cursor holds, or None when there is none or the text is not one this module wrote (the caller then falls back). The senders
    come back under "sender_ids", keyed by place_id: the record holds no sender."""
    try:
        found = json.loads(text) if text else None
    except ValueError:
        return None
    if not isinstance(found, dict) or found.get("v") != 2 or not isinstance(found.get("groups"), list):
        return None
    names, channels, senders = found["groups"], found.get("channels"), found.get("senders")
    if not isinstance(channels, dict) or not isinstance(senders, dict) or not all(isinstance(n, str) for n in names):
        return None

    def groups(value):
        if value is None:
            return None
        if not isinstance(value, str) or not all(c in "0123456789abcdef" for c in value) or not value:
            raise ValueError
        bits = int(value, 16)
        return [n for i, n in enumerate(names) if bits >> i & 1 and n in operations.GROUPS]

    try:
        out = {"channels": {c: groups(v) for c, v in channels.items() if c in operations.POLICY_CHANNELS},
               "senders": {}, "sender_ids": {k: groups(v) for k, v in senders.items() if isinstance(k, str)}}
    except ValueError:
        return None
    return out if len(out["channels"]) == len(channels) else None


def _legacy(text) -> dict:
    """The snapshot that POL-1's record of grants stands for: each channel with a grant holds its defaults plus those grants. Text that is not that list is nothing."""
    try:
        found = json.loads(text) if text else []
    except ValueError:
        return {"channels": {}, "senders": {}}
    held = {}
    for entry in found if isinstance(found, list) else []:
        channel, _, group = entry.partition(":") if isinstance(entry, str) else ("", "", "")
        if group in operations.GRANTS.get(channel, ()):
            held.setdefault(channel, []).append(group)
    return {"channels": {c: list(operations.default_groups(c)) + gs for c, gs in held.items()}, "senders": {}}


def baseline(effective_text, legacy_text) -> dict:
    """What the next acceptance compares with: the snapshot of the file accepted last; else what POL-1 recorded of its grants; else the defaults."""
    found = parse(effective_text)
    return found if found is not None else _legacy(legacy_text)


def concrete(channel: str, listed) -> set:
    """The groups a place effectively holds: its entry, else what the channel holds with no entry, and the groups those imply
    (operations.IMPLIED: `read` is `read-limited` and more, the umbrella of the effects is each effect's group)."""
    held = set(listed) if listed is not None else set(operations.default_groups(channel))
    for group in list(held):
        held.update(operations.IMPLIED.get(group, ()))
    return held


def _items(place: str, channel: str, groups) -> list:
    """The lines of one place, in the order of operations.GROUPS; a group that another one of the lines implies is not a line of its own."""
    implied = {i for g in groups for i in operations.IMPLIED.get(g, ())}
    return [{"place": place, "channel": channel, "group": g, "means": means(channel, g)} for g in operations.GROUPS if g in groups and g not in implied]


def widening(old: dict, new: dict) -> list:
    """The widenings of `new` over `old` (two snapshots): [{"place", "channel", "group", "means"}], deterministic. A channel is compared with
    itself (an absent entry is what the channel holds with no entry); a listed sender with the groups it had in `old` (its profile, else the
    channel's), or, for a sender `old` did not list, with what the channel had; a sender that follows the channel in both files is the channel's line."""
    out = []
    for channel in ORDER:
        before = concrete(channel, old["channels"].get(channel))
        after = concrete(channel, new["channels"].get(channel))
        out += _items(channel, channel, after - before)
    old_channel = concrete("messaging", old["channels"].get("messaging"))
    new_channel = concrete("messaging", new["channels"].get("messaging"))
    recorded = dict(old.get("sender_ids") or {})
    recorded.update({place_id(k): v for k, v in old["senders"].items()})
    for key in sorted(new["senders"]):
        mine, had = new["senders"][key], recorded.get(place_id(key))
        if mine is None and had is None:
            continue
        before = concrete("messaging", had) if had is not None else old_channel
        after = concrete("messaging", mine) if mine is not None else new_channel
        out += _items(key, "messaging", after - before)
    return out


def widening_sha256(listed):
    """The sha256 of the widening list, one `<place>:<group>` line each with a newline after it; None for an empty list."""
    if not listed:
        return None
    text = "".join(line_of(item["place"], item["group"]) + "\n" for item in listed)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def lines(listed: list) -> str:
    """The widening list as the refusal and the terminal print it: `  <place>:<group>: what it gives away` one per line, the first part being the
    very line the hash is taken of."""
    return "".join(f"\n  {line_of(i['place'], i['group'])}: {i['means']}" for i in listed)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
