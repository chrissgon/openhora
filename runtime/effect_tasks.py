#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The effect kind of a change to the person's own task list (package CB-5): the task a step task prepared is added to, or marked as completed in, the list the project's
`accounts` names (`task_lists`), exactly as the person approved it, once. Nobody is told; nothing is removed, moved or marked open again: the writers have no verb for any of it
(limit L57).

It is registered under the side-effect word `tasks` (runtime/effects.py KINDS; contracts/environment.md) and is the STEP path of an effect, like the calendar's
(runtime/effect_calendar.py): a step task of the kind `tasks-item` (runtime/step_tasks_item.py) writes the document of runtime/tasks_document.py and opens an `effect` decision whose
hash is the document's; nothing in the engine or in the kind writes. The write happens in one place, `execute`, which runtime/ops_step_effects.py calls from the operation `approve` and
nowhere else, with the approval the person gave (limit L55). What a kind module of this path exposes, besides the names of runtime/effect_write.py (the document, `check`, `title`, `body`,
`describe`, `summary`, `execute`):

    PROVIDER_CLASS, GATE, POLICY, STEP   writer:tasks; False and False (no skill's gate names `tasks`, and no standing approval covers it: every change is approved by the hash of its
                                         exact content); True
    NOTHING_DONE                         "nothing was written": how a refusal of the approval starts
    FORGETS_KEYS                         False: the writer's ledger keeps a key; the age of a decision is no reason to refuse it
    preflight(cfg, doc, root)            the account is one the project's `accounts` lists, with the address of the document; the list is one of its `task_lists` under the same
                                         name and id (limit L55); the writer of the document serves the class ((exit code, sentence) or None)
    caller(cfg, root)                    the `call(verb, args, implementation=)` that reaches the writer with the account's token in its environment and nothing else of the secrets
    idempotency_key(doc, default)        the document's own key: one request is done once, however many decisions reach it
    is_long(doc)                         True: a write opens connections, so an answer or a cancel of the decision is refused while it runs
    on_cards(doc)                        True: the card is the whole change
    APPROVAL_GROUP                       the policy group that lets a messaging app approve this kind (`approve-effect-tasks`)

Execution (`execute`). It refuses unless `approval` is the person's approval of exactly this document (scope action, status pending-execution, payload_sha256 the hash of the document's
canonical text) and `key` is the document's own. For a completion the task is read again from the service and its version (the etag) is compared with the one the task read (limit
L56): another version is `stale`, nothing is written, and the task starts over from the step that reads (one exception: a task that is completed already, left so by an attempt
whose answer was lost, goes on to the writer, which tells from its ledger). The writer is asked for a dry run, and what it prints must hash to the document's `dry_run_sha256` (a writer
that would send another request than the one previewed is a `deviation`); then the same verb is called with `--confirmed`. The words of the person go to the writer in a private file,
never on a command line. Results: `done`; `replayed` (the key was done already, or the writer found the task in the list after an earlier attempt lost its answer: nothing was written
again); `unknown` (the writer's exit code 4, or a call that timed out: the request may or may not have landed; the effect stays open, and approving it again meets the writer's
ledger); or a refusal with nothing written (the writer's exit 1 guarantees it; its message starts with `changed:` when the task moved and with `ambiguous:` when a lost answer cannot be
settled, and then nothing is sent and the person is told to look at the list).

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
import effects  # noqa: E402
import phrases  # noqa: E402
import project_config  # noqa: E402
import tasks_document  # noqa: E402
from tasks_document import WORD, document, check, title, describe, summary, body, sha  # noqa: E402,F401  (the pure half, re-exported)

PROVIDER_CLASS = "writer:tasks"
GATE = False      # no skill's confirmation gate names this word
POLICY = False    # no standing approval covers a task change: every one is approved by the hash of its exact content
STEP = True       # opened by a step task (runtime/steps.py, Gate) and approved through runtime/ops_step_effects.py
FORGETS_KEYS = False      # the writer's ledger keeps a key for ever, so an old decision is no reason to refuse
APPROVAL_GROUP = "approve-effect-tasks"      # the group a project's policy grants to let a messaging app approve a task change
NOTHING_DONE = "nothing was written"      # the words ops_step_effects.py starts a refusal with
UNKNOWN_EXIT = 4          # the writer's exit code for "the request may or may not have landed"
CALL_TIMEOUT = 120        # seconds
IMPLEMENTATIONS = tuple(tasks_document.IMPLEMENTATION.values())
SECRET_OF = {impl: tasks_document.SECRET[account] for account, impl in tasks_document.IMPLEMENTATION.items()}
UNKNOWN_NEXT = ("the outcome is unknown: look in your task list. The effect stays open. Approving it again with the same hash looks in the list first (by the key the request "
                "carries): found, it is recorded as done; not found, it is sent once more")
STALE_NOTE = ("Nothing was written by this attempt: the task is not as the preparation read it (it was changed, completed or removed meanwhile). The task starts over from the "
              "step that reads it; start it again to be asked about the task as it is now.")
AMBIGUOUS_NOTE = ("ambiguous: more than one open task of the list has this title and was added after the request was sent, so it cannot be told whether it landed. Nothing was "
                  "sent; look in your task list and add it yourself if it is not there")


class StaleError(effects.EffectError):
    """The task is not as the preparation read it."""

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
    """Whether the whole change can be on a messaging card: it is. The card names the whole change: the account, the list and the title."""
    return True


def idempotency_key(doc: dict, default: str) -> str:
    """The document's own key (runtime/tasks_document.py key_of), not the pending decision's."""
    return doc["idempotency_key"]


def serves(root: str, implementation: str):
    """None when providers/writer/<implementation>.py is shipped and declares `SERVES = "writer:tasks"`, else the sentence that says why not. An implementation that is not one of
    IMPLEMENTATIONS, or that serves another class, is never called."""
    if implementation not in IMPLEMENTATIONS:
        return f"{project_config.clean_name(implementation)!r} is not a tasks writer"
    resolve = project_config.resolver(root)
    if not resolve.serves_class(PROVIDER_CLASS, implementation, root=root, strict=True):      # the one reader of the SERVES line (providers/resolve.py)
        return f"the writer {implementation} does not declare that it serves {PROVIDER_CLASS}"
    try:
        resolve.resolve(PROVIDER_CLASS, root=root, implementation=implementation)
    except (resolve.UnknownClass, resolve.Unresolved) as e:
        return str(e)
    return None


def preflight(cfg: dict, doc: dict, root: str):
    """(exit code, sentence) when the project is not configured for this change now, else None: the account is listed, with the address the document has, the list is listed under the
    name and the id the document has (limit L55: whatever the token could reach, only a listed list is written to), and the writer serves the class. Nothing is written when it
    answers."""
    entry = project_config.account_entry(cfg, doc.get("account"))
    if entry is None:
        return 3, phrases.en("ACCT_NOT_CONFIGURED").format(account=project_config.clean_name(doc.get("account"), 20)) + " Nothing was written."
    if entry["address"] != doc.get("address"):
        return 1, "nothing was written: the account's address is not the one the change was prepared for"
    found, why = project_config.account_target(cfg, doc["account"], "task_lists", doc.get("list"))
    if why:
        return 1, f"nothing was written: {why}"
    if found != doc.get("list_id") and not (found == "default" and doc["account"] == "microsoft"):      # Microsoft's `default` was resolved to an id when the change was prepared
        return 1, "nothing was written: the id of the list is not the one the change was prepared for"
    why = serves(root, doc["implementation"])
    if why:
        return 3, f"nothing was written: {why}"
    return None


def provider_call(root: str, implementation: str, verb: str, args, secrets=(), timeout: int = CALL_TIMEOUT) -> dict:
    """One verb of a tasks writer, started by providers/resolve.py with the minimum environment plus the names in `secrets` (the one token of the account, when the verb reads or
    writes the account). The writer is checked to serve the class first. EffectError: usage, not-configured, unknown (UnknownError), stale (StaleError, the writer's `changed:`) or
    provider (an `ambiguous:` answer included)."""
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
            raise UnknownError(f"{verb}: {e.reason}") from None
        if e.exit_code == 1 and "changed:" in said:
            raise StaleError(f"{verb}: the task moved ({said[:200]})") from None
        if e.exit_code == 1 and "ambiguous:" in said:
            raise effects.EffectError("provider", f"{verb}: {AMBIGUOUS_NOTE}") from None
        raise effects.EffectError({"usage": "usage", "not-configured": "not-configured"}.get(e.kind, "provider"), f"{verb}: {e.reason}") from None


def caller(cfg: dict, root: str):
    """The `call(verb, args, implementation=)` that reaches the writer of the document's account: the token of that account in its environment, nothing else of the secrets. A call
    that timed out, or whose writer exited with UNKNOWN_EXIT, is `unknown`; a `changed:` refusal is `stale`; any other refusal is a failure with nothing written."""
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
    """The private file the writer is handed (the person's words never go on a command line), or None for a completion."""
    if doc["operation"] != "add":
        return None
    return _private_file(folder, "spec.json", json.dumps(tasks_document.spec_of(doc), ensure_ascii=False, sort_keys=True).encode("utf-8"))


def _unchanged(doc: dict, got) -> None:
    """StaleError unless the task is as the preparation read it: found, open, with the version the preparation read (limit L56). A task that is completed already goes on (an
    earlier attempt of this very completion may have landed and lost its answer): the writer's ledger tells."""
    if not isinstance(got, dict) or not isinstance(got.get("found"), bool):
        raise UnknownError("the writer's answer about the task is not one this code understands")
    if not got["found"]:
        raise StaleError("the task is not in the list any more")
    task = got.get("task")
    if not isinstance(task, dict):
        raise UnknownError("the writer's answer about the task is not one this code understands")
    if task.get("etag") == doc["base_etag"] and task.get("status") == "open":
        return
    if task.get("status") == "completed":
        return
    raise StaleError("the task has another version than the one the preparation read")


def execute(doc: dict, approval: dict, call, key: str, work_dir=None, project=None) -> dict:
    """The write, and the only place it is made. It refuses unless `approval` is the person's approval of exactly this document: scope action, status pending-execution, and a
    payload_sha256 equal to the hash of the document's canonical text (EffectError deviation), and unless `key` is the document's own. Then the document is checked again; for a
    completion the task is read again and compared (StaleError); the writer's dry run must hash to the document's dry_run_sha256 (EffectError deviation); and the verb is called with
    --confirmed. `call(verb, args, implementation=)` is the seam: the writer's one JSON object, or EffectError (UnknownError when the outcome is not known). Returns
    tasks_document.facts."""
    if not isinstance(approval, dict) or approval.get("scope") != "action" or approval.get("status") != "pending-execution" \
            or approval.get("payload_sha256") != sha(effects._text(doc)):
        raise effects.EffectError("deviation", "there is no approval of this exact content: nothing is written")
    check(doc)
    if key != doc["idempotency_key"]:
        raise effects.EffectError("deviation", "the key is not the one this request derives: nothing is written")
    implementation = doc["implementation"]
    if doc["operation"] == "complete":
        _unchanged(doc, call("task-get", tasks_document.get_args(doc), implementation=implementation))
    folder = tempfile.mkdtemp(prefix="openhora-tasks-", dir=work_dir)
    try:
        args = tasks_document.provider_args(doc, spec_file(folder, doc))
        verb = tasks_document.verb_of(doc)
        shown = call(verb, args + ["--dry-run"], implementation=implementation)
        if not isinstance(shown, dict) or shown.get("would_sha256") != doc["dry_run_sha256"]:
            raise effects.EffectError("deviation", "the writer would send something other than the request that was previewed: nothing is written")
        done = call(verb, args + ["--confirmed"], implementation=implementation)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    if not isinstance(done, dict) or done.get("done") is not True:
        raise UnknownError("the writer's answer is not a finished request: the change may or may not have been made")
    return tasks_document.facts(doc, "replayed" if done.get("replayed") else "done", done)


if __name__ == "__main__":
    print(__doc__.strip())
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
