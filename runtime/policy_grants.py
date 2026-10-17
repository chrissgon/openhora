#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The grants of the channel policy (package POL-1), pure: what a project's configuration asks to WIDEN, what that gives away in
words, and the hash a person types to accept it.

A channel restriction is a policy: the default is today's restrictive rule, and the person may widen it in the project's
configuration, one grant at a time (operations.GRANTS: a group a channel reaches only when the project's own entry lists it). Narrowing
needs no ceremony; a widening needs one step more: accept-config stops, prints the list and takes its hash. The hash is not a proof of
reading (whoever can run accept-config can compute it) and covers GRANTS alone: a group inside a channel's ceiling is added by listing it. So:

  grants(channels)            the grants the file lists, as [{"channel", "group", "means"}] in the order of operations.GRANTS
  widening(recorded, channels)  those the last accepted file did not list (what accept-config is about to give away)
  widening_sha256(list)       the sha256 of the widening list written one `<channel>:<group>` per line, a newline after each: what
                              `config` shows next to the list and `accept-config --widen` takes. An empty list has no hash (None): nothing to confirm.
  parse(text), dump(pairs)    the cursor `config:grants` of the store, where the accepted file's grants are recorded when it is accepted
  warnings(cfg)               sentences `config` shows beside the grants (never a refusal)

No module here calls the store or a provider: ops_config and ops hand in the text of the cursor. Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import operations  # noqa: E402

CURSOR = "config:grants"   # the store's cursor that holds the grants of the file the person accepted last, as a JSON list of "<channel>:<group>"


def line_of(channel: str, group: str) -> str:
    return f"{channel}:{group}"


def means(channel: str, group: str) -> str:
    """What the person gives away by this grant: operations.GRANT_TEXT, else the group's name (a grant added to GRANTS without its text is a test failure)."""
    return operations.GRANT_TEXT.get(line_of(channel, group), group)


def items(pairs) -> list:
    return [{"channel": c, "group": g, "means": means(c, g)} for c, g in pairs]


def grants(channels) -> list:
    """The grants the file's `channels` lists, [{"channel", "group", "means"}], in the order of operations.GRANTS."""
    return items(operations.grants(channels or {}))


def parse(text) -> list:
    """The grants recorded in the cursor, [(channel, group)]. Nothing recorded, or text that is not the list this module writes, is none:
    every grant of the file is then a widening, which fails closed (the person confirms it)."""
    try:
        found = json.loads(text) if text else []
    except ValueError:
        return []
    if not isinstance(found, list):
        return []
    out = []
    for entry in found:
        channel, _, group = entry.partition(":") if isinstance(entry, str) else ("", "", "")
        if group in operations.GRANTS.get(channel, ()):
            out.append((channel, group))
    return out


def dump(channels) -> str:
    """The cursor's text for the file's grants."""
    return json.dumps([line_of(c, g) for c, g in operations.grants(channels or {})])


def widening(recorded, channels) -> list:
    """The grants of `channels` that `recorded` (parse's answer) does not hold: [{"channel", "group", "means"}]."""
    held = set(recorded)
    return items([(c, g) for c, g in operations.grants(channels or {}) if (c, g) not in held])


def widening_sha256(listed):
    """The sha256 of the widening list, one `<channel>:<group>` line each with a newline after it; None for an empty list."""
    if not listed:
        return None
    text = "".join(line_of(item["channel"], item["group"]) + "\n" for item in listed)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def warnings(cfg: dict) -> list:
    """What `config` warns about, never refuses: a messaging effect grant while the notices carry no text (a card of "count" holds
    nothing the person could approve), so the grant does nothing until `messaging.notices` is "text"."""
    out = []
    effect = [g for c, g in operations.grants(cfg.get("channels") or {}) if c == "messaging" and g.startswith("approve-effect-")]
    if effect and ((cfg.get("messaging") or {}).get("notices") == "count"):
        out.append("messaging.notices is 'count': a card then carries none of the text, and an effect is approved only from a card that "
                   f"carries the whole text, so {', '.join(effect)} approves nothing until notices is 'text'")
    return out


def view(recorded_text, cfg: dict) -> dict:
    """What `config` adds to its answer: {"grants", "widening", "widening_sha256", "warnings"} for the file as it is, accepted or not.
    `recorded_text` is the cursor's text."""
    channels = cfg.get("channels") or {}
    wide = widening(parse(recorded_text), channels)
    return {"grants": grants(channels), "widening": wide, "widening_sha256": widening_sha256(wide), "warnings": warnings(cfg)}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
