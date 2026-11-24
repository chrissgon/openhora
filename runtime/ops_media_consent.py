#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The media consent check (package P6, decision VD17): the one function every sender of recording-derived data calls before it sends.

`require(ctx, purposes, channel=None, sender=None)` answers None when what the sender is about to send is consented, and raises core.OpsError (code 1,
`media_consent_missing: ...`) when it is not. A purpose is a word of MODEL_WORDS or of MESSAGING_WORDS:

  - a model word (transcript, intonation, published-frames, render-ocr: the closed tuple project_config.MEDIA_CONSENT_WORDS) is the project's key: the word is listed
    in `media.consent` of runtime.json and its item, at its current terms version, is in the record `accept-config --widen` writes (policy_widening.consent_missing).
    The channel and the sender are not read: the key is the project's;
  - `messaging-captions` (the caption words sent to a messaging app) goes only to a sender whose profile holds `media-phone` (decision D10: that group's shown text
    says the captions pass through the app's servers);
  - `messaging-preview` (the preview of a delivery, captions drawn in) goes only to a sender whose profile covers `approve` of the delivery effect (the grant
    `approve-effect-deliver`, whose shown text says the preview passes through the messaging provider's servers).

Any other purpose, an empty list included, is a ValueError, a programming error never shown to a person: there is no word for audio or for a frame of a recording (D2).
It writes nothing, logs nothing and holds no caption word. SENDERS is the list of the calls of `require` in runtime/ (a test reads the modules and keeps it equal). The
transcriber is local (VD5): a hosted one would need a word of its own.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import operations  # noqa: E402
import ops_config  # noqa: E402
import ops_core as core  # noqa: E402
import policy_widening  # noqa: E402
import project_config  # noqa: E402

MODEL_WORDS = project_config.MEDIA_CONSENT_WORDS      # sent to a model or a hosted service other than a messaging app: the key
MESSAGING_WORDS = ("messaging-captions", "messaging-preview")      # sent to a messaging app: the sender's profile (decision D10)
SENDERS = (("ops_media_phone", "_caption_text", "messaging-captions"),
           ("ops_media_preview", "video_preview", "messaging-preview"))      # every call of require in runtime/ (module, enclosing function, first purpose), kept equal by a test
CHANNEL = "messaging"
EFFECT_KIND = "effect:deliver"


def _fail(text: str) -> "core.OpsError":
    return core.OpsError("media_consent_missing: " + text, 1)


def require(ctx: dict, purposes, *, channel=None, sender=None) -> None:
    """Refuse (core.OpsError `media_consent_missing`) unless every purpose in `purposes` is consented; see the module's docstring."""
    if not isinstance(purposes, (list, tuple)) or not purposes or not all(isinstance(w, str) and w in MODEL_WORDS + MESSAGING_WORDS for w in purposes):
        raise ValueError("purposes must be a non-empty list of words of MODEL_WORDS or MESSAGING_WORDS")
    model = [w for w in purposes if w in MODEL_WORDS]
    if model:
        record = core._stored(ctx, ctx["store"].cursor_get, policy_widening.ACCOUNTS)
        missing = policy_widening.consent_missing(record, ctx["cfg"], model, ops_config._digest_key(ctx))
        if missing:
            raise _fail(f"the recording's {', '.join(missing)} may not leave this computer: media.consent in docs/workbench/runtime.json does not list it, "
                        "or its terms were not accepted; run config to read them, then accept-config --widen")
    channels = ctx["cfg"]["channels"]
    if "messaging-captions" in purposes:
        held = operations.effective_groups(CHANNEL, channels, sender) if channel == CHANNEL and sender else None
        if "media-phone" not in (held or ()):
            raise _fail("the caption words go to a messaging app only for a sender whose profile holds media-phone")
    if "messaging-preview" in purposes:
        if channel != CHANNEL or not sender or operations.refusal("approve", CHANNEL, channels, EFFECT_KIND, sender=sender) is not None:
            raise _fail("the preview of a delivery goes to a messaging app only for a sender whose profile covers the approval of that delivery")
    return None


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
