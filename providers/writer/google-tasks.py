#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["keyring==25.7.0"]
# ///
"""Tasks writer for Google Tasks: an implementation of the class writer:tasks (package CB-4, SPEC-CATALOG-BATCH). It adds one task to one list of the person's own Google
account and marks one task of it as completed, and reads one task back. It is called only by the effect module of the tasks word (runtime/effect_tasks.py, CB-5: the two
write verbs, after the person approved the exact request) and by one read-only seam of the runtime (`task-get`, and the dry run of the others); never by a skill, a run or
a handler. THERE IS NO REMOVAL, NO MOVE AND NO CLEARING OF COMPLETED TASKS: the allow-list below holds GET, POST and PATCH on the list and task paths and nothing else (L57).
No due date, no note and no parent is ever sent (OPEN-CB-11).

Sources (Google's own documentation, accessed 2026-10-27; what is not read there is listed under "To verify" in providers/writer/README.md):
- tasks.insert (POST https://tasks.googleapis.com/tasks/v1/lists/{tasklist}/tasks; optional `parent` and `previous`, never sent; body a Task; scope
  https://www.googleapis.com/auth/tasks): https://developers.google.com/workspace/tasks/reference/rest/v1/tasks/insert
- tasks.patch (PATCH .../tasks/{task}; "supports patch semantics"; scope tasks; the page mentions no If-Match and no etag): https://developers.google.com/workspace/tasks/reference/rest/v1/tasks/patch
- tasks.get (GET .../tasks/{task}; scopes tasks and tasks.readonly) and tasks.list (GET .../tasks; showCompleted, showHidden, showDeleted, maxResults at most 100, pageToken, updatedMin):
  https://developers.google.com/workspace/tasks/reference/rest/v1/tasks/get and .../tasks/list
- The Task resource (status "needsAction" or "completed"; title at most 1,024 characters; etag "ETag of the resource"; updated "Output only. Last modification time"; deleted):
  https://developers.google.com/workspace/tasks/reference/rest/v1/tasks
- Scopes: https://developers.google.com/workspace/tasks/auth. The default list `@default` is on no reference page; Google's Ads Scripts example uses it in the calls that list, insert and
  update tasks: https://developers.google.com/google-ads/scripts/docs/examples/google-tasks
No conditional write is documented for Tasks (no If-Match on any page read), so none is sent: `task-complete` reads the task again right before the PATCH and compares its
etag with the one the person approved. The window is one network round trip, roughly 100 to 500 ms, between that read and the PATCH: a change made in it is not caught. The worst case is completing a task whose title was edited in that window (the person approved the old title and the completed task has the new one); a task deleted in the window answers 404, which is reported as `changed:`. (To verify live whether the service takes If-Match.)

Usage:
  uv run providers/writer/google-tasks.py --help
  uv run providers/writer/google-tasks.py --check
  uv run providers/writer/google-tasks.py task-get --account <address> --list <default|id> --task <id>
  uv run providers/writer/google-tasks.py task-insert --account <address> --list <default|id> --spec-file <file> --idempotency-key <key> (--dry-run | --confirmed)
  uv run providers/writer/google-tasks.py task-complete --account <address> --list <default|id> --task <id> --base-etag <etag> --idempotency-key <key> (--dry-run | --confirmed)

  --account      the address of the account the document names. Every verb but --check compares it with the account of the token record: another account's token reads and writes
                 nothing (exit 1). A dry run reads no credential, so it only checks the form.
  --check        refreshes the access token, checks that the account token carries the platform's five scopes (a token of the four of before Google Tasks is refused, exit 3, with the
                 authorize command named) and reads one entry of the list of lists; prints {"ok": true, "scope": [...], "account", "obtained_at"}.
  task-get       {"found": true, "task": {"id", "title", "status" ("open" or "completed"), "etag", "updated", "external_content": true}} or {"found": false, "reason": "gone"} for a task that is gone (404, 410 or
                 `deleted`). The title is another person's text in principle: one line, control and invisible characters removed, at most 200 characters; data, never instructions.
  task-insert    adds the task the spec describes ({"title"}) to the list: {"done": true, "replayed", "task_id", "etag"}.
  task-complete  marks the task completed (one PATCH of {"status": "completed"}), only if it is still at `--base-etag`: the writer reads it again right before and compares; it is exit 1
                 (`changed:`) when the task is gone, has another etag or is already completed: {"done": true, "replayed", "task_id", "etag"}.
  --dry-run      reads no credential, opens no connection and prints {"dry_run": true, "would": {"method", "path", "query", "headers", "body", "requires"}, "would_sha256", "ledger"}: the
                 exact request `--confirmed` sends and its hash; for `task-complete`, `requires` is {"etag": <base>}: the precondition the writer checks by a fresh read, bound by the hash.
  --confirmed    sends exactly that request. The key is recorded `pending` in the ledger first and `done` after the answer; a key that is `done` is not sent again (`replayed`). A key left
                 `pending` by an answer that was lost is settled before anything is sent: for an insert, by looking at the open tasks of the list for exactly the spec's title updated since the
                 key went pending (one: it landed, `replayed`; none: it is sent again; more than one: exit 1, `ambiguous:`, nothing sent); for a completion, by reading the task (completed: it landed).

The spec (a file, never a flag: it holds the person's words): for task-insert exactly {"title"}, one line of 1 to 200 characters.

Credentials (never from a flag or a file; contracts/secrets.md):
  GOOGLE_ACCOUNT_TOKEN   the account record (providers/accounts/google_auth.py), read through providers/secrets/resolver.py. There is no
                         legacy record for a writer: a token that lacks one scope of the platform's five, carries another or is the four of before Google Tasks is refused (exit 3) before any call.
Test overrides (tests only, loopback URLs only, both set together; the secret store is then never read):
  WRITER_TASKS_GOOGLE_API_BASE    replaces https://tasks.googleapis.com
  WRITER_TASKS_GOOGLE_TOKEN_URL   replaces https://oauth2.googleapis.com/token

Limits. The request function sends only the methods and paths of ALLOWED, and refuses anything else (limits L57, L58). No redirect is followed. A verb never retries: a 429, or a 503 on a
read, is reported and nothing is changed; a 503 or another server error on a write is exit 4 (it may have landed) and the key stays pending. Every request has a 60-second timeout. Prints
one JSON object on stdout; diagnostics on stderr, and no title is written to stderr. Exit codes: 0 ok, 1 refused with nothing changed (the service said no, the task changed since it was
read: the message starts with `changed:`, or the lookup after a lost answer is not clear: it starts with `ambiguous:`), 2 usage, 3 not configured, 4 unknown (the request may have landed: send
the same key again).
"""
from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from http.client import HTTPException    # by name: this module's own http() function shadows the module
from pathlib import Path

SERVES = "writer:tasks"
IMPLEMENTATION = "google-tasks"
DEFAULT_API_BASE = "https://tasks.googleapis.com"
DEFAULT_TOKEN_URL = "https://oauth2.googleapis.com/token"
ENV_BASE = "WRITER_TASKS_GOOGLE_API_BASE"
ENV_TOKEN_URL = "WRITER_TASKS_GOOGLE_TOKEN_URL"
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
HTTP_TIMEOUT_SECONDS = 60
ANSWER_LIMIT_BYTES = 1024 * 1024
# The only requests this writer sends (limits L57 and L58): a method and a full-match pattern of the path, as the request function sees it (ids are percent-encoded; `@default` is the
# literal word). GET, POST and PATCH on the list and task paths: no removal, no move of a task, no clearing of completed tasks.
LIST = r"(?:@default|(?:[A-Za-z0-9_-]|%3D)+)"
TASK = r"(?:[A-Za-z0-9_-]|%3D)+"
ALLOWED = (("GET", r"/tasks/v1/users/@me/lists"),
           ("GET", rf"/tasks/v1/lists/{LIST}/tasks"),
           ("GET", rf"/tasks/v1/lists/{LIST}/tasks/{TASK}"),
           ("POST", rf"/tasks/v1/lists/{LIST}/tasks"),
           ("PATCH", rf"/tasks/v1/lists/{LIST}/tasks/{TASK}"))
LIST_LISTS, LIST_TASKS, GET_TASK, INSERT, PATCH = ALLOWED
TASK_FIELDS = "id,title,status,etag,updated,deleted"
RESULT_FIELDS = "id,etag"
SETTLE_PAGE = 100
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
HIDDEN = ("Cc", "Cf", "Zl", "Zp", "Cs", "Co")
_SECRET_VALUES: list = []   # every credential this process held: scrubbed from any text before it is printed


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


_google = _shared("providers_google_account", "_google.py")
_tasks = _shared("providers_writer_tasks", "_writer_tasks.py")
ProviderError = _tasks.WriterError
EXIT_OK, EXIT_REFUSED, EXIT_USAGE, EXIT_NOT_CONFIGURED, EXIT_UNKNOWN = (_tasks.EXIT_OK, _tasks.EXIT_REFUSED, _tasks.EXIT_USAGE, _tasks.EXIT_NOT_CONFIGURED, _tasks.EXIT_UNKNOWN)


def scrub(text: str) -> str:
    for value in _SECRET_VALUES:
        text = text.replace(value, "<hidden>")
    return _google.scrub(text)


def line(value, limit: int = 200) -> str:
    """Third-party text on one line: invisible and control characters removed, the space folded, cut at `limit`, no credential in it."""
    text = "".join(c for c in str(value if value is not None else "") if unicodedata.category(c) not in HIDDEN or c in " \t\n")
    return scrub(" ".join(CONTROL_RE.sub(" ", text).split()))[:limit]


def log(message: str) -> None:
    print(message, file=sys.stderr)


def emit(obj: dict) -> int:
    print(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True))
    return EXIT_OK


# --- configuration -----------------------------------------------------------------------------------------------------------


def endpoints() -> tuple:
    """(API base, token URL, test mode). The overrides are for tests and must be loopback URLs, both set together."""
    api, token = os.environ.get(ENV_BASE), os.environ.get(ENV_TOKEN_URL)
    if not api and not token:
        return DEFAULT_API_BASE, DEFAULT_TOKEN_URL, False
    if not (api and token):
        raise ProviderError(f"{ENV_BASE} and {ENV_TOKEN_URL} are for tests only and are set together", EXIT_USAGE)
    for name, value in ((ENV_BASE, api), (ENV_TOKEN_URL, token)):
        parsed = urllib.parse.urlparse(value)
        if parsed.scheme not in ("http", "https") or parsed.hostname not in LOOPBACK_HOSTS:
            raise ProviderError(f"{name} is for tests only and must be a loopback URL such as http://127.0.0.1:8080", EXIT_USAGE)
    return api.rstrip("/"), token, True


def secret_resolver():
    """The workbench's one secret resolver, by path: next to this file first (a copy run from a job folder), then providers/secrets/resolver.py."""
    here = Path(__file__).resolve()
    path = next((c for c in (here.parent / "resolver.py", here.parents[1] / "secrets" / "resolver.py") if c.is_file()), None)
    if path is None:
        raise ProviderError("providers/secrets/resolver.py is not next to this script nor in the workbench", EXIT_NOT_CONFIGURED)
    spec = importlib.util.spec_from_file_location("workbench_secret_resolver", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def open_session(account=None):
    """(the API base, an access token, the record) from the account record: the whole five-scope set, or exit 3; and, when `account` is given, only when the token belongs to it
    (the address the document names), or exit 1 with nothing read or changed. There is no legacy record for a writer."""
    base, token_url, test_mode = endpoints()
    loaded = _google.load_account_record(secret_resolver(), test_mode, legacy=None, error=ProviderError)
    _google.hold(*(loaded.record[k] for k in _google.RECORD_TEXTS))
    if account is not None:
        mine = loaded.record.get("account")
        if not isinstance(mine, str) or mine.casefold() != account.casefold():
            raise ProviderError("the account token belongs to another account than the one the document names: nothing was read or changed", EXIT_REFUSED)
    data = _google.refresh_access_token(token_url, loaded.record, ProviderError, tasks=True)
    _SECRET_VALUES.append(data["access_token"])
    return base, data["access_token"], loaded.record


# --- HTTP --------------------------------------------------------------------------------------------------------------------


class Lost(ProviderError):
    """The request may have reached the service and its answer was lost: exit 4."""

    def __init__(self, message):
        super().__init__(message, EXIT_UNKNOWN)


class RefuseRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: every request carries a credential to an address that was checked."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        fp.close()
        lost = Lost if req.get_method() != "GET" else ProviderError      # a write that was answered with a redirect reached the service: its outcome is not known
        raise lost(f"refusing to follow a {code} redirect on {req.get_method()} {urllib.parse.urlparse(req.full_url).path}; the request carries a credential")


OPENER = urllib.request.build_opener(RefuseRedirect)


def http(method: str, url: str, headers: dict, body, sent_on_error: bool) -> tuple:
    """One request; (status, at most ANSWER_LIMIT_BYTES + 1 bytes of the body, the Retry-After header or "") for any HTTP answer. A failure before the request could have reached
    the service is ProviderError (exit 1); one after it may have is Lost (exit 4) when `sent_on_error`."""
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    path = urllib.parse.urlparse(url).path
    unknown = Lost if sent_on_error else ProviderError
    try:
        with OPENER.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return response.status, response.read(ANSWER_LIMIT_BYTES + 1), ""
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.read(65536), line(exc.headers.get("Retry-After"), 40)
        finally:
            exc.close()
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ConnectionRefusedError) or "Name or service not known" in str(exc.reason):
            raise ProviderError(f"cannot reach Google on {method} {path}: nothing was sent") from None
        raise unknown(f"the connection to Google failed on {method} {path} ({line(exc.reason, 80)}): the request may or may not have landed") from None
    except TimeoutError:
        raise unknown(f"Google timed out on {method} {path} after {HTTP_TIMEOUT_SECONDS} s: the request may or may not have landed") from None
    except OSError as exc:
        raise unknown(f"the connection to Google failed on {method} {path} ({type(exc).__name__}): the request may or may not have landed") from None
    except (ValueError, HTTPException) as exc:
        raise unknown(f"the request {method} {path} could not be made or read ({type(exc).__name__})") from None


def request(entry: tuple, base: str, token: str, path: str, query: dict, body=None, sent_on_error: bool = False) -> tuple:
    """The one function that sends a request to the Tasks API. `entry` must be a pair of ALLOWED and `path` must match its pattern; anything else is refused before a connection is
    opened. Returns (status, body bytes, Retry-After)."""
    method, pattern = entry
    if entry not in ALLOWED or not re.fullmatch(pattern, path):
        raise ProviderError(f"this writer does not send {method} {path}: it is not a request of its allow-list", EXIT_USAGE)
    url = base + path + ("?" + urllib.parse.urlencode(query) if query else "")
    sent = {"Authorization": f"Bearer {token}", "Accept": "application/json", "User-Agent": "openhora-writer-tasks-google"}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        sent["Content-Type"] = "application/json; charset=utf-8"
    return http(method, url, sent, data, sent_on_error)


def failure(status: int, body: bytes, retry: str, what: str) -> ProviderError:
    message = ""
    try:
        error = json.loads(body).get("error")
        if isinstance(error, dict):
            message = line(error.get("message"), 160)
    except (ValueError, AttributeError):
        pass
    detail = f": {message}" if message else ""
    if status == 401:
        return ProviderError(f"Google rejected the access token ({what}){detail}; run: {_google.AUTH_COMMAND}", EXIT_NOT_CONFIGURED, status)
    if status in (404, 410):
        return ProviderError(f"changed: the task or its list is not as it was read ({what}, {status}){detail}", EXIT_REFUSED, status)
    after = f" Retry-After: {retry}." if retry else ""
    if status == 503 and not what.startswith("GET"):      # a write that got a 503 may have been taken: like any other server error, its outcome is not known
        return Lost(f"Google answered 503 ({what}){detail}.{after} The request may or may not have landed")
    if status in (429, 503):
        return ProviderError(f"Google asked to slow down ({status} on {what}){detail}.{after} Nothing was changed or retried", EXIT_REFUSED, status)
    if status == 403:
        return ProviderError(f"Google refused the request ({what}){detail}; check that the Google Tasks API is enabled and that the list is the person's own", EXIT_REFUSED, status)
    if status >= 500 and not what.startswith("GET"):      # a read changes nothing: only a write may have landed
        return Lost(f"Google answered {status} ({what}){detail}: the request may or may not have landed")
    return ProviderError(f"Google returned {status} ({what}){detail}", EXIT_REFUSED, status)


def json_body(body: bytes) -> dict:
    try:
        data = json.loads(body) if body else {}
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


# --- checking the ids and the arguments ---------------------------------------------------------------------------------------


def list_id(value) -> str:
    if value == "default" or (isinstance(value, str) and _tasks.LIST_ID.fullmatch(value)):
        return value
    raise ProviderError("--list is `default` or a Google task list id (letters, digits, = _ and -, at most 300 characters)", EXIT_USAGE)


def task_id(value) -> str:
    if not isinstance(value, str) or not _tasks.TASK_ID.fullmatch(value):
        raise ProviderError("--task is a task id (letters, digits, = _ and -)", EXIT_USAGE)
    return value


def base_etag(value) -> str:
    if not isinstance(value, str) or not _tasks.ETAG.fullmatch(value):
        raise ProviderError("--base-etag is the etag the task had when it was read", EXIT_USAGE)
    return value


def idempotency_key(value) -> str:
    if not isinstance(value, str) or not _tasks.KEY.fullmatch(value):
        raise ProviderError("--idempotency-key is letters, digits, dots, hyphens and underscores, at most 128 characters", EXIT_USAGE)
    return value


def tasks_path(lst: str, task=None) -> str:
    """The path of the tasks of a list, or of one task of it: the default list by its word `@default`, another by its percent-encoded id."""
    root = "/tasks/v1/lists/@default/tasks" if lst == "default" else f"/tasks/v1/lists/{urllib.parse.quote(lst, safe='')}/tasks"
    return root if task is None else f"{root}/{urllib.parse.quote(task, safe='')}"


# --- the requests, built without a connection -----------------------------------------------------------------------------------


def build(verb: str, args) -> dict:
    """The request a verb sends, as {"entry", "method", "path", "query", "headers", "body", "requires"}: checked arguments in, no credential, no connection. `requires` is the
    precondition the writer checks by a fresh read before it sends (the etag the person approved), part of what is hashed; it is not sent."""
    lst, key = list_id(args.list), idempotency_key(args.idempotency_key)
    _tasks.account_flag(args.account)
    if verb == "task-insert":
        spec = _tasks.read_spec(args.spec_file)
        return {"entry": INSERT, "method": "POST", "path": tasks_path(lst), "query": {"fields": RESULT_FIELDS}, "headers": {}, "body": {"title": spec["title"]}, "requires": None}
    task, etag = task_id(args.task), base_etag(args.base_etag)
    # The body MUST stay the code literal {"status": "completed"}: Google documents the removal flag of a task (the field named `deleted` in its resource) as writable, so a body built from anything else could remove a task (L57);
    # test_the_patch_body_is_the_one_code_literal pins it.
    return {"entry": PATCH, "method": "PATCH", "path": tasks_path(lst, task), "query": {"fields": RESULT_FIELDS}, "headers": {}, "body": {"status": "completed"},
            "requires": {"etag": etag}}


def would_of(built: dict) -> dict:
    return {k: built[k] for k in ("method", "path", "query", "headers", "body", "requires")}


# --- the task as the service printed it ---------------------------------------------------------------------------------------


def read_task(item) -> dict:
    """The task as `task-get` prints it. ProviderError (exit 1) when the service's answer is not a task this writer understands."""
    if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not _tasks.TASK_ID.fullmatch(item["id"]) or item.get("status") not in ("needsAction", "completed"):
        raise ProviderError("Google answered a task this writer does not understand")
    etag, updated = item.get("etag"), item.get("updated")
    return {"id": item["id"], "title": line(item.get("title"), 200), "status": "completed" if item["status"] == "completed" else "open",
            "etag": etag if isinstance(etag, str) and _tasks.ETAG.fullmatch(etag) else None,
            "updated": updated if isinstance(updated, str) and _tasks.stamp(updated) is not None else None}


def fetch_task(base: str, token: str, lst: str, task: str):
    """The task as the service holds it, or None when it is gone (404, 410, or deleted)."""
    status, body, retry = request(GET_TASK, base, token, tasks_path(lst, task), {"fields": TASK_FIELDS})
    if status in (404, 410):
        return None
    if status != 200:
        raise failure(status, body, retry, "GET task")
    item = json_body(body)
    return None if item.get("deleted") is True else item


def open_tasks(base: str, token: str, lst: str, since: str) -> list:
    """The open tasks of a list updated since `since` (RFC 3339, less the clock skew), one page of at most SETTLE_PAGE, as `read_task` prints them."""
    floor = _tasks.stamp(since)
    query = {"showCompleted": "false", "showHidden": "false", "showDeleted": "false", "maxResults": SETTLE_PAGE, "fields": "items(id,title,status,etag,updated,deleted),nextPageToken"}
    if floor is not None:
        query["updatedMin"] = (floor.replace(microsecond=0) - datetime.timedelta(seconds=_tasks.SKEW_SECONDS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    status, body, retry = request(LIST_TASKS, base, token, tasks_path(lst), query)
    if status != 200:
        raise failure(status, body, retry, "GET tasks")
    data = json_body(body)
    if data.get("nextPageToken"):
        raise ProviderError(f"ambiguous: the open tasks of the list since the key went pending are more than {SETTLE_PAGE}: nothing was sent; look at the list and ask the person", EXIT_REFUSED)
    return [read_task(i) for i in (data.get("items") if isinstance(data.get("items"), list) else []) if isinstance(i, dict) and i.get("deleted") is not True and i.get("status") == "needsAction"]


# --- the verbs ---------------------------------------------------------------------------------------------------------------


def cmd_check(args) -> int:
    base, token, record = open_session()
    status, body, retry = request(LIST_LISTS, base, token, "/tasks/v1/users/@me/lists", {"maxResults": 1, "fields": "items(id)"})
    if status != 200:
        raise failure(status, body, retry, "GET task lists")
    return emit({"ok": True, "scope": sorted(_google.PLATFORM_SCOPES), "account": record.get("account"), "obtained_at": record.get("obtained_at")})


def cmd_task_get(args) -> int:
    lst, task = list_id(args.list), task_id(args.task)
    account = _tasks.account_flag(args.account)
    base, token, _ = open_session(account)
    item = fetch_task(base, token, lst, task)
    if item is None:
        return emit({"found": False, "reason": "gone"})
    return emit({"found": True, "task": {**read_task(item), "external_content": True}})


def settle_after_lost(base: str, token: str, verb: str, args, entry: dict):
    """After an answer that was lost: the facts ({"task_id", "etag"}) when the request of the key landed, None when it did not (it may be sent). ProviderError `ambiguous:`
    (exit 1) when an insert cannot be told apart."""
    lst = list_id(args.list)
    if verb == "task-complete":
        item = fetch_task(base, token, lst, task_id(args.task))
        if item is not None and item.get("status") == "completed":
            return {"task_id": item.get("id"), "etag": item.get("etag")}
        return None
    spec = _tasks.read_spec(args.spec_file)
    verdict, task = _tasks.lost_insert_verdict(open_tasks(base, token, lst, entry.get("created_at") or ""), spec["title"], entry.get("created_at") or "")
    if verdict == "ambiguous":
        raise ProviderError("ambiguous: more than one open task of the list has exactly this title since the earlier attempt went pending, or the time of that attempt cannot be read: nothing "
                            "was sent; look at the list and ask the person", EXIT_REFUSED)
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
        base, token, _ = open_session(account)
    except BaseException:
        if fresh:
            _tasks.settle(IMPLEMENTATION, key, "released")
        raise
    if not fresh:               # an earlier attempt's answer was lost: look in the list before anything is sent
        try:
            found = settle_after_lost(base, token, verb, args, entry)
        except ProviderError as exc:
            if str(exc).startswith("ambiguous:"):
                raise          # nothing was sent and the key stays pending: the person decides
            raise Lost(f"an earlier attempt with this key did not say whether it landed, and the list cannot be looked up now ({line(exc, 160)}): the key stays pending; send it again later") from None
        if found is not None:
            _record_done(key, found)
            return emit({"done": True, "replayed": True, **found})
    if verb == "task-complete":
        try:
            item = fetch_task(base, token, list_id(args.list), task_id(args.task))
        except BaseException:
            if fresh:
                _tasks.settle(IMPLEMENTATION, key, "released")
            raise
        problem = None
        if item is None:
            problem = "the task is gone"
        elif item.get("status") == "completed":
            problem = "the task is already completed"
        elif item.get("etag") != args.base_etag:
            problem = "the task is not at the etag the person approved"
        if problem:
            if fresh:
                _tasks.settle(IMPLEMENTATION, key, "released")      # nothing was sent: the key is free
            raise ProviderError(f"changed: {problem}; nothing was changed", EXIT_REFUSED)
    try:
        status, body, retry = request(built["entry"], base, token, built["path"], built["query"], built["body"], sent_on_error=True)
    except Lost:
        raise          # the key stays pending: sending it again looks in the list first
    except BaseException:
        _tasks.settle(IMPLEMENTATION, key, "released")      # nothing was sent
        raise
    if status not in (200, 204):
        problem = failure(status, body, retry, f"{built['method']} task")
        if not isinstance(problem, Lost):
            _tasks.settle(IMPLEMENTATION, key, "released")      # the service said no: nothing changed, the key is free
        raise problem
    answer = json_body(body)
    done = {"task_id": answer.get("id") if isinstance(answer.get("id"), str) else getattr(args, "task", None), "etag": answer.get("etag") if isinstance(answer.get("etag"), str) else None}
    _record_done(key, done)
    return emit({"done": True, "replayed": False, **done})


def _record_done(key: str, facts: dict) -> None:
    """Record the key done. A ledger that cannot be written after the request landed does not turn it into a failure: the key stays pending, and the next request with it finds the
    task in the list."""
    try:
        _tasks.settle(IMPLEMENTATION, key, "done", **{k: v for k, v in facts.items() if isinstance(v, str)})
    except (ProviderError, OSError) as exc:
        log(f"warning: the request landed, and the ledger could not record it ({line(exc, 160)}): the key {key} stays pending")


VERBS = ("task-get", "task-insert", "task-complete")
FLAG_NAMES = {"account": "--account", "list": "--list", "task": "--task", "base_etag": "--base-etag", "spec_file": "--spec-file", "idempotency_key": "--idempotency-key"}
VERB_FLAGS = {"task-get": {"account", "list", "task"}, "task-insert": {"account", "list", "spec_file", "idempotency_key"},
              "task-complete": {"account", "list", "task", "base_etag", "idempotency_key"}, None: set()}


def check_flags(args) -> None:
    """A flag given to a verb that does not read it is a usage error, a required one that is missing too; --check takes no verb."""
    if args.check and args.verb:
        raise ProviderError(f"--check takes no verb: run --check alone, or {args.verb} without --check", EXIT_USAGE)
    if args.check:
        extra = [flag for dest, flag in FLAG_NAMES.items() if getattr(args, dest) is not None]
        if extra:
            raise ProviderError(f"{', '.join(extra)}: not a flag of --check (see --help)", EXIT_USAGE)
        return
    if not args.verb:
        raise ProviderError("give a verb (task-get, task-insert, task-complete) or --check; see --help", EXIT_USAGE)
    wanted = VERB_FLAGS[args.verb]
    extra = [flag for dest, flag in FLAG_NAMES.items() if getattr(args, dest) is not None and dest not in wanted]
    if extra:
        raise ProviderError(f"{', '.join(extra)}: not a flag of {args.verb} (see --help)", EXIT_USAGE)
    missing = [FLAG_NAMES[dest] for dest in wanted if getattr(args, dest) is None]
    if missing:
        raise ProviderError(f"{args.verb} needs {', '.join(sorted(missing))}", EXIT_USAGE)
    if args.verb != "task-get" and bool(args.dry_run) == bool(args.confirmed):
        raise ProviderError(f"{args.verb} needs exactly one of --dry-run and --confirmed", EXIT_USAGE)
    if args.verb == "task-get" and (args.dry_run or args.confirmed):
        raise ProviderError("task-get is a read: it takes neither --dry-run nor --confirmed", EXIT_USAGE)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="google-tasks.py", description=__doc__.split("\n\n")[0], epilog=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("verb", nargs="?", choices=list(VERBS), help="the action to run")
    parser.add_argument("--check", action="store_true", help="refresh a token, check its scope and read one list entry; prints no secret")
    parser.add_argument("--account", help="the address of the account the document names")
    parser.add_argument("--list", help="`default`, or the task list id")
    parser.add_argument("--task", help="the task id")
    parser.add_argument("--base-etag", dest="base_etag", help="the etag the task had when it was read")
    parser.add_argument("--spec-file", dest="spec_file", help="the file that holds the new task ({\"title\"}) as JSON")
    parser.add_argument("--idempotency-key", dest="idempotency_key", help="the key of this one request")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="print the exact request and its hash; read no credential, open no connection")
    parser.add_argument("--confirmed", action="store_true", help="send exactly that request")
    return parser


def main(argv=None) -> int:
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
    except ProviderError as exc:
        log(f"error: {scrub(str(exc))}")
        return exc.code
    except Exception as exc:     # last resort: no traceback, which can hold a header or a title; only the kind of the failure
        log(f"error: unexpected {type(exc).__name__}; nothing was changed")
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
