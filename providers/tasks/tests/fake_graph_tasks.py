"""A stand-in for Microsoft To Do on 127.0.0.1, for the tests of the Tasks reader (providers/tasks/microsoft.py) and writer (providers/writer/microsoft-todo.py), package CB-4: the
Microsoft identity token endpoint (a public client, a new refresh token on every refresh, the old one left valid; it records the `scope` each refresh names) and the lists and tasks
of the signed-in person through Graph (list of lists, list of tasks in pages with `@odata.nextLink`, get, create, patch). It keeps its tasks in memory, gives each an `@odata.etag` that
moves with every change and a `lastModifiedDateTime` from a clock the test sets, and RECORDS every request (method, path, query, headers that matter, body) so that a test can assert the
exact list. `unexpected()` lists any request the providers should never send. Like Graph as far as its pages say, it takes no If-Match and no OData parameter on the To Do endpoints: a
request that carries one is recorded, and a test asserts there is none.

  fake = FakeGraphTasks()                     # starts on a free loopback port in a daemon thread; fake.close() stops it
  fake.record_json(**over)                    # a MICROSOFT_ACCOUNT_TOKEN value this fake accepts (the six permissions by default)
  fake.env("INTEGRATION_TASKS_MICROSOFT")     # the test overrides of a provider (both URLs, set together); "WRITER_TASKS_MICROSOFT" for the writer
  fake.add_task(list_id, task_id, title, **more)   # a task that is already there; returns it
  fake.tick(seconds)                          # moves the service's clock
  fake.lose_answer_once, fake.refuse_next = (status, code), fake.redirect_next, fake.fail_get_next    # as in the other stand-ins
  fake.page_cap                               # at most this many tasks in a page (and an `@odata.nextLink` while more remain)
  fake.link_base                              # the base of every `@odata.nextLink` (default: this listener): a test points it at another host
  fake.scope_granted                          # what a refresh says the token carries (default: the six permissions and the words that grant nothing)

Every value is a stand-in made up for the tests; none is a credential.
"""
from __future__ import annotations

import datetime
import json
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ADDRESS = "casey.rivera@mail.example"
CLIENT_ID = "77777777-8888-9999-aaaa-bbbbbbbbbbbb"
TENANT = "common"
REFRESH_TOKEN = "fake-refresh-token-0-not-real"
ACCESS_TOKEN = "fake-access-token-not-real"
SECRETS = (REFRESH_TOKEN, ACCESS_TOKEN)
PREVIOUS = ("Mail.ReadWrite", "Mail.Send", "Calendars.ReadWrite", "Files.ReadWrite", "User.Read")      # a token made before To Do tasks was added
PLATFORM = PREVIOUS + ("Tasks.ReadWrite",)
PREFIX = "https://graph.microsoft.com/"
GRANTED = " ".join(PREFIX + name for name in PLATFORM) + " offline_access openid profile"
GRANTED_PREVIOUS = " ".join(PREFIX + name for name in PREVIOUS) + " offline_access openid profile"
GRAPH = "/v1.0"
DEFAULT_LIST = "AAMkADIyAAAAABrJAAA="
OTHER_LIST = "AAMkADIyAAAEFTTrJAAA="
FLAGGED_LIST = "AAMkADIyAAAFlaggedAAA="


class FakeGraphTasks:
    def __init__(self):
        self.requests: list = []
        self.token_forms: list = []
        self.lists: dict = {DEFAULT_LIST: ("Tasks", "defaultList"), OTHER_LIST: ("Groceries", "none"), FLAGGED_LIST: ("Flagged email", "flaggedEmails")}
        self.tasks: dict = {DEFAULT_LIST: {}, OTHER_LIST: {}, FLAGGED_LIST: {}}
        self.clock = datetime.datetime(2026, 10, 27, 12, 0, 0, tzinfo=datetime.timezone.utc)
        self.version = 0
        self.counter = 0
        self.rotations = 0
        self.valid_refresh = {REFRESH_TOKEN}
        self.scope_granted = GRANTED
        self.lose_answer_once = False
        self.refuse_next = None
        self.redirect_next = False
        self.fail_get_next = None
        self.page_cap = None
        self.link_base = None
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *args):
                return

            def _send(self, status, body, headers=None):
                data = b"" if body is None else body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def _handle(self):
                parsed = urllib.parse.urlparse(self.path)
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                if self.command == "POST" and parsed.path == "/token":
                    form = {k: v[0] for k, v in urllib.parse.parse_qs(raw.decode()).items()}
                    owner.token_forms.append(form)
                    return self._send(*owner.token(form))
                try:
                    body = json.loads(raw) if raw else None
                except ValueError:
                    body = {"unreadable": True}
                entry = {"method": self.command, "path": urllib.parse.unquote(parsed.path), "raw_path": parsed.path,
                         "query": {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}, "body": body, "if_match": self.headers.get("If-Match"),
                         "bearer": self.headers.get("Authorization") == f"Bearer {ACCESS_TOKEN}", "host": self.headers.get("Host")}
                owner.requests.append(entry)
                if not entry["bearer"]:
                    return self._send(401, {"error": {"code": "InvalidAuthenticationToken", "message": "Access token is empty or invalid."}})
                if owner.redirect_next:
                    owner.redirect_next = False
                    return self._send(307, None, {"Location": "http://127.0.0.1:1/elsewhere"})
                if self.command == "GET" and owner.fail_get_next:
                    status, owner.fail_get_next = owner.fail_get_next, None
                    return self._send(status, {"error": {"code": "generalException", "message": "stand-in failure"}})
                status, answer, headers, apply = owner.api(entry)
                if self.command != "GET" and owner.lose_answer_once and apply:
                    owner.lose_answer_once = False
                    apply()
                    self.connection.close()      # the request landed and the answer is lost
                    return None
                if apply:
                    answer = apply() or answer
                return self._send(status, answer, headers)

            do_GET = do_POST = do_PATCH = do_DELETE = do_PUT = _handle   # noqa: N815

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.root = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.base = self.root + GRAPH
        self.token_url = f"{self.root}/token"
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    # --- the service -------------------------------------------------------------------------------------------------------------

    def token(self, form):
        if form.get("client_id") != CLIENT_ID or "client_secret" in form:
            return 401, {"error": "invalid_client", "error_description": "AADSTS700016: Application not found."}
        if form.get("grant_type") == "refresh_token" and form.get("refresh_token") in self.valid_refresh:
            self.rotations += 1
            rotated = f"fake-refresh-token-{self.rotations}-not-real"
            self.valid_refresh.add(rotated)
            return 200, {"access_token": ACCESS_TOKEN, "expires_in": 3599, "token_type": "Bearer", "scope": self.scope_granted, "refresh_token": rotated}
        return 400, {"error": "invalid_grant", "error_description": "AADSTS70000: bad refresh token"}

    def tick(self, seconds=1):
        self.clock += datetime.timedelta(seconds=seconds)

    def stamp(self):
        return self.clock.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")

    def next_etag(self):
        self.version += 1
        return f'W/"etag{1000 + self.version}=="'

    def add_task(self, list_id, task_id, title, **more):
        item = {"@odata.etag": self.next_etag(), "id": task_id, "title": title, "status": "notStarted", "importance": "normal", "isReminderOn": False,
                "createdDateTime": self.stamp(), "lastModifiedDateTime": self.stamp(), "body": {"content": "", "contentType": "text"}, "categories": []}
        item.update(more)
        self.tasks[list_id][task_id] = item
        return item

    def unexpected(self):
        """The requests that are not one of the two providers' allow-lists (a method or a path they should never send)."""
        found = []
        for entry in self.requests:
            path, method = entry["path"], entry["method"]
            tail = r"/v1\.0/me/todo/lists/[A-Za-z0-9_=-]+/tasks"
            ok = (path == GRAPH + "/me/todo/lists" and method == "GET") or (re.fullmatch(tail, path) and method in ("GET", "POST")) \
                or (re.fullmatch(tail + r"/[A-Za-z0-9_=-]+", path) and method in ("GET", "PATCH"))
            if not ok:
                found.append((method, path))
        return found

    def api(self, entry):
        """(status, answer, headers, apply) where apply() changes the tasks (called after the answer is decided, before it is sent) and may return the answer."""
        method, path, query = entry["method"], entry["path"], entry["query"]
        if path == GRAPH + "/me/todo/lists" and method == "GET":
            return 200, {"value": [{"@odata.type": "#microsoft.graph.todoTaskList", "id": i, "displayName": n, "isOwner": True, "isShared": False, "wellknownListName": w}
                                   for i, (n, w) in self.lists.items()]}, {}, None
        found = re.fullmatch(GRAPH + r"/me/todo/lists/([^/]+)/tasks(?:/([^/]+))?", path)
        if not found:
            return 405, {"error": {"code": "methodNotAllowed", "message": "not served"}}, {}, None
        list_id, task_id = found.group(1), found.group(2)
        if list_id not in self.tasks:
            return 404, {"error": {"code": "ErrorItemNotFound", "message": "The specified object was not found in the store."}}, {}, None
        if method in ("POST", "PATCH") and self.refuse_next:
            status, code = self.refuse_next
            self.refuse_next = None
            return status, {"error": {"code": code, "message": code}}, ({"Retry-After": "30"} if status in (429, 503) else {}), None
        if task_id is None and method == "GET":
            items = [dict(t) for t in self.tasks[list_id].values()]
            size = self.page_cap or 100
            start = int(query.get("$skip", "0"))
            answer = {"value": items[start:start + size]}
            if start + size < len(items):
                following = {**query, "$skip": str(start + size)}
                answer["@odata.nextLink"] = f"{self.link_base or self.root}{GRAPH}{path[len(GRAPH):]}?" + urllib.parse.urlencode(following)
            return 200, answer, {}, None
        if task_id is None and method == "POST":
            self.counter += 1
            new_id = f"AAMkTask{self.counter:04d}="

            def apply():
                self.add_task(list_id, new_id, entry["body"]["title"])
                return dict(self.tasks[list_id][new_id])
            return 201, {"id": new_id}, {}, apply
        item = self.tasks[list_id].get(task_id)
        if item is None:
            return 404, {"error": {"code": "ErrorItemNotFound", "message": "The specified object was not found in the store."}}, {}, None
        if method == "GET":
            return 200, dict(item), {}, None
        if method == "PATCH":
            def apply():
                for key, value in entry["body"].items():
                    item[key] = value
                item["@odata.etag"], item["lastModifiedDateTime"] = self.next_etag(), self.stamp()
                return dict(item)
            return 200, dict(item), {}, apply
        return 405, {"error": {"code": "methodNotAllowed", "message": "not served"}}, {}, None

    # --- what a test hands to a provider -------------------------------------------------------------------------------------------

    def record_json(self, **over) -> str:
        record = {"slot": "main", "refresh_token": REFRESH_TOKEN, "client_id": CLIENT_ID, "tenant": TENANT, "scope": " ".join(PLATFORM),
                  "account_kind": "personal", "account": ADDRESS, "obtained_at": "2026-10-27T08:00:00Z"}
        record.update(over)
        return json.dumps({k: v for k, v in record.items() if v is not None})

    def env(self, prefix="INTEGRATION_TASKS_MICROSOFT") -> dict:
        return {f"{prefix}_API_BASE": self.base, f"{prefix}_TOKEN_URL": self.token_url}

    def graph_requests(self):
        return [r for r in self.requests if r["path"].startswith(GRAPH + "/")]

    def writes(self) -> list:
        """The requests that are not reads: [(method, path, query, body)]."""
        return [(r["method"], r["path"], r["query"], r["body"]) for r in self.graph_requests() if r["method"] != "GET"]
