#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["keyring==25.7.0"]
# ///
"""Task-board provider on Notion: an implementation of the class integration:issue-tracker in which the board is a
data source (a base) of the person's workspace, one row per item.

The base is `base` of the project configuration's `task_board` object: the identifier of the data source (in the
app, the base's settings, "Manage data sources", "Copy data source ID"). `fields` maps title, state and shown to the
names of the base's properties (defaults Name, Status, Runtime: a title, a status or select, and a text property);
`states` maps each of the nine task states to the option name the base uses (default: the state's own word). An
option the map does not know is read as state null; a row with no option is `requested`. The item's text is the body
of the row's page, converted with providers/documents/notion_blocks.py, the one file this script loads from another
class's folder. `shown` is written to the shown property as "key: value" lines and never read back.

`version` is the page's last_edited_time. It covers the content: measured on the live service (README.md, "Measured
on the live service"), it is rounded to the minute and a comment does not move it; the stand-in service of the tests
does the same. Comments are those of the row's page and of each block of its body (`get`); `comments` lists the row's
own, in one listing, whatever the version. An upsert reads the row first and writes only the properties and the body that differ, so
a write of a value already there changes nothing.

Usage:
  uv run providers/issue-tracker/notion.py --help
  uv run providers/issue-tracker/notion.py --check --config-file <f>
  uv run providers/issue-tracker/notion.py list --config-file <f>
  uv run providers/issue-tracker/notion.py get --config-file <f> --id <id>
  uv run providers/issue-tracker/notion.py comments --config-file <f> --id <id>
  uv run providers/issue-tracker/notion.py upsert --config-file <f> [--id <id>] --item-file <json>
                                          --idempotency-key <k> (--dry-run | --confirmed)
  uv run providers/issue-tracker/notion.py resolve --config-file <f> --idempotency-key <k>
                                          (--id <id> | --not-created) (--dry-run | --confirmed)

--config-file is a JSON file holding the task_board object, whole: {"provider": "notion", "base": "<data source id>",
"expires": "YYYY-MM-DD", "fields": {...}, "states": {...}}. The item file is {"title", "text", "state", "shown"},
every key optional; a key that is absent is not written. A creation needs a title.

At most one row per idempotency key: the key is recorded as pending in the local ledger, under a file lock, before
the creation, and as done after it. A creation whose outcome is unknown (a timeout, a 5xx, a 408, a 429) leaves the
key pending, and the key blocks every new attempt until resolve records what the person found on the base (--id) or
releases it (--not-created). The ledger lives in the data folder (~/Library/Application Support/ai-workbench/ on
macOS, $XDG_DATA_HOME/ai-workbench/ or ~/.local/share/ai-workbench/ elsewhere), mode 0600.

Environment:
  NOTION_TOKEN                                 the integration's token, read only through
                                               providers/secrets/resolver.py (else the OS secret store, username
                                               notion); never printed
  INTEGRATION_ISSUE_TRACKER_NOTION_LEDGER      another ledger file (an absolute path)
  INTEGRATION_ISSUE_TRACKER_NOTION_API_BASE    tests only: a loopback URL that replaces the service's address;
                                               the secret store is then never read

No redirect is followed: every request carries the token. Too many requests (429) or a 5xx: exit 1 with the status
on stderr; a verb never retries. A dry run reads no credential and makes no call.

Prints one JSON object on stdout; diagnostics on stderr. Exit codes: 0 ok, 1 failed (the service answered an error
or could not be reached, an item that does not exist), 2 usage, 3 not configured (no config file, no base, no
token, a token the service rejects, a base the integration was not given, a property the base lacks).
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
    "retrieve_base": ("GET", "/v1/data_sources/{id}"),
    "query_base": ("POST", "/v1/data_sources/{id}/query"),
    "retrieve_page": ("GET", "/v1/pages/{id}"),
    "create_page": ("POST", "/v1/pages"),
    "update_page": ("PATCH", "/v1/pages/{id}"),
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

ENV_BASE = "INTEGRATION_ISSUE_TRACKER_NOTION_API_BASE"
ENV_LEDGER = "INTEGRATION_ISSUE_TRACKER_NOTION_LEDGER"
SECRET = "NOTION_TOKEN"
KEYRING_USERNAME = "notion"
LEDGER_NAME = "issue-tracker-notion.json"
EXIT_OK, EXIT_SERVICE, EXIT_USAGE, EXIT_NOT_CONFIGURED = 0, 1, 2, 3

STATES = ("requested", "planned", "ready", "running", "waiting", "blocked", "done", "failed", "cancelled")
FIELDS = {"title": "Name", "state": "Status", "shown": "Runtime"}
ITEM_KEYS = ("title", "text", "state", "shown")
NOTION_ID = re.compile(r"[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
SHOWN_KEY = re.compile(r"[a-z0-9][a-z0-9_-]*")


def load_blocks():
    """The block helper of the documents class, by path: the only file this script loads from another class."""
    path = Path(__file__).resolve().parents[1] / "documents" / "notion_blocks.py"
    spec = importlib.util.spec_from_file_location("notion_blocks_for_board", path)
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


# --- configuration -------------------------------------------------------------


def notion_id(value, what: str, code: int = EXIT_USAGE) -> str:
    if not isinstance(value, str) or not NOTION_ID.fullmatch(value.strip().lower()):
        raise ProviderError(f"{what} is a page or base identifier: 32 hexadecimal characters, with or without hyphens",
                            code)
    return value.strip().lower()


def board_config(config_file) -> dict:
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
        raise ProviderError("the configuration file holds the task_board object", EXIT_USAGE)
    if not config.get("base"):
        raise ProviderError("task_board.base is not set: the identifier of the base (its data source)",
                            EXIT_NOT_CONFIGURED)
    base = notion_id(config["base"], "task_board.base")
    fields = config.get("fields") or {}
    if not isinstance(fields, dict) or set(fields) - set(FIELDS) or not all(
            isinstance(v, str) and v.strip() for v in fields.values()):
        raise ProviderError("task_board.fields maps title, state and shown to property names", EXIT_USAGE)
    states = config.get("states") or {}
    if not isinstance(states, dict) or set(states) - set(STATES) or not all(
            isinstance(v, str) and v.strip() for v in states.values()):
        raise ProviderError("task_board.states maps task states to option names", EXIT_USAGE)
    options = {s: states.get(s, s) for s in STATES}
    if len(set(options.values())) != len(STATES):
        raise ProviderError("task_board.states gives two states the same option", EXIT_USAGE)
    return {"base": base, "fields": {**FIELDS, **fields}, "options": options,
            "states": {name: state for state, name in options.items()}}


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
                "Accept": "application/json", "User-Agent": "openhora-issue-tracker-notion"}
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

    def paged(self, name: str, ident: str | None = None, query=None, body=None) -> tuple[list, bool]:
        """Every result of a paginated call; (results, truncated)."""
        out, cursor = [], None
        for _ in range(MAX_PAGES):
            if name == "query_base":
                answer = self.call(name, ident, body={**(body or {}), "page_size": PAGE_SIZE,
                                                      **({"start_cursor": cursor} if cursor else {})})
            else:
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

    def append(self, parent: str, blocks: list) -> None:
        """Append blocks under a parent, at most MAX_CHILDREN_PER_CALL per call. A block is sent without its children
        (a table keeps its rows, one level); the children are appended under the block the answer names."""
        for start in range(0, len(blocks), MAX_CHILDREN_PER_CALL):
            batch, later = [], []
            for b in blocks[start:start + MAX_CHILDREN_PER_CALL]:
                kind = b["type"]
                body = dict(b[kind])
                kids = [] if kind == "table" else body.pop("children", None) or []
                batch.append({**b, kind: body})
                later.append(kids)
            made = self.call("append_children", parent, body={"children": batch}).get("results")
            if not isinstance(made, list) or len(made) != len(batch):
                raise ProviderError("the answer to an append does not list the blocks it made; the body may be "
                                    "incomplete, write it again")
            for block, kids in zip(made, later):
                if kids:
                    self.append(notion_id(block.get("id"), "a block's id", EXIT_SERVICE), kids)

    def replace_body(self, page: str, blocks: list) -> None:
        """The new body first, then the old blocks deleted: a failure never leaves the page empty."""
        old = [b["id"] for b in self.paged("list_children", page)[0]]
        self.append(page, blocks)
        for ident in old:
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
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".issue-tracker-notion.", suffix=".tmp")
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
            "is unknown; nothing was sent this time. Look at the base, then run resolve --idempotency-key <k> with "
            "--id <id> if the row exists or --not-created if it does not, and --confirmed")


# --- items ---------------------------------------------------------------------


def plain(rich) -> str:
    return "".join((r.get("plain_text") if r.get("plain_text") is not None else (r.get("text") or {}).get("content", ""))
                   for r in rich or [] if isinstance(r, dict))


def text_objects(text: str) -> list:
    return [{"type": "text", "text": {"content": text[i:i + TEXT_LIMIT]}} for i in range(0, len(text), TEXT_LIMIT)]


def archived(page: dict) -> bool:
    return bool(page.get("in_trash") or page.get("is_archived") or page.get("archived"))


def prop(page: dict, name: str, cfg_name: str):
    value = (page.get("properties") or {}).get(name)
    if not isinstance(value, dict):
        raise ProviderError(f"the base has no property {name!r} (task_board.fields.{cfg_name})", EXIT_NOT_CONFIGURED)
    return value


def read_state(page: dict, cfg: dict):
    value = prop(page, cfg["fields"]["state"], "state")
    kind = value.get("type")
    option = value.get(kind) if kind in ("status", "select") else None
    if not option:
        return "requested"
    return cfg["states"].get(option.get("name"))


def block_ids(blocks: list) -> list:
    """The ids of the blocks given and of their children, at every depth, in reading order."""
    out = []
    for b in blocks:
        out.append(b.get("id"))
        kind = b.get("type")
        out += block_ids(((b.get(kind) if isinstance(kind, str) else None) or {}).get("children") or [])
    return [i for i in out if isinstance(i, str)]


def comments_of(service: Service, ident: str, blocks: list) -> list:
    """The comments of the row's page and of every block in its body: the service lists a comment made on a block
    under that block only (measured, README.md, N4). One listing per block; a comment met twice is kept once."""
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


def item_of(service: Service, page: dict, cfg: dict) -> dict:
    """A row as the contract shows it. The body of a row in the trash cannot be listed (the service answers 404,
    measured, README.md, N8): it is read as no text and no comments, and archived is true."""
    ident = page["id"]
    gone = archived(page)
    blocks = [] if gone else service.blocks(ident)
    return {"id": ident, "version": page.get("last_edited_time"),
            "title": plain(prop(page, cfg["fields"]["title"], "title").get("title")),
            "text": nb.to_markdown(blocks).strip(), "state": read_state(page, cfg),
            "archived": gone, "url": page.get("url"),
            "comments": [] if gone else comments_of(service, ident, blocks)}


def shown_text(shown: dict) -> str:
    return "\n".join(f"{k}: {v}" for k, v in sorted(shown.items()))


def item_file(path) -> dict:
    if not path:
        raise ProviderError("--item-file is required", EXIT_USAGE)
    try:
        with open(path, encoding="utf-8") as f:
            item = json.load(f)
    except OSError:
        raise ProviderError(f"the item file {path} cannot be read", EXIT_USAGE) from None
    except ValueError:
        raise ProviderError(f"the item file {path} is not JSON", EXIT_USAGE) from None
    if not isinstance(item, dict):
        raise ProviderError("the item file holds an object", EXIT_USAGE)
    unknown = sorted(set(item) - set(ITEM_KEYS))
    if unknown:
        raise ProviderError(f"the item file has unknown keys: {', '.join(unknown)}", EXIT_USAGE)
    if "title" in item and (not isinstance(item["title"], str) or not item["title"].strip() or "\n" in item["title"]):
        raise ProviderError("title is one line of text", EXIT_USAGE)
    if "text" in item and not isinstance(item["text"], str):
        raise ProviderError("text is text", EXIT_USAGE)
    if "state" in item and item["state"] not in STATES:
        raise ProviderError(f"state is one of {', '.join(STATES)}", EXIT_USAGE)
    if "shown" in item and (not isinstance(item["shown"], dict) or not all(
            isinstance(k, str) and SHOWN_KEY.fullmatch(k) and isinstance(v, str) and "\n" not in v
            for k, v in item["shown"].items())):
        raise ProviderError("shown is an object of one-line text values, keyed by lowercase names", EXIT_USAGE)
    return item


def properties_for(item: dict, cfg: dict, state_kind: str, page=None) -> dict:
    """The property values to write: only those the item names and, for an existing row, only those that differ."""
    fields, out = cfg["fields"], {}
    if "title" in item:
        title = item["title"].strip()
        if page is None or plain(prop(page, fields["title"], "title").get("title")) != title:
            out[fields["title"]] = {"title": text_objects(title)}
    if "state" in item:
        option = cfg["options"][item["state"]]
        if page is None or read_state(page, cfg) != item["state"]:
            out[fields["state"]] = {state_kind: {"name": option}}
    if "shown" in item:
        shown = shown_text(item["shown"])
        if page is None or plain(prop(page, fields["shown"], "shown").get("rich_text")) != shown:
            out[fields["shown"]] = {"rich_text": text_objects(shown)}
    return out


def schema_check(schema: dict, cfg: dict) -> str:
    """Check the base has the three properties; return the kind of the state property (status or select)."""
    props = schema.get("properties") or {}
    wanted = (("title", ("title",)), ("state", ("status", "select")), ("shown", ("rich_text",)))
    for key, kinds in wanted:
        name = cfg["fields"][key]
        if not isinstance(props.get(name), dict) or props[name].get("type") not in kinds:
            raise ProviderError(f"the base has no {' or '.join(kinds)} property {name!r} (task_board.fields.{key})",
                                EXIT_NOT_CONFIGURED)
    return props[cfg["fields"]["state"]]["type"]


def not_given(exc: ProviderError, what: str) -> ProviderError:
    if exc.status in (403, 404):
        return ProviderError(f"{what} does not exist or the integration was not given it ({exc})", EXIT_NOT_CONFIGURED)
    return exc


# --- verbs ---------------------------------------------------------------------


def mode_of(args: dict) -> str:
    if args.get("--dry-run") and args.get("--confirmed"):
        raise ProviderError("give --dry-run or --confirmed, not both", EXIT_USAGE)
    if not args.get("--dry-run") and not args.get("--confirmed"):
        raise ProviderError("this verb changes the board: give --dry-run to see the write, or --confirmed to make it",
                            EXIT_USAGE)
    return "dry" if args.get("--dry-run") else "confirmed"


def key_of(args: dict) -> str:
    key = args.get("--idempotency-key")
    if not isinstance(key, str) or not key.strip() or len(key) > 512 or re.search(r"[\x00-\x1f\x7f]", key):
        raise ProviderError("--idempotency-key is required: one line of at most 512 characters", EXIT_USAGE)
    return key


def cmd_check(args: dict) -> int:
    cfg = board_config(args.get("--config-file"))
    service = Service()
    try:
        schema = service.call("retrieve_base", cfg["base"])
    except ProviderError as exc:
        raise not_given(exc, "the base") from None
    schema_check(schema, cfg)
    return emit({"ok": True})


def cmd_list(args: dict) -> int:
    cfg = board_config(args.get("--config-file"))
    pages, truncated = Service().paged("query_base", cfg["base"])
    return emit({"items": [{"id": p.get("id"), "version": p.get("last_edited_time"), "archived": archived(p)}
                           for p in pages], "truncated": truncated})


def retrieve(service: Service, ident: str) -> dict:
    try:
        return service.call("retrieve_page", ident)
    except ProviderError as exc:
        if exc.status == 404:
            raise ProviderError(f"no item {ident} on the board") from None
        raise


def cmd_get(args: dict) -> int:
    cfg = board_config(args.get("--config-file"))
    ident = notion_id(args.get("--id"), "--id")
    service = Service()
    return emit(item_of(service, retrieve(service, ident), cfg))


def cmd_comments(args: dict) -> int:
    """The row's own open comments, in one listing (paginated), whatever its version: a comment does not move the
    version (measured, N3), so the runtime lists them at every pull. The comments on its body's blocks come with get."""
    board_config(args.get("--config-file"))
    ident = notion_id(args.get("--id"), "--id")
    try:
        listed = Service().paged("list_comments", query={"block_id": ident})[0]
    except ProviderError as exc:
        if exc.status == 404:
            raise ProviderError(f"no item {ident} on the board") from None
        raise
    return emit({"id": ident, "comments": [comment_of(c) for c in listed]})


def cmd_upsert(args: dict) -> int:
    cfg = board_config(args.get("--config-file"))
    mode = mode_of(args)
    key = key_of(args)
    ident = notion_id(args["--id"], "--id") if args.get("--id") is not None else None
    item = item_file(args.get("--item-file"))
    entry = ledger_entry(cfg["base"], key) if ident is None else None
    if entry and entry.get("status") != "done":
        raise ProviderError(pending_message(key, entry))
    if entry:
        ident = entry["id"]
    create = ident is None
    if create and "title" not in item:
        raise ProviderError("an item is created with a title", EXIT_USAGE)
    if mode == "dry":
        return emit({"dry_run": True, "would": {"verb": "upsert", "id": ident, "create": create, "item": item}})
    service = Service()
    if create:
        try:
            state_kind = schema_check(service.call("retrieve_base", cfg["base"]), cfg)
        except ProviderError as exc:
            raise not_given(exc, "the base") from None
        if ledger_claim(cfg["base"], key):  # another run claimed it meanwhile
            raise ProviderError(pending_message(key, ledger_entry(cfg["base"], key) or {}))
        body = {"parent": {"type": "data_source_id", "data_source_id": cfg["base"]},
                "properties": properties_for(item, cfg, state_kind)}
        try:
            made = service.call("create_page", body=body)
        except ProviderError as exc:
            refused = exc.status is not None and 400 <= exc.status < 500 and exc.status not in UNKNOWN_OUTCOME
            ledger_set(cfg["base"], key, None if refused else
                       {"status": "pending", "started_at": now_iso(), "error": str(exc)})
            raise
        except BaseException:
            ledger_set(cfg["base"], key, {"status": "pending", "started_at": now_iso(), "error": "interrupted"})
            raise
        try:
            ident = notion_id(made.get("id"), "the created row's id", EXIT_SERVICE)
        except ProviderError:
            ledger_set(cfg["base"], key, {"status": "pending", "started_at": now_iso(),
                                          "error": "the answer named no row"})
            raise ProviderError("the answer to the creation names no row; the key stays pending until resolve")
        ledger_set(cfg["base"], key, {"status": "done", "id": ident, "recorded_at": now_iso()})
        if item.get("text", "").strip():
            service.append(ident, nb.to_blocks(item["text"]))
    else:
        page = retrieve(service, ident)
        kind = prop(page, cfg["fields"]["state"], "state").get("type")
        changes = properties_for(item, cfg, kind if kind in ("status", "select") else "status", page)
        if changes:
            service.call("update_page", ident, body={"properties": changes})
        if "text" in item:
            wanted = nb.round_trip(item["text"]).strip() if item["text"].strip() else ""
            current = service.blocks(ident)
            if nb.to_markdown(current).strip() != wanted:
                service.replace_body(ident, nb.to_blocks(item["text"]) if wanted else [])
    page = retrieve(service, ident)
    return emit({"id": ident, "version": page.get("last_edited_time"), "created": create})


def cmd_resolve(args: dict) -> int:
    cfg = board_config(args.get("--config-file"))
    mode = mode_of(args)
    key = key_of(args)
    given, not_created = args.get("--id"), args.get("--not-created")
    if (given is None) == (not not_created):
        raise ProviderError("give --id <id> or --not-created", EXIT_USAGE)
    ident = notion_id(given, "--id") if given is not None else None
    if mode == "dry":
        return emit({"dry_run": True, "would": {"verb": "resolve", "key": key, "id": ident}})
    ledger_set(cfg["base"], key, {"status": "done", "id": ident, "recorded_at": now_iso(), "resolved": True}
               if ident else None)
    return emit({"key": key, "id": ident, "resolved": True})


VERBS = {"list": cmd_list, "get": cmd_get, "comments": cmd_comments, "upsert": cmd_upsert, "resolve": cmd_resolve}
VALUE_FLAGS = ("--config-file", "--id", "--item-file", "--idempotency-key")
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
