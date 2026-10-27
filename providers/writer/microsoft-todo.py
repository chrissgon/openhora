#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["keyring==25.7.0"]
# ///
"""Tasks writer for Microsoft To Do (Microsoft 365 and outlook.com): an implementation of the class writer:tasks (package CB-4, SPEC-CATALOG-BATCH). It adds one task to one list
of the person's own Microsoft account and marks one task of it as completed through Microsoft Graph, and reads one task back. It is called only by the effect module of the tasks
word (runtime/effect_tasks.py, CB-5: the two write verbs, after the person approved the exact request) and by one read-only seam of the runtime (`task-get`, and the dry run of
the others); never by a skill, a run or a handler. THERE IS NO REMOVAL, NO MOVE AND NO CHANGE OF A LIST: the allow-list below holds GET, POST and PATCH on the list and task paths and
nothing else (L57). No due date, no note, no category and no reminder is ever sent (OPEN-CB-11).

Sources (Microsoft's own documentation, accessed 2026-10-27; what is not read there is listed under "To verify" in providers/writer/README.md):
- Create todoTask (POST /me/todo/lists/{todoTaskListId}/tasks; least privileged delegated permission Tasks.ReadWrite for a work or school and for a personal account; request headers
  Authorization and Content-Type only; 201 Created, the answer carries "@odata.etag"): https://learn.microsoft.com/en-us/graph/api/todotasklist-post-tasks?view=graph-rest-1.0
- Update todoTask (PATCH /me/todo/lists/{todoTaskListId}/tasks/{taskId}; Tasks.ReadWrite; request headers Authorization and Content-Type only: no If-Match is documented; 200 OK with the
  updated task): https://learn.microsoft.com/en-us/graph/api/todotask-update?view=graph-rest-1.0
- The todoTask resource (id; title, "A brief description of the task", no length stated; status, one of notStarted, inProgress, completed, waitingOnOthers, deferred; lastModifiedDateTime):
  https://learn.microsoft.com/en-us/graph/api/resources/todotask?view=graph-rest-1.0
- List tasks (GET /me/todo/lists/{todoTaskListId}/tasks; "some of the OData query parameters", none named, so none is sent) and the todoTaskList resource (wellknownListName):
  https://learn.microsoft.com/en-us/graph/api/todotasklist-list-tasks?view=graph-rest-1.0 and .../resources/todotasklist
No conditional write is documented for To Do, so none is sent: `task-complete` reads the task again right before the PATCH and compares its etag with the one the person approved. A change
in the few milliseconds between that read and the PATCH is not caught (to verify live).

Usage:
  uv run providers/writer/microsoft-todo.py --help
  uv run providers/writer/microsoft-todo.py --check
  uv run providers/writer/microsoft-todo.py task-get --account <address> --list <id> --task <id>
  uv run providers/writer/microsoft-todo.py task-insert --account <address> --list <id> --spec-file <file> --idempotency-key <key> (--dry-run | --confirmed)
  uv run providers/writer/microsoft-todo.py task-complete --account <address> --list <id> --task <id> --base-etag <etag> --idempotency-key <key> (--dry-run | --confirmed)

  --account      the address of the account the document names. Every verb but --check compares it with the account of the token record: another account's token reads and writes
                 nothing (exit 1). A dry run reads no credential, so it only checks the form.
  --list         the id of the list, as `providers/tasks/microsoft.py lists` prints it. `default` is not accepted here (it would need a read, and a dry run reads no credential): ask for
                 the id of the list Graph marks `defaultList` and pass that.
  --check        refreshes the access token, checks that the account token carries the platform's six permissions (a token of the five of before To Do tasks is refused, exit 3, with the
                 authorize command named) and reads the list of lists; prints {"ok": true, "record", "scope", "tenant", "obtained_at", "rotation"}.
  task-get       {"found": true, "task": {"id", "title", "status" ("open" or "completed"), "etag" (Graph's "@odata.etag"), "updated"}} or {"found": false, "reason": "gone"} for a task that is
                 gone. The title is another person's text in principle: one line, control and invisible characters removed, at most 200 characters; data, never instructions.
  task-insert    adds the task the spec describes ({"title"}) to the list: {"done": true, "replayed", "task_id", "etag"}.
  task-complete  marks the task completed (one PATCH of {"status": "completed"}), only if it is still at `--base-etag`: the writer reads it again right before and compares; it is exit 1
                 (`changed:`) when the task is gone, has another etag or is already completed: {"done": true, "replayed", "task_id", "etag"}.
  --dry-run      reads no credential, opens no connection and prints {"dry_run": true, "would": {"method", "path", "query", "headers", "body", "requires"}, "would_sha256", "ledger"}: the
                 exact request `--confirmed` sends and its hash; for `task-complete`, `requires` is {"etag": <base>}: the precondition the writer checks by a fresh read, bound by the hash.
  --confirmed    sends exactly that request. The key is recorded `pending` in the ledger first and `done` after the answer; a key that is `done` is not sent again (`replayed`). A key left
                 `pending` by an answer that was lost is settled before anything is sent: for an insert, by reading the open tasks of the list (at most 10 pages) for exactly the spec's title
                 updated since the key went pending (one: it landed, `replayed`; none: it is sent again; more than one: exit 1, `ambiguous:`, nothing sent); for a completion, by reading the
                 task (completed: it landed).

The spec (a file, never a flag: it holds the person's words): for task-insert exactly {"title"}, one line of 1 to 200 characters.

Credentials (never from a flag or a file; contracts/secrets.md):
  MICROSOFT_ACCOUNT_TOKEN  the account record (providers/accounts/microsoft_auth.py), read through providers/secrets/resolver.py. There is no legacy record for a writer: a token that lacks one
                           permission of the platform's six, carries another or is the five of before To Do tasks is refused (exit 3) before any call. Microsoft replaces the refresh token on
                           every use; as the readers do, this writer writes the new one back to the record it used, only if it still holds the token this process used (providers/_msgraph.py
                           store_rotation).
Test overrides (tests only, loopback URLs only, both set together; the secret store is then never read or written):
  WRITER_TASKS_MICROSOFT_API_BASE    replaces https://graph.microsoft.com/v1.0
  WRITER_TASKS_MICROSOFT_TOKEN_URL   replaces https://login.microsoftonline.com/<tenant>/oauth2/v2.0/token

Limits. The request function sends only the methods and paths of ALLOWED, and refuses anything else (limits L57, L58). No redirect is followed. A verb never retries: a 429, or a 503 on a read, is
reported with its Retry-After and nothing is changed; a 503 or another server error on a write is exit 4 (it may have landed) and the key stays pending. Every request has a 60-second timeout.
Prints one JSON object on stdout; diagnostics on stderr, and no title is written to stderr. Exit codes: 0 ok, 1 refused with nothing changed (the service said no, the task changed since it was
read: the message starts with `changed:`, or the lookup after a lost answer is not clear: it starts with `ambiguous:`), 2 usage, 3 not configured, 4 unknown (the request may have landed: send the
same key again).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import unicodedata
import urllib.parse
from pathlib import Path


def _shared(name: str, filename: str):
    """providers/<filename>, by path: next to this folder's parent first (the workbench), then next to this file (a copy)."""
    here = Path(__file__).resolve()
    path = next((c for c in (here.parents[1] / filename, here.parent / filename) if c.is_file()), None)
    if path is None:
        raise SystemExit(f"error: providers/{filename} is not next to this script's folder")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


msgraph = _shared("providers_msgraph", "_msgraph.py")
_tasks = _shared("providers_writer_tasks", "_writer_tasks.py")
GraphError, WriterError = msgraph.ProviderError, _tasks.WriterError
EXIT_OK, EXIT_REFUSED, EXIT_USAGE, EXIT_NOT_CONFIGURED, EXIT_UNKNOWN = (_tasks.EXIT_OK, _tasks.EXIT_REFUSED, _tasks.EXIT_USAGE, _tasks.EXIT_NOT_CONFIGURED, _tasks.EXIT_UNKNOWN)

SERVES = "writer:tasks"
IMPLEMENTATION = "microsoft-todo"
# The only requests this writer sends (limits L57 and L58): a method and a full-match pattern of the path, as the request function sees it (ids are percent-encoded). An id in a path is what
# the builders let through, percent-encoded as they send it: letters, digits, `_` and `-`, and the encoding of `=` (%3D). No dot, so `.` and `..` are not a segment, and no `/`, so a path cannot leave
# the tasks of a list. GET, POST and PATCH: no removal, no move, no change of a list.
ID = r"(?:[A-Za-z0-9_-]|%3D)+"
ALLOWED = (("GET", r"/me/todo/lists"),
           ("GET", rf"/me/todo/lists/{ID}/tasks"),
           ("GET", rf"/me/todo/lists/{ID}/tasks/{ID}"),
           ("POST", rf"/me/todo/lists/{ID}/tasks"),
           ("PATCH", rf"/me/todo/lists/{ID}/tasks/{ID}"))
LIST_LISTS, LIST_TASKS, GET_TASK, INSERT, PATCH = ALLOWED
PROFILE = msgraph.account_profile(
    run_hint="uv run <workbench>/providers/writer/microsoft-todo.py", env_prefix="WRITER_TASKS_MICROSOFT", user_agent="openhora-writer-tasks-microsoft",
    not_found="Microsoft To Do does not know the task list or the task, or it is not one of the person's",
    forbidden_hint="check that the account token carries the platform's whole set (Tasks.ReadWrite included) and that the list is one of the person's own", tasks=True)
PAGE_BYTES = 1024 * 1024
SETTLE_PAGES = 10
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
HIDDEN = ("Cc", "Cf", "Zl", "Zp", "Cs", "Co")
STATUSES = ("notStarted", "inProgress", "completed", "waitingOnOthers", "deferred")


class Lost(WriterError):
    """The request may have reached the service and its answer was lost: exit 4."""

    def __init__(self, message):
        super().__init__(message, EXIT_UNKNOWN)


def log(message: str) -> None:
    print(message, file=sys.stderr)


def line(text, limit: int = 200) -> str:
    """Third-party text on one line: invisible and control characters removed, the space folded, cut at `limit`."""
    kept = "".join(c for c in str(text if text is not None else "") if unicodedata.category(c) not in HIDDEN or c in " \t\n")
    return " ".join(CONTROL_RE.sub(" ", kept).split())[:limit]


def emit(obj: dict) -> int:
    print(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True))
    return EXIT_OK


# --- the account token ---------------------------------------------------------------------------------------------------------------------------


def secret_resolver():
    return msgraph.secret_resolver(__file__)


def keyring_module(test_mode: bool):
    return msgraph.keyring_module(PROFILE, test_mode)


class Session:
    """What a verb that talks to Graph holds: the base address, an access token, and the record's address."""

    def __init__(self, client, record: dict):
        self.client, self.record = client, record


def open_session(account=None) -> Session:
    """An access token from the account record: the whole six-permission set, or exit 3; and, when `account` is given, only when the token belongs to it (the address the document names), or
    exit 1 with nothing read or changed. There is no legacy record for a writer."""
    base, token_url, _, test_mode = msgraph.endpoints(PROFILE)
    found = msgraph.find_account_record(secret_resolver(), PROFILE, test_mode)
    if found is None:
        raise GraphError(f"no Microsoft account authorization: run {PROFILE.auth_command}, or export {PROFILE.secret} (the JSON record)", EXIT_NOT_CONFIGURED)
    record = msgraph.parse_account_record(PROFILE, found[0])
    if account is not None:
        mine = record.get("account")
        if not isinstance(mine, str) or mine.casefold() != account.casefold():
            raise WriterError("the account token belongs to another account than the one the document names: nothing was read or changed", EXIT_REFUSED)
    access, rotated = msgraph.refresh_access_token(PROFILE, token_url or msgraph.TOKEN_URL_TEMPLATE.format(tenant=record["tenant"]), record)
    record["rotation"] = msgraph.store_rotation(PROFILE, record, rotated, found[1], test_mode, secret_resolver, keyring_module)
    return Session(msgraph.GraphClient(PROFILE, base, access, test_mode), record)


# --- HTTP --------------------------------------------------------------------------------------------------------------------------


def request(entry: tuple, session: Session, path: str, query: dict, body=None, write: bool = False, url: str | None = None) -> tuple:
    """The one function that sends a request to Graph. `entry` must be a pair of ALLOWED and `path` must match its pattern; anything else is refused before a connection is opened. `url` is a
    next-page address already checked to be the request's own. Returns (status, response headers, body bytes). A failure of a write after the request could have reached Graph is Lost (exit 4)."""
    method, pattern = entry
    if entry not in ALLOWED or not re.fullmatch(pattern, path):
        raise WriterError(f"this writer does not send {method} {path}: it is not a request of its allow-list", EXIT_USAGE)
    client = session.client
    sent = {"Authorization": f"Bearer {client.token}", "Accept": "application/json", "User-Agent": PROFILE.user_agent}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        sent["Content-Type"] = "application/json; charset=utf-8"
    try:
        return msgraph.http(method, url or client.url_for(path, query), sent, data, PAGE_BYTES, what="Microsoft Graph")
    except GraphError as exc:
        if write:
            raise Lost(f"{exc}: the request may or may not have landed") from None
        raise


def failure(session: Session, status: int, headers, body: bytes, what: str):
    """The error for an answer that is not the one wanted. A write answered with a redirect or a server error may have landed (Lost)."""
    if status in (404, 409, 410):
        return WriterError(f"changed: the task or its list is not as it was read ({what}, {status})", EXIT_REFUSED, status)
    if not what.startswith("GET") and (status in msgraph.REDIRECT_STATUSES or status >= 500):      # a read changes nothing: only a write may have landed
        return Lost(f"Graph answered {status} ({what}): the request may or may not have landed")
    problem = session.client.failure(status, headers, body, what)
    return WriterError(str(problem), problem.code, status)


def json_body(body: bytes):
    try:
        found = json.loads(body)
    except ValueError:
        found = None
    return found if isinstance(found, dict) else None


# --- checking the ids and the arguments ---------------------------------------------------------------------------------------


def list_id(value) -> str:
    if value == "default":
        raise WriterError("--list is the id of the list (`providers/tasks/microsoft.py lists` prints it, and marks the default one): `default` needs a read, and a dry run reads no credential", EXIT_USAGE)
    if not isinstance(value, str) or not _tasks.LIST_ID.fullmatch(value):
        raise WriterError("--list is a To Do task list id (letters, digits, = _ and -, at most 300 characters)", EXIT_USAGE)
    return value


def task_id(value) -> str:
    if not isinstance(value, str) or not _tasks.TASK_ID.fullmatch(value):
        raise WriterError("--task is a task id (letters, digits, = _ and -)", EXIT_USAGE)
    return value


def base_etag(value) -> str:
    if not isinstance(value, str) or not _tasks.ETAG.fullmatch(value):
        raise WriterError("--base-etag is the etag the task had when it was read", EXIT_USAGE)
    return value


def idempotency_key(value) -> str:
    if not isinstance(value, str) or not _tasks.KEY.fullmatch(value):
        raise WriterError("--idempotency-key is letters, digits, dots, hyphens and underscores, at most 128 characters", EXIT_USAGE)
    return value


def tasks_path(lst: str, task=None) -> str:
    """The path of the tasks of a list, or of one task of it: ids percent-encoded."""
    root = f"/me/todo/lists/{urllib.parse.quote(lst, safe='')}/tasks"
    return root if task is None else f"{root}/{urllib.parse.quote(task, safe='')}"


# --- the requests, built without a connection -----------------------------------------------------------------------------------


def build(verb: str, args) -> dict:
    """The request a verb sends, as {"entry", "method", "path", "query", "headers", "body", "requires"}: checked arguments in, no credential, no connection. `requires` is the precondition the
    writer checks by a fresh read before it sends (the etag the person approved), part of what is hashed; it is not sent."""
    lst, key = list_id(args.list), idempotency_key(args.idempotency_key)
    _tasks.account_flag(args.account)
    if verb == "task-insert":
        spec = _tasks.read_spec(args.spec_file)
        return {"entry": INSERT, "method": "POST", "path": tasks_path(lst), "query": {}, "headers": {}, "body": {"title": spec["title"]}, "requires": None}
    task, etag = task_id(args.task), base_etag(args.base_etag)
    return {"entry": PATCH, "method": "PATCH", "path": tasks_path(lst, task), "query": {}, "headers": {}, "body": {"status": "completed"}, "requires": {"etag": etag}}


def would_of(built: dict) -> dict:
    return {k: built[k] for k in ("method", "path", "query", "headers", "body", "requires")}


# --- the task as Graph printed it ---------------------------------------------------------------------------------------------


def read_task(item) -> dict:
    """The task as `task-get` prints it. WriterError (exit 1) when Graph's answer is not a task this writer understands."""
    if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not _tasks.TASK_ID.fullmatch(item["id"]) or item.get("status") not in STATUSES:
        raise WriterError("Graph answered a task this writer does not understand")
    etag, updated = item.get("@odata.etag"), item.get("lastModifiedDateTime")
    return {"id": item["id"], "title": line(item.get("title"), 200), "status": "completed" if item["status"] == "completed" else "open",
            "etag": etag if isinstance(etag, str) and _tasks.ETAG.fullmatch(etag) else None,
            "updated": updated if isinstance(updated, str) and _tasks.stamp(updated) is not None else None}


def fetch_task(session: Session, lst: str, task: str):
    """The task as Graph holds it, or None when it is gone (404)."""
    status, headers, body = request(GET_TASK, session, tasks_path(lst, task), {})
    if status in (404, 410):
        return None
    if status != 200:
        raise failure(session, status, headers, body, "GET task")
    item = json_body(body)
    if item is None:
        raise WriterError("Graph answered something this writer does not understand")
    return item


def open_tasks(session: Session, lst: str) -> list:
    """The open tasks of a list as `read_task` prints them: the pages Graph names, each next-page address followed only when it is the request's own, at most SETTLE_PAGES pages; more is
    `ambiguous:` (nothing is sent). No OData parameter is sent: the pages read do not say which To Do takes."""
    first = session.client.url_for(tasks_path(lst), {})
    found, url, pages = [], None, 0
    while True:
        pages += 1
        status, headers, body = request(LIST_TASKS, session, tasks_path(lst), {}, url=url)
        if status != 200:
            raise failure(session, status, headers, body, "GET tasks")
        data = json_body(body)
        if data is None or not isinstance(data.get("value"), list):
            raise WriterError("Graph answered something this writer does not understand")
        found += [read_task(i) for i in data["value"] if isinstance(i, dict) and i.get("status") != "completed"]
        link = data.get("@odata.nextLink")
        if link is None:
            return found
        url = msgraph.next_page(link, first) if pages < SETTLE_PAGES else None
        if url is None:
            raise WriterError(f"ambiguous: the list has more than {SETTLE_PAGES} pages of tasks to look through: nothing was sent; look at the list and ask the person", EXIT_REFUSED)


# --- the verbs ---------------------------------------------------------------------------------------------------------------


def cmd_check(args) -> int:
    session = open_session()
    status, headers, body = request(LIST_LISTS, session, "/me/todo/lists", {})
    if status != 200:
        raise failure(session, status, headers, body, "GET task lists")
    record = session.record
    return emit({"ok": True, "record": "account", "scope": " ".join(PROFILE.scopes), "tenant": record["tenant"], "obtained_at": record.get("obtained_at"),
                 "rotation": record["rotation"]})


def cmd_task_get(args) -> int:
    lst, task = list_id(args.list), task_id(args.task)
    account = _tasks.account_flag(args.account)
    session = open_session(account)
    item = fetch_task(session, lst, task)
    if item is None:
        return emit({"found": False, "reason": "gone"})
    return emit({"found": True, "task": read_task(item)})


def settle_after_lost(session: Session, verb: str, args, entry: dict):
    """After an answer that was lost: the facts ({"task_id", "etag"}) when the request of the key landed, None when it did not (it may be sent). WriterError `ambiguous:` (exit 1) when an insert
    cannot be told apart."""
    lst = list_id(args.list)
    if verb == "task-complete":
        item = fetch_task(session, lst, task_id(args.task))
        if item is not None and item.get("status") == "completed":
            return {"task_id": item.get("id"), "etag": item.get("@odata.etag")}
        return None
    spec = _tasks.read_spec(args.spec_file)
    since = entry.get("created_at") or ""
    verdict, task = _tasks.lost_insert_verdict(open_tasks(session, lst), spec["title"], since)
    if verdict == "ambiguous":
        raise WriterError("ambiguous: more than one open task of the list has exactly this title since the earlier attempt went pending, or the time of that attempt cannot be read: nothing was "
                          "sent; look at the list and ask the person", EXIT_REFUSED)
    return {"task_id": task["id"], "etag": task["etag"]} if verdict == "found" else None


def write(verb: str, args) -> int:
    built = build(verb, args)
    would, key = would_of(built), args.idempotency_key
    digest = _tasks.sha(_tasks.canonical(would))
    operation = {"task-insert": "insert", "task-complete": "complete"}[verb]
    if args.dry_run:
        peeked = _tasks.ledger_peek(IMPLEMENTATION, key)
        return emit({"dry_run": True, "would": would, "would_sha256": digest, "ledger": (peeked or {}).get("status", "absent")})
    account = _tasks.account_flag(args.account)
    state, entry = _tasks.claim(IMPLEMENTATION, key, digest, operation)
    if state == "done":
        return emit({"done": True, "replayed": True, "task_id": entry.get("task_id"), "etag": entry.get("etag")})
    fresh = state == "new"      # this attempt made the key: until something may have been sent, a failure frees it. A key an earlier attempt left pending stays pending.
    try:
        session = open_session(account)
    except BaseException:
        if fresh:
            _tasks.settle(IMPLEMENTATION, key, "released")
        raise
    if not fresh:               # an earlier attempt's answer was lost: look in the list before anything is sent
        try:
            found = settle_after_lost(session, verb, args, entry)
        except (WriterError, GraphError) as exc:
            if str(exc).startswith("ambiguous:"):
                raise          # nothing was sent and the key stays pending: the person decides
            raise Lost(f"an earlier attempt with this key did not say whether it landed, and the list cannot be looked up now ({line(exc, 160)}): the key stays pending; send it again later") from None
        if found is not None:
            _record_done(key, found)
            return emit({"done": True, "replayed": True, **found})
    if verb == "task-complete":
        try:
            item = fetch_task(session, list_id(args.list), task_id(args.task))
        except BaseException:
            if fresh:
                _tasks.settle(IMPLEMENTATION, key, "released")
            raise
        problem = None
        if item is None:
            problem = "the task is gone"
        elif item.get("status") == "completed":
            problem = "the task is already completed"
        elif item.get("@odata.etag") != args.base_etag:
            problem = "the task is not at the etag the person approved"
        if problem:
            if fresh:
                _tasks.settle(IMPLEMENTATION, key, "released")      # nothing was sent: the key is free
            raise WriterError(f"changed: {problem}; nothing was changed", EXIT_REFUSED)
    try:
        status, headers, body = request(built["entry"], session, built["path"], built["query"], built["body"], write=True)
    except Lost:
        raise          # the key stays pending: sending it again looks in the list first
    except BaseException:
        _tasks.settle(IMPLEMENTATION, key, "released")      # nothing was sent
        raise
    if status not in (200, 201, 204):
        problem = failure(session, status, headers, body, f"{built['method']} task")
        if not isinstance(problem, Lost):
            _tasks.settle(IMPLEMENTATION, key, "released")      # the service said no: nothing changed, the key is free
        raise problem
    answer = json_body(body) or {}
    done = {"task_id": answer.get("id") if isinstance(answer.get("id"), str) else getattr(args, "task", None),
            "etag": answer.get("@odata.etag") if isinstance(answer.get("@odata.etag"), str) else None}
    _record_done(key, done)
    return emit({"done": True, "replayed": False, **done})


def _record_done(key: str, facts: dict) -> None:
    """Record the key done. A ledger that cannot be written after the request landed does not turn it into a failure: the key stays pending, and the next request with it finds the task in the
    list."""
    try:
        _tasks.settle(IMPLEMENTATION, key, "done", **{k: v for k, v in facts.items() if isinstance(v, str)})
    except (WriterError, OSError) as exc:
        log(f"warning: the request landed, and the ledger could not record it ({line(exc, 160)}): the key {key} stays pending")


VERBS = ("task-get", "task-insert", "task-complete")
FLAG_NAMES = {"account": "--account", "list": "--list", "task": "--task", "base_etag": "--base-etag", "spec_file": "--spec-file", "idempotency_key": "--idempotency-key"}
VERB_FLAGS = {"task-get": {"account", "list", "task"}, "task-insert": {"account", "list", "spec_file", "idempotency_key"},
              "task-complete": {"account", "list", "task", "base_etag", "idempotency_key"}, None: set()}


def check_flags(args) -> None:
    """A flag given to a verb that does not read it is a usage error, a required one that is missing too; --check takes no verb."""
    if args.check and args.verb:
        raise WriterError(f"--check takes no verb: run --check alone, or {args.verb} without --check", EXIT_USAGE)
    if args.check:
        extra = [flag for dest, flag in FLAG_NAMES.items() if getattr(args, dest) is not None]
        if extra:
            raise WriterError(f"{', '.join(extra)}: not a flag of --check (see --help)", EXIT_USAGE)
        return
    if not args.verb:
        raise WriterError("give a verb (task-get, task-insert, task-complete) or --check; see --help", EXIT_USAGE)
    wanted = VERB_FLAGS[args.verb]
    extra = [flag for dest, flag in FLAG_NAMES.items() if getattr(args, dest) is not None and dest not in wanted]
    if extra:
        raise WriterError(f"{', '.join(extra)}: not a flag of {args.verb} (see --help)", EXIT_USAGE)
    missing = [FLAG_NAMES[dest] for dest in wanted if getattr(args, dest) is None]
    if missing:
        raise WriterError(f"{args.verb} needs {', '.join(sorted(missing))}", EXIT_USAGE)
    if args.verb != "task-get" and bool(args.dry_run) == bool(args.confirmed):
        raise WriterError(f"{args.verb} needs exactly one of --dry-run and --confirmed", EXIT_USAGE)
    if args.verb == "task-get" and (args.dry_run or args.confirmed):
        raise WriterError("task-get is a read: it takes neither --dry-run nor --confirmed", EXIT_USAGE)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="microsoft-todo.py", description=__doc__.split("\n\n")[0], epilog=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("verb", nargs="?", choices=list(VERBS), help="the action to run")
    parser.add_argument("--check", action="store_true", help="refresh a token, check its scope and read the list of lists; prints no secret")
    parser.add_argument("--account", help="the address of the account the document names")
    parser.add_argument("--list", help="the task list id")
    parser.add_argument("--task", help="the task id")
    parser.add_argument("--base-etag", dest="base_etag", help="the etag the task had when it was read")
    parser.add_argument("--spec-file", dest="spec_file", help="the file that holds the new task ({\"title\"}) as JSON")
    parser.add_argument("--idempotency-key", dest="idempotency_key", help="the key of this one request")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="print the exact request and its hash; read no credential, open no connection")
    parser.add_argument("--confirmed", action="store_true", help="send exactly that request")
    return parser


def run(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        check_flags(args)
        if args.check:
            return cmd_check(args)
        if args.verb == "task-get":
            return cmd_task_get(args)
        return write(args.verb, args)
    except WriterError as exc:
        log(f"error: {exc}")
        return exc.code
    except GraphError as exc:
        log(f"error: {exc}")
        return exc.code
    except Exception as exc:     # last resort: no traceback, which can hold a header or a title; only the kind of the failure
        log(f"error: unexpected {type(exc).__name__}; nothing was changed")
        return EXIT_REFUSED


def main(argv=None) -> int:
    return run(argv)


if __name__ == "__main__":
    sys.exit(main())
