#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""What `config` shows of the channel policy (packages POL-1 and POL-2), pure: the grants a file lists, what a configuration widens and the hash
a person types to accept it, and the warnings that are never a refusal.

A channel restriction is a policy: the default is today's restrictive rule, and the person may widen it in the project's configuration.
Narrowing needs no ceremony; a widening needs one step more: accept-config stops, prints the list and takes its hash. What counts as a
widening, and the hash, are runtime/policy_widening.py (a group a place did not effectively have in the file accepted before: a grant of
operations.GRANTS and also a group inside a channel's ceiling; a place is a channel or one listed sender).

  grants(cfg)        the grants the file lists, as [{"channel", "group", "means"}] in the order of operations.GRANTS, then those the profiles of
                     the listed senders hold, each with "sender" (`<platform>:<sender id>`)
  warnings(cfg)      sentences `config` shows beside the grants (never a refusal)
  view(effective, legacy, cfg, accepted_before)   what `config` adds to its answer: {"grants", "widening", "widening_sha256", "warnings"} for the file as it is,
                     accepted or not; the two texts are the store's cursors (policy_widening.EFFECTIVE and LEGACY)

No module here calls the store or a provider: ops_config and ops hand in the text of the cursors. Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import operations  # noqa: E402
import policy_widening  # noqa: E402


def grants(cfg: dict) -> list:
    """The grants the file's policy lists, [{"channel", "group", "means"}] (a sender's also carry "sender"), channels first in the order of operations.GRANTS."""
    channels = cfg.get("channels") or {}
    out = [{"channel": c, "group": g, "means": policy_widening.means(c, g)} for c, g in operations.grants(channels)]
    out += [{"channel": "messaging", "sender": key, "group": g, "means": policy_widening.means("messaging", g)}
            for key, g in operations.sender_grants(channels)]
    return out


def warnings(cfg: dict) -> list:
    """What `config` warns about, never refuses: a messaging effect grant (a channel's or a sender's profile) while the notices carry no text (a card of
    "count" holds nothing the person could approve), so the grant does nothing until `messaging.notices` is "text"; and a profile nobody uses."""
    out = []
    channels = cfg.get("channels") or {}
    effect = [g for c, g in operations.grants(channels) if c == "messaging" and g.startswith("approve-effect-")]
    effect += [g for _, g in operations.sender_grants(channels) if g.startswith("approve-effect-")]
    if effect and ((cfg.get("messaging") or {}).get("notices") == "count"):
        out.append("messaging.notices is 'count': a card then carries none of the text, and an effect is approved only from a card that "
                   f"carries the whole text, so {', '.join(dict.fromkeys(effect))} approves nothing until notices is 'text'")
    used = set((cfg.get("channel_profiles") or {}).values())
    for named in ((cfg.get("messaging") or {}).get("sender_profiles") or {}).values():
        used |= set(named.values())
    unused = [name for name in (cfg.get("policies") or {}) if name not in used]
    if unused:
        out.append(f"the profile {', '.join(unused)} is assigned to no channel and no sender, so it does nothing")
    return out


def view(effective_text, legacy_text, cfg: dict, accepted_before: bool = False, accounts_text=None, secret: str = "") -> dict:
    """What `config` adds to its answer: {"grants", "widening", "widening_sha256", "warnings"} for the file as it is, accepted or not.
    The texts are the cursors of the store (policy_widening.EFFECTIVE and LEGACY; `accounts_text` is ACCOUNTS; `secret` is the project's key of the digests, policy_widening.KEY); `accepted_before` says that a file was accepted at some time."""
    wide = policy_widening.widening(policy_widening.baseline(effective_text, legacy_text, accepted_before), policy_widening.snapshot(cfg), secret)
    wide += policy_widening.account_widening(accounts_text, cfg, secret)      # FND: the accounts the platform may write to are a widening of the same kind
    return {"grants": grants(cfg), "widening": wide, "widening_sha256": policy_widening.widening_sha256(wide), "warnings": warnings(cfg)}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
