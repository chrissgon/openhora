"""A stand-in for the Notion API on 127.0.0.1, for the offline tests of providers/issue-tracker/notion.py and
providers/documents/notion.py. Not a test file, and never a copy of the live service's behaviour: it serves exactly
the calls of the two providers' tables (their README.md, "Calls this provider makes"), keeps pages, blocks, rows and
comments in memory, and returns stored blocks as given.

What it decides where the live service differs or is not measured yet (README.md, "Measured on the live service"): a
page's last_edited_time moves on every change to the page and to a block under it, by one second per change (live,
N1 and N2: it is rounded to the minute), and, as on the live service (N3), not on a comment; a listed
comment is an open one (N5); a deleted block and a trashed page are left out of every list. As measured (N4, N8): a
comment made on a block is listed under that block only, and with the page once the block is deleted; the children
of a page in the trash cannot be listed (404).
It refuses what the reference says the service refuses: no Notion-Version header, a wrong token, more than 100
children in one append, more than two levels of nesting in one request, a text object over 2,000 characters, a
position other than end or start (after_block, which the providers do not use, is refused too), and,
as measured (N11), a code block whose language is not one of the reference's list (LANGUAGES of
providers/documents/notion_blocks.py, the one copy of that list).

Usage (from a test or a harness):
  fake = fake_notion.shared()        one server per process, started on first use (a daemon thread)
  fake.base, fake.token              what the provider's environment names
  fake.create_base(...), fake.create_page(...), fake.person_*(...)
  fake.requests                      every request served: (method, path, JSON body or None)
  fake.user_agents                   the User-Agent header of every request served, in the same order
  fake.fail_next(name, status, carried_out=False), fake.redirect_next = True
"""
from __future__ import annotations

import importlib.util
import json
import re
import secrets
import threading
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

VERSION = "2026-03-11"
MAX_CHILDREN = 100
MAX_NESTING = 2
TEXT_LIMIT = 2000
MAX_PAGE_SIZE = 100
EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)
_spec = importlib.util.spec_from_file_location(
    "notion_blocks_for_fake", Path(__file__).resolve().parents[1] / "notion_blocks.py")
_blocks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_blocks)
LANGUAGES = _blocks.LANGUAGES

ROUTES = [  # (call name, method, path pattern): the union of the two providers' tables
    ("retrieve_base", "GET", r"/v1/data_sources/(?P<id>[^/]+)"),
    ("query_base", "POST", r"/v1/data_sources/(?P<id>[^/]+)/query"),
    ("retrieve_page", "GET", r"/v1/pages/(?P<id>[^/]+)"),
    ("create_page", "POST", r"/v1/pages"),
    ("update_page", "PATCH", r"/v1/pages/(?P<id>[^/]+)"),
    ("list_children", "GET", r"/v1/blocks/(?P<id>[^/]+)/children"),
    ("append_children", "PATCH", r"/v1/blocks/(?P<id>[^/]+)/children"),
    ("delete_block", "DELETE", r"/v1/blocks/(?P<id>[^/]+)"),
    ("list_comments", "GET", r"/v1/comments"),
]


class Answer(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code = status, code


def new_id() -> str:
    return str(uuid.uuid4())


def rich(text: str) -> list:
    return [{"type": "text", "text": {"content": text, "link": None}, "plain_text": text, "href": None,
             "annotations": {"bold": False, "italic": False, "strikethrough": False, "underline": False,
                             "code": False, "color": "default"}}] if text else []


def depth(blocks: list) -> int:
    """Levels of nesting below the blocks given: 0 for blocks with no children."""
    return max((1 + depth(b.get(b.get("type"), {}).get("children") or []) for b in blocks
                if b.get(b.get("type"), {}).get("children")), default=0)


def check_languages(blocks: list, where: str = "body.children") -> None:
    """A code block's language must be on the list; the message has the live service's shape (N11), shortened."""
    for n, b in enumerate(blocks or []):
        body = b.get(b.get("type")) if isinstance(b, dict) else None
        if not isinstance(body, dict):
            continue
        if b.get("type") == "code" and body.get("language") not in LANGUAGES:
            raise Answer(400, "validation_error", f"body failed validation: {where}[{n}].code.language should be "
                                                  "one of the service's languages")
        check_languages(body.get("children") or [], f"{where}[{n}].{b.get('type')}.children")


def check_text(value) -> None:
    if isinstance(value, dict):
        content = (value.get("text") or {}).get("content") if value.get("type") == "text" else None
        if isinstance(content, str) and len(content) > TEXT_LIMIT:
            raise Answer(400, "validation_error", f"text content is longer than {TEXT_LIMIT}")
        for v in value.values():
            check_text(v)
    elif isinstance(value, list):
        for v in value:
            check_text(v)


class FakeNotion:
    def __init__(self):
        self.token = "fake-notion-" + secrets.token_hex(12)
        self.lock = threading.RLock()
        self.clock = 0
        self.bases, self.pages, self.blocks, self.children, self.comments = {}, {}, {}, {}, {}
        self.requests, self.failures, self.redirect_next, self.redirected = [], {}, False, 0
        self.user_agents = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler())
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    # --- the model -------------------------------------------------------------

    def tick(self) -> str:
        self.clock += 1
        return (EPOCH + timedelta(seconds=self.clock)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    def page_of(self, ident: str):
        while ident in self.blocks:
            ident = self.blocks[ident]["parent_id"]
        return ident if ident in self.pages else None

    def deleted(self, ident: str) -> bool:
        """A block is deleted when it or a block above it is."""
        while ident in self.blocks:
            if self.blocks[ident]["in_trash"]:
                return True
            ident = self.blocks[ident]["parent_id"]
        return False

    def touch(self, ident: str) -> None:
        page = self.page_of(ident)
        if page:
            self.pages[page]["last_edited_time"] = self.tick()

    def create_base(self, state_kind: str = "status", names=("Name", "Status", "Runtime")) -> str:
        ident = new_id()
        with self.lock:
            self.bases[ident] = {"object": "data_source", "id": ident, "properties": {
                names[0]: {"id": "title", "name": names[0], "type": "title", "title": {}},
                names[1]: {"id": "stat", "name": names[1], "type": state_kind, state_kind: {"options": []}},
                names[2]: {"id": "rt", "name": names[2], "type": "rich_text", "rich_text": {}}}}
        return ident

    def property_value(self, kind: str, value) -> dict:
        if kind in ("title", "rich_text"):
            check_text(value)
            return {"type": kind, kind: [{**r, "plain_text": (r.get("text") or {}).get("content", ""), "href": None}
                                         for r in value or []]}
        return {"type": kind, kind: ({"name": value["name"]} if isinstance(value, dict) and value.get("name") else None)}

    def set_properties(self, page: dict, values: dict) -> None:
        schema = self.bases[page["parent"]["data_source_id"]]["properties"] if "data_source_id" in page["parent"] \
            else {"title": {"type": "title"}}
        for name, value in values.items():
            if name not in schema or not isinstance(value, dict) or schema[name]["type"] not in value:
                raise Answer(400, "validation_error", f"{name} is not a property that exists")
            kind = schema[name]["type"]
            page["properties"][name] = {"id": schema[name].get("id", name), **self.property_value(kind, value[kind])}

    def create_root(self) -> str:
        """A page at the top of the workspace, as a person makes one to share with the integration."""
        ident = new_id()
        with self.lock:
            when = self.tick()
            self.pages[ident] = {"object": "page", "id": ident, "created_time": when, "last_edited_time": when,
                                 "in_trash": False, "is_archived": False, "parent": {"type": "workspace", "workspace": True},
                                 "properties": {"title": {"id": "title", "type": "title", "title": rich("Workbench")}},
                                 "url": f"https://notion.example/{ident.replace('-', '')}"}
            self.children[ident] = []
        return ident

    def create_page(self, parent: dict, properties: dict, children=None) -> dict:
        with self.lock:
            if parent.get("type") == "data_source_id" and parent.get("data_source_id") in self.bases:
                schema = self.bases[parent["data_source_id"]]["properties"]
                props = {n: {"id": p.get("id", n), "type": p["type"], p["type"]: [] if p["type"] in ("title", "rich_text")
                             else None} for n, p in schema.items()}
            elif parent.get("type") == "page_id" and parent.get("page_id") in self.pages:
                if set(properties) - {"title"}:
                    raise Answer(400, "validation_error", "title is the only valid property of a page under a page")
                props = {"title": {"id": "title", "type": "title", "title": []}}
            else:
                raise Answer(404, "object_not_found", "Could not find the parent.")
            ident = new_id()
            when = self.tick()
            page = {"object": "page", "id": ident, "created_time": when, "last_edited_time": when, "in_trash": False,
                    "is_archived": False, "parent": dict(parent), "properties": props,
                    "url": f"https://notion.example/{ident.replace('-', '')}"}
            self.pages[ident] = page
            self.set_properties(page, properties or {})
            self.children[ident] = []
            if children:
                self.store(ident, children)
            return page

    def store(self, parent: str, blocks: list, first: bool = False) -> list:
        """Keep blocks under a parent: after its other children, or before them when first (position "start")."""
        made = []
        for n, b in enumerate(blocks):
            kind = b.get("type")
            if not isinstance(kind, str) or not isinstance(b.get(kind), dict):
                raise Answer(400, "validation_error", "a block has no body of its type")
            body = json.loads(json.dumps(b[kind]))
            kids = body.pop("children", None) or []
            ident = new_id()
            self.blocks[ident] = {"object": "block", "id": ident, "type": kind, kind: body, "parent_id": parent,
                                  "in_trash": False}
            if first:
                self.children[parent].insert(n, ident)
            else:
                self.children[parent].append(ident)
            self.children[ident] = []
            self.store(ident, kids)
            made.append(ident)
        self.touch(parent)
        return made

    def shown(self, ident: str) -> dict:
        b = self.blocks[ident]
        out = {k: json.loads(json.dumps(v)) for k, v in b.items() if k != "parent_id"}
        out["has_children"] = bool(self.children.get(ident))
        out["parent"] = {"type": "page_id" if b["parent_id"] in self.pages else "block_id",
                         ("page_id" if b["parent_id"] in self.pages else "block_id"): b["parent_id"]}
        return out

    def comment(self, ident: str, text: str) -> None:
        with self.lock:
            self.comments.setdefault(ident, []).append({
                "object": "comment", "id": new_id(), "discussion_id": new_id(), "created_time": self.tick(),
                "created_by": {"object": "user", "id": new_id()}, "rich_text": rich(text),
                "parent": {"type": "block_id", "block_id": ident} if ident in self.blocks
                else {"type": "page_id", "page_id": ident}})
            # As on the live service (N3): a comment does not move the page's last_edited_time.

    # --- what a person does in the app ------------------------------------------

    def person_replaces_body(self, ident: str, blocks: list) -> None:
        with self.lock:
            for kid in self.children[ident]:
                self.blocks[kid]["in_trash"] = True
            self.children[ident] = []
            self.store(ident, blocks)
            self.touch(ident)

    def person_sets(self, ident: str, name: str, value) -> None:
        """A property of a row: text for a title or text property, an option name (or None) for a status."""
        with self.lock:
            page = self.pages[ident]
            kind = page["properties"][name]["type"]
            page["properties"][name] = {**page["properties"][name], **self.property_value(
                kind, [{"type": "text", "text": {"content": value}}] if kind in ("title", "rich_text")
                else ({"name": value} if value else None))}
            self.touch(ident)

    def person_trashes(self, ident: str) -> None:
        with self.lock:
            self.pages[ident]["in_trash"] = True
            self.touch(ident)

    def fail_next(self, name: str, status: int, carried_out: bool = False) -> None:
        """The next call of that name answers status; carried_out: it is made first, as a lost answer would be."""
        self.failures[name] = (status, carried_out)

    def count(self, name: str) -> int:
        method, pattern = next((m, p) for n, m, p in ROUTES if n == name)
        return sum(1 for m, path, _ in self.requests if m == method and re.fullmatch(pattern, path))

    # --- the calls ---------------------------------------------------------------

    def listing(self, items: list, cursor, size) -> dict:
        size = min(int(size or MAX_PAGE_SIZE), MAX_PAGE_SIZE)
        start = int(cursor or 0)
        chunk = items[start:start + size]
        more = start + size < len(items)
        return {"object": "list", "results": chunk, "has_more": more, "next_cursor": str(start + size) if more else None}

    def serve(self, name: str, ids: dict, query: dict, body):
        if name == "retrieve_base":
            if ids["id"] not in self.bases:
                raise Answer(404, "object_not_found", "Could not find data source.")
            return self.bases[ids["id"]]
        if name == "query_base":
            if ids["id"] not in self.bases:
                raise Answer(404, "object_not_found", "Could not find data source.")
            rows = [p for p in self.pages.values() if p["parent"].get("data_source_id") == ids["id"] and not p["in_trash"]]
            return self.listing(rows, (body or {}).get("start_cursor"), (body or {}).get("page_size"))
        if name == "create_page":
            return self.create_page((body or {}).get("parent") or {}, (body or {}).get("properties") or {},
                                    self.checked_children(body or {}))
        if name in ("retrieve_page", "update_page"):
            page = self.pages.get(ids["id"])
            if page is None:
                raise Answer(404, "object_not_found", "Could not find page.")
            if name == "update_page":
                self.set_properties(page, (body or {}).get("properties") or {})
                page["last_edited_time"] = self.tick()
            return page
        if name in ("list_children", "append_children"):
            if ids["id"] not in self.children or self.blocks.get(ids["id"], {}).get("in_trash") \
                    or self.pages.get(ids["id"], {}).get("in_trash"):
                raise Answer(404, "object_not_found", "Could not find block.")
            if name == "append_children":
                position = (body or {}).get("position") or {"type": "end"}
                if not isinstance(position, dict) or position.get("type") not in ("end", "start"):
                    raise Answer(400, "validation_error", "position should be end or start in this stand-in")
                made = self.store(ids["id"], self.checked_children(body or {}), first=position["type"] == "start")
                if position["type"] == "start":  # as observed live (N12): not only the blocks it made
                    return self.listing([self.shown(i) for i in self.children[ids["id"]]
                                         if not self.blocks[i]["in_trash"]], None, None)
                return {"object": "list", "results": [self.shown(i) for i in made], "has_more": False,
                        "next_cursor": None}
            kids = [self.shown(i) for i in self.children[ids["id"]] if not self.blocks[i]["in_trash"]]
            return self.listing(kids, query.get("start_cursor"), query.get("page_size"))
        if name == "delete_block":
            block = self.blocks.get(ids["id"])
            if block is None or block["in_trash"]:
                raise Answer(404, "object_not_found", "Could not find block.")
            block["in_trash"] = True
            self.children[block["parent_id"]].remove(ids["id"])
            self.touch(block["parent_id"])
            return self.shown(ids["id"])
        if name == "list_comments":
            target = query.get("block_id")
            if not target or (target not in self.pages and target not in self.blocks):
                raise Answer(404, "object_not_found", "Could not find block.")
            listed = list(self.comments.get(target, []))
            if target in self.pages:  # the comments of a deleted block surface with its page
                listed += [c for b, cs in self.comments.items() if b in self.blocks and self.deleted(b)
                           and self.page_of(b) == target for c in cs]
            return self.listing(listed, query.get("start_cursor"), query.get("page_size"))
        raise Answer(400, "invalid_request_url", "Invalid request URL.")

    def checked_children(self, body: dict) -> list:
        kids = body.get("children") or []
        if not isinstance(kids, list):
            raise Answer(400, "validation_error", "children should be an array")
        if len(kids) > MAX_CHILDREN:
            raise Answer(400, "validation_error", f"children length should be <= {MAX_CHILDREN}")
        if depth(kids) > MAX_NESTING:
            raise Answer(400, "validation_error", f"more than {MAX_NESTING} levels of nesting in one request")
        check_text(kids)
        check_languages(kids)
        return kids

    def handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def answer(self, status: int, data: dict, headers=()) -> None:
                raw = json.dumps(data).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                for k, v in headers:
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(raw)

            def handle_any(self):
                url = urlparse(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                body = json.loads(raw) if raw else None
                with fake.lock:
                    fake.requests.append((self.command, url.path, body))
                    fake.user_agents.append(self.headers.get("User-Agent"))
                    if url.path == "/redirected":
                        fake.redirected += 1
                        return self.answer(200, {})
                    if fake.redirect_next:
                        fake.redirect_next = False
                        return self.answer(307, {}, [("Location", fake.base + "/redirected")])
                    if self.headers.get("Notion-Version") != VERSION:
                        return self.answer(400, {"object": "error", "status": 400, "code": "missing_version",
                                                 "message": "Notion-Version header failed validation."})
                    if self.headers.get("Authorization") != f"Bearer {fake.token}":
                        return self.answer(401, {"object": "error", "status": 401, "code": "unauthorized",
                                                 "message": "API token is invalid."})
                    route = next(((n, m) for n, method, p in ROUTES if method == self.command
                                  for m in [re.fullmatch(p, url.path)] if m), None)
                    if route is None:
                        return self.answer(400, {"object": "error", "status": 400, "code": "invalid_request_url",
                                                 "message": "Invalid request URL."})
                    name, match = route
                    failure = fake.failures.pop(name, None)
                    query = {k: v[0] for k, v in parse_qs(url.query).items()}
                    try:
                        if failure and failure[1]:
                            fake.serve(name, match.groupdict(), query, body)
                        if failure:
                            headers = [("Retry-After", "1")] if failure[0] == 429 else []
                            return self.answer(failure[0], {"object": "error", "status": failure[0],
                                                            "code": "rate_limited" if failure[0] == 429 else "error",
                                                            "message": "Stand-in failure."}, headers)
                        return self.answer(200, fake.serve(name, match.groupdict(), query, body))
                    except Answer as e:
                        return self.answer(e.status, {"object": "error", "status": e.status, "code": e.code,
                                                      "message": str(e)})

            do_GET = do_POST = do_PATCH = do_DELETE = handle_any

        return Handler


_SHARED = None


def shared() -> FakeNotion:
    global _SHARED
    if _SHARED is None:
        _SHARED = FakeNotion()
    return _SHARED
