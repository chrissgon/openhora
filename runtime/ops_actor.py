#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Who acted (package POL-2), in the operations layer: the sender of a messaging app, the profile the accepted configuration gives that sender, and the
record of both with a decision.

A messaging app tells the layer who acted by `sender`, the key `<platform>:<sender id>` that the bridge built from the update the PROVIDER
authenticated (operations.sender_key). Nothing else is taken from the caller: the profile is read here, from the configuration the layer loaded for
this very call (so a sender removed or narrowed loses the act at once), and nothing a sender writes can name one. The terminal, the page and the MCP
mode have no person identity; they record their own name.

  label(cfg, channel, sender)    the text the store keeps in `actor`: `terminal`, `page`, `mcp`, `chat`, or `messaging:<platform>:<profile>:<sender id>`
                                 (the id last: it is the only part that may hold a colon); None for a call that named no channel
  public(label)                  the same without the sender id, for what a person or a versioned file reads: `<profile> on <platform>`, or the channel
  profile_of(cfg, sender)        the profile name of a sender (project_config.DEFAULT_PROFILE for a sender with none of their own and no profile for the channel)
  require(channel, sender)       a call from a messaging app names its sender (code 1 otherwise: the policy is asked for a person, never for the channel alone)
  guard(ctx, op, channel, sender, kind)   refuse, as the bridge does, an act of a messaging sender whose profile does not cover it (code 1)
  carried_by(channel)            a context in which a command typed into a line is done as `chat` but recorded as the channel that carried the line
  shown(item)                    a pending decision as a shell reads it: the actor replaced by its public form (the id stays in the store)

It is a sibling of runtime/ops.py. The names every module of the layer shares are read as `core.<name>`. Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import contextlib
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import operations  # noqa: E402
import ops_core as core  # noqa: E402

_CARRIER = threading.local()
DEFAULT_PROFILE = "default"   # project_config.DEFAULT_PROFILE (that module is not imported here: it needs nothing else of it)
MESSAGING = "messaging"


def split(sender) -> tuple:
    """(platform, sender id) of a sender key; ("", "") for anything that is not one."""
    platform, colon, rest = sender.partition(":") if isinstance(sender, str) else ("", "", "")
    return (platform, rest) if colon and platform and rest else ("", "")


def profile_of(cfg: dict, sender) -> str:
    """The profile name of a sender, from the configuration loaded for this call: the sender's own profile, else the profile the messaging channel
    names, else DEFAULT_PROFILE."""
    platform, ident = split(sender)
    named = ((cfg.get("messaging") or {}).get("sender_profiles") or {}).get(platform) or {}
    return named.get(ident) or (cfg.get("channel_profiles") or {}).get(MESSAGING) or DEFAULT_PROFILE


def label(cfg: dict, channel, sender=None):
    """The text the store keeps in `actor` for a call (see the module's text); None when no channel is named."""
    if channel == MESSAGING and sender:
        platform, ident = split(sender)
        if platform:
            return f"{MESSAGING}:{platform}:{profile_of(cfg, sender)}:{ident}"
    if channel == "chat" and getattr(_CARRIER, "channel", None):
        return _CARRIER.channel        # a command typed on the page or through the MCP mode is done as `chat` (the operation's own rules) and was the page's or the client's
    return channel or None


@contextlib.contextmanager
def carried_by(channel):
    """While it lasts, an act done as `chat` is recorded as `channel` (the page or the MCP mode that carried the typed line)."""
    before = getattr(_CARRIER, "channel", None)
    _CARRIER.channel = channel if channel in ("page", "mcp", "terminal") else None
    try:
        yield
    finally:
        _CARRIER.channel = before


def require(channel, sender) -> None:
    """A call from a messaging app names the sender who acted: without one the policy would be asked for the channel alone, and a sender with a
    narrower profile than the channel's would get the channel's wider set. The bridge always names it; a call that does not is refused."""
    if channel == MESSAGING and not (isinstance(sender, str) and split(sender)[0]):
        raise core.OpsError("a call from a messaging app names the sender who acts (<platform>:<id>); nothing was done", 1)


def public(actor) -> str | None:
    """An actor as it is shown: `<profile> on <platform>` for a messaging sender (never the id), else the channel's name (operations.actor_text)."""
    return operations.actor_text(actor)


def guard(ctx: dict, op: str, channel, sender, kind=None) -> None:
    """For an act that came from a messaging app: refuse, with the sentence the bridge uses, when the sender's profile does not cover the operation
    (and the kind of decision). Other channels are checked where they always were. The policy is the configuration loaded for this call."""
    if channel != MESSAGING:
        return
    require(channel, sender)
    refused = operations.refusal(op, MESSAGING, ctx["cfg"]["channels"], kind, sender=sender)
    if refused:
        raise core.OpsError(refused, 1)


def shown(item: dict) -> dict:
    """A pending decision (or an approval) as a shell reads it: `actor` is replaced by `acted_by`, its public form."""
    if not isinstance(item, dict) or "actor" not in item:
        return item
    out = {k: v for k, v in item.items() if k != "actor"}
    out["acted_by"] = public(item.get("actor"))
    return out


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
