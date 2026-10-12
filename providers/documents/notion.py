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
  uv run providers/documents/notion.py comments --config-file <f> --id <id>
  uv run providers/documents/notion.py write --config-file <f> [--id <id>] --path <project-relative path>
                                       --markdown-file <f> --idempotency-key <k> [--notice <text>]
                                       (--dry-run | --confirmed)
  uv run providers/documents/notion.py notice --config-file <f> --id <id> --text <text> (--dry-run | --confirmed)
  uv run providers/documents/notion.py resolve --config-file <f> --idempotency-key <k>
                                       (--id <id> | --not-created) (--dry-run | --confirmed)

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
  INTEGRATION_DOCUMENTS_NOTION_LEDGER      another ledger file (an absolute path)
  INTEGRATION_DOCUMENTS_NOTION_API_BASE    tests only: a loopback URL that replaces the service's address; the
                                           secret store is then never read

No redirect is followed: every request carries the token. Too many requests (429) or a 5xx: exit 1 with the status
on stderr; a verb never retries. A dry run reads no credential and makes no call.

Prints one JSON object on stdout; diagnostics on stderr. Exit codes: 0 ok, 1 failed (the service answered an error
or could not be reached, a document that does not exist), 2 usage (a path that is absolute, holds "..", or does not
end in .md, a write without --dry-run or --confirmed), 3 not configured (no config file, no parent, no token, a token
the service rejects, a parent the integration was not given).
"""
from __future__ import annotations

import contextlib
import fcntl
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
from datetime import datetime, timezone
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
}
PAGE_SIZE = 100  # the maximum of every paginated call
MAX_CHILDREN_PER_CALL = 100  # append: children per request
MAX_PAGES = 1000  # a longer chain of cursors is treated as a service error
TEXT_LIMIT = 2000  # characters of one text object
HTTP_TIMEOUT_SECONDS = 30
LOCK_TIMEOUT_SECONDS = 10
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
UNKNOWN_OUTCOME = (408, 429)  # with every 5xx: the request may have been carried out

ENV_BASE = "INTEGRATION_DOCUMENTS_NOTION_API_BASE"
ENV_LEDGER = "INTEGRATION_DOCUMENTS_NOTION_LEDGER"
SECRET = "NOTION_TOKEN"
KEYRING_USERNAME = "notion"
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


class ProviderError(Exception):
    def __init__(self, message: str, code: int = EXIT_SERVICE, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status


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


def load_token(test_mode: bool) -> str:
    found = secret_resolver().resolve(SECRET, allow_store=not test_mode)
    token = found[0] if found else ""
    if not token:
        raise ProviderError(f"no Notion token: export {SECRET}, or store one with "
                            f"uv run --with keyring==25.7.0 keyring set openhora {KEYRING_USERNAME}",
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
    def __init__(self):
        self.base, test_mode = api_base()
        self.token = load_token(test_mode)

    def call(self, name: str, ident: str | None = None, body=None, query=None) -> dict:
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
            code = EXIT_NOT_CONFIGURED if exc.code == 401 else EXIT_SERVICE
            raise ProviderError(f"Notion returned {exc.code} on {where}{detail}", code, exc.code) from None
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
            "--id <id> if the page exists or --not-created if it does not, and --confirmed")




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
    documents_config(args.get("--config-file"))
    ident = doc_id(args.get("--id"))
    service = Service()
    page = retrieve(service, ident)
    blocks = service.blocks(ident)
    notice = notice_of(blocks[0]) if blocks else None
    body = blocks[1:] if notice is not None else blocks
    return emit({"id": ident, "version": page.get("last_edited_time"), "markdown": nb.to_markdown(body),
                 "notice": notice, "comments": comments_of(service, ident, blocks)})


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
    notice = notice_text(args["--notice"], "--notice") if args.get("--notice") is not None else None
    entry = ledger_entry(cfg["parent"], key) if ident is None else None
    if entry and entry.get("status") != "done":
        raise ProviderError(pending_message(key, entry))
    if entry:
        ident = entry["id"]
    create = ident is None
    if mode == "dry":
        return emit({"dry_run": True, "would": {"verb": "write", "id": ident, "create": create, "path": path,
                                                 "blocks": len(blocks), "bytes": len(markdown.encode("utf-8"))}})
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
    return emit({"id": ident, "version": page.get("last_edited_time"), "created": create, "url": page.get("url")})


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
    if mode == "dry":
        return emit({"dry_run": True, "would": {"verb": "resolve", "key": key, "id": ident}})
    ledger_set(cfg["parent"], key, {"status": "done", "id": ident, "recorded_at": now_iso(), "resolved": True}
               if ident else None)
    return emit({"key": key, "id": ident, "resolved": True})


VERBS = {"stat": cmd_stat, "read": cmd_read, "comments": cmd_comments, "write": cmd_write, "notice": cmd_notice,
         "resolve": cmd_resolve}
VALUE_FLAGS = ("--config-file", "--id", "--path", "--markdown-file", "--idempotency-key", "--notice", "--text")
SWITCHES = ("--dry-run", "--confirmed", "--not-created", "--check")


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
        return VERBS[verb](args)
    except ProviderError as e:
        print(f"error: {e}", file=sys.stderr)
        return e.code


if __name__ == "__main__":
    sys.exit(main())
