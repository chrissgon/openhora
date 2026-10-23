#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The effect kind of a change to the person's own mailbox (package W3): the messages a step task listed are archived, moved to a folder or label the project's
`accounts` names, marked as read or unread, or moved to the provider's trash, or a draft is saved, exactly as the person approved, once. NOTHING IS SENT (a draft is
saved in the Drafts folder, never sent: no writer has a verb that sends) and NOTHING IS REMOVED FOR GOOD (the trash is the provider's: Gmail empties it after 30 days,
Outlook deletes what is in Deleted Items after 30 days; the code never does).

It is registered under the side-effect word `mailbox` (runtime/effects.py KINDS; contracts/environment.md) and is the STEP path of an effect, like the write-back
(runtime/effect_write.py), the send (runtime/effect_send.py) and the calendar (runtime/effect_calendar.py): a step task of the kind `mailbox-change`
(runtime/step_mailbox.py) writes the document of runtime/mailbox_document.py and opens an `effect` decision whose hash is the document's; nothing in the engine or in the
kind writes. The write happens in one place, `execute`, which runtime/ops_step_effects.py calls from the operation `approve` and nowhere else, with the approval the person
gave (limit L55). What a kind module of this path exposes, besides the names of runtime/effect_write.py (the document, `check`, `title`, `body`, `describe`, `summary`,
`execute`):

    PROVIDER_CLASS, GATE, POLICY, STEP   writer:mailbox; False and False (no skill's gate names `mailbox`, and no standing approval covers it: every change is approved
                                         by the hash of its exact content); True
    NOTHING_DONE                         "nothing was written": how a refusal of the approval starts
    FORGETS_KEYS                         False: the writer's ledger keeps a key; the age of a decision is no reason to refuse it
    preflight(cfg, doc, root)            the account is one the project's `accounts` lists, with the address of the document; a move goes to a mail folder it lists
                                         under the same name and id, and leaves the inbox as its `move_removes_inbox` says (limit L55); the writer of the document
                                         serves the class ((exit code, sentence) or None)
    caller(cfg, root)                    the `call(verb, args, implementation=)` that reaches the writer with the account's token in its environment and nothing else
                                         of the secrets
    idempotency_key(doc, default)        the document's own key: one request is done once, however many decisions reach it
    is_long(doc)                         True: a write opens connections, so an answer or a cancel of the decision is refused while it runs
    on_cards(doc)                        True: the card lists every message (at most 20) or is the whole draft
    APPROVAL_GROUP                       the policy group that lets a messaging app approve this kind (`approve-effect-mailbox`)

Execution (`execute`). It refuses unless `approval` is the person's approval of exactly this document (scope action, status pending-execution, payload_sha256 the hash of
the document's canonical text) and `key` is the document's own. For a change of messages, the writer is asked for the state of EVERY message just before (limit L56): one
that is not as it was read (its labels, or its changeKey and folder, moved; or it is gone) makes the whole card `stale`, nothing is written, and the task starts over from
the step that reads (a message the writer's ledger shows done, or pending from an earlier attempt, is left to the writer, which tells by state). The writer is asked for a
dry run, and what it prints must hash to the document's `dry_run_sha256` (a writer that would send other requests than the ones previewed is a `deviation`); then the same
verb is called with `--confirmed`. The words of the person go to the writer in a private file, never on a command line. Results: `done`; `replayed` (every message was done
already: nothing was written again); `unknown` (the writer's exit code 4, or a call that timed out: the request may or may not have landed; after the first message it
says which positions are done; the effect stays open, and approving it again meets the writer's ledger, which holds one entry per message); or a refusal with nothing
written (the writer's exit 1 guarantees it).

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import effects  # noqa: E402
import mailbox_document  # noqa: E402
import phrases  # noqa: E402
import project_config  # noqa: E402
from mailbox_document import WORD, document, check, title, describe, summary, body, sha  # noqa: E402,F401  (the pure half, re-exported)

PROVIDER_CLASS = "writer:mailbox"
GATE = False      # no skill's confirmation gate names this word
POLICY = False    # no standing approval covers a mailbox change: every one is approved by the hash of its exact content
STEP = True       # opened by a step task (runtime/steps.py, Gate) and approved through runtime/ops_step_effects.py
FORGETS_KEYS = False      # the writer's ledger keeps a key for ever, so an old decision is no reason to refuse
APPROVAL_GROUP = "approve-effect-mailbox"      # the group a project's policy grants to let a messaging app approve a mailbox change
NOTHING_DONE = "nothing was written"      # the words ops_step_effects.py starts a refusal with
UNKNOWN_EXIT = 4          # the writer's exit code for "the request may or may not have landed"
CALL_TIMEOUT = 300        # seconds: up to 20 messages, one request each
SERVES_LINE = re.compile(r'^SERVES\s*=\s*"([^"\n]+)"\s*(?:#.*)?$', re.M)
PARTIAL = re.compile(r"partial: done ([0-9,]+|none) of (\d+)")
IMPLEMENTATIONS = tuple(mailbox_document.IMPLEMENTATION.values())
SECRET_OF = {impl: mailbox_document.SECRET[account] for account, impl in mailbox_document.IMPLEMENTATION.items()}
UNKNOWN_NEXT = ("the outcome is unknown: look in the mailbox. The effect stays open. Approving it again with the same hash looks at each message first (the writer keeps "
                "one entry for each): one that is already as asked is recorded as done, the others are sent")
STALE_NOTE = ("Nothing was written by this attempt: the messages are not as the task read them (one was moved, relabelled, read or removed meanwhile). The task starts over "
              "from the step that reads them; start it again to be asked about the messages as they are now.")


class StaleError(effects.EffectError):
    """The messages are not as the task read them."""

    def __init__(self, reason: str):
        super().__init__("stale", reason)
        self.answer = STALE_NOTE


class UnknownError(effects.EffectError):
    """The outcome of the write is not known."""

    def __init__(self, reason: str, done=None, total=None):
        super().__init__("unknown", reason)
        self.next = UNKNOWN_NEXT if done is None else (f"{len(done)} of {total} messages are done (positions {', '.join(done) or 'none'} on the card); the others are not "
                                                       f"known to be. The effect stays open. Approving it again with the same hash looks at each message first: the done ones "
                                                       "are left, the others are sent")


def is_long(doc) -> bool:
    """Whether the write is made without the project's write lock, under the lock of the decision: every one is (it opens connections)."""
    return isinstance(doc, dict)


def on_cards(doc) -> bool:
    """Whether the whole change can be on a messaging card: it is (the card lists every message, at most 20, or is the whole draft; nothing the hash covers is left off it)."""
    return True


def idempotency_key(doc: dict, default: str) -> str:
    """The document's own key (runtime/mailbox_document.py key_of), not the pending decision's."""
    return doc["idempotency_key"]


def serves(root: str, implementation: str):
    """None when providers/writer/<implementation>.py is shipped and declares `SERVES = "writer:mailbox"`, else the sentence that says why not. An implementation that is
    not one of IMPLEMENTATIONS, or that serves another class, is never called."""
    if implementation not in IMPLEMENTATIONS:
        return f"{project_config.clean_name(implementation)!r} is not a mailbox writer"
    resolve = project_config.resolver(root)
    try:
        path = resolve.resolve(PROVIDER_CLASS, root=root, implementation=implementation)["path"]
        with open(path, encoding="utf-8") as f:
            found = SERVES_LINE.search(f.read(20000))
    except (resolve.UnknownClass, resolve.Unresolved) as e:
        return str(e)
    except OSError:
        return f"the writer {implementation} cannot be read"
    if not found or found.group(1) != PROVIDER_CLASS:
        return f"the writer {implementation} does not declare that it serves {PROVIDER_CLASS}"
    return None


def preflight(cfg: dict, doc: dict, root: str):
    """(exit code, sentence) when the project is not configured for this change now, else None: the account is listed, with the address the document has; a move goes to
    a mail folder listed under the name and the id the document has, and leaves the inbox as the project's `move_removes_inbox` says (limit L55: whatever the token could
    reach, only a listed folder is written to); and the writer serves the class. Nothing is written when it answers."""
    entry = project_config.account_entry(cfg, doc.get("account"))
    if entry is None:
        return 3, phrases.en("ACCT_NOT_CONFIGURED").format(account=project_config.clean_name(doc.get("account"), 20)) + " Nothing was written."
    if entry["address"] != doc.get("address"):
        return 1, "nothing was written: the account's address is not the one the change was prepared for"
    if doc["action"] == "move":
        found, why = project_config.account_target(cfg, doc["account"], "mail_folders", doc.get("folder"))
        if why:
            return 1, f"nothing was written: {why}"
        if found != doc.get("folder_id"):
            return 1, "nothing was written: the id of the folder is not the one the change was prepared for"
        if doc["account"] == "google" and entry["move_removes_inbox"] is not doc["remove_inbox"]:
            return 1, "nothing was written: the configuration says otherwise than the change was prepared for about leaving the inbox on a move"
    why = serves(root, doc["implementation"])
    if why:
        return 3, f"nothing was written: {why}"
    return None


def provider_call(root: str, implementation: str, verb: str, args, secrets=(), timeout: int = CALL_TIMEOUT) -> dict:
    """One verb of a mailbox writer, started by providers/resolve.py with the minimum environment plus the names in `secrets` (the one token of the account, when the
    verb reads or writes the account). The writer is checked to serve the class first. EffectError: usage, not-configured, unknown (UnknownError, the writer's exit 4 or
    a timeout: the last line of what it said names the positions done after a first message), stale (StaleError, the writer's `changed:`) or provider."""
    why = serves(root, implementation)
    if why:
        raise effects.EffectError("not-configured", why)
    resolve = project_config.resolver(root)
    try:
        return resolve.call(PROVIDER_CLASS, verb, args, root=root, implementation=implementation, timeout=timeout,
                            env=resolve.provider_environment(PROVIDER_CLASS, None, tuple(secrets)))
    except resolve.ProviderCallError as e:
        said = e.stderr_last or e.reason
        if e.kind == "timeout" or e.exit_code == UNKNOWN_EXIT:
            partial = PARTIAL.search(said)
            if partial:
                raise UnknownError(f"{verb}: {said[:200]}", [] if partial.group(1) == "none" else partial.group(1).split(","), partial.group(2)) from None
            raise UnknownError(f"{verb}: {e.reason}") from None
        if e.exit_code == 1 and "changed:" in said:
            raise StaleError(f"{verb}: the messages moved ({said[:200]})") from None
        raise effects.EffectError({"usage": "usage", "not-configured": "not-configured"}.get(e.kind, "provider"), f"{verb}: {e.reason}") from None


def caller(cfg: dict, root: str):
    """The `call(verb, args, implementation=)` that reaches the writer of the document's account: the token of that account in its environment, nothing else of the
    secrets. A call that timed out, or whose writer exited with UNKNOWN_EXIT, is `unknown`; a `changed:` refusal is `stale`; any other refusal is a failure with nothing
    written."""
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


def spec_file(folder: str, doc: dict) -> str:
    """The private file the writer is handed (the person's words and the ids never go on a command line)."""
    return _private_file(folder, "spec.json", json.dumps(mailbox_document.spec_of(doc), ensure_ascii=False, sort_keys=True).encode("utf-8"))


def moved_positions(doc: dict, got) -> list:
    """The positions (1-based, as on the card) of the messages that are not as the task read them, from the writer's `message-meta` answer. A message whose ledger entry is
    `done` (this very request moved it) or `pending` (an earlier attempt's outcome is not known: the writer tells by state) is left out. UnknownError when the answer is not
    one this code understands."""
    rows = got.get("messages") if isinstance(got, dict) else None
    if not isinstance(rows, list) or not all(isinstance(r, dict) and isinstance(r.get("id"), str) for r in rows):
        raise UnknownError("the writer's answer about the messages is not one this code understands")
    by_id = {r["id"]: r for r in rows}
    out = []
    for item in doc["messages"]:
        row = by_id.get(item["id"])
        if row is None or not isinstance(row.get("found"), bool):
            raise UnknownError("the writer's answer about the messages is not one this code understands")
        if row.get("done") in ("done", "pending"):
            continue
        if not row["found"]:
            out.append(item["n"])
        elif doc["account"] == "google":
            if row.get("labels") != item["labels"]:
                out.append(item["n"])
        elif row.get("change_key") != item["change_key"] or row.get("folder_id") != item["folder_id"]:
            out.append(item["n"])
    return out


def execute(doc: dict, approval: dict, call, key: str, work_dir=None, project=None) -> dict:
    """The write, and the only place it is made. It refuses unless `approval` is the person's approval of exactly this document: scope action, status
    pending-execution, and a payload_sha256 equal to the hash of the document's canonical text (EffectError deviation), and unless `key` is the document's own. Then the
    document is checked again; for a change of messages the state of every message is read and compared (StaleError); the writer's dry run must hash to the document's
    dry_run_sha256 (EffectError deviation); and the verb is called with --confirmed. `call(verb, args, implementation=)` is the seam: the writer's one JSON object, or
    EffectError (UnknownError when the outcome is not known). Returns mailbox_document.facts."""
    if not isinstance(approval, dict) or approval.get("scope") != "action" or approval.get("status") != "pending-execution" \
            or approval.get("payload_sha256") != sha(effects._text(doc)):
        raise effects.EffectError("deviation", "there is no approval of this exact content: nothing is written")
    check(doc)
    if key != doc["idempotency_key"]:
        raise effects.EffectError("deviation", "the key is not the one this request derives: nothing is written")
    implementation = doc["implementation"]
    if doc["messages"]:
        moved = moved_positions(doc, call("message-meta", mailbox_document.meta_args(doc), implementation=implementation))
        if moved:
            raise StaleError(f"the messages at positions {', '.join(str(n) for n in moved)} of the card are not as they were read")
    folder = tempfile.mkdtemp(prefix="openhora-mailbox-", dir=work_dir)
    try:
        args = mailbox_document.provider_args(doc, spec_file(folder, doc))
        verb = mailbox_document.verb_of(doc)
        shown = call(verb, args + ["--dry-run"], implementation=implementation)
        if not isinstance(shown, dict) or shown.get("would_sha256") != doc["dry_run_sha256"]:
            raise effects.EffectError("deviation", "the writer would send something other than the requests that were previewed: nothing is written")
        done = call(verb, args + ["--confirmed"], implementation=implementation)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    if not isinstance(done, dict) or done.get("done") is not True:
        raise UnknownError("the writer's answer is not a finished request: the change may or may not have been made")
    return mailbox_document.facts(doc, "replayed" if done.get("replayed") else "done", done)


if __name__ == "__main__":
    print(__doc__.strip())
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
