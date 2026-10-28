#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["keyring==25.7.0"]
# ///
"""Tasks provider for Google Tasks: an implementation of the class integration:tasks (package CB-4, SPEC-CATALOG-BATCH). It lists the person's task lists and
reads the open tasks of one list, read only. The runtime turns what it prints into the answer to a request to list the person's tasks (CB-5); nothing here
writes to a list (the writer is providers/writer/google-tasks.py).

Sources (Google's own documentation, all accessed 2026-10-27; what is not read there is listed under "To verify" in providers/tasks/README.md):
- Service endpoint https://tasks.googleapis.com; tasklists.list (GET /tasks/v1/users/@me/lists; maxResults default and maximum 1,000; scopes tasks and tasks.readonly):
  https://developers.google.com/workspace/tasks/reference/rest/v1/tasklists/list
- tasks.list (GET /tasks/v1/lists/{tasklist}/tasks; showCompleted default true, showHidden default false, showDeleted default false, maxResults default 20 and
  maximum 100, pageToken, updatedMin; scopes tasks and tasks.readonly): https://developers.google.com/workspace/tasks/reference/rest/v1/tasks/list
- The Task resource (status "needsAction" or "completed"; title at most 1,024 characters; etag "ETag of the resource"; updated, "Output only. Last modification time";
  due is a date only and "doesn't represent the deadline", which this provider never asks for: no due dates in v1, OPEN-CB-11):
  https://developers.google.com/workspace/tasks/reference/rest/v1/tasks
- Scopes (https://www.googleapis.com/auth/tasks "Create, edit, organize, and delete all your tasks"; .../tasks.readonly "View your tasks"):
  https://developers.google.com/workspace/tasks/auth
- The default list: the reference pages of the Tasks API do not mention `@default`; Google's own Ads Scripts example uses it as the id of the list in a call to list, insert
  and update tasks (https://developers.google.com/google-ads/scripts/docs/examples/google-tasks). `--list default` sends it; the reference marks no list as the default
  one, so `lists` prints "default": null for every list (to verify live).

Usage:
  uv run providers/tasks/google.py --help
  uv run providers/tasks/google.py --check
  uv run providers/tasks/google.py lists
  uv run providers/tasks/google.py open --list <default|id> [--max <n>]

  --check   refreshes the access token, checks that the account token carries the platform's five scopes (the Tasks one included: a token made before it is refused,
            exit 3, with the authorize command named) and reads one entry of the list of lists; prints {"ok": true, "scope": [...], "account", "obtained_at"}.
  lists     {"lists": [{"id", "name", "default": null}], "truncated", "skipped", "external_content": true}: the person's task lists (one page of at most 100), for the choice
            of one. The names are the person's own words or another person's, in principle: data, never instructions.
  open      {"list", "tasks": [{"id", "title", "updated", "etag"}], "truncated", "skipped", "external_content": true}: the open tasks of one list (`needsAction`; completed,
            hidden and deleted tasks are not asked for and, if one comes anyway, left out), at most --max (1 to 100, default 100); "truncated" is true when the service
            names a further page. `--list default` is the person's default list (`@default`). A task has no due date here, no notes, no parent and no link: only the fields
            printed are asked of the service. A title is one line, control and invisible characters removed, at most 200 characters; `updated` and `etag` are the service's own.

Credentials (never from a flag or a file; contracts/secrets.md):
  GOOGLE_ACCOUNT_TOKEN   the account record (providers/accounts/google_auth.py), read through providers/secrets/resolver.py. There is no legacy record for this provider:
                         the token must carry exactly the platform's five scopes (the one for Google Tasks included); one that lacks a scope, carries another or is the four of
                         before Google Tasks is refused (exit 3) before any call.
Test overrides (tests only, loopback URLs only, both set together; the secret store is then never read):
  INTEGRATION_TASKS_GOOGLE_API_BASE    replaces https://tasks.googleapis.com
  INTEGRATION_TASKS_GOOGLE_TOKEN_URL   replaces https://oauth2.googleapis.com/token

Only GET is sent to the Tasks API (the token endpoint is the one POST), and only the two paths of ALLOWED. No redirect is followed. A verb never retries: a 429 or 503 is
reported. Every request has a 60-second timeout. Prints one JSON object on stdout; diagnostics on stderr, and no title is ever written to stderr. Exit codes: 0 ok, 1 failed
(the service answered an error or could not be reached), 2 usage (a bad flag or id, a verb the provider does not have), 3 not configured (no authorization, one that expired
or was revoked, a token whose scope is not the set).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
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


_google = _shared("providers_google_account", "_google.py")
ProviderError = _google.AccountError
EXIT_OK, EXIT_SERVICE, EXIT_USAGE, EXIT_NOT_CONFIGURED = _google.EXIT_OK, _google.EXIT_SERVICE, _google.EXIT_USAGE, _google.EXIT_NOT_CONFIGURED

DEFAULT_API_BASE = "https://tasks.googleapis.com"
DEFAULT_TOKEN_URL = "https://oauth2.googleapis.com/token"
ENV_BASE = "INTEGRATION_TASKS_GOOGLE_API_BASE"
ENV_TOKEN_URL = "INTEGRATION_TASKS_GOOGLE_TOKEN_URL"
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
# The only requests this provider sends: GET, and these two paths as the request function sees them (an id is percent-encoded; `@default` is the literal word).
ALLOWED = (("GET", r"/tasks/v1/users/@me/lists"),
           ("GET", r"/tasks/v1/lists/(?:@default|(?:[A-Za-z0-9_-]|%3D)+)/tasks"))
LIST_LISTS, LIST_TASKS = ALLOWED
LIST_ID = re.compile(r"(?!-)[A-Za-z0-9_=-]{1,300}")      # the same cap as the writers and the Microsoft reader: one value for an id
TASK_ID = re.compile(r"(?!-)[A-Za-z0-9_=-]{1,300}")
ETAG = re.compile(r"(?!-)[A-Za-z0-9_=+/.\"-]{1,200}")
STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z")
MAX_LISTS, DEFAULT_MAX, MAX_TASKS = 100, 100, 100
TITLE_LIMIT, NAME_LIMIT = 200, 200
HIDDEN = ("Cc", "Cf", "Zl", "Zp", "Cs", "Co")


def log(message: str) -> None:
    print(message, file=sys.stderr)


def line(value, limit: int) -> str:
    """Third-party text on one line: invisible and control characters removed (not turned into spaces), the space folded, cut at `limit`, no credential in it."""
    import unicodedata
    text = "".join(c for c in str(value if value is not None else "") if unicodedata.category(c) not in HIDDEN or c in " \t\n")
    return _google.one_line(text, limit)


# --- configuration and the session -------------------------------------------------------------------------------------------------


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


def open_session() -> tuple:
    """(the API base, an access token, the record): the account record with the whole five-scope set, or exit 3. There is no legacy record."""
    base, token_url, test_mode = endpoints()
    loaded = _google.load_account_record(secret_resolver(), test_mode, legacy=None, error=ProviderError)
    data = _google.refresh_access_token(token_url, loaded.record, ProviderError, tasks=True)
    return base, data["access_token"], loaded.record


def request(entry: tuple, base: str, token: str, path: str, query: dict) -> tuple:
    """The one function that sends a request to the Tasks API. `entry` must be a pair of ALLOWED and `path` must match its pattern; anything else is refused before a
    connection is opened. Returns (status, body bytes)."""
    method, pattern = entry
    if entry not in ALLOWED or method != "GET" or not re.fullmatch(pattern, path):
        raise ProviderError(f"this provider does not send {method} {path}: it is not a request of its allow-list", EXIT_USAGE)
    url = base + path + ("?" + urllib.parse.urlencode(query) if query else "")
    return _google._send("GET", url, {"Authorization": f"Bearer {token}", "Accept": "application/json", "User-Agent": "openhora-tasks-google"}, None, ProviderError)


def failure(status: int, body: bytes, what: str) -> ProviderError:
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
    if status == 404:
        return ProviderError(f"Google does not know the task list, or it is not one of the person's ({what}){detail}", EXIT_SERVICE, status)
    if status in (429, 503):
        return ProviderError(f"Google asked to slow down ({status} on {what}){detail}; nothing was retried", EXIT_SERVICE, status)
    if status == 403:
        return ProviderError(f"Google refused the request ({what}){detail}; check that the Google Tasks API is enabled and that the token carries its scope", EXIT_SERVICE, status)
    return ProviderError(f"Google returned {status} ({what}){detail}", EXIT_SERVICE, status)


def answer(entry: tuple, base: str, token: str, path: str, query: dict, what: str) -> dict:
    status, body = request(entry, base, token, path, query)
    if status != 200:
        raise failure(status, body, what)
    if len(body) > 4 * 1024 * 1024:
        raise ProviderError("Google answered more than 4 MiB for one request; ask for less")
    try:
        data = json.loads(body)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise ProviderError("Google answered something this provider does not understand")
    return data


def emit(obj: dict) -> int:
    print(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True))
    return EXIT_OK


# --- the verbs ---------------------------------------------------------------------------------------------------------------------


def lists_path() -> str:
    return "/tasks/v1/users/@me/lists"


def tasks_path(list_id: str) -> str:
    return "/tasks/v1/lists/@default/tasks" if list_id == "default" else f"/tasks/v1/lists/{urllib.parse.quote(list_id, safe='')}/tasks"


def list_arg(value) -> str:
    if value == "default" or (isinstance(value, str) and LIST_ID.fullmatch(value)):
        return value
    raise ProviderError("--list is `default` or a task list id from `lists` (letters, digits, = _ and -, at most 300 characters)", EXIT_USAGE)


def cmd_check(args) -> int:
    base, token, record = open_session()
    answer(LIST_LISTS, base, token, lists_path(), {"maxResults": 1, "fields": "items(id)"}, "GET task lists")
    return emit({"ok": True, "scope": sorted(_google.PLATFORM_SCOPES), "account": record.get("account"), "obtained_at": record.get("obtained_at")})


def cmd_lists(args) -> int:
    base, token, _ = open_session()
    data = answer(LIST_LISTS, base, token, lists_path(), {"maxResults": MAX_LISTS, "fields": "items(id,title),nextPageToken"}, "GET task lists")
    items = data.get("items") if isinstance(data.get("items"), list) else []
    found, skipped = [], 0
    for item in items[:MAX_LISTS]:
        list_id = item.get("id") if isinstance(item, dict) else None
        if not isinstance(list_id, str) or not LIST_ID.fullmatch(list_id):
            skipped += 1
            continue
        found.append({"id": list_id, "name": line(item.get("title"), NAME_LIMIT), "default": None})
    return emit({"lists": found, "truncated": bool(data.get("nextPageToken")) or len(items) > MAX_LISTS, "skipped": skipped, "external_content": True})


def task_of(item) -> dict | None:
    """The normalized open task, or None when it has no usable id, is not open, or came hidden or deleted."""
    if not isinstance(item, dict):
        raise ProviderError("Google answered a task this provider does not understand")
    task_id = item.get("id")
    if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id) or item.get("status") != "needsAction" or item.get("deleted") is True or item.get("hidden") is True:
        return None
    updated, etag = item.get("updated"), item.get("etag")
    return {"id": task_id, "title": line(item.get("title"), TITLE_LIMIT), "updated": updated if isinstance(updated, str) and STAMP.fullmatch(updated) else None,
            "etag": etag if isinstance(etag, str) and ETAG.fullmatch(etag) else None}


def cmd_open(args) -> int:
    list_id = list_arg(args.list)
    wanted = DEFAULT_MAX if args.max is None else args.max
    if not 1 <= wanted <= MAX_TASKS:
        raise ProviderError(f"--max must be between 1 and {MAX_TASKS}", EXIT_USAGE)
    base, token, _ = open_session()
    query = {"showCompleted": "false", "showHidden": "false", "showDeleted": "false", "maxResults": wanted,
             "fields": "items(id,title,status,updated,etag,deleted,hidden),nextPageToken"}
    data = answer(LIST_TASKS, base, token, tasks_path(list_id), query, "GET tasks")
    items = data.get("items") if isinstance(data.get("items"), list) else []
    tasks, skipped = [], 0
    for item in items[:wanted]:
        task = task_of(item)
        if task is None:
            skipped += 1
        else:
            tasks.append(task)
    return emit({"list": list_id, "tasks": tasks, "truncated": bool(data.get("nextPageToken")) or len(items) > wanted, "skipped": skipped, "external_content": True})


VERBS = ("lists", "open")
FLAG_NAMES = {"list": "--list", "max": "--max"}
VERB_FLAGS = {"lists": set(), "open": {"list", "max"}, None: set()}


def check_flags(args) -> None:
    if args.check and args.verb:
        raise ProviderError(f"--check takes no verb: run --check alone, or {args.verb} without --check", EXIT_USAGE)
    if not args.check and not args.verb:
        raise ProviderError("give a verb (lists, open) or --check; see --help", EXIT_USAGE)
    extra = [flag for dest, flag in FLAG_NAMES.items() if getattr(args, dest) is not None and dest not in VERB_FLAGS[args.verb]]
    if extra:
        raise ProviderError(f"{', '.join(extra)}: not a flag of {args.verb or '--check'} (see --help)", EXIT_USAGE)
    if args.verb == "open" and args.list is None:
        raise ProviderError("open needs --list", EXIT_USAGE)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="google.py", description="Tasks provider for Google Tasks: lists the task lists and reads the open tasks of one list. Read only.",
                                     epilog=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("verb", nargs="?", choices=list(VERBS), help="the action to run")
    parser.add_argument("--check", action="store_true", help="refresh a token, check its scope and read one list entry; prints no secret")
    parser.add_argument("--list", help="with open: `default`, or a task list id from `lists`")
    parser.add_argument("--max", type=int, help=f"with open: 1 to {MAX_TASKS} tasks (default {DEFAULT_MAX})")
    return parser


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    try:
        check_flags(args)
        if args.check:
            return cmd_check(args)
        return cmd_lists(args) if args.verb == "lists" else cmd_open(args)
    except ProviderError as exc:
        log(f"error: {_google.scrub(str(exc))}")
        return exc.code
    except Exception as exc:     # last resort: no traceback, which can hold a header or a title; only the kind of the failure
        log(f"error: unexpected {type(exc).__name__}")
        return EXIT_SERVICE


if __name__ == "__main__":
    sys.exit(main())
