#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The document of a change to the person's own task list, and nothing that writes (package CB-5, SPEC-CATALOG-BATCH 6.5): what the step kind `tasks-item` builds and the effect
kind `tasks` approves. The effect document (its keys, its checks, the credential scan of the words the person gave), the card the person reads, the one line that says what is
approved, the closed facts a decision's payload records, and the arguments of the writer's verbs. It holds no function that calls a provider or executes an effect: that is
runtime/effect_tasks.py, reached from the operation `approve` only. The step kind imports this module and not that one, so a step kind has no function in reach that could write
(limit L30; limit L55).

The document. `effect` ("tasks"), `task` (the step task that prepared it), `account` (`google` or `microsoft`), `implementation` (the tasks writer of that account, a provider of
providers/writer/: `google-tasks` or `microsoft-todo`), `address` (the account's address as the project's `accounts` lists it), `list` (the name the project's `accounts` gives the list,
`accounts.<a>.task_lists`) and `list_id` (the id the writer is handed: the service's own id, or `default` for Google's default list; Microsoft's default list is resolved to its id before
the document is made; `default_list` says it was, and the effect resolves it again before it writes), `operation` (`add` or `complete`), `task_id` and `base_etag` (the task a completion is about and the version of it the preparation read; both null for an add),
`read_at` (when the preparation read it, null for an add), `title` (for an add, the person's words; for a completion, the title the preparation read, which another person may have
written: one line, hidden characters removed, possibly empty), `asker` (who asked), `idempotency_key` (derived from everything above: one request is done once) and `dry_run_sha256` (the
hash of what the writer's dry run printed: the exact request it would send).

A task is a title. Nothing else is read, written or shown: no due date, no note, no parent, no list change (OPEN-CB-11, decided 2026-10-27). A task is never removed and never marked
open again: the writers have no verb for either (limit L57).

Standard library only, plus the credential scan of runtime/workcopy.py, the error class of runtime/effects.py and the phrase table. Runs on Python 3.9.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import effects  # noqa: E402  (the error class only)
import phrases  # noqa: E402
import workcopy  # noqa: E402  (the credential formats, loaded from this checkout)

WORD = "tasks"
OPERATIONS = ("add", "complete")
ACCOUNTS = ("google", "microsoft")
IMPLEMENTATION = {"google": "google-tasks", "microsoft": "microsoft-todo"}      # the writer of each account (providers/writer/)
SECRET = {"google": "GOOGLE_ACCOUNT_TOKEN", "microsoft": "MICROSOFT_ACCOUNT_TOKEN"}   # the one secret a writer of that account is started with
SERVICE = {"google": "Google Tasks", "microsoft": "Microsoft To Do"}      # the products' names: a card says them in every language
VERBS = {"add": "task-insert", "complete": "task-complete"}      # the verb of each operation in both writers (providers/writer/README.md)
TITLE_KEY = {"add": "TITLE_TODO_ADD", "complete": "TITLE_TODO_DONE"}
KEYS = ("effect", "task", "account", "implementation", "address", "list", "list_id", "default_list", "operation", "task_id", "base_etag", "read_at", "title", "asker", "idempotency_key",
        "dry_run_sha256")
ASKER = re.compile(r"(?:terminal|page|[a-z][a-z0-9-]{0,31}:[A-Za-z0-9_.@+=-]{1,128})")      # who asked: a channel of the person's own, or a messaging sender (<platform>:<id>)
TITLE_MAX = 200
SHA256 = re.compile(r"[0-9a-f]{64}")
KEY = re.compile(r"todo-[0-9a-f]{32}")      # (ids below never start with a hyphen: a flag would read it)
NAME = re.compile(r"[a-z0-9-]{1,32}")
LIST_ID = re.compile(r"(?!-)[A-Za-z0-9_=-]{1,300}")
TASK_ID = re.compile(r"(?!-)[A-Za-z0-9_=-]{1,300}")
ETAG = re.compile(r"(?!-)[A-Za-z0-9_=+/.\"-]{1,200}")
READ_AT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})")
HIDDEN = ("Cc", "Cf", "Zl", "Zp", "Cs", "Co")      # control, format (a right-to-left override, a zero-width character), separators, surrogate, private use


def sha(data) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def _usage(reason: str):
    return effects.EffectError("usage", reason)


# --- the words the person gives and the words a service gives ------------------------------------------------------------------------------------------


def line(value, what: str, maximum: int, required: bool = False) -> str:
    """A one-line text of the person's: at most `maximum` characters, no control, format or separator character, no space around it. EffectError usage otherwise."""
    if not isinstance(value, str):
        raise _usage(f"{what} is a text")
    if required and not value.strip():
        raise _usage(f"{what} is not empty")
    if len(value) > maximum or value != value.strip() or any(unicodedata.category(c) in HIDDEN for c in value):
        raise _usage(f"{what} is one line of at most {maximum} characters, with no space around it and no hidden or control character")
    return value


def line_or_blank(value, maximum: int = TITLE_MAX) -> str:
    """Another person's text on one line for the card: hidden characters removed, the space folded, cut at `maximum`."""
    spaced = "".join(" " if c in "\n\r\t\v\f" else c for c in str(value if value is not None else ""))      # a line end or a tab is a space, not nothing: two words never run together
    text = "".join(c for c in spaced if unicodedata.category(c) not in HIDDEN or c == " ")
    return " ".join(text.split())[:maximum]


def utc_text(stamp) -> str:
    """`YYYY-MM-DDTHH:MM:SSZ` of an ISO-8601 time with or without an offset (a time without one is read as UTC); EffectError usage when it is not a time."""
    try:
        moment = datetime.datetime.fromisoformat(stamp[:-1] + "+00:00" if isinstance(stamp, str) and stamp.endswith("Z") else stamp)
    except (ValueError, TypeError):
        raise _usage("the time of a reading is an ISO-8601 time") from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    return moment.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def etag_short(etag: str) -> str:
    return "".join(c for c in etag if c not in '"')[:12]


# --- the document ---------------------------------------------------------------------------------------------------------------------------------


def key_of(doc: dict) -> str:
    """`todo-` and 32 hex digits: the key of one request, from everything the person approves of it (the key and the dry-run hash are not content)."""
    said = {k: doc[k] for k in KEYS if k not in ("idempotency_key", "dry_run_sha256")}
    return "todo-" + sha(json.dumps(said, sort_keys=True, ensure_ascii=True, separators=(",", ":")))[:32]


def document(*, task_id: int, account: str, address: str, list_name: str, list_id: str, operation: str, title: str, remote_id=None, base_etag=None, read_at=None,
             asker: str = "terminal", dry_run_sha256: str, default_list: bool = False) -> dict:
    """The effect document, checked. `task_id` is the step task that prepared it, `remote_id` the task of the service a completion is about. EffectError usage when a piece is not in its
    form, a limit is passed, or the words hold what looks like a credential."""
    doc = {"effect": WORD, "task": task_id, "account": account, "implementation": IMPLEMENTATION.get(account, ""), "address": address, "list": list_name, "list_id": list_id,
           "default_list": default_list, "operation": operation, "task_id": remote_id, "base_etag": base_etag, "read_at": read_at, "title": title, "asker": asker, "idempotency_key": "",
           "dry_run_sha256": dry_run_sha256}
    doc["idempotency_key"] = key_of(doc)
    check(doc)
    return doc


def check(doc) -> dict:
    """The document is in its form, or EffectError usage. Run when it is made and again just before the write."""
    if not isinstance(doc, dict) or set(doc) != set(KEYS) or doc["effect"] != WORD:
        raise _usage("the effect document of a task change has exactly its keys")
    if not isinstance(doc["task"], int) or isinstance(doc["task"], bool) or doc["task"] < 1:
        raise _usage("task is a task id")
    if doc["account"] not in ACCOUNTS or doc["implementation"] != IMPLEMENTATION[doc["account"]]:
        raise _usage("the account is google or microsoft, with the writer that serves it")
    if doc["operation"] not in OPERATIONS:
        raise _usage(f"the operation is one of {', '.join(OPERATIONS)}")
    if not isinstance(doc["address"], str) or not 3 <= len(doc["address"]) <= 254 or "@" not in doc["address"]:
        raise _usage("address is the account's address")
    if not isinstance(doc["list"], str) or not NAME.fullmatch(doc["list"]) or not isinstance(doc["list_id"], str) or not LIST_ID.fullmatch(doc["list_id"]):
        raise _usage("the list is a name and an id the project lists")
    if doc["account"] == "microsoft" and doc["list_id"] == "default":
        raise _usage("Microsoft's default list is named by its id: `default` is not one")
    if not isinstance(doc["default_list"], bool) or (doc["default_list"] and doc["account"] != "microsoft"):
        raise _usage("default_list is true only when Microsoft's default list was resolved to the id the document holds, and false otherwise")
    if not isinstance(doc["asker"], str) or not ASKER.fullmatch(doc["asker"]):
        raise _usage("asker is terminal, page or the messaging sender who asked")
    if doc["operation"] == "add":
        if doc["task_id"] is not None or doc["base_etag"] is not None or doc["read_at"] is not None:
            raise _usage("a new task has no earlier task, version or reading")
        line(doc["title"], "the title", TITLE_MAX, True)
    else:
        if not isinstance(doc["task_id"], str) or not TASK_ID.fullmatch(doc["task_id"]) or not isinstance(doc["base_etag"], str) or not ETAG.fullmatch(doc["base_etag"]) \
                or not isinstance(doc["read_at"], str) or not READ_AT.fullmatch(doc["read_at"]):
            raise _usage("a completion names the task, the version of it that was read, and when")
        if not isinstance(doc["title"], str) or len(doc["title"]) > TITLE_MAX or line_or_blank(doc["title"]) != doc["title"]:
            raise _usage("the title of a task read from the service is one clean line of at most 200 characters")
    if not isinstance(doc["dry_run_sha256"], str) or not SHA256.fullmatch(doc["dry_run_sha256"]):
        raise _usage("dry_run_sha256 is the hash of what the writer's dry run printed")
    if not isinstance(doc["idempotency_key"], str) or not KEY.fullmatch(doc["idempotency_key"]) or doc["idempotency_key"] != key_of(doc):
        raise _usage("the key is the one the content derives")
    why = workcopy.scan(doc["title"].encode("utf-8"))
    if why:
        raise _usage(f"the title {why}: it is not written anywhere")
    return doc


# --- what the person reads -------------------------------------------------------------------------------------------------------------------------


def title(doc: dict) -> str:
    """The title of the pending decision: a sentence of the phrase table, written by code (the person's words are never in it)."""
    return phrases.en(TITLE_KEY[doc["operation"]])


def describe(doc: dict) -> str:
    """What is approved, in one line. It holds none of the person's words: the state file is versioned."""
    verb = {"add": "add a task to", "complete": "mark a task as completed in"}[doc["operation"]]
    return f"{verb} the task list '{doc['list']}' of the {doc['account']} account {doc['address']}"


def summary(doc: dict) -> dict:
    """What the pending decision's payload records of the effect: closed words and numbers, never the person's words."""
    return {"operation": doc["operation"], "account": doc["account"], "list": doc["list"]}


def facts(doc: dict, kind: str, got: dict) -> dict:
    """What the execution records of a write that landed: `kind` is "done" or "replayed"; `got` is what the writer printed. Closed words and the service's ids."""
    return {"done": True, "replayed": kind == "replayed", "operation": doc["operation"], "account": doc["account"], "list": doc["list"], "list_id": doc["list_id"],
            "asker": doc["asker"], "task_id": got.get("task_id") or doc["task_id"], "etag": got.get("etag"), "idempotency_key": doc["idempotency_key"]}


def card_lines(doc: dict, digest: str) -> list:
    """The card, line by line: [[key, {field: text}], ...], every key of the family CARD_ (runtime/phrases.py card_valid). The account and the list first, then the task. The title of a
    task the service holds now is under a key of phrases.CARD_PRIVATE (a messaging app draws it only for a sender who holds the group `tasks-read`: phrases.CARD_PRIVATE_GROUP_OF). No id and no version is on
    the card: the hash covers them, and a phone is shown no id (limit L62)."""
    head = [["CARD_ACCOUNT", {"account": doc["account"], "address": doc["address"]}], ["CARD_TODO_LIST", {"list": doc["list"], "service": SERVICE[doc["account"]]}]]
    if doc["operation"] == "add":
        return [["CARD_TODO_ADD", {}]] + head + [["CARD_TODO_TITLE", {"title": doc["title"]}], ["CARD_TODO_PLAIN", {}]]
    return [["CARD_TODO_DONE", {"read_at": doc["read_at"]}]] + head + [["CARD_TODO_NOW_TITLE", {"title": doc["title"] or "-"}]]


def body(doc: dict, digest: str) -> str:
    """What the person reads before approving, in English: the lines of the card (runtime/phrases.py card_text). A messaging app says the same lines in the project's language; the
    hash on the card is the effect's own, in every language."""
    return phrases.card_text(card_lines(doc, digest))


# --- the writer's verbs ------------------------------------------------------------------------------------------------------------------------------


def spec_of(doc: dict) -> dict:
    """What the writer is handed as a file: the title of a new task, nothing for a completion."""
    return {"title": doc["title"]} if doc["operation"] == "add" else {}


def verb_of(doc: dict) -> str:
    return VERBS[doc["operation"]]


def provider_args(doc: dict, spec_file) -> list:
    """The flags of the writer's verb for this document, without --dry-run or --confirmed. `spec_file` is the private path of the spec (None for a completion)."""
    args = ["--account", doc["address"], "--list", doc["list_id"]]
    if doc["operation"] == "complete":
        args += ["--task", doc["task_id"], "--base-etag", doc["base_etag"]]
    if spec_file:
        args += ["--spec-file", spec_file]
    return args + ["--idempotency-key", doc["idempotency_key"]]


def get_args(doc: dict) -> list:
    """The flags of the writer's `task-get` for the task a document (or {"address", "list_id", "task_id"}) names."""
    args = ["--account", doc["address"], "--list", doc["list_id"], "--task", doc["task_id"]]
    return args


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
