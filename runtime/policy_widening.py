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
  * a new sender (an id the earlier file did not list), with a profile or without: compared with nothing, so that an id added to an edited file
    gives nobody a power unseen and the person widens by choice;
  * a channel's entry removed, when the channel then holds more than it did (the page's whole ceiling).

What the earlier file effectively had is a record of the store, written when a configuration is accepted (the cursor `config:effective`, a JSON
snapshot; outside the repository; a sender is in it only as a short hash of its key, which hides nothing from someone who can guess a phone number). A project accepted before this record existed has only the grants of POL-1 (the cursor
`config:grants`) or nothing, and cannot say what its accepted file gave: the baseline is then "unknown", read as "only those grants were confirmed", so
every group of every channel (an absent entry is its default or its ceiling) and of every sender is listed by `config` and confirmed once with
`accept-config --widen`, so an edit made after that old acceptance cannot widen anything unseen. Only `accept-config` writes the record (and a
mode change, when one exists already): nothing else ends the unknown state. A project that never accepted a file
has the defaults. The hash proves no reading: whoever can run accept-config can compute it. It binds
exactly the list that was shown, and nobody types a phone number.

  snapshot(cfg)              the record of a loaded configuration: {"channels": {channel: [groups] or None}, "senders": {key: [groups] or None}}
  dump(snapshot), parse(text)   the cursor's text, and the snapshot it holds (None when the text is not one)
  baseline(effective, grants, accepted_before)   the snapshot the next acceptance compares with, from the two cursors' texts
  widening(old, new)         [{"place", "channel", "group", "means"}], channels in the order of ORDER, then senders by key
  widening_sha256(list)      the sha256 of the list written one `<place>:<group>` per line, a newline after each; None for an empty list

The accounts the platform may write to (package FND) are a widening too, of the same kind and with the same hash: a new account, a changed address, a new
calendar, folder or mail folder name, a changed id behind a name already there, and `move_removes_inbox` turned on. Removals and narrowing need no ceremony. The
record of what the accepted file named is its own cursor (`config:accounts`, outside the repository), one short KEYED digest per item (the digests of the senders' record are keyed the same way, `digest_of` with the project's key `config:digest-key`: a name or an id written into the file cannot be chosen to collide with a held digest), since a target's name and id
would not fit with the senders in the 4 KiB of one cursor; an absent record is "nothing was accepted", so the first file that names an account lists all of it.

  account_items(cfg)              [{"place": "accounts", "channel": "accounts", "group", "means", "digest"}] of the accounts a configuration names, in order
  dump_accounts(cfg), parse_accounts(text)   the cursor's text, and the set of digests it holds (None when the text is not one)
  account_widening(old_text, cfg) the items of `cfg` that the record does not hold, without the digest; a `move_removes_inbox` only for an account the record held

The fallback companies (S41-10, the group `interpret-fallback`) are a third record of the same kind: the person's consent to the group is tied to the companies in force when they accepted, kept in the cursor
`config:fallbacks` as the keyed digests of the sorted `route:route_sha256` of `interpreter_enable.fallback_routes()`. The group is listed again, with each company named, for every place that holds it
whenever the set in force is not a subset of the accepted one, and it is not accepted at all while no fallback is in force.

  dump_fallbacks(routes, secret), fallbacks_covered(text, routes, secret)   the cursor's text, and whether it holds every route of `routes` (the set in force is a subset of the accepted one)
  fallback_widening(old_text, new, secret, listed, routes)   the lines of `interpret-fallback` to show again, for the places of `new` that hold the group and are not in `listed`
  fallback_refusal(listed, routes)   the sentence that refuses the group while no fallback is in force, or None

No module here calls the store or a provider. Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import operations  # noqa: E402

ORDER = ("messaging", "mcp", "page")   # the order of the widening list: the channel that reaches a person's phone first, then the MCP mode, then the page
EFFECTIVE = "config:effective"   # the store's cursor that holds the snapshot of the file the person accepted last
KEY = "config:digest-key"       # the store's cursor that holds the project's secret for the digests of the two records (random, made at the first acceptance, never in a file)
PLACE = 12                      # hexadecimal characters of a sender's place_id
PENDING_SECRET = "pending"      # what a read uses while no key exists yet: no digest of an older record can match it, so such a record lists everything once
ACCOUNTS = "config:accounts"     # the store's cursor that holds the digests of the account targets the file accepted last named (package FND)
FALLBACKS = "config:fallbacks"   # S41-10: the store's cursor that holds the keyed digests of the fallback routes the person was shown (and accepted) when they last accepted a file
LEGACY = "config:grants"         # POL-1's cursor: the grants of that file, as a JSON list of "<channel>:<group>" (read when EFFECTIVE is absent)
# The masks of the record. Versions 2 (no key) and 3 (keyed) wrote each mask as hexadecimal digits (4 bits a digit); S41-10 added the 49th group, which would have been one more digit on each
# of 100 senders (3,969 bytes of the 4,096 a cursor holds), so versions 4 (no key) and 5 (keyed) write a digit of 6 bits (the record's own `groups` list says which bit is which group, as before).
# A record of version 2 or 3 is still read as it was written; every acceptance writes version 4 or 5, and code that reads only 2 and 3 finds no record and lists everything once (the safe side).
DIGITS64 = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_"


def line_of(place: str, group: str) -> str:
    return f"{place}:{group}"


def means(channel: str, group: str) -> str:
    """What the person gives away by this group at a place of this channel: operations.GRANT_TEXT for a grant, else operations.GROUP_TEXT."""
    text = operations.GRANT_TEXT.get(line_of(channel, group)) or operations.GROUP_TEXT.get(group, group)
    if group == "interpret":      # the person sees what the model service keeps of a line before they widen this group (S1): the daily route's own terms
        import interpreter_enable      # at call time: this module stays pure for every other group
        kept = interpreter_enable.retention()
        text = text + (f" Retention of the daily route: {kept}" if kept else " Retention: the route's terms are not readable here.")
    if group == "interpret-fallback":      # S41-10: the person sees WHICH company would receive a line, and what it keeps of it, before they widen this group: each fallback route the newest entry names
        import interpreter_enable
        shown = [f"{r['route']} (model {r['model']}, served by {r['pin']}): {r['retention']}" for r in interpreter_enable.fallback_routes()]
        text = text + (" Fallback route" + ("s" if len(shown) > 1 else "") + " in force, each a company that would receive a plain line when the usual service is out: " + " | ".join(shown) if shown
                       else " No fallback route is in force in this checkout, so this group cannot be accepted until the maintainer's dated entry names one.")
    return text


def digest_of(text: str, size: int, secret: str = "") -> str:
    """The first `size` hexadecimal characters of the digest of a text, the ONE helper of both records (senders and accounts). With a `secret` (the project's
    key, KEY) it is the HMAC-SHA256 of the text, so that a name or an id written into the file cannot be CHOSEN to collide with a digest the record holds:
    whoever edits runtime.json does not hold the key, which is in the store outside the project. Without one (the tests, and nothing else) it is the plain
    sha256. A short digest stays short because the collision a person could search for needs the key."""
    if secret:
        return hmac.new(secret.encode("utf-8"), text.encode("utf-8"), hashlib.sha256).hexdigest()[:size]
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:size]


def place_id(key: str, secret: str = "") -> str:
    """The short name under which a sender is recorded: the first 12 hexadecimal characters of the digest of its key (digest_of; keyed in the runtime). It
    keeps the record of the store from carrying a readable phone number or account id, and fits the 4 KiB of a cursor for as many senders as project_config
    allows. The keyed digest cannot be searched for a collision by whoever writes the sender's id into the file; it hides a number from whoever reads the
    store only as far as the key is not read with it (the store is outside the project's repository)."""
    return digest_of(key, PLACE, secret)


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


def _digits64(bits: int) -> str:
    """The number written in DIGITS64, the most significant digit first, at least one digit."""
    out = ""
    while True:
        out = DIGITS64[bits & 63] + out
        bits >>= 6
        if not bits:
            return out


def dump(snap: dict, secret: str = "") -> str:
    """The cursor's text: the groups in the order of operations.GROUPS now, and each place as a bit mask over that list written in base 64 (a sender by place_id). Compact
    on purpose: a cursor holds 4 KiB. Version 4 (no key) or 5 (keyed); `parse` also reads the hexadecimal versions 2 and 3."""
    names = list(operations.GROUPS)
    mask = lambda groups: None if groups is None else _digits64(sum(1 << names.index(g) for g in groups if g in names))   # noqa: E731
    senders = {place_id(k, secret): mask(v) for k, v in snap["senders"].items()}
    senders.update({k: mask(v) for k, v in (snap.get("sender_ids") or {}).items()})
    return json.dumps({"v": 5 if secret else 4, "groups": names, "channels": {c: mask(v) for c, v in snap["channels"].items()}, "senders": senders},
                      sort_keys=True, separators=(",", ":"))


def parse(text):
    """The snapshot a cursor holds, or None when there is none or the text is not one this module wrote (the caller then falls back). The senders
    come back under "sender_ids", keyed by place_id: the record holds no sender."""
    try:
        found = json.loads(text) if text else None
    except ValueError:
        return None
    if not isinstance(found, dict) or found.get("v") not in (2, 3, 4, 5) or not isinstance(found.get("groups"), list):
        return None
    dense = found["v"] >= 4
    names, channels, senders = found["groups"], found.get("channels"), found.get("senders")
    if not isinstance(channels, dict) or not isinstance(senders, dict) or not all(isinstance(n, str) for n in names):
        return None

    def groups(value):
        if value is None:
            return None
        if not isinstance(value, str) or not value or not all(c in (DIGITS64 if dense else "0123456789abcdef") for c in value):
            raise ValueError
        bits = 0
        for c in value:
            bits = bits * 64 + DIGITS64.index(c) if dense else bits * 16 + int(c, 16)
        return [n for i, n in enumerate(names) if bits >> i & 1 and n in operations.GROUPS]

    try:
        out = {"channels": {c: groups(v) for c, v in channels.items() if c in operations.POLICY_CHANNELS},
               "senders": {}, "sender_ids": {k: groups(v) for k, v in senders.items() if isinstance(k, str)}}
    except ValueError:
        return None
    return out if len(out["channels"]) == len(channels) else None


def _legacy(text) -> dict:
    """The grants POL-1 recorded, {channel: [groups]}. Text that is not that list is nothing."""
    try:
        found = json.loads(text) if text else []
    except ValueError:
        return {}
    held = {}
    for entry in found if isinstance(found, list) else []:
        channel, _, group = entry.partition(":") if isinstance(entry, str) else ("", "", "")
        if group in operations.GRANTS.get(channel, ()):
            held.setdefault(channel, []).append(group)
    return held


def baseline(effective_text, legacy_text, accepted_before: bool = False) -> dict:
    """What the next acceptance compares with: the snapshot of the file accepted last. A project that has never accepted a file has the defaults
    (nothing recorded, nothing accepted). A project that accepted a file before the record existed has no way to say what that file gave (POL-1
    kept its grants alone, or nothing): the baseline is then `unknown`, which widening() reads as "only the grants POL-1 recorded were confirmed",
    so that every group an entry lists beyond them is listed once, and a file edited after that acceptance cannot widen a page or an MCP entry
    unseen. The file stays in force; only the next acceptance asks."""
    found = parse(effective_text)
    if found is not None:
        return found
    if not accepted_before:
        return {"channels": {}, "senders": {}}
    return {"channels": _legacy(legacy_text), "senders": {}, "unknown": True}


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


def widening(old: dict, new: dict, secret: str = "") -> list:
    """The widenings of `new` over `old` (two snapshots): [{"place", "channel", "group", "means"}], deterministic. Every channel is compared with
    itself (an absent entry is what the channel holds with no entry: its default or its ceiling). A sender that `old` listed is compared with the groups
    it had (its profile, else the channel's); a sender it did not list (a person newly allowed to write) is compared with NOTHING: a restrictive default
    the person widens by choice, so adding an id to an edited file gives it nothing unseen. When `old` is unknown (a file accepted before the record
    existed, of which only POL-1's grants were confirmed) every channel is compared with those grants alone and every sender with nothing."""
    out = []
    unknown = bool(old.get("unknown"))
    for channel in ORDER:
        before = concrete(channel, (old["channels"].get(channel) or []) if unknown else old["channels"].get(channel))
        out += _items(channel, channel, concrete(channel, new["channels"].get(channel)) - before)
    old_channel = concrete("messaging", (old["channels"].get("messaging") or []) if unknown else old["channels"].get("messaging"))
    new_channel = concrete("messaging", new["channels"].get("messaging"))
    recorded = dict(old.get("sender_ids") or {})
    recorded.update({place_id(k, secret): v for k, v in old["senders"].items()})
    for key in sorted(new["senders"]):
        mine = new["senders"][key]
        listed_before = place_id(key, secret) in recorded and not unknown
        had = recorded.get(place_id(key, secret))
        if listed_before and mine is None and had is None:
            continue
        if unknown:
            before = set()      # nobody can tell who the old file listed: a sender is compared with nothing, so a new id inherits no grant unseen
        else:
            before = concrete("messaging", had) if had is not None else (old_channel if listed_before else set())
        after = concrete("messaging", mine) if mine is not None else new_channel
        out += _items(key, "messaging", after - before)
    return out


PROVIDER_NAME = {"google": "Google", "microsoft": "Microsoft"}
ACCOUNT_KINDS = (("calendars", "calendar", "the platform may create, change and remove events on the {provider} calendar '{name}'"),
                 ("folders", "folder", "the platform may create files and write new revisions in the {provider} folder '{name}'"),
                 ("mail_folders", "mail-folder", "the platform may move messages into the {provider} mail folder '{name}' (and mark, archive and trash in the mailbox)"))
DIGEST = 10     # hexadecimal characters of one item's digest


def _digest(group: str, secret: str = "") -> str:
    return digest_of(group, DIGEST, secret)


def account_items(cfg: dict, secret: str = "") -> list:
    """The items of the accounts a loaded configuration names (project_config `accounts`), in a fixed order: for each provider the account, its address, its
    calendars (with the DEFAULT one: the first in the file, where an event goes when none is named, so that reordering the file is a gain), folders and mail
    folders by name, and `move_removes_inbox` when it is on. The `group` of an item carries what the hash binds: the provider, the kind, the name AND the id (so a
    changed id behind a name is another item), or the address. `secret` keys the digests (digest_of)."""
    out = []
    for provider in ("google", "microsoft"):
        entry = ((cfg or {}).get("accounts") or {}).get(provider)
        if not isinstance(entry, dict):
            continue
        shown = PROVIDER_NAME[provider]
        inbox = " (moving a message to a mail folder also takes it out of the Inbox, as the file says)" if entry.get("move_removes_inbox") is True else ""
        items = [(f"{provider}:account", f"the platform may write in your {shown} account, within the targets listed with it{inbox}"),
                 (f"{provider}:address={entry['address']}", f"the {shown} account is {entry['address']}")]
        for section, kind, means in ACCOUNT_KINDS:
            for name in sorted(entry.get(section) or {}):
                items.append((f"{provider}:{kind}:{name}={entry[section][name]}", means.format(provider=shown, name=name)))
            if section == "calendars" and entry.get(section):
                first = next(iter(entry[section]))
                items.append((f"{provider}:default-calendar={first}", f"an event with no calendar named goes to the {shown} calendar '{first}' (the first of the file)"))
        if entry.get("move_removes_inbox") is True:
            items.append((f"{provider}:move_removes_inbox", f"moving a message to a mail folder of the {shown} account also takes it out of the Inbox"))
        out += [{"place": "accounts", "channel": "accounts", "group": group, "means": means, "digest": _digest(group, secret)} for group, means in items]
    default = ((cfg or {}).get("accounts") or {}).get("default")
    if default in PROVIDER_NAME:      # NR-5 (Q2): a line in words that names no service goes to this account when both could serve it
        group = f"default-account={default}"
        out.append({"place": "accounts", "channel": "accounts", "group": group, "means": f"a line in words that names no service goes to your {PROVIDER_NAME[default]} account when both could serve it",
                    "digest": _digest(group, secret)})
    return out


def dump_accounts(cfg: dict, secret: str = "") -> str:
    """The cursor's text: the (keyed) digests of the items, sorted, in one string (two providers of 154 items each fit in a cursor)."""
    return json.dumps({"v": 1, "items": "".join(sorted(i["digest"] for i in account_items(cfg, secret)))}, separators=(",", ":"))


def parse_accounts(text):
    """The set of digests a cursor holds, or None when there is none or the text is not one this module wrote."""
    try:
        found = json.loads(text) if text else None
    except ValueError:
        return None
    items = found.get("items") if isinstance(found, dict) and found.get("v") == 1 else None
    if not isinstance(items, str) or len(items) % DIGEST or not all(c in "0123456789abcdef" for c in items):
        return None
    return {items[i:i + DIGEST] for i in range(0, len(items), DIGEST)}


def account_widening(old_text, cfg: dict, secret: str = "") -> list:
    """What `cfg` names of the accounts and the record (`old_text`, the cursor ACCOUNTS) does not hold: the items, in order, without their digest. No record,
    or one that is not readable, holds nothing, so the first file that names an account lists everything it names. `move_removes_inbox` is listed only for
    an account the record held (for a new account it is part of the account)."""
    held = parse_accounts(old_text) or set()
    out = []
    for item in account_items(cfg, secret):
        if item["digest"] in held:
            continue
        if item["group"].endswith(":move_removes_inbox") and _digest(item["group"].split(":")[0] + ":account", secret) not in held:
            continue
        out.append({k: v for k, v in item.items() if k != "digest"})
    return out


FALLBACK_GROUP = "interpret-fallback"


def fallback_digest(route: str, route_sha256: str, secret: str = "") -> str:
    """The keyed digest that stands for one fallback route AND the hash it was decided on (a changed row is another item)."""
    return _digest(f"fallback:{route}:{route_sha256}", secret)


def dump_fallbacks(routes=None, secret: str = "") -> str:
    """The cursor FALLBACKS' text: the keyed digests of the fallback routes in force (`routes`: what interpreter_enable.fallback_routes() returns, which it is asked when None), sorted, in one string."""
    if routes is None:
        import interpreter_enable
        routes = interpreter_enable.fallback_routes()
    return json.dumps({"v": 1, "items": "".join(sorted(fallback_digest(r["route"], r["route_sha256"], secret) for r in routes))}, separators=(",", ":"))


def fallbacks_covered(text, routes, secret: str = "") -> bool:
    """Whether the record (`text`, the cursor FALLBACKS) holds every route of `routes`: the set in force is a subset of the set the person accepted. No record holds nothing."""
    held = parse_accounts(text) or set()      # the same one-string-of-digests form as the record of the accounts
    return all(fallback_digest(r["route"], r["route_sha256"], secret) in held for r in routes)


def fallback_widening(old_text, new: dict, secret: str = "", listed=None, routes=None) -> list:
    """The lines of `interpret-fallback` that the group's own widening does not list but that a person must see again: for every place of the snapshot `new` that holds the group, one line,
    when the fallback routes in force are not all in the record of what was accepted (`old_text`, FALLBACKS). `listed` is the widening already made (a place it lists for the group is not repeated);
    `routes` is what interpreter_enable.fallback_routes() returns, asked when None. With no route in force, or all of them accepted, nothing. The text of each line names every company and its retention (`means`)."""
    if routes is None:
        import interpreter_enable
        routes = interpreter_enable.fallback_routes()
    if not routes or fallbacks_covered(old_text, routes, secret):
        return []
    already = {i["place"] for i in (listed or []) if i["group"] == FALLBACK_GROUP}
    places = []
    if FALLBACK_GROUP in concrete("messaging", new["channels"].get("messaging")):
        places.append("messaging")
    channel = concrete("messaging", new["channels"].get("messaging"))
    for key in sorted(new["senders"]):
        mine = new["senders"][key]
        if FALLBACK_GROUP in (concrete("messaging", mine) if mine is not None else channel):
            places.append(key)
    return [{"place": p, "channel": "messaging", "group": FALLBACK_GROUP, "means": means("messaging", FALLBACK_GROUP)} for p in places if p not in already]


def fallback_refusal(listed, routes=None):
    """The sentence that refuses an acceptance that widens `interpret-fallback` while no fallback route is in force (a person cannot consent to a company that is not named), or None."""
    if not any(i["group"] == FALLBACK_GROUP for i in listed):
        return None
    if routes is None:
        import interpreter_enable
        routes = interpreter_enable.fallback_routes()
    if routes:
        return None
    return ("the group 'interpret-fallback' is not accepted while no fallback route is in force: the newest entry of runtime/interpreter_enable.json names none, so there is no company to consent to; "
            "nothing was accepted. Take the group out of the file, or accept it after the maintainer's dated entry names a fallback route")


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
