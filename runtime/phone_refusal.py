#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""What a phone is told when it is refused (slice S10, limit L62): one plain sentence, never a slash command, "error:" or the name of an operation.

The operations layer refuses with a precise text (`/file-read is not enabled for this channel; the project's configuration (channels.messaging) turns it on`): useful
on the page, in the terminal and in the conversation, where the person can act on it, and nonsense on a messaging app. So the one function every phone path calls is
`said(refused, channel, cfg)`: on the channel `messaging` it is `sentence(cfg)` ("You do not have permission for that here yet. It can be turned on on the platform's
page." in the project's language, with the page link when the project has one), on any other channel it is `error: <the precise text>` as before.

  sentence(cfg)             the plain sentence, in the project's language (phrase key PHONE_NOT_ALLOWED)
  said(refused, channel, cfg)  the reply of a refusal: the plain sentence on a messaging app, `error: <refused>` elsewhere
  plain(text, cfg)          the net under the bridge's send point for the operations layer's own error text (a Refused or an OpsError raised below the reply): a text
                            that is, whole, a refusal of `operations.not_enabled` (or "is not done from a messaging app"), with or without `error: `, becomes the plain
                            sentence (or, for a place where it is done, the phone's "that is not done from a message" sentence); any other text is returned unchanged

Standard library only. Runs on Python 3.9: python3 runtime/phone_refusal.py --help
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import phrases  # noqa: E402  (the same folder)

CHANNEL = "messaging"
DENIED = re.compile(r"/[\w-]+ is not enabled for this channel; the project's configuration \(channels\.[\w-]+\) turns it on")
ELSEWHERE = re.compile(r"/[\w-]+ is (?:done (?:in the terminal|on the page)(?: or (?:in the terminal|on the page))?|not done on this channel|not done from a messaging app)")


def sentence(cfg=None) -> str:
    """The plain sentence of a refusal, in the project's language, with the page link when the project has one."""
    return phrases.phone("PHONE_NOT_ALLOWED", cfg)


def said(refused: str, channel, cfg=None) -> str:
    """The reply of a refusal on `channel`: the plain sentence on a messaging app, `error: <refused>` on any other channel (the precise text is useful there)."""
    if channel != CHANNEL:
        return f"error: {refused}"
    return plain(f"error: {refused}", cfg) if ELSEWHERE.fullmatch(str(refused)) else sentence(cfg)      # "is done in the terminal / not done on this channel": where it is done, not a permission


def plain(text, cfg=None):
    """`text` as a phone may read it: a text that is, whole, one of the operations layer's refusals (see the module's text) is the plain sentence; anything else, unchanged."""
    if not isinstance(text, str):
        return text
    body = text[len("error: "):] if text.startswith("error: ") else text
    if DENIED.fullmatch(body):
        return sentence(cfg)
    if ELSEWHERE.fullmatch(body):
        return phrases.phone("PHONE_ELSEWHERE", cfg)
    return text


def main(argv=None) -> int:
    print(__doc__.strip(), file=sys.stdout if (argv or sys.argv[1:]) in (["--help"], ["-h"]) else sys.stderr)
    return 0 if (argv or sys.argv[1:]) in (["--help"], ["-h"]) else 2


if __name__ == "__main__":
    sys.exit(main())
