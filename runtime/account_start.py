#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The start of a write to the person's own accounts (package FND): one operation prepares the change, runs the preparation, and stops at the card that
asks the person to approve it; nothing is written to any account here.

An operation of the family (an event, a mail, a change of the mailbox, a file: SPEC-SECRETARY-WRITES, "The operations") calls `start` and nothing else of
this file. `start` does, in this order, and stops at the first that refuses:

  1. the words of the call are the code's: the key (the operation's name, lowercase words joined by hyphens) and the title (a few words of letters, a
     colon at most: "Calendar: new event") are fixed by the operation, never the person's words (a title is shown on every card and in the terminal);
  2. the channel's policy: the terminal and a call with no channel pass; a messaging app needs the sender's group for the operation
     (ops_actor.guard, as `remind` does); the page needs its group (operations.refusal); the MCP mode and any other channel are refused, always;
  3. the account is one the project's accepted configuration lists (`accounts` of runtime.json, project_config.account_entry): the token of an account
     could reach more than the platform may write to, and a call for an account that is not listed makes nothing (limit L55);
  4. the step kind is registered, ends in a gate whose effect word is one of WORDS (a kind with no gate, or whose gate opens another word, is refused:
     this is not a way to start any step), and checks its arguments (steps.add_task: a refusal is a usage error naming the field);
  5. one request with one step task is made (steps.add_task: no model, no plan), and the task runs in this process (ops_steps.run_step): its `prepare`
     reads what it needs through the read-only seams and writes the effect document; its gate opens the `effect` decision whose hash is the document's.

It returns {"request", "task", "pending" (the decision's id), "word" (the effect word), "on_cards" (whether the whole effect fits on a messaging card)}; the
messaging bridge sends that decision's card as it sends every card and says `reply_text` (ACCT_CARD_SENT). A preparation that fails leaves the task failed
and the request as it is, and raises the step's own sentence. The effect is executed by `ops_step_effects.approve` and nowhere else (limit L55): this file
imports no effect module, no provider and no writer, and a test holds that.

  start(project, kind, args, *, key_words, title, account, channel=None, sender=None)   the above
  reply_text(cfg, started)                                                              the sentence a messaging app answers with

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import operations  # noqa: E402
import ops_actor  # noqa: E402
import ops_core as core  # noqa: E402
import ops_grants  # noqa: E402
import ops_steps  # noqa: E402
import phrases  # noqa: E402
import project_config  # noqa: E402
import steps  # noqa: E402

WORDS = project_config.ACCOUNT_EFFECT_WORDS + ("send",)      # the effect words of a write to a person's own account; no other gate is started from here
KEY = re.compile(r"[a-z]+(-[a-z]+){0,5}")
TITLE = re.compile(r"[A-Z][a-z]+( [a-z]+){0,3}(: [a-z]+( [a-z]+){0,3})?")
TITLE_MAX = 60
TASK_TEXT = "Prepare the change to the person's own account and ask for approval."
NOT_MCP = "a write to your own accounts is not available from a connected AI client: ask for it in the terminal, on the page or in a messaging app"


def _words(key_words, title) -> None:
    if not isinstance(key_words, str) or not KEY.fullmatch(key_words) or len(key_words) > 40:
        raise core.OpsError("the key of an account write is the operation's name: lowercase words joined by hyphens", 2)
    if not isinstance(title, str) or len(title) > TITLE_MAX or not TITLE.fullmatch(title):
        raise core.OpsError("the title of an account write is a few words written by code, never the person's words", 2)


def _policy(ctx: dict, operation: str, channel, sender) -> None:
    """The channel's policy for the operation. The terminal (and a call that names no channel) is never narrowed. A messaging app names its sender and
    needs the group; the page needs its group; any other channel is refused."""
    if channel in (None, "terminal"):
        return
    if channel == "messaging":
        ops_actor.guard(ctx, operation, channel, sender)
        return
    if channel == "mcp":
        raise core.OpsError(NOT_MCP, 1)
    refused = operations.refusal(operation, channel, ctx["cfg"]["channels"], sender=sender) if channel == "page" else \
        operations.not_enabled(operation, str(channel))
    if refused:
        raise core.OpsError(refused, 1)


def _gate_word(kind_name: str) -> str:
    """The effect word of the gate of a registered step kind, or a usage error: the kind exists, ends in a gate and the gate opens a word of WORDS."""
    try:
        kind = steps.kind_of(kind_name)
    except steps.StepFailure:
        raise core.OpsError(f"there is no step kind {str(kind_name)[:40]!r} in this checkout", 2) from None
    gates = list(kind.gates.values())
    if len(gates) != 1 or gates[0].word not in WORDS:
        raise core.OpsError(f"the step kind {kind.name} does not open a write to a person's own account", 2)
    return gates[0].word


def _sentence(failure: steps.StepFailure) -> str:
    """The step's own sentence for a refusal: the field it names and what to do next."""
    record = steps.failure_record("", failure, "")
    return " ".join(p for p in (record["field"] and f"{record['field']}:", failure.next or record["code"].replace("_", " ")) if p)


def start(project: str, kind: str, args, *, key_words: str, title: str, account: str, channel=None, sender=None) -> dict:
    """Prepare one write to the person's own account and stop at its card. See the module's text for the order of the checks. `kind` is the step kind,
    `args` its arguments (the kind checks them), `key_words` the operation's name and the task's key, `title` the code-written title of the card, `account`
    `google` or `microsoft`, `channel` and `sender` who asks. Returns {"request", "task", "pending", "word", "on_cards"}; core.OpsError otherwise."""
    _words(key_words, title)
    if not isinstance(args, dict):
        raise core.OpsError("the arguments of an account write are an object", 2)
    ctx = core.context(project)
    cfg = ctx["cfg"]
    _policy(ctx, key_words, channel, sender)
    if project_config.account_entry(cfg, account) is None:
        raise core.OpsError(phrases.en("ACCT_NOT_CONFIGURED").format(account=str(account)[:20]), 3)
    if "account" in args and args["account"] != account:
        raise core.OpsError("the account of the arguments is not the account of the call", 2)
    word = _gate_word(kind)
    store = ctx["store"]
    try:
        made = steps.add_task(store, ctx["conn"], kind, args, key=key_words, title=title, text=TASK_TEXT)
    except steps.StepFailure as e:
        raise core.OpsError(_sentence(e), 2) from None
    except store.StoreError as e:
        raise core.OpsError(str(e), e.code) from None
    out = ops_steps.run_step(project, made["task"])
    if out.get("ran") is None:                  # held (a cap of the runtime) or refused: nothing ran, the task waits
        raise core.OpsError(str(out.get("reason") or "the preparation could not start now"), 1)
    if out.get("ok") is not True:               # a preparation that failed: the step's own sentence, the task failed
        failure = steps.StepFailure(str(out.get("code") or "failed"), str(out.get("field") or ""), "", str(out.get("next") or ""))
        raise core.OpsError(steps.note_of(str(out.get("failed") or "prepare"), failure), 1)
    if not out.get("stopped") or not out.get("pending"):
        raise core.OpsError("the preparation ended without a card to approve; nothing was written", 1)
    item = core._stored(ctx, store.pending_get, out["pending"])
    facts = ops_grants.effect_facts(ctx, item) if item.get("kind") == "effect" else {"word": None, "on_cards": False}
    if facts["word"] not in (None, word):
        raise core.OpsError("the card that was opened is not the effect this operation prepares; nothing was written", 1)
    return {"request": made["request"], "task": made["task"], "pending": out["pending"], "word": facts["word"], "on_cards": facts["on_cards"]}


def reply_text(cfg, started: dict) -> str:
    """What a messaging app answers once the card was sent, in the project's language (ACCT_CARD_SENT)."""
    return phrases.text("ACCT_CARD_SENT", cfg, pending=started["pending"])


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
