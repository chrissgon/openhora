#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["keyring==25.7.0"]
# ///
"""Documents provider on Notion: an implementation of the class integration:documents in which each document of a
project is a page of the person's workspace, under one parent page.

The parent is `parent` of the project configuration's `documents` object: the identifier of a page the integration
was given. A document is created as a page under it, titled by its project-relative path; its id is the page's
identifier. A write converts the Markdown with notion_blocks.to_blocks (next to this file) and replaces every child
block of the page: the new blocks are appended first, at most 100 per call, a block's own children in later calls
under it, then the old blocks are deleted, so a write that fails never leaves the page empty. A read lists the
children at every depth and converts them with notion_blocks.to_markdown: what comes back is the round trip of what
was written (notion_blocks.py says what changes on the way), not the same bytes. Comments are the open comments the
service lists for the page and for each of its blocks (a comment on a block is listed under that block only): `read`
lists them all; `comments` lists the page's own, in one listing, whatever the version.

A write prints `expected_sha256` too, in its dry run as well (which makes no call): the sha256 of the text `read` prints
after it, notion_blocks.round_trip of the Markdown given, so a caller can tell its own write from a person's edit when it
does not hold the page `read` printed after the write (the answer was lost, or the listing lagged behind the write).

A notice (write --notice, the verb notice) is the page's first block: a callout with this provider's icon (NOTICE_ICON)
and the notice's text, written by the runtime. A write with --notice keeps a notice with the same text and adds one
where there is none (inserted at the start, the append call's position "start"); `notice` adds it to a page that has
none and touches nothing else; `read` leaves it out of markdown and prints its text as `notice` (null when the first
block is not one).

`version` is the page's last_edited_time, and `stat` retrieves the page object only. It covers the content: measured
on the live service (README.md, "Measured on the live service"), it is rounded to the minute and a comment does not
move it; the stand-in service of the tests does the same.

Usage:
  uv run providers/documents/notion.py --help
  uv run providers/documents/notion.py --check --config-file <f>
  uv run providers/documents/notion.py stat  --config-file <f> --id <id>
  uv run providers/documents/notion.py read  --config-file <f> --id <id>
  uv run providers/documents/notion.py read  --id <id> --as-source
  uv run providers/documents/notion.py comments --config-file <f> --id <id>
  uv run providers/documents/notion.py write --config-file <f> [--id <id>] --path <project-relative path>
                                       --markdown-file <f> --idempotency-key <k> [--notice <text>]
                                       (--dry-run | --confirmed)
  uv run providers/documents/notion.py notice --config-file <f> --id <id> --text <text> (--dry-run | --confirmed)
  uv run providers/documents/notion.py resolve --config-file <f> [--parent <page id>] --idempotency-key <k>
                                       (--id <id> | --not-created) (--dry-run | --confirmed)
  uv run providers/documents/notion.py page-create --config-file <f> --parent <page id> --title <text>
                                       --markdown-file <f> --idempotency-key <k> (--dry-run | --confirmed)
  uv run providers/documents/notion.py table-read --config-file <f> --id <data source id>
  uv run providers/documents/notion.py table-create --config-file <f> --parent <page id> --title <text>
                                       --table-file <json> --idempotency-key <k> (--dry-run | --confirmed)
  uv run providers/documents/notion.py rows-append --config-file <f> --id <data source id> --table-file <json>
                                       --schema-sha256 <hash> --idempotency-key <k> (--dry-run | --confirmed)

The outputs of a task (package NOTION-OUT; runtime/effect_write.py is the only caller of the three that write): `page-create` makes
a page under the page `--parent` (any page the integration was given, not only the configured parent), titled `--title`, with the
Markdown as its body; `table-create` makes a database under `--parent` with the columns and rows of the table file and fills it;
`rows-append` adds the rows of the table file to an existing data source after checking that its columns are the file's (and that
its whole schema hashes to `--schema-sha256`, when given); `table-read` prints the data source's columns, the hash of them, its
row count and the time of its newest edit, and changes nothing. The table file is described in notion_tables.py: at most 500 rows
and 30 columns, a text of at most 2,000 characters. These verbs retry a 429 and a 529 (up to 4 times, waiting the `Retry-After`
the service names, at most 60 s) and keep to 2.8 calls a second, under the 3 a second of a workspace that is not on a Business or
Enterprise plan; the verbs above never retry. Idempotency, per operation and per row: the key is recorded in the ledger before
the call and marked done after it (a page or a database under its parent; a row under its data source, as `<key>/row-<n>`); a row
whose outcome is unknown (a lost answer, a timeout, a 5xx) is looked for in the table on the next run (a row created since the
attempt began, holding exactly the row's values, that no other row of the ledger claims) and written only if it is not there; a
page or a database whose outcome is unknown is looked for the same way among its parent's children (exactly one with the title,
created since), and, when there is none or more than one, the key stays pending until `resolve`. A dry run of these verbs reads
the ledger and prints what a run would do, and makes no call and reads no credential.

`read --as-source` reads a page the person chose as a SOURCE of the project (runtime/sources.py, decision D13), not a document of the
project: it takes no --config-file (a page chosen as a source has no parent in the project's documents object), and it uses a
SEPARATE secret, NOTION_SOURCES_TOKEN, the token of an integration that can only read content and was given only the pages chosen
as sources (secret S7). It never uses NOTION_TOKEN, which can write. It prints the page's text and version, and no comments: a
source is the page's content, and the integration needs no comment capability. No other verb takes --as-source.

--config-file is a JSON file holding the documents object, whole: {"provider": "notion", "parent": "<page id>",
"expires": "YYYY-MM-DD"}. An id that is not a page identifier names no document (exit 1).

At most one page per idempotency key: the key is recorded as pending in the local ledger, under a file lock, before
the creation, and as done after it, so a second write with the key writes to the page it created. A creation whose
outcome is unknown (a timeout, a 5xx, a 408, a 429) leaves the key pending, and the key blocks every new attempt until
resolve records what the person found (--id) or releases it (--not-created). The ledger lives in the data folder
(~/Library/Application Support/ai-workbench/ on macOS, $XDG_DATA_HOME/ai-workbench/ or ~/.local/share/ai-workbench/
elsewhere), mode 0600.

Environment:
  NOTION_TOKEN                             the integration's token, read only through providers/secrets/resolver.py
                                           (else the OS secret store, username notion); never printed
  NOTION_SOURCES_TOKEN                     the read-only integration of `read --as-source` (else the OS secret store, username
                                           notion-sources); the only token that verb uses
  INTEGRATION_DOCUMENTS_NOTION_LEDGER      another ledger file (an absolute path)
  INTEGRATION_DOCUMENTS_NOTION_API_BASE    tests only: a loopback URL that replaces the service's address; the
                                           secret store is then never read

No redirect is followed: every request carries the token. Too many requests (429) or a 5xx: exit 1 with the status
on stderr; the verbs that write or read a page never retry (those of the outputs above do). A dry run reads no credential and makes no call.

Prints one JSON object on stdout; diagnostics on stderr. Exit codes: 0 ok, 1 failed (the service answered an error
or could not be reached, a document that does not exist), 2 usage (a path that is absolute, holds "..", or does not
end in .md, a write without --dry-run or --confirmed), 3 not configured (no config file, no parent, no token, a token
the service rejects, a parent the integration was not given).
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# The one table of the service. Every call and header this file makes, from the public API reference
# (README.md, "Calls this provider makes"); a correction is one line here.
API_VERSION = "2026-03-11"
DEFAULT_API_BASE = "https://api.notion.com"
CALLS = {
    "retrieve_page": ("GET", "/v1/pages/{id}"),
    "create_page": ("POST", "/v1/pages"),
    "list_children": ("GET", "/v1/blocks/{id}/children"),
    "append_children": ("PATCH", "/v1/blocks/{id}/children"),
    "delete_block": ("DELETE", "/v1/blocks/{id}"),
    "list_comments": ("GET", "/v1/comments"),
    "create_database": ("POST", "/v1/databases"),
    "retrieve_database": ("GET", "/v1/databases/{id}"),
    "retrieve_base": ("GET", "/v1/data_sources/{id}"),
    "query_base": ("POST", "/v1/data_sources/{id}/query"),
}
PAGE_SIZE = 100  # the maximum of every paginated call
MAX_CHILDREN_PER_CALL = 100  # append: children per request
MAX_PAGES = 1000  # a longer chain of cursors is treated as a service error
TEXT_LIMIT = 2000  # characters of one text object
HTTP_TIMEOUT_SECONDS = 30
LOCK_TIMEOUT_SECONDS = 10
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
UNKNOWN_OUTCOME = (408, 429)  # with every 5xx: the request may have been carried out
RETRY_STATUSES = (429, 529)  # the verbs of the outputs retry these and only these, with the service's Retry-After
RETRY_MAX = 4  # retries of one call, after the first attempt
RETRY_WAIT_CAP = 60  # seconds: the service's Retry-After for a connection is at most 60
PACE_SECONDS = 0.35  # between two calls of the verbs of the outputs: 2.8 a second, under the 3 a second of the plans without a Business tier
ADOPT_SKEW_SECONDS = 120  # a row, page or database created this long before the attempt began still counts as made by it (clock skew)
TABLE_ROWS_MAX = 2000  # table-read counts a table's rows by listing them: a longer table is refused (21 calls at most)

ENV_BASE = "INTEGRATION_DOCUMENTS_NOTION_API_BASE"
ENV_LEDGER = "INTEGRATION_DOCUMENTS_NOTION_LEDGER"
SECRET = "NOTION_TOKEN"
KEYRING_USERNAME = "notion"
SOURCES_SECRET = "NOTION_SOURCES_TOKEN"   # the separate, read-only secret of `read --as-source` (secret S7)
SOURCES_USERNAME = "notion-sources"
LEDGER_NAME = "documents-notion.json"
EXIT_OK, EXIT_SERVICE, EXIT_USAGE, EXIT_NOT_CONFIGURED = 0, 1, 2, 3

NOTICE_ICON = "\U0001F512"  # the icon that marks the runtime's notice among a page's callouts
NOTICE_COLOR = "gray_background"
NOTION_ID = re.compile(r"[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
SIDE = ".comments.md"


def load_blocks():
    """The block helper, next to this file."""
    path = Path(__file__).resolve().parent / "notion_blocks.py"
    spec = importlib.util.spec_from_file_location("notion_blocks_for_documents", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


nb = load_blocks()


def load_tables():
    """The pure half of the tables, next to this file."""
    path = Path(__file__).resolve().parent / "notion_tables.py"
    spec = importlib.util.spec_from_file_location("notion_tables_for_documents", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


nt = load_tables()


class ProviderError(Exception):
    def __init__(self, message: str, code: int = EXIT_SERVICE, status: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.retry_after = retry_after


def emit(data: dict) -> int:
    print(json.dumps(data, ensure_ascii=False, sort_keys=True))
    return EXIT_OK


def one_line(text, limit: int = 200) -> str:
    cleaned = "".join(ch if ch.isprintable() else " " for ch in str(text))
    return " ".join(cleaned.split())[:limit]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")




def notion_id(value, what: str, code: int = EXIT_USAGE) -> str:
    if not isinstance(value, str) or not NOTION_ID.fullmatch(value.strip().lower()):
        raise ProviderError(f"{what} is a page identifier: 32 hexadecimal characters, with or without hyphens",
                            code)
    return value.strip().lower()



def api_base() -> tuple[str, bool]:
    """(base URL, test mode). The override is for tests only and must be a loopback URL."""
    override = os.environ.get(ENV_BASE)
    if not override:
        return DEFAULT_API_BASE, False
    parsed = urllib.parse.urlparse(override)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ProviderError(f"{ENV_BASE} is for tests only and must be a loopback URL such as http://127.0.0.1:8080",
                            EXIT_USAGE)
    return override.rstrip("/"), True


def secret_resolver():
    """The workbench's secret resolver, by path: next to this file first (a copy run from a job folder), then
    providers/secrets/resolver.py."""
    here = Path(__file__).resolve()
    candidates = (here.parent / "resolver.py", here.parents[1] / "secrets" / "resolver.py")
    path = next((c for c in candidates if c.is_file()), None)
    if path is None:
        raise ProviderError("providers/secrets/resolver.py is not next to this script nor in the workbench",
                            EXIT_NOT_CONFIGURED)
    spec = importlib.util.spec_from_file_location("workbench_secret_resolver", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_token(test_mode: bool, secret: str = SECRET, username: str = KEYRING_USERNAME) -> str:
    found = secret_resolver().resolve(secret, allow_store=not test_mode)
    token = found[0] if found else ""
    if not token:
        raise ProviderError(f"no Notion token: export {secret}, or store one with "
                            f"uv run --with keyring==25.7.0 keyring set openhora {username}",
                            EXIT_NOT_CONFIGURED)
    if any(ch.isspace() or not ch.isprintable() for ch in token):
        raise ProviderError("the Notion token contains whitespace or control characters", EXIT_NOT_CONFIGURED)
    return token



# --- HTTP ----------------------------------------------------------------------


class RefuseRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: every request carries the token to an address that was checked."""

    def redirect_request(self, req, fp, code, msg, hdrs, newurl):
        fp.close()
        path = urllib.parse.urlparse(req.full_url).path
        raise ProviderError(f"refusing to follow a {code} redirect on {req.get_method()} {path}; "
                            "the request carries the Notion token", EXIT_SERVICE, code)


OPENER = urllib.request.build_opener(RefuseRedirect)


class Service:
    def __init__(self, secret: str = SECRET, username: str = KEYRING_USERNAME, bulk: bool = False):
        """bulk: the verbs of the outputs, which retry a 429 or a 529 and keep to PACE_SECONDS between calls (in the tests, which
        reach the loopback stand-in only, neither waits more than a few hundredths of a second)."""
        self.base, test_mode = api_base()
        self.token = load_token(test_mode, secret, username)
        self.retries = RETRY_MAX if bulk else 0
        self.pace = (0.0 if test_mode else PACE_SECONDS) if bulk else 0.0
        self.test_mode = test_mode
        self.last_call = 0.0

    def call(self, name: str, ident: str | None = None, body=None, query=None) -> dict:
        for attempt in range(self.retries + 1):
            if self.pace:
                wait = self.last_call + self.pace - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
            try:
                return self.call_once(name, ident, body, query)
            except ProviderError as exc:
                if exc.status in RETRY_STATUSES and attempt < self.retries:
                    time.sleep(0.05 if self.test_mode else min(max(exc.retry_after or 1.0, 1.0) * (1 + attempt / 4), RETRY_WAIT_CAP))
                    continue
                raise
            finally:
                self.last_call = time.monotonic()
        raise AssertionError("unreachable")

    def call_once(self, name: str, ident: str | None = None, body=None, query=None) -> dict:
        method, template = CALLS[name]
        path = template.replace("{id}", ident or "")
        url = self.base + path + ("?" + urllib.parse.urlencode(query) if query else "")
        hdrs = {"Authorization": f"Bearer {self.token}", "Notion-Version": API_VERSION,
                "Accept": "application/json", "User-Agent": "openhora-documents-notion"}
        data = None
        if body is not None:
            hdrs["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method, headers=hdrs)
        where = f"{method} {template}"
        try:
            with OPENER.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                answer = json.loads(exc.read(65536))
                detail = f": {one_line(answer.get('code', ''))} {one_line(answer.get('message', ''))}".rstrip()
            except (ValueError, AttributeError, OSError):
                pass
            retry = exc.headers.get("Retry-After") if exc.headers else None
            if retry:
                detail += f" (Retry-After {one_line(retry, 20)} s)"
            try:
                seconds = float(retry) if retry else None
            except ValueError:
                seconds = None
            code = EXIT_NOT_CONFIGURED if exc.code == 401 else EXIT_SERVICE
            raise ProviderError(f"Notion returned {exc.code} on {where}{detail}", code, exc.code, seconds) from None
        except urllib.error.URLError as exc:
            raise ProviderError(f"cannot reach Notion on {where}: {one_line(exc.reason)}") from None
        except TimeoutError:
            raise ProviderError(f"Notion timed out on {where} after {HTTP_TIMEOUT_SECONDS} s") from None
        except OSError as exc:
            raise ProviderError(f"the connection to Notion failed on {where}: {type(exc).__name__}") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ProviderError(f"the answer to {where} is over {MAX_RESPONSE_BYTES} bytes")
        try:
            out = json.loads(raw)
        except ValueError:
            raise ProviderError(f"the answer to {where} is not JSON") from None
        if not isinstance(out, dict):
            raise ProviderError(f"the answer to {where} is not an object")
        return out

    def paged(self, name: str, ident: str | None = None, query=None) -> tuple[list, bool]:
        """Every result of a paginated call; (results, truncated)."""
        out, cursor = [], None
        for _ in range(MAX_PAGES):
            answer = self.call(name, ident, query={**(query or {}), "page_size": PAGE_SIZE,
                                                   **({"start_cursor": cursor} if cursor else {})})
            results = answer.get("results")
            if not isinstance(results, list):
                raise ProviderError(f"the answer to {CALLS[name][0]} {CALLS[name][1]} has no results list")
            out += results
            if not answer.get("has_more"):
                return out, False
            cursor = answer.get("next_cursor")
            if not isinstance(cursor, str) or not cursor:
                raise ProviderError(f"the answer to {CALLS[name][0]} {CALLS[name][1]} has more and no cursor")
        return out, True

    def blocks(self, ident: str) -> list:
        """The children of a block at every depth: a block's children go in its body's "children"."""
        out = self.paged("list_children", ident)[0]
        for b in out:
            if b.get("has_children") and isinstance(b.get("type"), str):
                b.setdefault(b["type"], {})["children"] = self.blocks(b["id"])
        return out

    def append(self, parent: str, blocks: list, first: bool = False) -> None:
        """Append blocks under a parent, at most MAX_CHILDREN_PER_CALL per call. A block is sent without its children
        (a table keeps its rows, one level); the children are appended under the block the answer names. first: the
        blocks (at most one call's worth) go before the parent's other children (position "start")."""
        if first and (len(blocks) > MAX_CHILDREN_PER_CALL or any(b[b["type"]].get("children") for b in blocks)):
            raise ProviderError("at most one call's worth of blocks, with no children, goes at the start", EXIT_USAGE)
        for start in range(0, len(blocks), MAX_CHILDREN_PER_CALL):
            batch, later = [], []
            for b in blocks[start:start + MAX_CHILDREN_PER_CALL]:
                kind = b["type"]
                body = dict(b[kind])
                kids = [] if kind == "table" else body.pop("children", None) or []
                batch.append({**b, kind: body})
                later.append(kids)
            body = {"children": batch, **({"position": {"type": "start"}} if first else {})}
            made = self.call("append_children", parent, body=body).get("results")
            if first and isinstance(made, list):
                # Measured live (README.md, N12): the answer to an append at the start does not list only the
                # blocks it made, so it is not read; blocks put at the start have no children to append under them.
                continue
            if not isinstance(made, list) or len(made) != len(batch):
                raise ProviderError("the answer to an append does not list the blocks it made; the body may be "
                                    "incomplete, write it again")
            for block, kids in zip(made, later):
                if kids:
                    self.append(notion_id(block.get("id"), "a block's id", EXIT_SERVICE), kids)

    def replace_body(self, page: str, blocks: list, notice=None) -> None:
        """The new body first, then the old blocks deleted: a failure never leaves the page empty. With a notice,
        a first block that is that notice is kept, and where there is none the notice is put at the start first."""
        listed = self.paged("list_children", page)[0]
        keep = listed[0]["id"] if notice is not None and listed and notice_of(listed[0]) == notice else None
        if notice is not None and keep is None:
            self.append(page, [notice_block(notice)], first=True)
        self.append(page, blocks)
        for ident in [b["id"] for b in listed if b["id"] != keep]:
            self.call("delete_block", ident)




# --- the idempotency ledger ------------------------------------------------------


def data_home() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ai-workbench"
    data = os.environ.get("XDG_DATA_HOME")
    base = Path(data) if data and os.path.isabs(data) else Path.home() / ".local" / "share"
    return base / "ai-workbench"


def ledger_path() -> Path:
    override = os.environ.get(ENV_LEDGER)
    if override:
        if not os.path.isabs(override):
            raise ProviderError(f"{ENV_LEDGER} must be an absolute path", EXIT_USAGE)
        return Path(override)
    return data_home() / LEDGER_NAME


def ledger_read() -> dict:
    path = ledger_path()
    if not path.exists():
        return {"version": 1, "entries": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ProviderError("the idempotency ledger is not valid JSON; nothing was sent") from None
    if not isinstance(data, dict) or not isinstance(data.get("entries"), dict):
        raise ProviderError("the idempotency ledger has no entries object; nothing was sent")
    return data


def ledger_save(data: dict) -> None:
    path = ledger_path()
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".documents-notion.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, sort_keys=True)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


@contextlib.contextmanager
def ledger_locked():
    path = ledger_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(f"{path}.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    raise ProviderError(f"the idempotency ledger stayed locked for {LOCK_TIMEOUT_SECONDS} s")
                time.sleep(0.05)
        yield ledger_read()
    finally:
        os.close(fd)


def ledger_entry(scope: str, key: str):
    return ledger_read()["entries"].get(f"{scope}/{key}")


def ledger_set(scope: str, key: str, entry) -> None:
    with ledger_locked() as data:
        if entry is None:
            data["entries"].pop(f"{scope}/{key}", None)
        else:
            data["entries"][f"{scope}/{key}"] = entry
        ledger_save(data)


def ledger_claim(scope: str, key: str):
    """Record the key as pending and return None, or return the entry that already holds it."""
    with ledger_locked() as data:
        existing = data["entries"].get(f"{scope}/{key}")
        if existing:
            return existing
        data["entries"][f"{scope}/{key}"] = {"status": "pending", "started_at": now_iso()}
        ledger_save(data)
    return None


def pending_message(key: str, entry: dict) -> str:
    return (f"idempotency key {key!r} has a pending creation from {entry.get('started_at', 'an unknown time')} whose outcome "
            "is unknown; nothing was sent this time. Look under the parent page, then run resolve --idempotency-key <k> with "
            "--id <id> if the page exists or --not-created if it does not, and --confirmed (with --parent <the page it was "
            "made under> when that is not the configured parent)")




def plain(rich) -> str:
    return "".join((r.get("plain_text") if r.get("plain_text") is not None else (r.get("text") or {}).get("content", ""))
                   for r in rich or [] if isinstance(r, dict))


def text_objects(text: str) -> list:
    return [{"type": "text", "text": {"content": text[i:i + TEXT_LIMIT]}} for i in range(0, len(text), TEXT_LIMIT)]


def notice_block(text: str) -> dict:
    return {"object": "block", "type": "callout", "callout": {
        "rich_text": text_objects(text), "icon": {"type": "emoji", "emoji": NOTICE_ICON}, "color": NOTICE_COLOR}}


def notice_of(block) -> str | None:
    """The text of a block that is the runtime's notice (a callout with NOTICE_ICON), else None."""
    if not isinstance(block, dict) or block.get("type") != "callout":
        return None
    body = block.get("callout") or {}
    icon = body.get("icon") or {}
    if icon.get("type") != "emoji" or icon.get("emoji") != NOTICE_ICON:
        return None
    return plain(body.get("rich_text"))


def notice_text(value, flag: str) -> str:
    """A notice: one line of at most TEXT_LIMIT characters."""
    if not isinstance(value, str) or not value.strip() or len(value) > TEXT_LIMIT \
            or re.search(r"[\x00-\x1f\x7f]", value):
        raise ProviderError(f"{flag} is one line of at most {TEXT_LIMIT} characters", EXIT_USAGE)
    return value.strip()


def archived(page: dict) -> bool:
    return bool(page.get("in_trash") or page.get("is_archived") or page.get("archived"))



def not_given(exc: ProviderError, what: str) -> ProviderError:
    if exc.status in (403, 404):
        return ProviderError(f"{what} does not exist or the integration was not given it ({exc})", EXIT_NOT_CONFIGURED)
    return exc




def mode_of(args: dict) -> str:
    if args.get("--dry-run") and args.get("--confirmed"):
        raise ProviderError("give --dry-run or --confirmed, not both", EXIT_USAGE)
    if not args.get("--dry-run") and not args.get("--confirmed"):
        raise ProviderError("this verb changes a document: give --dry-run to see the write, or --confirmed to make it",
                            EXIT_USAGE)
    return "dry" if args.get("--dry-run") else "confirmed"


def key_of(args: dict) -> str:
    key = args.get("--idempotency-key")
    if not isinstance(key, str) or not key.strip() or len(key) > 512 or re.search(r"[\x00-\x1f\x7f]", key):
        raise ProviderError("--idempotency-key is required: one line of at most 512 characters", EXIT_USAGE)
    return key




# --- documents -----------------------------------------------------------------


def documents_config(config_file) -> dict:
    if not config_file:
        raise ProviderError("--config-file is required", EXIT_USAGE)
    try:
        with open(config_file, encoding="utf-8") as f:
            config = json.load(f)
    except OSError:
        raise ProviderError(f"the configuration file {config_file} cannot be read", EXIT_NOT_CONFIGURED) from None
    except ValueError:
        raise ProviderError(f"the configuration file {config_file} is not JSON", EXIT_USAGE) from None
    if not isinstance(config, dict):
        raise ProviderError("the configuration file holds the documents object", EXIT_USAGE)
    if not config.get("parent"):
        raise ProviderError("documents.parent is not set: the identifier of the page documents go under",
                            EXIT_NOT_CONFIGURED)
    return {"parent": notion_id(config["parent"], "documents.parent")}


def doc_path(value) -> str:
    """A project-relative path of a Markdown document: relative, no "." or ".." part, ending in .md."""
    if not isinstance(value, str) or not value:
        raise ProviderError("--path is required", EXIT_USAGE)
    parts = value.split("/")
    if (value.startswith(("/", "~")) or "\\" in value or any(p in ("", ".", "..") for p in parts)
            or not value.endswith(".md") or value.endswith(SIDE) or re.search(r"[\x00-\x1f\x7f]", value)):
        raise ProviderError("--path must be a relative path inside the project that ends in .md", EXIT_USAGE)
    return value


def doc_id(value) -> str:
    if not isinstance(value, str) or not value:
        raise ProviderError("--id is required", EXIT_USAGE)
    if not NOTION_ID.fullmatch(value.strip().lower()):
        raise ProviderError(f"no document {one_line(value, 80)}: an id is the identifier of a page")
    return value.strip().lower()


def retrieve(service: Service, ident: str) -> dict:
    try:
        return service.call("retrieve_page", ident)
    except ProviderError as exc:
        if exc.status == 404:
            raise ProviderError(f"no document {ident}") from None
        raise


def block_ids(blocks: list) -> list:
    """The ids of the blocks given and of their children, at every depth, in reading order."""
    out = []
    for b in blocks:
        out.append(b.get("id"))
        kind = b.get("type")
        out += block_ids(((b.get(kind) if isinstance(kind, str) else None) or {}).get("children") or [])
    return [i for i in out if isinstance(i, str)]


def comments_of(service: Service, ident: str, blocks: list) -> list:
    """The comments of the page and of every block in it: the service lists a comment made on a block under that
    block only, not with the page's (measured, README.md, N4). One listing per block; a comment met twice is kept once."""
    out, seen = [], set()
    for target in [ident] + block_ids(blocks):
        for c in service.paged("list_comments", query={"block_id": target})[0]:
            if c.get("id") in seen:
                continue
            seen.add(c.get("id"))
            out.append(comment_of(c))
    return out


def comment_of(c: dict) -> dict:
    return {"id": c.get("id"), "author": (c.get("created_by") or {}).get("id"), "created_at": c.get("created_time"),
            "text": plain(c.get("rich_text"))}


def cmd_check(args: dict) -> int:
    cfg = documents_config(args.get("--config-file"))
    service = Service()
    try:
        service.call("retrieve_page", cfg["parent"])
    except ProviderError as exc:
        raise not_given(exc, "the parent page") from None
    return emit({"ok": True})


def cmd_stat(args: dict) -> int:
    documents_config(args.get("--config-file"))
    ident = doc_id(args.get("--id"))
    page = retrieve(Service(), ident)
    return emit({"id": ident, "version": page.get("last_edited_time"), "archived": archived(page)})


def cmd_read(args: dict) -> int:
    if args.get("--as-source"):
        return read_as_source(args)
    documents_config(args.get("--config-file"))
    ident = doc_id(args.get("--id"))
    service = Service()
    page = retrieve(service, ident)
    blocks = service.blocks(ident)
    notice = notice_of(blocks[0]) if blocks else None
    body = blocks[1:] if notice is not None else blocks
    return emit({"id": ident, "version": page.get("last_edited_time"), "markdown": nb.to_markdown(body),
                 "notice": notice, "comments": comments_of(service, ident, blocks)})


def read_as_source(args: dict) -> int:
    """A page chosen as a source: its text and version, read with the read-only secret of sources, no comments, no documents
    configuration. The page is a person's page and may hold anything: what comes back is text for the caller to treat as data."""
    ident = doc_id(args.get("--id"))
    service = Service(SOURCES_SECRET, SOURCES_USERNAME)
    page = retrieve(service, ident)
    if archived(page):
        raise ProviderError(f"the page {ident} is in the trash")
    blocks = service.blocks(ident)
    notice = notice_of(blocks[0]) if blocks else None
    body = blocks[1:] if notice is not None else blocks
    return emit({"id": ident, "version": page.get("last_edited_time"), "markdown": nb.to_markdown(body), "notice": notice,
                 "comments": [], "as_source": True})


def cmd_comments(args: dict) -> int:
    """The page's own open comments, in one listing (paginated), whatever its version: a comment does not move the
    version (measured, N3), so the runtime lists them at every pull. The comments on its blocks come with `read`."""
    documents_config(args.get("--config-file"))
    ident = doc_id(args.get("--id"))
    try:
        listed = Service().paged("list_comments", query={"block_id": ident})[0]
    except ProviderError as exc:
        if exc.status == 404:
            raise ProviderError(f"no document {ident}") from None
        raise
    return emit({"id": ident, "comments": [comment_of(c) for c in listed]})


def cmd_write(args: dict) -> int:
    cfg = documents_config(args.get("--config-file"))
    mode = mode_of(args)
    key = key_of(args)
    path = doc_path(args.get("--path"))
    ident = doc_id(args["--id"]) if args.get("--id") is not None else None
    source = args.get("--markdown-file")
    if not source:
        raise ProviderError("--markdown-file is required", EXIT_USAGE)
    try:
        with open(source, encoding="utf-8") as f:
            markdown = f.read()
    except (OSError, UnicodeDecodeError):
        raise ProviderError(f"the Markdown file {source} cannot be read as UTF-8 text", EXIT_USAGE) from None
    blocks = nb.to_blocks(markdown)
    expected = hashlib.sha256(nb.round_trip(markdown).encode("utf-8")).hexdigest()  # what `read` will print after this write
    notice = notice_text(args["--notice"], "--notice") if args.get("--notice") is not None else None
    entry = ledger_entry(cfg["parent"], key) if ident is None else None
    if entry and entry.get("status") != "done":
        raise ProviderError(pending_message(key, entry))
    if entry:
        ident = entry["id"]
    create = ident is None
    if mode == "dry":
        return emit({"dry_run": True, "would": {"verb": "write", "id": ident, "create": create, "path": path,
                                                 "blocks": len(blocks), "bytes": len(markdown.encode("utf-8")),
                                                 "expected_sha256": expected}})
    service = Service()
    if create:
        if ledger_claim(cfg["parent"], key):  # another run claimed it meanwhile
            raise ProviderError(pending_message(key, ledger_entry(cfg["parent"], key) or {}))
        body = {"parent": {"type": "page_id", "page_id": cfg["parent"]},
                "properties": {"title": {"title": text_objects(path)}}}
        try:
            made = service.call("create_page", body=body)
        except ProviderError as exc:
            refused = exc.status is not None and 400 <= exc.status < 500 and exc.status not in UNKNOWN_OUTCOME
            ledger_set(cfg["parent"], key, None if refused else
                       {"status": "pending", "started_at": now_iso(), "error": str(exc)})
            raise not_given(exc, "the parent page") if refused else exc from None
        except BaseException:
            ledger_set(cfg["parent"], key, {"status": "pending", "started_at": now_iso(), "error": "interrupted"})
            raise
        try:
            ident = notion_id(made.get("id"), "the created page's id", EXIT_SERVICE)
        except ProviderError:
            ledger_set(cfg["parent"], key, {"status": "pending", "started_at": now_iso(),
                                            "error": "the answer named no page"})
            raise ProviderError("the answer to the creation names no page; the key stays pending until resolve")
        ledger_set(cfg["parent"], key, {"status": "done", "id": ident, "path": path, "recorded_at": now_iso()})
        service.append(ident, ([notice_block(notice)] if notice is not None else []) + blocks)
    else:
        retrieve(service, ident)
        service.replace_body(ident, blocks, notice)
    page = retrieve(service, ident)
    return emit({"id": ident, "version": page.get("last_edited_time"), "created": create, "url": page.get("url"),
                 "expected_sha256": expected})


def cmd_notice(args: dict) -> int:
    """Add the notice as the page's first block when its first block is not one; nothing else of the page is
    touched. A dry run makes no call, so it cannot say whether the notice would be added."""
    documents_config(args.get("--config-file"))
    mode = mode_of(args)
    ident = doc_id(args.get("--id"))
    text = notice_text(args.get("--text"), "--text")
    if mode == "dry":
        return emit({"dry_run": True, "would": {"verb": "notice", "id": ident}})
    service = Service()
    retrieve(service, ident)
    first = service.call("list_children", ident, query={"page_size": 1}).get("results") or []
    if first and notice_of(first[0]) is not None:
        return emit({"id": ident, "added": False})
    service.append(ident, [notice_block(text)], first=True)
    return emit({"id": ident, "added": True})


def cmd_resolve(args: dict) -> int:
    cfg = documents_config(args.get("--config-file"))
    mode = mode_of(args)
    key = key_of(args)
    given, not_created = args.get("--id"), args.get("--not-created")
    if (given is None) == (not not_created):
        raise ProviderError("give --id <id> or --not-created", EXIT_USAGE)
    ident = notion_id(given, "--id") if given is not None else None
    scope = notion_id(args["--parent"], "--parent") if args.get("--parent") else cfg["parent"]  # a page or a table made under another parent
    if mode == "dry":
        return emit({"dry_run": True, "would": {"verb": "resolve", "key": key, "id": ident}})
    ledger_set(scope, key, {"status": "done", "id": ident, "recorded_at": now_iso(), "resolved": True}
               if ident else None)
    return emit({"key": key, "id": ident, "resolved": True})


# --- the outputs of a task: a page, a table, rows (package NOTION-OUT) ---------------------------------------------


def table_file(args: dict) -> dict:
    path = args.get("--table-file")
    if not path:
        raise ProviderError("--table-file is required", EXIT_USAGE)
    try:
        return nt.load(path)
    except nt.TableError as exc:
        raise ProviderError(f"the table file is refused: {exc}", EXIT_USAGE) from None


def title_arg(args: dict) -> str:
    value = args.get("--title")
    if not isinstance(value, str) or not value.strip() or len(value) > 200 or re.search(r"[\x00-\x1f\x7f]", value):
        raise ProviderError("--title is one line of 1 to 200 characters", EXIT_USAGE)
    return value.strip()


def since_of(entry: dict) -> str:
    """When an attempt began, less the clock skew: what a thing made by it is looked for after."""
    try:
        began = datetime.fromisoformat(str(entry.get("started_at")).replace("Z", "+00:00"))
    except ValueError:
        began = datetime.now(timezone.utc)
    return (began - timedelta(seconds=ADOPT_SKEW_SECONDS)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def claimed(scope: str, prefix: str = "") -> set:
    """The ids the ledger holds as made under a scope (a parent page or a data source), by any key."""
    return {e.get("id") for k, e in ledger_read()["entries"].items()
            if k.startswith(scope + "/" + prefix) and isinstance(e, dict) and e.get("status") in ("done", "created") and e.get("id")}


def adopt_child(service: Service, parent: str, kind: str, title: str, entry: dict):
    """The page (kind child_page) or database (child_database) an attempt of unknown outcome made, found among the parent's children:
    exactly one with this title, created since the attempt began and not claimed by the ledger. Else None."""
    since = since_of(entry)
    taken = claimed(parent)
    found = []
    for block in service.paged("list_children", parent)[0]:
        if block.get("type") != kind or (block.get(kind) or {}).get("title") != title or block.get("in_trash"):
            continue
        if str(block.get("created_time") or "") >= since and block.get("id") not in taken:
            found.append(block.get("id"))
    return notion_id(found[0], "the found object's id", EXIT_SERVICE) if len(found) == 1 else None


def refused_status(exc: ProviderError) -> bool:
    return exc.status is not None and 400 <= exc.status < 500 and exc.status not in UNKNOWN_OUTCOME


def query_rows(service: Service, source: str, since: str | None = None, limit: int = TABLE_ROWS_MAX) -> tuple[list, bool]:
    """The rows of a data source (pages), at most `limit`; (rows, capped). With `since` only the rows created at or after it."""
    out, cursor = [], None
    for _ in range(MAX_PAGES):
        body = {"page_size": PAGE_SIZE, **({"start_cursor": cursor} if cursor else {}),
                **({"filter": {"timestamp": "created_time", "created_time": {"on_or_after": since}}} if since else {})}
        answer = service.call("query_base", source, body=body)
        results = answer.get("results")
        if not isinstance(results, list):
            raise ProviderError("the answer to a query has no results list")
        out += results
        if len(out) > limit:
            return out[:limit], True
        if not answer.get("has_more"):
            return out, False
        cursor = answer.get("next_cursor")
        if not isinstance(cursor, str) or not cursor:
            raise ProviderError("the answer to a query has more and no cursor")
    return out, True


def retrieve_source(service: Service, source: str) -> list:
    """The data source's columns: [{"name", "type"}], sorted by name. A data source the integration was not given is exit 3."""
    try:
        answer = service.call("retrieve_base", source)
    except ProviderError as exc:
        raise not_given(exc, "the table") from None
    try:
        return nt.schema_of(answer)
    except nt.TableError as exc:
        raise ProviderError(str(exc)) from None


def cmd_table_read(args: dict) -> int:
    documents_config(args.get("--config-file"))
    source = notion_id(args.get("--id"), "--id")
    service = Service(bulk=True)
    schema = retrieve_source(service, source)
    rows, capped = query_rows(service, source)
    if capped:
        raise ProviderError(f"the table holds more than {TABLE_ROWS_MAX} rows: this provider does not count a table longer than that",
                            EXIT_SERVICE)
    edited = max((str(r.get("last_edited_time") or "") for r in rows), default="") or None
    return emit({"id": source, "schema": schema, "schema_sha256": nt.schema_sha256(schema), "row_count": len(rows), "last_edited": edited,
                 "title": next((c["name"] for c in schema if c["type"] == "title"), None)})


def fill(service: Service, source: str, table: dict, key: str) -> dict:
    """The rows of the table into the data source, one by one, each once for the key. A row done in the ledger is skipped; a row
    pending (its call's outcome is unknown) is looked for in the table and written only if it is not there. {"created", "replayed"}."""
    columns, rows = table["columns"], table["rows"]
    created = replayed = 0
    candidates = None
    taken = claimed(source, key + "/")
    for n, row in enumerate(rows):
        row_key = f"{key}/row-{n + 1:04d}"
        entry = ledger_entry(source, row_key)
        if entry and entry.get("status") == "done":
            replayed += 1
            continue
        if entry:  # pending: did it land?
            if candidates is None:
                since = min([since_of(e) for k, e in ledger_read()["entries"].items()
                             if k.startswith(f"{source}/{key}/row-") and isinstance(e, dict) and e.get("status") == "pending"]
                            or [since_of(entry)])
                candidates, _ = query_rows(service, source, since)
            hits = [p for p in candidates if p.get("id") not in taken and nt.row_matches(p, columns, row)]
            if hits:
                page = notion_id(hits[0].get("id"), "a row's id", EXIT_SERVICE)
                taken.add(page)
                ledger_set(source, row_key, {"status": "done", "id": page, "recorded_at": now_iso(), "adopted": True})
                replayed += 1
                continue
        ledger_set(source, row_key, {"status": "pending", "started_at": now_iso()})
        try:
            made = service.call("create_page", body={"parent": {"type": "data_source_id", "data_source_id": source},
                                                     "properties": nt.row_properties(columns, row)})
        except ProviderError as exc:
            if refused_status(exc):
                ledger_set(source, row_key, None)
                raise ProviderError(f"row {n + 1} was refused ({exc}); {created} rows were written by this run, {replayed} were already "
                                    "there", EXIT_SERVICE, exc.status) from None
            ledger_set(source, row_key, {"status": "pending", "started_at": now_iso(), "error": one_line(exc, 120)})
            raise ProviderError(f"row {n + 1}: {exc}; its outcome is unknown ({created} rows written by this run, {replayed} already "
                                "there): running again looks for it in the table before it writes it", EXIT_SERVICE, exc.status) from None
        try:
            page = notion_id(made.get("id"), "a row's id", EXIT_SERVICE)
        except ProviderError:
            raise ProviderError(f"row {n + 1}: the answer named no page; running again looks for the row before it writes it") from None
        taken.add(page)
        ledger_set(source, row_key, {"status": "done", "id": page, "recorded_at": now_iso()})
        created += 1
    return {"created": created, "replayed": replayed}


def ledger_counts(source: str, key: str, total: int) -> dict:
    done = pending = 0
    for n in range(total):
        entry = ledger_entry(source, f"{key}/row-{n + 1:04d}")
        if entry and entry.get("status") == "done":
            done += 1
        elif entry:
            pending += 1
    return {"rows": total, "rows_done": done, "rows_pending": pending, "rows_new": total - done - pending}


def cmd_rows_append(args: dict) -> int:
    documents_config(args.get("--config-file"))
    mode = mode_of(args)
    key = key_of(args)
    source = notion_id(args.get("--id"), "--id")
    table = table_file(args)
    expected = args.get("--schema-sha256")
    if expected is not None and not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ProviderError("--schema-sha256 is the 64-hex hash table-read printed", EXIT_USAGE)
    if mode == "dry":
        return emit({"dry_run": True, "would": {"verb": "rows-append", "id": source, **ledger_counts(source, key, len(table["rows"]))}})
    service = Service(bulk=True)
    schema = retrieve_source(service, source)
    if expected is not None and nt.schema_sha256(schema) != expected:
        raise ProviderError("the table's columns are not the ones the task read: nothing was written")
    problem = nt.problem_with(table["columns"], schema)
    if problem:
        raise ProviderError(f"the rows do not fit the table ({problem}): nothing was written")
    done = fill(service, source, table, key)
    return emit({"id": source, "rows": len(table["rows"]), "rows_created": done["created"], "rows_replayed": done["replayed"],
                 "schema_sha256": nt.schema_sha256(schema)})


def database_of(service: Service, made: dict) -> tuple[str, str, str | None]:
    """(database id, data source id, url) from the answer to a creation, asking for the database when the answer is partial."""
    ident = notion_id(made.get("id"), "the created database's id", EXIT_SERVICE)
    sources = made.get("data_sources")
    if not isinstance(sources, list):
        made = service.call("retrieve_database", ident)
        sources = made.get("data_sources")
    if not isinstance(sources, list) or len(sources) != 1 or not isinstance(sources[0], dict):
        raise ProviderError("the created database does not have exactly one data source")
    return ident, notion_id(sources[0].get("id"), "the data source's id", EXIT_SERVICE), made.get("url")


def cmd_table_create(args: dict) -> int:
    documents_config(args.get("--config-file"))
    mode = mode_of(args)
    key = key_of(args)
    parent = notion_id(args.get("--parent"), "--parent")
    title = title_arg(args)
    table = table_file(args)
    entry = ledger_entry(parent, key)
    state = "new" if not entry else ("done" if entry.get("status") == "done" else "pending")
    if mode == "dry":
        counts = ledger_counts(entry["data_source"], key, len(table["rows"])) if state == "done" and entry.get("data_source") \
            else {"rows": len(table["rows"]), "rows_done": 0, "rows_pending": 0, "rows_new": len(table["rows"])}
        return emit({"dry_run": True, "would": {"verb": "table-create", "parent": parent, "state": state,
                                                 "id": entry.get("id") if entry else None, **counts}})
    service = Service(bulk=True)
    created = state == "new"
    if state == "new":
        if ledger_claim(parent, key):  # another run claimed it meanwhile
            raise ProviderError(pending_message(key, ledger_entry(parent, key) or {}))
        body = {"parent": {"type": "page_id", "page_id": parent}, "title": nt.text_objects(title),
                "initial_data_source": {"properties": nt.schema_properties(table["columns"], table["rows"])}}
        try:
            made = service.call("create_database", body=body)
        except ProviderError as exc:
            ledger_set(parent, key, None if refused_status(exc) else {"status": "pending", "started_at": now_iso(), "error": str(exc)})
            raise not_given(exc, "the parent page") if refused_status(exc) else exc from None
        except BaseException:
            ledger_set(parent, key, {"status": "pending", "started_at": now_iso(), "error": "interrupted"})
            raise
        try:
            ident, source, url = database_of(service, made)
        except ProviderError:
            ledger_set(parent, key, {"status": "pending", "started_at": now_iso(), "error": "the answer named no usable database"})
            raise ProviderError("the answer to the creation names no usable database; running again looks for it among the "
                                "parent's children before it creates another") from None
        entry = {"status": "done", "id": ident, "data_source": source, "url": url, "title": title, "recorded_at": now_iso()}
        ledger_set(parent, key, entry)
    elif state == "pending":
        found = adopt_child(service, parent, "child_database", title, entry)
        if found is None:
            raise ProviderError(pending_message(key, entry))
        ident, source, url = database_of(service, {"id": found})
        entry = {"status": "done", "id": ident, "data_source": source, "url": url, "title": title, "recorded_at": now_iso(),
                 "adopted": True}
        ledger_set(parent, key, entry)
        created = False
    else:
        ident, source, url = entry["id"], entry.get("data_source"), entry.get("url")
        if not source:  # a database the person recorded with resolve: its data source is asked for
            ident, source, url = database_of(service, {"id": ident})
    schema = retrieve_source(service, source)
    problem = nt.problem_with(table["columns"], schema)
    if problem:
        raise ProviderError(f"the database made is not the one asked for ({problem}): nothing more was written")
    done = fill(service, source, table, key)
    return emit({"id": ident, "data_source_id": source, "url": url, "created": created, "rows": len(table["rows"]),
                 "rows_created": done["created"], "rows_replayed": done["replayed"], "schema_sha256": nt.schema_sha256(schema)})


def cmd_page_create(args: dict) -> int:
    documents_config(args.get("--config-file"))
    mode = mode_of(args)
    key = key_of(args)
    parent = notion_id(args.get("--parent"), "--parent")
    title = title_arg(args)
    source = args.get("--markdown-file")
    if not source:
        raise ProviderError("--markdown-file is required", EXIT_USAGE)
    try:
        with open(source, encoding="utf-8") as f:
            markdown = f.read()
    except (OSError, UnicodeDecodeError):
        raise ProviderError(f"the Markdown file {source} cannot be read as UTF-8 text", EXIT_USAGE) from None
    blocks = nb.to_blocks(markdown)
    expected = hashlib.sha256(nb.round_trip(markdown).encode("utf-8")).hexdigest()
    entry = ledger_entry(parent, key)
    state = "new" if not entry else entry.get("status", "pending")
    if mode == "dry":
        return emit({"dry_run": True, "would": {"verb": "page-create", "parent": parent, "state": state,
                                                 "id": entry.get("id") if entry else None, "blocks": len(blocks),
                                                 "bytes": len(markdown.encode("utf-8")), "expected_sha256": expected}})
    service = Service(bulk=True)
    replayed = state != "new"
    if state == "new":
        if ledger_claim(parent, key):
            raise ProviderError(pending_message(key, ledger_entry(parent, key) or {}))
        body = {"parent": {"type": "page_id", "page_id": parent}, "properties": {"title": {"title": nt.text_objects(title)}}}
        try:
            made = service.call("create_page", body=body)
        except ProviderError as exc:
            ledger_set(parent, key, None if refused_status(exc) else {"status": "pending", "started_at": now_iso(), "error": str(exc)})
            raise not_given(exc, "the parent page") if refused_status(exc) else exc from None
        except BaseException:
            ledger_set(parent, key, {"status": "pending", "started_at": now_iso(), "error": "interrupted"})
            raise
        try:
            ident = notion_id(made.get("id"), "the created page's id", EXIT_SERVICE)
        except ProviderError:
            ledger_set(parent, key, {"status": "pending", "started_at": now_iso(), "error": "the answer named no page"})
            raise ProviderError("the answer to the creation names no page; running again looks for it among the parent's children "
                                "before it creates another") from None
        ledger_set(parent, key, {"status": "created", "id": ident, "title": title, "recorded_at": now_iso()})
        service.append(ident, blocks)
    else:
        if state == "pending":
            found = adopt_child(service, parent, "child_page", title, entry)
            if found is None:
                raise ProviderError(pending_message(key, entry))
            ident = found
        else:
            ident = notion_id(entry.get("id"), "the ledger's page id", EXIT_SERVICE)
        retrieve(service, ident)
        if state != "done":  # made by this key but not finished: the body is written again whole (the page is ours alone)
            service.replace_body(ident, blocks)
    ledger_set(parent, key, {"status": "done", "id": ident, "title": title, "recorded_at": now_iso()})
    page = retrieve(service, ident)
    return emit({"id": ident, "version": page.get("last_edited_time"), "created": not replayed, "replayed": replayed,
                 "url": page.get("url"), "expected_sha256": expected})


VERBS = {"stat": cmd_stat, "read": cmd_read, "comments": cmd_comments, "write": cmd_write, "notice": cmd_notice,
         "resolve": cmd_resolve, "page-create": cmd_page_create, "table-read": cmd_table_read, "table-create": cmd_table_create,
         "rows-append": cmd_rows_append}
VALUE_FLAGS = ("--config-file", "--id", "--path", "--markdown-file", "--idempotency-key", "--notice", "--text", "--parent", "--title",
               "--table-file", "--schema-sha256")
SWITCHES = ("--dry-run", "--confirmed", "--not-created", "--check", "--as-source")


def parse_args(argv: list) -> tuple:
    verb, args, i = None, {}, 0
    while i < len(argv):
        word = argv[i]
        if word in VALUE_FLAGS:
            if i + 1 >= len(argv):
                raise ProviderError(f"{word} needs a value", EXIT_USAGE)
            args[word] = argv[i + 1]
            i += 2
        elif word in SWITCHES:
            args[word] = True
            i += 1
        elif verb is None and word in VERBS:
            verb = word
            i += 1
        else:
            raise ProviderError(f"unknown argument {one_line(word, 60)!r}; see --help", EXIT_USAGE)
    return verb, args


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("--help", "-h"):
        print(__doc__.strip(), file=sys.stdout if argv else sys.stderr)
        return EXIT_OK if argv else EXIT_USAGE
    try:
        verb, args = parse_args(argv)
        if args.get("--check"):
            if verb is not None:
                raise ProviderError("--check takes no verb", EXIT_USAGE)
            return cmd_check(args)
        if verb is None:
            raise ProviderError("give a verb or --check; see --help", EXIT_USAGE)
        if args.get("--as-source") and verb != "read":
            raise ProviderError("--as-source is for the verb read only", EXIT_USAGE)
        return VERBS[verb](args)
    except ProviderError as e:
        print(f"error: {e}", file=sys.stderr)
        return e.code


if __name__ == "__main__":
    sys.exit(main())
