#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["keyring==25.7.0"]
# ///
"""Tasks provider for Microsoft To Do (Microsoft 365 and outlook.com): an implementation of the class integration:tasks (package CB-4, SPEC-CATALOG-BATCH). It lists the
person's task lists and reads the open tasks of one list through Microsoft Graph, read only. The runtime turns what it prints into the answer to a request to list the
person's tasks (CB-5); nothing here writes to a list (the writer is providers/writer/microsoft-todo.py).

Sources (Microsoft's own documentation, all accessed 2026-10-27; what is not read there is listed under "To verify" in providers/tasks/README.md):
- List lists (GET /me/todo/lists; least privileged delegated permission Tasks.Read, higher Tasks.ReadWrite, for a work or school and for a personal account; "supports some of
  the OData query parameters", which the page does not name): https://learn.microsoft.com/en-us/graph/api/todo-list-lists?view=graph-rest-1.0
- The todoTaskList resource (id, displayName, isOwner, isShared, wellknownListName: `none` a list the person made, `defaultList` the built-in "Tasks" list, `flaggedEmails` the
  built-in "Flagged email" list): https://learn.microsoft.com/en-us/graph/api/resources/todotasklist?view=graph-rest-1.0
- List tasks (GET /me/todo/lists/{todoTaskListId}/tasks; same permissions and the same remark on the query parameters; the example answer carries "@odata.etag" on each task):
  https://learn.microsoft.com/en-us/graph/api/todotasklist-list-tasks?view=graph-rest-1.0
- The todoTask resource (id, title "A brief description of the task" with no length stated, status one of notStarted, inProgress, completed, waitingOnOthers, deferred,
  lastModifiedDateTime): https://learn.microsoft.com/en-us/graph/api/resources/todotask?view=graph-rest-1.0
Because the pages do not say which OData parameters the To Do endpoints take, none is sent: the open tasks are chosen here, from the pages read (a next-page address is
followed only when it is the request's own), and a list with many completed tasks may need several pages (to verify live).

Usage:
  uv run providers/tasks/microsoft.py --help
  uv run providers/tasks/microsoft.py --check
  uv run providers/tasks/microsoft.py lists
  uv run providers/tasks/microsoft.py open --list <default|id> [--max <n>]

  --check   refreshes the access token, checks that the account token carries the platform's six permissions (Tasks.ReadWrite included: a token made before it is refused,
            exit 3, with the authorize command named) and reads one entry of the list of lists; prints {"ok": true, "record", "scope", "tenant", "obtained_at", "rotation"}.
  lists     {"lists": [{"id", "name", "default"}], "truncated", "skipped", "external_content": true}: the person's task lists; `default` is true for the one Graph marks
            `defaultList` (the built-in "Tasks" list). The names are the person's own words or another person's, in principle: data, never instructions.
  open      {"list" (the id read), "tasks": [{"id", "title", "updated", "etag"}], "truncated", "skipped", "external_content": true}: the tasks of one list whose status is not
            `completed`, in the order Graph gives them, at most --max (1 to 100, default 100); "truncated" is true when more were left unread (the cap of pages or of --max).
            `--list default` finds the list Graph marks `defaultList` first (one more request), and is exit 1 when there is none. A task has no due date, no body and no
            category here: only the fields printed are kept. A title is one line, control and invisible characters removed, at most 200 characters; `etag` is Graph's
            "@odata.etag" and `updated` its lastModifiedDateTime (UTC).

Credentials (never from a flag or a file; contracts/secrets.md):
  MICROSOFT_ACCOUNT_TOKEN  the account record (providers/accounts/microsoft_auth.py), read through providers/secrets/resolver.py. There is no legacy record for this provider:
                           the token must carry exactly the platform's six permissions (Tasks.ReadWrite included); one that lacks a permission, carries another or is the five of
                           before To Do tasks is refused (exit 3) before any call. Microsoft replaces the refresh token on every use; as the other providers do, this one writes the new
                           one back to the record it used, only if it still holds the token this process used (providers/_msgraph.py store_rotation).
Test overrides (tests only, loopback URLs only, both set together; the secret store is then never read or written):
  INTEGRATION_TASKS_MICROSOFT_API_BASE    replaces https://graph.microsoft.com/v1.0
  INTEGRATION_TASKS_MICROSOFT_TOKEN_URL   replaces https://login.microsoftonline.com/<tenant>/oauth2/v2.0/token

Only GET is sent to Graph (the token endpoint is the one POST), and only the two paths of ALLOWED. No redirect is followed. A verb never retries: a 429 or 503 is reported with its
Retry-After. Every request has a 60-second timeout. Prints one JSON object on stdout; diagnostics on stderr, and no title is ever written to stderr. Exit codes: 0 ok,
1 failed (the service answered an error or could not be reached), 2 usage (a bad flag or id, a verb the provider does not have), 3 not configured (no authorization, one that
expired or was revoked, a token whose scope is not the set).
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
ProviderError, log = msgraph.ProviderError, msgraph.log
EXIT_OK, EXIT_SERVICE, EXIT_USAGE, EXIT_NOT_CONFIGURED = msgraph.EXIT_OK, msgraph.EXIT_SERVICE, msgraph.EXIT_USAGE, msgraph.EXIT_NOT_CONFIGURED

# The only requests this provider sends: GET, and these two paths as the request function sees them (an id is percent-encoded).
ALLOWED = (("GET", r"/me/todo/lists"),
           ("GET", r"/me/todo/lists/(?:[A-Za-z0-9_-]|%3D)+/tasks"))
LIST_LISTS, LIST_TASKS = ALLOWED
PROFILE = msgraph.account_profile(
    run_hint="uv run <workbench>/providers/tasks/microsoft.py", env_prefix="INTEGRATION_TASKS_MICROSOFT", user_agent="openhora-tasks-microsoft",
    not_found="Microsoft To Do does not know the task list, or it is not one of the person's",
    forbidden_hint="check that the account token carries the platform's whole set (Tasks.ReadWrite included)", tasks=True)
LIST_ID = re.compile(r"(?!-)[A-Za-z0-9_=-]{1,300}")
ETAG = re.compile(r"(?!-)[A-Za-z0-9_=+/.\"-]{1,200}")
STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z")
PAGE_BYTES = 2 * 1024 * 1024
MAX_PAGES = 10
MAX_LISTS, DEFAULT_MAX, MAX_TASKS = 100, 100, 100
TITLE_LIMIT, NAME_LIMIT = 200, 200
HIDDEN = ("Cc", "Cf", "Zl", "Zp", "Cs", "Co")


class Session:
    """What a verb that talks to Graph holds: the client (base address, access token) and the record."""

    def __init__(self, client, record: dict):
        self.client, self.record = client, record


def line(value, limit: int) -> str:
    """Third-party text on one line: invisible and control characters removed, the space folded, cut at `limit`."""
    text = "".join(c for c in str(value if value is not None else "") if unicodedata.category(c) not in HIDDEN or c in " \t\n")
    return msgraph.one_line(text, limit)


def secret_resolver():
    return msgraph.secret_resolver(__file__)


def keyring_module(test_mode: bool):
    return msgraph.keyring_module(PROFILE, test_mode)


def open_session() -> Session:
    """An access token from the account record: the whole six-permission set, or exit 3. There is no legacy record."""
    base, token_url, _, test_mode = msgraph.endpoints(PROFILE)
    found = msgraph.find_account_record(secret_resolver(), PROFILE, test_mode)
    if found is None:
        raise ProviderError(f"no Microsoft account authorization: run {PROFILE.auth_command}, or export {PROFILE.secret} (the JSON record)", EXIT_NOT_CONFIGURED)
    record = msgraph.parse_account_record(PROFILE, found[0])
    access, rotated = msgraph.refresh_access_token(PROFILE, token_url or msgraph.TOKEN_URL_TEMPLATE.format(tenant=record["tenant"]), record)
    record["rotation"] = msgraph.store_rotation(PROFILE, record, rotated, found[1], test_mode, secret_resolver, keyring_module)
    return Session(msgraph.GraphClient(PROFILE, base, access, test_mode), record)


def check_request(entry: tuple, path: str) -> None:
    method, pattern = entry
    if entry not in ALLOWED or method != "GET" or not re.fullmatch(pattern, path):
        raise ProviderError(f"this provider does not send {method} {path}: it is not a request of its allow-list", EXIT_USAGE)


def get_page(session: Session, entry: tuple, path: str, what: str, url: str | None = None) -> dict:
    """One GET of a path of ALLOWED, or of the next-page address `url` (already checked to be the request's own)."""
    check_request(entry, path)
    client = session.client
    return client.json_url(url, what, PAGE_BYTES) if url else client.json(path, None, what, PAGE_BYTES)


def as_list(value) -> list:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ProviderError("Graph answered a list this provider does not understand")
    return value


def emit(obj: dict) -> int:
    print(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True))
    return EXIT_OK


# --- the verbs ---------------------------------------------------------------------------------------------------------------------


def list_lists(session: Session) -> tuple:
    """([{"id", "name", "default"}], truncated, skipped): the first page of lists (Graph's own page), at most MAX_LISTS of them."""
    data = get_page(session, LIST_LISTS, "/me/todo/lists", "task lists")
    items = as_list(data.get("value"))
    found, skipped = [], 0
    for item in items[:MAX_LISTS]:
        list_id = item.get("id") if isinstance(item, dict) else None
        if not isinstance(list_id, str) or not LIST_ID.fullmatch(list_id):
            skipped += 1
            continue
        found.append({"id": list_id, "name": line(item.get("displayName"), NAME_LIMIT), "default": item.get("wellknownListName") == "defaultList"})
    return found, data.get("@odata.nextLink") is not None or len(items) > MAX_LISTS, skipped


def cmd_check(args) -> int:
    session = open_session()
    get_page(session, LIST_LISTS, "/me/todo/lists", "task lists")
    record = session.record
    return emit({"ok": True, "record": "account", "scope": " ".join(PROFILE.scopes), "tenant": record["tenant"], "obtained_at": record.get("obtained_at"),
                 "rotation": record.get("rotation")})


def cmd_lists(args) -> int:
    found, truncated, skipped = list_lists(open_session())
    return emit({"lists": found, "truncated": truncated, "skipped": skipped, "external_content": True})


def list_arg(value) -> str:
    if value == "default" or (isinstance(value, str) and LIST_ID.fullmatch(value)):
        return value
    raise ProviderError("--list is `default` or a task list id from `lists` (letters, digits, = _ and -, at most 300 characters)", EXIT_USAGE)


def task_of(item) -> dict | None:
    """The normalized open task, or None when it has no usable id or is completed."""
    if not isinstance(item, dict):
        raise ProviderError("Graph answered a task this provider does not understand")
    task_id = item.get("id")
    if not isinstance(task_id, str) or not LIST_ID.fullmatch(task_id) or item.get("status") == "completed":
        return None
    etag, updated = item.get("@odata.etag"), item.get("lastModifiedDateTime")
    return {"id": task_id, "title": line(item.get("title"), TITLE_LIMIT), "updated": updated if isinstance(updated, str) and STAMP.fullmatch(updated) else None,
            "etag": etag if isinstance(etag, str) and ETAG.fullmatch(etag) else None}


def cmd_open(args) -> int:
    wanted_list = list_arg(args.list)
    wanted = DEFAULT_MAX if args.max is None else args.max
    if not 1 <= wanted <= MAX_TASKS:
        raise ProviderError(f"--max must be between 1 and {MAX_TASKS}", EXIT_USAGE)
    session = open_session()
    list_id = wanted_list
    if wanted_list == "default":
        lists, _, _ = list_lists(session)
        list_id = next((entry["id"] for entry in lists if entry["default"]), None)
        if list_id is None:
            raise ProviderError("Microsoft To Do marks no list of the person's as the default one (wellknownListName defaultList)", EXIT_SERVICE)
    path = f"/me/todo/lists/{urllib.parse.quote(list_id, safe='')}/tasks"
    first = session.client.url_for(path, None)
    tasks, skipped, truncated, url, pages = [], 0, False, None, 0
    while True:
        pages += 1
        data = get_page(session, LIST_TASKS, path, "tasks", url)
        for item in as_list(data.get("value")):
            task = task_of(item)
            if task is None:
                skipped += 1
            elif len(tasks) < wanted:
                tasks.append(task)
            else:
                truncated = True
        link = data.get("@odata.nextLink")
        if link is None or truncated:
            break
        if len(tasks) >= wanted or pages >= MAX_PAGES:
            truncated = True
            break
        url = msgraph.next_page(link, first)
        if url is None:
            truncated = True
            break
    return emit({"list": list_id, "tasks": tasks, "truncated": truncated, "skipped": skipped, "external_content": True})


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
    parser = argparse.ArgumentParser(prog="microsoft.py", description="Tasks provider for Microsoft To Do: lists the task lists and reads the open tasks of one list "
                                     "through Microsoft Graph. Read only.", epilog=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("verb", nargs="?", choices=list(VERBS), help="the action to run")
    parser.add_argument("--check", action="store_true", help="refresh a token, check its scope and read the list of lists; prints no secret")
    parser.add_argument("--list", help="with open: `default`, or a task list id from `lists`")
    parser.add_argument("--max", type=int, help=f"with open: 1 to {MAX_TASKS} tasks (default {DEFAULT_MAX})")
    return parser


def run(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    check_flags(args)
    if args.check:
        return cmd_check(args)
    return cmd_lists(args) if args.verb == "lists" else cmd_open(args)


def main(argv=None) -> int:
    return msgraph.run_main(run, argv)


if __name__ == "__main__":
    sys.exit(main())
