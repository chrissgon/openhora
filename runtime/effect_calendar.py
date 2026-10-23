#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The effect kind of a change to the person's own calendar (package W1): the event a step task prepared is created, changed or removed in the calendar the
project's `accounts` names, exactly as the person approved it, once. Nobody is told: no attendee is ever sent and no invitation or e-mail goes out.

It is registered under the side-effect word `calendar` (runtime/effects.py KINDS; contracts/environment.md) and is the STEP path of an effect, like the write-back
(runtime/effect_write.py) and the send (runtime/effect_send.py): a step task of the kind `calendar-event` (runtime/step_calendar_event.py) writes the document of
runtime/calendar_document.py and opens an `effect` decision whose hash is the document's; nothing in the engine or in the kind writes. The write happens in one
place, `execute`, which runtime/ops_step_effects.py calls from the operation `approve` and nowhere else, with the approval the person gave (limit L55). What a kind
module of this path exposes, besides the names of runtime/effect_write.py (the document, `check`, `title`, `body`, `describe`, `summary`, `execute`):

    PROVIDER_CLASS, GATE, POLICY, STEP   writer:calendar; False and False (no skill's gate names `calendar`, and no standing approval covers it yet: every change
                                         is approved by the hash of its exact content); True
    NOTHING_DONE                         "nothing was written": how a refusal of the approval starts
    FORGETS_KEYS                         False: the writer's ledger keeps a key; the age of a decision is no reason to refuse it
    preflight(cfg, doc, root)            the account is one the project's `accounts` lists, with the address of the document; the calendar is one of its `calendars`
                                         under the same name and id (limit L55); the writer of the document serves the class ((exit code, sentence) or None)
    caller(cfg, root)                    the `call(verb, args, implementation=)` that reaches the writer with the account's token in its environment and nothing
                                         else of the secrets
    idempotency_key(doc, default)        the document's own key: one request is done once, however many decisions reach it
    is_long(doc)                         True: a write opens connections, so an answer or a cancel of the decision is refused while it runs
    on_cards(doc)                        True: the card is the whole event
    APPROVAL_GROUP                       the policy group that lets a messaging app approve this kind (`approve-effect-calendar`)

Execution (`execute`). It refuses unless `approval` is the person's approval of exactly this document (scope action, status pending-execution, payload_sha256 the
hash of the document's canonical text) and `key` is the document's own. For a change or a removal the event is read again from the calendar and its version (the
etag, Graph's changeKey) is compared with the one the task read (limit L56): another version is `stale`, nothing is written, and the task starts over from the step
that reads (one exception: a change whose parts are already in the event, left there by an attempt whose answer was lost, goes on to the writer, which tells from its
ledger). The writer is asked for a dry run, and what it prints must hash to the document's `dry_run_sha256` (a writer that would send another request than the one
previewed is a `deviation`); then the same verb is called with `--confirmed`. The words of the person go to the writer in a private file, never on a command line.
Results: `done`; `replayed` (the key was done already, or the writer found the event in the calendar after an earlier attempt lost its answer: nothing was written
again); `unknown` (the writer's exit code 4, or a call that timed out: the request may or may not have landed; the effect stays open, and approving it again meets
the writer's ledger); or a refusal with nothing written (the writer's exit 1 guarantees it).

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import calendar_document  # noqa: E402
import effects  # noqa: E402
import phrases  # noqa: E402
import project_config  # noqa: E402
from calendar_document import WORD, document, check, title, describe, summary, body, sha  # noqa: E402,F401  (the pure half, re-exported)

PROVIDER_CLASS = "writer:calendar"
GATE = False      # no skill's confirmation gate names this word
POLICY = False    # no standing approval covers a calendar change yet: every one is approved by the hash of its exact content
STEP = True       # opened by a step task (runtime/steps.py, Gate) and approved through runtime/ops_step_effects.py
FORGETS_KEYS = False      # the writer's ledger keeps a key for ever, so an old decision is no reason to refuse
APPROVAL_GROUP = "approve-effect-calendar"      # the group a project's policy grants to let a messaging app approve a calendar change
NOTHING_DONE = "nothing was written"      # the words ops_step_effects.py starts a refusal with
UNKNOWN_EXIT = 4          # the writer's exit code for "the request may or may not have landed"
CALL_TIMEOUT = 120        # seconds
IMPLEMENTATIONS = tuple(calendar_document.IMPLEMENTATION.values())
SECRET_OF = {impl: calendar_document.SECRET[account] for account, impl in calendar_document.IMPLEMENTATION.items()}
UNKNOWN_NEXT = ("the outcome is unknown: look in the calendar. The effect stays open. Approving it again with the same hash looks in the calendar first (by the "
                "key the request carries): found, it is recorded as done; not found, it is sent once more")
STALE_NOTE = ("Nothing was written by this attempt: the event is not as the task read it (it was changed, moved or removed meanwhile). The task starts over from the "
              "step that reads it; start it again to be asked about the event as it is now.")


class StaleError(effects.EffectError):
    """The event is not as the task read it."""

    def __init__(self, reason: str):
        super().__init__("stale", reason)
        self.answer = STALE_NOTE


class UnknownError(effects.EffectError):
    """The outcome of the write is not known."""

    def __init__(self, reason: str):
        super().__init__("unknown", reason)
        self.next = UNKNOWN_NEXT


def is_long(doc) -> bool:
    """Whether the write is made without the project's write lock, under the lock of the decision: every one is (it opens connections)."""
    return isinstance(doc, dict)


def on_cards(doc) -> bool:
    """Whether the whole change can be on a messaging card: it is. The card names the whole event; a phone's text leaves off the event's id, the snapshot's name and the version (the page and
    the terminal show every line, and the hash covers them all), and what it does show (account, calendar, title, the time as read now, and the time after) names the event."""
    return True


def idempotency_key(doc: dict, default: str) -> str:
    """The document's own key (runtime/calendar_document.py key_of), not the pending decision's."""
    return doc["idempotency_key"]


def serves(root: str, implementation: str):
    """None when providers/writer/<implementation>.py is shipped and declares `SERVES = "writer:calendar"`, else the sentence that says why not. An implementation
    that is not one of IMPLEMENTATIONS, or that serves another class, is never called."""
    if implementation not in IMPLEMENTATIONS:
        return f"{project_config.clean_name(implementation)!r} is not a calendar writer"
    resolve = project_config.resolver(root)
    if not resolve.serves_class(PROVIDER_CLASS, implementation, root=root, strict=True):      # the one reader of the SERVES line (providers/resolve.py)
        return f"the writer {implementation} does not declare that it serves {PROVIDER_CLASS}"
    try:
        resolve.resolve(PROVIDER_CLASS, root=root, implementation=implementation)
    except (resolve.UnknownClass, resolve.Unresolved) as e:
        return str(e)
    return None


def preflight(cfg: dict, doc: dict, root: str):
    """(exit code, sentence) when the project is not configured for this change now, else None: the account is listed, with the address the document has, the
    calendar is listed under the name and the id the document has (limit L55: whatever the token could reach, only a listed calendar is written to), and the writer
    serves the class. Nothing is written when it answers."""
    entry = project_config.account_entry(cfg, doc.get("account"))
    if entry is None:
        return 3, phrases.en("ACCT_NOT_CONFIGURED").format(account=project_config.clean_name(doc.get("account"), 20)) + " Nothing was written."
    if entry["address"] != doc.get("address"):
        return 1, "nothing was written: the account's address is not the one the change was prepared for"
    found, why = project_config.account_target(cfg, doc["account"], "calendars", doc.get("calendar"))
    if why:
        return 1, f"nothing was written: {why}"
    if found != doc.get("calendar_id"):
        return 1, "nothing was written: the id of the calendar is not the one the change was prepared for"
    why = serves(root, doc["implementation"])
    if why:
        return 3, f"nothing was written: {why}"
    return None


def provider_call(root: str, implementation: str, verb: str, args, secrets=(), timeout: int = CALL_TIMEOUT) -> dict:
    """One verb of a calendar writer, started by providers/resolve.py with the minimum environment plus the names in `secrets` (the one token of the account, when
    the verb reads or writes the account). The writer is checked to serve the class first. EffectError: usage, not-configured, unknown (UnknownError), stale
    (StaleError, the writer's `changed:`) or provider."""
    why = serves(root, implementation)
    if why:
        raise effects.EffectError("not-configured", why)
    resolve = project_config.resolver(root)
    try:
        return resolve.call(PROVIDER_CLASS, verb, args, root=root, implementation=implementation, timeout=timeout,
                            env=resolve.provider_environment(PROVIDER_CLASS, None, tuple(secrets)))
    except resolve.ProviderCallError as e:
        if e.kind == "timeout" or e.exit_code == UNKNOWN_EXIT:
            raise UnknownError(f"{verb}: {e.reason}") from None
        if e.exit_code == 1 and "changed:" in (e.stderr_last or e.reason):
            raise StaleError(f"{verb}: the event moved ({(e.stderr_last or e.reason)[:200]})") from None
        raise effects.EffectError({"usage": "usage", "not-configured": "not-configured"}.get(e.kind, "provider"), f"{verb}: {e.reason}") from None


def caller(cfg: dict, root: str):
    """The `call(verb, args, implementation=)` that reaches the writer of the document's account: the token of that account in its environment, nothing else of
    the secrets. A call that timed out, or whose writer exited with UNKNOWN_EXIT, is `unknown`; a `changed:` refusal is `stale`; any other refusal is a failure with
    nothing written."""
    def call(verb, args, implementation=None):
        # a dry run reads no credential and opens no connection, so it is started without the token
        secrets = (SECRET_OF[implementation],) if implementation in SECRET_OF and "--dry-run" not in args else ()
        return provider_call(root, implementation, verb, args, secrets)
    return call


def _private_file(folder: str, name: str, data: bytes) -> str:
    path = os.path.join(folder, name)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path


def spec_file(folder: str, doc: dict):
    """The private file the writer is handed (the person's words never go on a command line), or None for a removal."""
    if doc["operation"] == "cancel":
        return None
    return _private_file(folder, "spec.json", json.dumps(calendar_document.spec_of(doc), ensure_ascii=False, sort_keys=True).encode("utf-8"))


def _applied(doc: dict, got: dict) -> bool:
    """Whether the event already holds every part a change would write: an attempt of this very change whose answer was lost left it so."""
    if doc["operation"] != "change" or not isinstance(got.get("event"), dict):
        return False
    try:
        now = calendar_document.from_service(got["event"])
        return not [name for name in calendar_document.changed_fields(now, doc["event"]) if name in doc["changed"]]
    except effects.EffectError:
        return False


def _unchanged(doc: dict, got) -> None:
    """StaleError unless the event is as the task read it: found with the version the task read (limit L56)."""
    if not isinstance(got, dict) or not isinstance(got.get("found"), bool):
        raise UnknownError("the writer's answer about the event is not one this code understands")
    if not got["found"]:
        if doc["operation"] == "cancel":
            return      # gone: an earlier attempt of this removal may have landed; the writer's ledger tells
        raise StaleError("the event is not in the calendar any more")
    event = got.get("event")
    if not isinstance(event, dict) or event.get("etag") != doc["base_etag"]:
        if not _applied(doc, got):
            raise StaleError("the event has another version than the one the task read")


def execute(doc: dict, approval: dict, call, key: str, work_dir=None, project=None) -> dict:
    """The write, and the only place it is made. It refuses unless `approval` is the person's approval of exactly this document: scope action, status
    pending-execution, and a payload_sha256 equal to the hash of the document's canonical text (EffectError deviation), and unless `key` is the document's own.
    Then the document is checked again; for a change or a removal the event is read again and compared (StaleError); the writer's dry run must hash to the
    document's dry_run_sha256 (EffectError deviation); and the verb is called with --confirmed. `call(verb, args, implementation=)` is the seam: the writer's one
    JSON object, or EffectError (UnknownError when the outcome is not known). Returns calendar_document.facts."""
    if not isinstance(approval, dict) or approval.get("scope") != "action" or approval.get("status") != "pending-execution" \
            or approval.get("payload_sha256") != sha(effects._text(doc)):
        raise effects.EffectError("deviation", "there is no approval of this exact content: nothing is written")
    check(doc)
    if key != doc["idempotency_key"]:
        raise effects.EffectError("deviation", "the key is not the one this request derives: nothing is written")
    implementation = doc["implementation"]
    if doc["operation"] != "create":
        _unchanged(doc, call("event-get", calendar_document.event_get_args(doc), implementation=implementation))
    folder = tempfile.mkdtemp(prefix="openhora-calendar-", dir=work_dir)
    try:
        args = calendar_document.provider_args(doc, spec_file(folder, doc))
        verb = calendar_document.verb_of(doc)
        shown = call(verb, args + ["--dry-run"], implementation=implementation)
        if not isinstance(shown, dict) or shown.get("would_sha256") != doc["dry_run_sha256"]:
            raise effects.EffectError("deviation", "the writer would send something other than the request that was previewed: nothing is written")
        done = call(verb, args + ["--confirmed"], implementation=implementation)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    if not isinstance(done, dict) or done.get("done") is not True:
        raise UnknownError("the writer's answer is not a finished request: the change may or may not have been made")
    return calendar_document.facts(doc, "replayed" if done.get("replayed") else "done", done)


if __name__ == "__main__":
    print(__doc__.strip())
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
