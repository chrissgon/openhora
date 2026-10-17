#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The effect, as the channel policy sees it (package POL-1): which word an `effect` decision carries, whether the whole of it can be on a
messaging card, and whether a channel outside the terminal and the page may approve it. A part of the operations layer that ops.py calls
from `approve` and `pending`; it reads the effect document by the decision's own hash and nothing else.

  effect_facts(ctx, item)                   {"word", "on_cards"} of an `effect` decision
  effect_kind(facts)                        the kind the policy is asked about: `effect:<word>`, or `effect` when the word is unknown
  effect_refusal(ctx, item, channel, facts)  the sentence that refuses an effect to a channel outside operations.EFFECT_CHANNELS, or None

The word is the `effect` key of the effect document (effects.KINDS), read only when the file's bytes have the hash of the decision
(effects.read_document: a file changed since the gate is not read), from the file the gate path recorded in the payload or the file of the
step path (ops_step_effects.effect_dir). Any failure is "no word" and `on_cards` False: the policy then asks about `effect` with no word,
which only the terminal, the page and its umbrella cover, and an effect that cannot be shown whole is never approvable from a card. The kind's
own `on_cards(doc)` (runtime/effect_send.py: False with an attachment; runtime/effect_publish.py: False with an image) is the one source of
"the whole of it fits on a card"; a kind without one is on cards.

It is a sibling of runtime/ops.py. The names every module of the layer shares are read as `core.<name>`. Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import effects  # noqa: E402
import operations  # noqa: E402
import ops_core as core  # noqa: E402
import ops_step_effects  # noqa: E402

NO_WORD = {"word": None, "on_cards": False}   # what an effect that cannot be read is: no word, and not on a card


def effect_document(ctx: dict, item: dict):
    """The effect document of an `effect` decision, read by the decision's own hash, or None."""
    sha = item.get("payload_sha256")
    payload = item.get("payload") or {}
    path = payload.get("effect_file") if isinstance(payload, dict) else None
    try:
        if not isinstance(path, str) or not path:
            found = ops_step_effects.step_effect_of(ctx, item)
            if found is None:
                return None
            path = os.path.join(ops_step_effects.effect_dir(ctx["cfg"], found[0]["id"], int(payload.get("cycle", 0))), effects.EFFECT_FILE)
        doc = effects.read_document(path, sha)
    except (effects.EffectError, core.OpsError, OSError, ValueError, TypeError, KeyError):
        return None
    return doc if isinstance(doc, dict) else None


def effect_facts(ctx: dict, item: dict) -> dict:
    """{"word": the effect's word or None, "on_cards": whether the whole effect can be on a messaging card} of an `effect` decision."""
    doc = effect_document(ctx, item)
    word = doc.get("effect") if doc else None
    if not isinstance(word, str) or word not in effects.KINDS:
        return dict(NO_WORD)
    try:
        module = effects.module_for(word)
        on_cards = getattr(module, "on_cards", None)
        whole = True if on_cards is None else bool(on_cards(doc))
    except Exception:   # a kind that fails to answer is not on a card: the check fails closed
        whole = False
    return {"word": word, "on_cards": whole}


def effect_kind(facts) -> str:
    """The kind of `approve` the policy is asked about for this effect."""
    word = (facts or {}).get("word")
    return "effect:" + word if word else "effect"


def effect_refusal(ctx: dict, item: dict, channel, facts: dict):
    """The sentence that refuses an `effect` to a channel outside operations.EFFECT_CHANNELS, or None when the project's accepted policy
    grants that channel this effect's word and the whole effect fits on a card. Fails closed: no channel, the conversation and the MCP mode
    are never granted (operations.policy_allows). The hash is checked by the caller (ops._approve_effect) and by the bridge's card."""
    if channel in operations.EFFECT_CHANNELS:
        return None
    command = core._command("approve", ctx["cfg"]["project"], pending_id=item["id"], sha256="<hash>")
    kind = effect_kind(facts)
    if not operations.permitted("approve", channel or "", ctx["cfg"]["channels"], kind):
        group = "approve-effect-" + facts["word"] if facts.get("word") in operations.EFFECT_APPROVAL_WORDS else None
        return ("an effect is approved in the terminal, with its hash: " + command
                + (f" (or on the page; a messaging app approves it only when the project's configuration grants it {group})" if group else ""))
    if not facts.get("on_cards"):
        return ("this effect carries more than a card can show (the hash covers something the card does not carry: a file, an image, every row of "
                "a table, or the code of a change), so it is not approved from a card: approve it in the terminal or on the page, with its hash: "
                + command)
    return None


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
