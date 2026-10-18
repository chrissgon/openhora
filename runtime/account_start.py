#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The start of a write to the person's own accounts (package FND): one operation prepares the change, runs the preparation, and stops at the card that asks the person to approve it; nothing is written to any account here.

An operation of the family (an event, a change of the mailbox, a file: SPEC-SECRETARY-WRITES, "The operations") calls `start` and nothing else of this file.
`start` does, in this order, and stops at the first that refuses:

  1. the words of the call are the code's: the key (the operation's name, lowercase words joined by hyphens) and the title, which is a phrase key of the family
     `TITLE_` with no field (`title_key`), so that the title is fixed text, said in the project's language on a phone, and never the person's words;
  2. the channel's policy: the terminal and a call with no channel pass; a messaging app needs the sender's group for the operation (ops_actor.guard, as `remind`
     does) and is refused while the step brake is `stopped` (a brake stops new work); the page needs its group (operations.refusal); the MCP mode and any other
     channel are refused, always;
  3. the account is one the project's accepted configuration lists (`accounts` of runtime.json, project_config.account_entry): the token of an account could
     reach more than the platform may write to, and a call for an account that is not listed makes nothing (limit L55);
  4. the step kind is registered, ends in a gate (its last step) whose effect word is one of WORDS, and the operation belongs to the policy group of that word
     (GROUP_OF_WORD: a word whose group does not exist yet, or does not list the operation, starts nothing); it checks its arguments (steps.add_task);
  5. one request with one step task is made (steps.add_task: no model, no plan), and the task runs in this process (ops_steps.run_step): its `prepare` reads
     what it needs through the read-only seams and writes the effect document; its gate opens the `effect` decision whose hash is the document's;
  6. the card is checked, and anything that is not what the operation prepared FAILS CLOSED: the decision's title is the code-written one, its payload carries
     a well-formed `card` (phrases.card_valid: no hidden character in a field) whose English lines are its body, and its effect word is the gate's.

It returns {"request", "task", "pending", "word", "on_cards"}; the messaging bridge sends that decision's card as it sends every card and says `reply_text`
(ACCT_CARD_SENT). After step 4 every refusal leaves nothing behind: the request is cancelled (ops_cancel.request_cancel: its task, and any decision, with it), so
that retries do not pile up planned or ready rows, and the step's own sentence is raised. The effect is executed by `ops_step_effects.approve` and nowhere else
(limit L55): this file imports no effect module, no provider and no writer, and a test holds that.

  start(project, kind, args, *, key_words, title_key, account, channel=None, sender=None)   the above
  reply_text(cfg, started)                                                                  the sentence a messaging app answers with

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import operations  # noqa: E402
import ops_actor  # noqa: E402
import ops_cancel  # noqa: E402
import ops_core as core  # noqa: E402
import ops_grants  # noqa: E402
import ops_steps  # noqa: E402
import phrases  # noqa: E402
import project_config  # noqa: E402
import steps  # noqa: E402

GROUP_OF_WORD = {"calendar": "calendar-write", "mailbox": "mail-organize", "files": "files-write"}      # the policy group that holds the operations of each effect word
WORDS = tuple(GROUP_OF_WORD)      # the effect words of a write to a person's own account; `send` (a mail from the outbox, or from the person's own account) joins with its package
KEY = re.compile(r"[a-z]+(-[a-z]+){0,5}")
TITLE_KEY = re.compile(r"TITLE_[A-Z0-9_]{1,40}")
TITLE_MAX = 60
TASK_TEXT = "Prepare the change to the person's own account and ask for approval."
NOT_MCP = "a write to your own accounts is not available from a connected AI client: ask for it in the terminal, on the page or in a messaging app"
STOPPED = "the runtime's step tasks are stopped (set-mode --agent runtime): nothing was prepared; start it from the terminal or lift the brake"
CARD_REFUSED = ("the card that was opened is not what this operation prepared ({why}): it was cancelled and nothing was written")


def _title(title_key) -> str:
    """The English title of a phrase key of the family TITLE_ with no field, or a usage error: the title is fixed text, never a person's words."""
    english = phrases.TABLE[phrases.DEFAULT]
    if not isinstance(title_key, str) or not TITLE_KEY.fullmatch(title_key) or title_key not in english or phrases._fields_of(english[title_key]) \
            or len(english[title_key]) > TITLE_MAX:
        raise core.OpsError("the title of an account write is a phrase of the table, written by code (a key of the family TITLE_ with no field)", 2)
    return english[title_key]


def _words(key_words) -> None:
    if not isinstance(key_words, str) or not KEY.fullmatch(key_words) or len(key_words) > 40:
        raise core.OpsError("the key of an account write is the operation's name: lowercase words joined by hyphens", 2)


def _policy(ctx: dict, operation: str, channel, sender) -> None:
    """The channel's policy for the operation. The terminal (and a call that names no channel) is never narrowed. A messaging app names its sender, needs the
    group and is refused while the step brake is stopped; the page needs its group; any other channel is refused."""
    if channel in (None, "terminal"):
        return
    if channel == "messaging":
        ops_actor.guard(ctx, operation, channel, sender)
        if ops_steps.steps_mode(ctx) == "stopped":
            raise core.OpsError(STOPPED, 1)
        return
    if channel == "mcp":
        raise core.OpsError(NOT_MCP, 1)
    refused = operations.refusal(operation, channel, ctx["cfg"]["channels"], sender=sender) if channel == "page" else \
        operations.not_enabled(operation, project_config.clean_name(channel))
    if refused:
        raise core.OpsError(refused, 1)


def _gate_word(kind_name, operation: str) -> str:
    """The effect word of the last step of a registered step kind, or a usage error: the kind exists, ends in a gate whose word is one of WORDS, and the
    operation is one of the policy group of that word."""
    try:
        kind = steps.kind_of(kind_name)
    except steps.StepFailure:
        raise core.OpsError(f"there is no step kind {project_config.clean_name(kind_name)!r} in this checkout", 2) from None
    gates = list(kind.gates.items())
    if len(gates) != 1 or gates[0][1].word not in WORDS or kind.order[-1] != gates[0][0]:
        raise core.OpsError(f"the step kind {kind.name} does not open a write to a person's own account", 2)
    word = gates[0][1].word
    group = operations.GROUPS.get(GROUP_OF_WORD[word])
    if group is None or operation not in group["operations"]:
        raise core.OpsError(f"the operation {operation} is not one of the group {GROUP_OF_WORD[word]}, which holds the writes of the effect {word}", 2)
    return word


def _sentence(failure: steps.StepFailure) -> str:
    """The step's own sentence for a refusal: the field it names and what to do next."""
    record = steps.failure_record("", failure, "")
    return " ".join(p for p in (record["field"] and f"{record['field']}:", failure.next or record["code"].replace("_", " ")) if p)


def _abandon(ctx: dict, request_id) -> None:
    """Nothing of a refused start stays behind: the request, its task and any decision it opened are cancelled (a start is always a new request, and
    nothing ever resumes one that failed)."""
    try:
        ops_cancel.request_cancel(ctx["conn"], request_id, by="code", context=ctx)
    except (core.OpsError, ctx["store"].StoreError):      # a request that cannot be cancelled now (it is being written) is left to the recovery
        pass


def _card_problem(item: dict, title: str, word: str, facts: dict):
    """Why the opened decision is not what the operation prepared, or None."""
    if item.get("kind") != "effect":
        return "it is not an effect"
    if item.get("title") != title:
        return "its title is not the one written by code"
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    card = payload.get("card")
    if not phrases.card_valid(card):
        return "it carries no well-formed card of lines"
    if phrases.card_text(card).strip() != str(item.get("body") or "").strip():
        return "its lines are not its body"
    if facts.get("word") != word:
        return "its effect is not the gate's"
    return None


def start(project: str, kind: str, args, *, key_words: str, title_key: str, account: str, channel=None, sender=None) -> dict:
    """Prepare one write to the person's own account and stop at its card. See the module's text for the order of the checks. `kind` is the step kind, `args`
    its arguments (the kind checks them), `key_words` the operation's name and the task's key, `title_key` the phrase (family TITLE_) that is the card's title,
    `account` `google` or `microsoft`, `channel` and `sender` who asks. Returns {"request", "task", "pending", "word", "on_cards"}; core.OpsError otherwise."""
    _words(key_words)
    title = _title(title_key)
    if not isinstance(args, dict):
        raise core.OpsError("the arguments of an account write are an object", 2)
    ctx = core.context(project)
    cfg = ctx["cfg"]
    _policy(ctx, key_words, channel, sender)
    if project_config.account_entry(cfg, account) is None:
        raise core.OpsError(phrases.en("ACCT_NOT_CONFIGURED").format(account=project_config.clean_name(account, 20)), 3)
    if "account" in args and args["account"] != account:
        raise core.OpsError("the account of the arguments is not the account of the call", 2)
    word = _gate_word(kind, key_words)
    store = ctx["store"]
    try:
        made = steps.add_task(store, ctx["conn"], kind, args, key=key_words, title=title, text=TASK_TEXT)
    except steps.StepFailure as e:
        raise core.OpsError(_sentence(e), 2) from None
    except store.StoreError as e:
        raise core.OpsError(str(e), e.code) from None
    try:
        out = ops_steps.run_step(project, made["task"])
    except BaseException:
        _abandon(ctx, made["request"])
        raise
    if out.get("ran") is None:                  # held (a cap of the runtime) or refused: nothing ran
        _abandon(ctx, made["request"])
        raise core.OpsError(str(out.get("reason") or "the preparation could not start now"), 1)
    if out.get("ok") is not True:               # a preparation that failed: the step's own sentence
        _abandon(ctx, made["request"])
        failure = steps.StepFailure(str(out.get("code") or "failed"), str(out.get("field") or ""), "", str(out.get("next") or ""))
        raise core.OpsError(steps.note_of(str(out.get("failed") or "prepare"), failure), 1)
    if not out.get("stopped") or not out.get("pending"):
        _abandon(ctx, made["request"])
        raise core.OpsError("the preparation ended without a card to approve; nothing was written", 1)
    try:
        item = core._stored(ctx, store.pending_get, out["pending"])
        facts = ops_grants.effect_facts(ctx, item) if item.get("kind") == "effect" else {"word": None, "on_cards": False}
        why = _card_problem(item, title, word, facts)
    except BaseException:
        _abandon(ctx, made["request"])
        raise
    if why:
        _abandon(ctx, made["request"])
        raise core.OpsError(CARD_REFUSED.format(why=why), 1)
    return {"request": made["request"], "task": made["task"], "pending": out["pending"], "word": facts["word"], "on_cards": facts["on_cards"]}


def reply_text(cfg, started: dict) -> str:
    """What a messaging app answers once the card was sent, in the project's language (ACCT_CARD_SENT)."""
    return phrases.text("ACCT_CARD_SENT", cfg, pending=started["pending"])


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
