"""A stand-in for Google Tasks on 127.0.0.1, for the tests of the Tasks reader (providers/tasks/google.py) and writer (providers/writer/google-tasks.py), package CB-4: the
token endpoint, the list of lists, and the tasks of the lists (list with its filters and pages, get, insert, patch). It keeps its lists and tasks in memory, gives each task an etag
that moves with every change and an `updated` time from a clock the test sets, and RECORDS every request (method, path, query, headers that matter, body) so that a test can assert
the exact list. A method or a path the provider should never send (a delete, a move, a clear, a list written) is answered 405 and recorded too, and `unexpected()` lists it.
Like the real service as far as its pages say, it takes no conditional write: a request that carries `If-Match` is recorded in `if_match` and a test asserts there is none.

  fake = FakeGoogleTasks()                    # starts on a free loopback port in a daemon thread; fake.close() stops it
  fake.record_json(**over)                    # a GOOGLE_ACCOUNT_TOKEN value this fake accepts (the five scopes by default)
  fake.env("INTEGRATION_TASKS_GOOGLE")        # the test overrides of a provider (both URLs, set together); "WRITER_TASKS_GOOGLE" for the writer
  fake.add_task(list_id, task_id, title, **more)   # a task that is already there; returns it
  fake.tick(seconds)                          # moves the service's clock (the `updated` of what is written next)
  fake.lose_answer_once = True                # the next write is APPLIED and the connection is closed with no answer (a lost answer)
  fake.refuse_next = (status, reason)         # the next write is answered with that status and changes nothing
  fake.redirect_next = True                   # the next request is answered 307 to another address
  fake.fail_get_next = 500                    # the next read is answered with that status
  fake.page_cap                               # at most this many tasks in a page of a list (and a nextPageToken while more remain)
  fake.refresh_scope                          # what a refresh says the token carries (default: the five scopes)

Every value is a stand-in made up for the tests; none is a credential.
"""
from __future__ import annotations

import datetime
import json
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ACCOUNT = "pat@example.com"
CLIENT_ID = "stand-in-client-id.example"
CLIENT_SECRET = "fake-client-secret-not-real-4f2a"
REFRESH_TOKEN = "fake-refresh-token-not-real-9b1c"
ACCESS_TOKEN = "fake-access-token-not-real-7d3e"
SECRETS = (CLIENT_SECRET, REFRESH_TOKEN, ACCESS_TOKEN)

GMAIL_MODIFY = "https://www.googleapis.com/auth/gmail.modify"
CALENDAR_EVENTS = "https://www.googleapis.com/auth/calendar.events"
CALENDAR_LIST = "https://www.googleapis.com/auth/calendar.calendarlist.readonly"
DRIVE = "https://www.googleapis.com/auth/drive"
TASKS = "https://www.googleapis.com/auth/tasks"
PREVIOUS_SET = (GMAIL_MODIFY, CALENDAR_EVENTS, CALENDAR_LIST, DRIVE)      # a token made before Google Tasks was added
PLATFORM_SET = PREVIOUS_SET + (TASKS,)

DEFAULT_LIST = "MTIzNDU2Nzg5MDEyMzQ1Njc4OTA"      # what `@default` stands for in this stand-in
OTHER_LIST = "T3RoZXJMaXN0MDAwMDAwMDAwMDA"
LISTS = f"/tasks/v1/users/@me/lists"


class FakeGoogleTasks:
    def __init__(self):
        self.requests: list = []
        self.lists: dict = {DEFAULT_LIST: "My Tasks", OTHER_LIST: "Groceries"}
        self.tasks: dict = {DEFAULT_LIST: {}, OTHER_LIST: {}}
        self.clock = datetime.datetime(2026, 10, 27, 12, 0, 0, tzinfo=datetime.timezone.utc)
        self.version = 0
        self.counter = 0
        self.refresh_scope = " ".join(PLATFORM_SET)
        self.lose_answer_once = False
        self.refuse_next = None
        self.redirect_next = False
        self.fail_get_next = None
        self.page_cap = None
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
                try:
                    body = json.loads(raw) if raw else None
                except ValueError:
                    body = {"unreadable": True}
                entry = {"method": self.command, "path": parsed.path, "query": {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()},
                         "body": body, "if_match": self.headers.get("If-Match"), "bearer": self.headers.get("Authorization") == f"Bearer {ACCESS_TOKEN}"}
                owner.requests.append(entry)
                if self.command == "POST" and parsed.path == "/token":
                    return self._send(*owner.token(urllib.parse.parse_qs(raw.decode())))
                if not entry["bearer"]:
                    return self._send(401, {"error": {"status": "UNAUTHENTICATED", "message": "no bearer token"}})
                if owner.redirect_next:
                    owner.redirect_next = False
                    return self._send(307, None, {"Location": "http://127.0.0.1:1/elsewhere"})
                if self.command == "GET" and owner.fail_get_next:
                    status, owner.fail_get_next = owner.fail_get_next, None
                    return self._send(status, {"error": {"code": status, "message": "stand-in failure"}})
                status, answer, headers, apply = owner.api(entry)
                if status == 405:
                    return self._send(405, answer)
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
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.token_url = f"{self.base}/token"
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    # --- the service -------------------------------------------------------------------------------------------------------------

    def token(self, form):
        first = lambda key: (form.get(key) or [""])[0]   # noqa: E731
        if first("client_id") != CLIENT_ID or first("client_secret") != CLIENT_SECRET:
            return 401, {"error": "invalid_client", "error_description": "stand-in: unknown client"}
        if first("grant_type") == "refresh_token" and first("refresh_token") == REFRESH_TOKEN:
            answer = {"access_token": ACCESS_TOKEN, "expires_in": 3599, "token_type": "Bearer"}
            if self.refresh_scope is not None:
                answer["scope"] = self.refresh_scope
            return 200, answer
        return 400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."}

    def tick(self, seconds=1):
        self.clock += datetime.timedelta(seconds=seconds)

    def stamp(self):
        return self.clock.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    def next_etag(self):
        self.version += 1
        return f'"LTE{1000 + self.version}"'

    def add_task(self, list_id, task_id, title, **more):
        item = {"id": task_id, "etag": self.next_etag(), "title": title, "status": "needsAction", "updated": self.stamp(), "kind": "tasks#task"}
        item.update(more)
        self.tasks[list_id][task_id] = item
        return item

    def real_list(self, name):
        return DEFAULT_LIST if name == "@default" else name

    def unexpected(self):
        """The requests that are not one of the two providers' allow-lists (a method or a path they should never send)."""
        found = []
        for entry in self.requests:
            path, method = entry["path"], entry["method"]
            tail = r"/tasks/v1/lists/(?:@default|[A-Za-z0-9_%-]+)/tasks"
            ok = (path == "/token" and method == "POST") or (path == LISTS and method == "GET") or (re.fullmatch(tail, path) and method in ("GET", "POST")) \
                or (re.fullmatch(tail + r"/[A-Za-z0-9_%-]+", path) and method in ("GET", "PATCH"))
            if not ok:
                found.append((method, path))
        return found

    def api(self, entry):
        """(status, answer, headers, apply) where apply() changes the tasks (called after the answer is decided, before it is sent) and may return the answer."""
        method, path, query = entry["method"], entry["path"], entry["query"]
        if path == LISTS and method == "GET":
            return 200, {"kind": "tasks#taskLists", "items": [{"id": i, "title": t, "kind": "tasks#taskList"} for i, t in self.lists.items()]}, {}, None
        found = re.fullmatch(r"/tasks/v1/lists/(@default|[^/]+)/tasks(?:/([^/]+))?", path)
        if not found:
            return 405, {"error": {"message": "this stand-in takes only the providers' requests"}}, {}, None
        list_id, task_id = self.real_list(urllib.parse.unquote(found.group(1))), found.group(2) and urllib.parse.unquote(found.group(2))
        if list_id not in self.tasks:
            return 404, {"error": {"code": 404, "message": "Task list not found"}}, {}, None
        if method in ("POST", "PATCH") and self.refuse_next:
            status, reason = self.refuse_next
            self.refuse_next = None
            return status, {"error": {"code": status, "message": reason}}, ({"Retry-After": "30"} if status in (429, 503) else {}), None
        if task_id is None and method == "GET":
            items = [dict(t) for t in self.tasks[list_id].values()]
            if query.get("showCompleted") == "false":
                items = [t for t in items if t.get("status") != "completed"]
            if query.get("showHidden") != "true":
                items = [t for t in items if not t.get("hidden")]
            if query.get("showDeleted") != "true":
                items = [t for t in items if not t.get("deleted")]
            if query.get("updatedMin"):
                items = [t for t in items if t["updated"].replace(".000Z", "Z") >= query["updatedMin"]]
            size = min(int(query.get("maxResults", 20)), 100, self.page_cap or 100)
            start = int(query.get("pageToken", "0"))
            answer = {"kind": "tasks#tasks", "items": items[start:start + size]}
            if start + size < len(items):
                answer["nextPageToken"] = str(start + size)
            return 200, answer, {}, None
        if task_id is None and method == "POST":
            self.counter += 1
            new_id = f"task{self.counter:04d}"

            def apply():
                self.add_task(list_id, new_id, entry["body"]["title"])
                return None
            made = {"id": new_id, "etag": f'"LTE{1000 + self.version + 1}"'}
            return 200, made, {}, apply
        item = self.tasks[list_id].get(task_id) if task_id else None
        if item is None:
            return 404, {"error": {"code": 404, "message": "Not Found"}}, {}, None
        if method == "GET":
            return 200, item, {}, None
        if method == "PATCH":
            def apply():
                for key, value in entry["body"].items():
                    item[key] = value
                if item.get("status") == "completed":
                    item["completed"] = self.stamp()
                item["etag"], item["updated"] = self.next_etag(), self.stamp()
                return {"id": item["id"], "etag": item["etag"]}
            return 200, {"id": item["id"], "etag": "(new)"}, {}, apply
        return 405, {"error": {"message": "this stand-in takes only the providers' requests"}}, {}, None

    # --- what a test hands to a provider -------------------------------------------------------------------------------------------

    def record_json(self, **over) -> str:
        record = {"slot": "main", "refresh_token": REFRESH_TOKEN, "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
                  "scope": " ".join(PLATFORM_SET), "account": ACCOUNT, "obtained_at": "2026-10-27T09:00:00Z"}
        record.update(over)
        return json.dumps({k: v for k, v in record.items() if v is not None})

    def env(self, prefix="INTEGRATION_TASKS_GOOGLE") -> dict:
        return {f"{prefix}_API_BASE": self.base, f"{prefix}_TOKEN_URL": self.token_url}

    def writes(self) -> list:
        """The requests that are not reads: [(method, path, query, body)]."""
        return [(r["method"], r["path"], r["query"], r["body"]) for r in self.requests if r["method"] not in ("GET",) and r["path"] != "/token"]

    def calls(self) -> list:
        """Every request after the token POST, as (method, path, query, body)."""
        return [(r["method"], r["path"], r["query"], r["body"]) for r in self.requests if r["path"] != "/token"]
