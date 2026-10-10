#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The local service: the operations layer of runtime/ops.py served on this machine through an API, with a token and
an origin check, and the static files of the interface/ folder of the checkout. A shell like the terminal's: it parses
a request, calls one operation and returns what it returned. It holds no rule of its own about the work (which words a
decision takes, what a state leads to, what a hash must equal are the operations layer's and the store's), reads no
project file, and imports only the operations layer and the kit it shares with the MCP mode (shell_kit.py).

Usage:
  uv run --with keyring==25.7.0 python3 runtime/service.py --project <dir> [--project <dir>]... [--port 8765]
                             [--poll-every 60] [--dispatch-every 30 | --no-dispatch] [--token-file <path>]
  python3 runtime/service.py --help

Start it with the `uv run --with keyring==25.7.0` form: the secret store is read through that library, and a service
started without it finds no credential and starts no task (it says so at its start). A plain `python3 runtime/service.py`
serves the pages and the reads all the same.

  --project        a project folder (runtime/project_config.py); repeat for several. Each is checked at start with the
                   `config` operation: a folder that is not a configured project ends the start (exit 3), a configuration
                   you did not accept yet does not (the project is listed with "accepted": false, and every route of it
                   answers 412 until `accept-config` is typed in the terminal)
  --port           the port on 127.0.0.1 (default 8765; 0 lets the system choose). There is no option for another address
  --poll-every     seconds between two runs of `poll` for each project (mirrors, expired approvals, releases by a mode; no
                   model); default 60; 0 turns it off
  --dispatch-every seconds between two rounds of `dispatch` for each project (the handlers' ticks, the releases by a mode,
                   the next ready tasks: model calls); default 30; 0 turns it off. A project that has a job running is
                   skipped. The daily caps and the modes of the area agents are what limits it
  --no-dispatch    do not dispatch: nothing starts a task but `run-next` in the terminal; `status` then says `dispatch off`
                   for every ready task (this service's own fact: it does not know of a scheduler job that dispatches).
                   Give it when the project already has the scheduler's two jobs (contracts/runtime.md, "The
                   dispatcher's two jobs"), so that two dispatchers do not run. It cannot be given with --dispatch-every
  --token-file     where the token is written (default: service.token in the data folder of the first project)

It prints one JSON line, {"url", "token_file", "projects": [{"id", "name"}]}, and never the token. After it, on
standard error, it says what it found at its start for each project (operation `service-check`: the secret store, the
credential, docker, the eval image, whether it dispatches); when the secret store cannot be read, the first lines give
the `uv run --with keyring==25.7.0` command that starts the service. The token is
`secrets.token_hex(32)`, new at every start, in a file readable by its owner only, removed when the service stops. The page
asks the person to paste it once per browser session; it is never in a URL, a log line or a page.

The rules of a request, in this order, each a refusal unless the request satisfies it:
  1. The socket is bound to 127.0.0.1, listening with a backlog of 128.
  2. Host is 127.0.0.1:<port> or localhost:<port>, else 403 "host".
  3. Origin, when present, is http://127.0.0.1:<port> or http://localhost:<port>, else 403 "origin"; a POST without an
     Origin is refused the same way.
  4. A path under /api/ needs "Authorization: Bearer <token>" (hmac.compare_digest), else 401 "token". The static files
     need none and hold no data. One more path needs none, GET /token-file, outside /api/: see "Before the token".
  5. Only GET and POST (OPTIONS and every other method: 405 "method", and no Access-Control-* header is ever sent). A
     POST needs Content-Type application/json and a Content-Length of at most 1 MiB (the file route: 34 MiB, the base64
     of a 25 MiB file), else 415 "content_type", 411 "length" or 413 "too_large". Its body is one JSON object whose keys
     are the arguments of the operation's row in the table (runtime/operations.py), by name; an unknown key, a repeated
     key, a wrong type or a missing required one is 400 "usage". No query string is read except a route's own.
  6. An unknown path is 404 "not_found", a known path with another method 405 "method", an unknown project id 404.
  7. One route calls one operation and returns what it returned, unchanged, with 200. OpsError code 1 is 409
     "refused", 2 is 400 "usage", 3 is 412 "not_configured"; anything else is 500 "internal" (the traceback on stderr
     only). An error body is {"error": "<word>", "message": "<text>"}, and the 412 adds "next", the accept-config command.
  8. A route whose operation's row has job true (it calls a model or a platform) returns 202 and a job,
     {"job": <n>, "op", "project", "state": "running", "result": null, "error": null, "started_at", "ended_at": null};
     GET /api/v1/jobs/<n> returns it again, "state" "done" or "failed" at the end. A job whose operation calls a model is
     refused with 409 "busy" while another such job of the project (or the dispatch or queue loop) runs, except a row
     with `queues` (say, route): it starts anyway, and the operation itself queues its call while a run holds the
     project. Jobs live in memory; the records are in the store.
  9. Every response: Cache-Control no-store and X-Content-Type-Options nosniff; a page also a Content-Security-Policy of
     "default-src 'self'; img-src 'self' blob:; frame-ancestors 'none'" and Referrer-Policy no-referrer.
 10. A static path is served only when its real path is inside the interface folder, with a known extension, no
     dotfile and no listing. /favicon.ico (which browsers ask for by default) is answered with /favicon.svg.
 11. The log line is the method, the path (never the query), the status and the duration. Never a header, a body or the
     token.
 12. Text a model or a stranger wrote leaves as a JSON string; the page shows it as text, never as markup.

Before the token. The page cannot tell the person where the token file is until it holds the token, so the service answers
one unauthenticated read, GET /token-file (outside /api/, under rules 2, 3, 5 and 9: no CORS header, Cache-Control no-store,
GET only, no query): {"token_file": <the absolute path>, "commands": {"macos", "linux", "powershell"}}, the commands
being the operations layer's text (operations.token_commands) that put the file's content on the clipboard or print it in
a terminal. It never holds the token. A path with a control character has no safe command: both values are then null. A
service without a token file (a test's) answers 404. What the answer names, the account and the project's folder, is
readable by any local process on this origin; contracts/runtime.md says why that is accepted.

The reads of the interface are GET routes that carry no job: /projects/<id>/agents, /conversation?after=&conversation=,
/skills, /costs?since=, /connections, /artifacts, /commands (the rows `/help` prints), /artifact?path= (the path is at most 512 bytes; the operation
refuses anything outside docs/, a hidden file, a link and the configuration), /artifact/raw?path= (the one route that
answers bytes: an image of the project, by its magic number, at most 25 MiB, with its media type, the page's policy
and Content-Disposition inline; its row lists the page channel only) and /version (the change signal of the project's store: a
number that grows on every write). Each takes the query keys it names and no other. The service's own GET /versions answers
the /version of every project in one request, so that a page that shows several asks once a second whatever their number.

A line of the conversation, or a request to route, that the page sends while a run holds the project is queued by the operation
(runtime/ops_say.py), not refused; a third loop, `route_queued`, runs every QUEUE_EVERY seconds (not task dispatch, so
--no-dispatch leaves it on) and answers or routes the oldest entry when no run is in progress.

Not exposed, on purpose: accept-config (a configuration hash is accepted in the terminal only, so a page can never accept
the change that widens what an agent may do), run-next (the dispatcher decides what runs), deps, proof, the standing
approvals, contained-run, poll, route-queued, handler, pin and service-check (the service calls it itself, at its start). An effect is
approved from here with the hash the page showed, as the channel "page" (the service passes it itself; a request cannot
name a channel). The route of set-mode may narrow autonomy and never widen it: a move down the order of the modes
(stopped < supervised < milestones < autonomous < autonomous-with-policy) is accepted by code at once, a move up leaves
the configuration unaccepted (every route then answers 412 with the command that accepts it, in the terminal).

When it stops (SIGINT or SIGTERM) it ends the runs a job started (ops.stop_runs) and does not exit before that returns;
a second signal while it stops is ignored.

Exit codes: 0 stopped by a signal, 1 the port could not be bound, 2 usage error, 3 a project is not configured.
Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import base64
import binascii
import hmac
import http.server
import json
import os
import re
import secrets
import shutil
import signal
import sys
import threading
import time
import traceback
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import ops  # noqa: E402  (the same folder: the operations layer)
import shell_kit  # noqa: E402  (the same folder: what this shell shares with the MCP mode; with ops, the only modules of the runtime this one imports)
from shell_kit import EXPOSED_KINDS, Busy, Stopping, project_id, status_of  # noqa: E402,F401

HOST = "127.0.0.1"
DISPATCH_EVERY = 30.0                     # seconds between two rounds of `dispatch` unless --dispatch-every or --no-dispatch says otherwise
QUEUE_EVERY = 5.0                         # seconds between two looks of `route_queued` at the lines and requests that wait for the end of a run
MODEL_LOOPS = ("dispatch", "route_queued")  # the loops that call a model: they hold the project's model slot while they run
PREFIX = "/api/v1"
JSON_LIMIT = 1024 * 1024                  # bytes of a request body
FILE_LIMIT = 34 * 1024 * 1024             # the file route: the base64 of 25 MiB is about 33.4 MiB
UPLOAD_BYTES = 25 * 1024 * 1024           # what a hand-over takes (runtime/drop.py checks it again)
UPLOAD_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")  # a plain file name (runtime/drop.py NAME, checked again there)
UPLOADS = "uploads"                       # <data_dir>/uploads/<random>/<name>, removed after the hand-over
TOKEN_NAME = "service.token"
TOKEN_FILE_ROUTE = "/token-file"          # the one path outside /api/ that answers data; it needs no token and never holds one
PATH_LIMIT = 2048
QUERY_VALUE_LIMIT = 512                   # bytes of one query value on a route that names a project file (artifact?path=)
STATIC_LIMIT = 16 * 1024 * 1024
ONCE = ("host", "origin", "authorization", "content-type", "content-length", "transfer-encoding")
# Three directives. `default-src 'self'` and `frame-ancestors 'none'` are the rule since the first page. `img-src 'self'
# blob:` is there for one reason: the raw bytes of an image sit behind the bearer header, so the page fetches them itself
# and shows them from a `blob:` URL it built; `blob:` can only name bytes the page made, nothing from another origin.
# Never `data:`, and no other directive is widened.
CSP = "default-src 'self'; img-src 'self' blob:; frame-ancestors 'none'"
# What a static file is served as. An extension not here is not served (the rule fails closed).
TYPES = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8", ".json": "application/json", ".txt": "text/plain; charset=utf-8",
    ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
    ".ico": "image/x-icon", ".woff2": "font/woff2", ".woff": "font/woff", ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
}
PAGE_TYPES = ("text/html", "image/svg+xml")  # a document the browser can run: it carries the policy headers
WORDS = {
    "host": "the Host header must be 127.0.0.1:<port> or localhost:<port>",
    "origin": "the Origin must be this service's own (http://127.0.0.1:<port> or http://localhost:<port>); a POST needs one",
    "token": "an API path needs the header Authorization: Bearer <the token in the token file>",
    "content_type": "a POST needs Content-Type: application/json",
    "length": "a POST needs a Content-Length, and no Transfer-Encoding",
    "too_large": "the request body is larger than this route takes",
    "method": "this path does not take that method",
    "not_found": "no such route, project or file",
    "usage": "the request is malformed",
    "refused": "the operation refused",
    "not_configured": "the project is not configured",
    "busy": "a job that calls a model is running for this project",
    "stopping": "the service is stopping",
    "internal": shell_kit.INTERNAL,
}
CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class Usage(Exception):
    """A request that is well-formed HTTP but not one this route takes: 400."""


# --- the routes ------------------------------------------------------------------------------------------------------
# One route calls one operation of the table (runtime/operations.py) by its verb; "bind" says which argument of the row
# a part of the path is, "take" which arguments the body (or, for a GET, the query) may carry (every other argument of
# the row that is not bound or hidden), "hidden" the arguments only the service supplies. Whether a route returns a job
# is not written here: it is the row's `job` key. A route with "own" is the service's own.


def _route(method, pattern, op=None, *, bind=None, take=None, hidden=(), own=None, upload=False, query_max=None,
           raw=False):
    return {"method": method, "pattern": pattern, "op": op, "bind": dict(bind or {}), "take": take,
            "hidden": tuple(hidden), "own": own, "upload": upload, "limit": FILE_LIMIT if upload else JSON_LIMIT,
            "query_max": query_max, "raw": raw}


ROUTES = (
    _route("GET", "/projects", own="projects"),
    _route("GET", "/projects/{p}/status", "status", take=()),
    _route("GET", "/projects/{p}/pending", "pending", take=()),
    _route("GET", "/projects/{p}/pending/{id}", "pending", bind={"pending_id": "id"}, take=()),
    _route("POST", "/projects/{p}/pending/{id}/answer", "answer", bind={"pending_id": "id"}),
    _route("POST", "/projects/{p}/pending/{id}/release", "release", bind={"pending_id": "id"}),
    _route("POST", "/projects/{p}/pending/{id}/approve", "approve", bind={"pending_id": "id"}),
    _route("POST", "/projects/{p}/pending/{id}/reject", "reject", bind={"pending_id": "id"}),
    _route("GET", "/projects/{p}/flows", "flows", take=()),
    _route("POST", "/projects/{p}/requests", "request"),
    _route("POST", "/projects/{p}/requests/{id}/route", "route", bind={"request_id": "id"}),
    _route("POST", "/projects/{p}/requests/{id}/cancel", "cancel", bind={"request_id": "id"}),
    _route("GET", "/projects/{p}/tasks/{id}", "task", bind={"task_id": "id"}, take=()),
    _route("POST", "/projects/{p}/tasks/{id}/retry", "retry", bind={"task_id": "id"}),
    _route("POST", "/projects/{p}/tasks/{id}/go-ahead", "go-ahead", bind={"task_id": "id"}),
    _route("POST", "/projects/{p}/tasks/{id}/files", "hand-over", bind={"task_id": "id"}, hidden=("file",), upload=True),
    _route("POST", "/projects/{p}/runs/{id}/verdict", "verdict", bind={"run_id": "id"}),
    _route("POST", "/projects/{p}/agents/{name}/mode", "set-mode", bind={"agent": "name"}),
    _route("GET", "/projects/{p}/progress", "progress"),
    _route("GET", "/projects/{p}/agents", "agents", take=()),
    _route("GET", "/projects/{p}/conversation", "conversation", take=("conversation", "after")),
    _route("GET", "/projects/{p}/skills", "skills", take=()),
    _route("GET", "/projects/{p}/costs", "costs", take=("since",)),
    _route("GET", "/projects/{p}/connections", "connections", take=()),
    _route("GET", "/projects/{p}/artifacts", "artifacts", take=()),
    _route("GET", "/projects/{p}/artifact", "artifact", take=("path",), query_max=QUERY_VALUE_LIMIT),
    _route("GET", "/projects/{p}/artifact/raw", "artifact-raw", take=("path",), query_max=QUERY_VALUE_LIMIT, raw=True),
    _route("GET", "/projects/{p}/version", "version", take=()),
    _route("GET", "/projects/{p}/commands", "commands", take=()),
    _route("GET", "/versions", own="versions"),
    _route("POST", "/projects/{p}/conversation", "say"),
    _route("POST", "/projects/{p}/sync", "sync"),
    _route("POST", "/projects/{p}/dispatch", "dispatch", take=()),
    _route("GET", "/jobs/{id}", own="job"),
)
PARTS = {"p": "[0-9a-f]{12}", "id": "[0-9]{1,9}", "name": "[A-Za-z0-9][A-Za-z0-9._-]{0,63}"}
COMPILED = tuple((re.compile(PREFIX + re.sub(r"\{(\w+)\}", lambda m: f"(?P<{m.group(1)}>{PARTS[m.group(1)]})", r["pattern"])), r)
                 for r in ROUTES)


def match(method: str, path: str):
    """The route of ROUTES a request names and its parameters, (route, {"p": ..., "id": ...}), or None. The path is the
    request's path without its query; nothing is decoded."""
    for compiled, route in COMPILED:
        found = compiled.fullmatch(path)
        if found and route["method"] == method:
            return route, found.groupdict()
    return None


def known_path(path: str) -> bool:
    """True when some route has this path, with any method."""
    return any(compiled.fullmatch(path) for compiled, _ in COMPILED)


# --- the rules of a request ------------------------------------------------------------------------------------------


def new_token() -> str:
    """A new token for this start: secrets.token_hex(32)."""
    return secrets.token_hex(32)


def write_token(path: str, token: str) -> None:
    """Write the token file for its owner only: an older file is removed first, then the new one is created with
    O_CREAT and O_EXCL at mode 0600 (it follows no link). The folder is made at mode 0700 when it is missing."""
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, mode=0o700, exist_ok=True)
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, (token + "\n").encode("ascii"))
    finally:
        os.close(fd)


def headers_of(pairs):
    """The request's headers as a dict with lower-case names, or None when a header that must appear once (Host, Origin,
    Authorization, Content-Type, Content-Length, Transfer-Encoding) appears twice: two readers could take two values."""
    out = {}
    for name, value in pairs:
        key = str(name).lower()
        if key in out and key in ONCE:
            return None
        out[key] = str(value)
    return out


def _is_api(bare: str) -> bool:
    return bare == "/api" or bare.startswith("/api/")


def check_request(method: str, path: str, headers: dict, port: int, token: str):
    """None when the request may proceed, else (status, error word): the rules 2 to 5 in order. It reads nothing but its
    arguments (no file, no socket); `path` may carry its query, which is not looked at here."""
    h = {str(k).lower(): v for k, v in headers.items()}
    host = h.get("host")
    if not isinstance(host, str) or host.lower() not in (f"{HOST}:{port}", f"localhost:{port}"):
        return 403, "host"
    origin = h.get("origin")
    if origin is not None:
        if not isinstance(origin, str) or origin.lower() not in (f"http://{HOST}:{port}", f"http://localhost:{port}"):
            return 403, "origin"
    elif method == "POST":
        return 403, "origin"
    bare = path.partition("?")[0]
    if not bare.startswith("/") or len(path) > PATH_LIMIT:
        return 400, "usage"
    if _is_api(bare):
        scheme, _, given = str(h.get("authorization", "")).partition(" ")
        same = hmac.compare_digest(given.encode("utf-8"), str(token).encode("utf-8"))
        if scheme.lower() != "bearer" or not given or not same:
            return 401, "token"
    if "transfer-encoding" in h:
        return 400, "usage"
    if method not in ("GET", "POST"):
        return 405, "method"
    if method == "POST":
        if str(h.get("content-type", "")).partition(";")[0].strip().lower() != "application/json":
            return 415, "content_type"
        length = h.get("content-length")
        if length is None:
            return 411, "length"
        if not (length.isascii() and length.isdigit()):
            return 400, "usage"
        found = match("POST", bare)
        if int(length) > (found[0]["limit"] if found else JSON_LIMIT):
            return 413, "too_large"
    return None


def _headers(content_type: str) -> dict:
    out = {"Content-Type": content_type, "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
    if content_type.partition(";")[0] in PAGE_TYPES:
        out["Content-Security-Policy"] = CSP
        out["Referrer-Policy"] = "no-referrer"
    return out


def _json(status: int, value) -> tuple:
    return status, _headers("application/json; charset=utf-8"), json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")


def _error(status: int, word: str, message: str | None = None, next: str | None = None) -> tuple:
    body = {"error": word, "message": message or WORDS[word]}
    if next:  # the command that gets past the refusal (the 412: the accept-config line), so a page reads a field
        body["next"] = next
    return _json(status, body)


def _ops_error(error) -> tuple:
    status, word = status_of(error)
    return _error(status, word, str(error) if word != "internal" else None,
                  getattr(error, "next", None) if word != "internal" else None)


def _no_duplicates(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"the key {key!r} appears twice")
        out[key] = value
    return out


def _body(raw: bytes) -> dict:
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates)
    except (UnicodeDecodeError, ValueError) as e:
        raise Usage(f"the body is not one JSON object: {e}") from None
    if not isinstance(data, dict):
        raise Usage("the body must be one JSON object")
    return data


def _query(route: dict, query: str) -> dict:
    """The query of a GET route that takes some: {name: text}. Any other query is refused, so a token (or anything
    else) in a URL is never read."""
    if not query:
        return {}
    if route["method"] != "GET" or route["take"] == ():
        raise Usage("this route takes no query")
    try:
        pairs = urllib.parse.parse_qsl(query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        raise Usage("the query is malformed") from None
    out = {}
    for key, value in pairs:
        if key in out:
            raise Usage(f"the query key {key!r} appears twice")
        out[key] = value
    return out


def _coerce(arg: dict, value, from_query: bool):
    kind, name = arg["kind"], arg["name"]
    if kind not in EXPOSED_KINDS:
        raise Usage(f"{name} cannot be given through the service")
    if kind == "int":
        if from_query:
            if isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 12:
                return int(value)
        elif type(value) is int and value >= 0:
            return value
        raise Usage(f"{name} must be a whole number of 0 or more")
    if from_query and kind != "str":
        raise Usage(f"{name} cannot be given in a query")
    if kind == "flag":
        if type(value) is not bool:
            raise Usage(f"{name} must be true or false")
        return value
    if kind == "list":
        if type(value) is not list or not all(isinstance(v, str) for v in value):
            raise Usage(f"{name} must be a list of text")
        return value
    if not isinstance(value, str):
        raise Usage(f"{name} must be text")
    if kind == "choice" and value not in arg["choices"]:
        raise Usage(f"{name} must be one of {', '.join(arg['choices'])}")
    return value


def arguments(row: dict, route: dict, params: dict, given: dict, from_query: bool) -> dict:
    """The keyword arguments of the operation, built from its row: the bound parts of the path, then the body's (or the
    query's) keys, each by the row argument's name and kind. A key the route does not take, a missing required argument
    and a value of the wrong type are a Usage. The channel is never an argument: the service passes its own."""
    args = {a["name"]: a for a in row["args"]}
    bound, hidden = route["bind"], set(route["hidden"])
    allowed = [n for n in (args if route["take"] is None else route["take"]) if n not in bound and n not in hidden]
    unknown = sorted(set(given) - set(allowed))
    if unknown:
        raise Usage("this route takes " + (", ".join(allowed) or "no key") + f"; not {', '.join(map(repr, unknown))}")
    out = {name: _coerce(args[name], params[part], True) for name, part in bound.items()}
    for name in allowed:
        if given.get(name) is not None:
            out[name] = _coerce(args[name], given[name], from_query)
        elif args[name].get("required"):
            raise Usage(f"{name} is required")
    return out


# --- the service object, the jobs and the loops ----------------------------------------------------------------------


class Service(shell_kit.Jobs):
    """What a request is served from: the operations object (the module ops, or a stand-in), the projects, the token,
    the port, the folder of the static files, the jobs (shell_kit.Jobs). Holds the token without ever showing it."""

    def __init__(self, ops_module, projects, token: str, port: int, interface_dir=None, log=None, token_file=None):
        if not isinstance(token, str) or len(token) < 32:
            raise ValueError("the token is at least 32 characters")
        super().__init__(ops_module, projects, log)
        self.token = token
        self.port = int(port)
        self.interface_dir = interface_dir
        self.token_file = token_file   # the absolute path of the token file, or None (then GET /token-file is not a route)
        self.address = None      # (host, port) the socket is bound to, set by serve()

    def __repr__(self) -> str:
        return f"<Service port={self.port} projects={len(self.projects)}>"


def dispatch_loop(service: Service, every: float, stop, op: str = "dispatch") -> None:
    """Call the operation `op` (`dispatch`, `route_queued`, or `poll` for the short job) for each project, every `every`
    seconds until `stop` is set. A project that has a job running is skipped; for `dispatch` and `route_queued` the
    project's model slot is held during the call, so a job that calls a model waits (a job that queues does not).
    An error is logged (once, while it repeats) and the loop goes on."""
    last = {}
    while not stop.wait(every):
        for project in service.projects:
            if service.stopping.is_set():
                return
            if service.running(project["id"]):
                continue
            if op in MODEL_LOOPS:
                with service.lock:
                    if project["id"] in service.exclusive:
                        continue
                    service.exclusive[project["id"]] = f"the {op} loop"
            try:
                getattr(service.ops, op)(project["path"])
                last.pop((op, project["id"]), None)
            except Exception as e:  # the loop survives whatever one round raises
                text = f"{op} of {project['id']}: {type(e).__name__}: {CONTROL.sub(' ', str(e))[:300]}"
                if last.get((op, project["id"])) != text:
                    service.log(text)
                last[(op, project["id"])] = text
            finally:
                if op in MODEL_LOOPS:
                    with service.lock:
                        service.exclusive.pop(project["id"], None)


# --- one request -----------------------------------------------------------------------------------------------------


def _job_get(service: Service, params: dict) -> tuple:
    shown = service.job_shown(int(params["id"]))
    return _json(200, shown) if shown else _error(404, "not_found", "no such job")


def _versions(service: Service) -> dict:
    """{"versions": {project id: {"version", "changed_at"}}}: the `version` operation of every project, so that a page that
    shows several asks once a second whatever their number. A project the operation cannot read is {"error": the word of the
    refusal, such as not_configured} (the sentence is in the project's own routes) and hides none of the others."""
    out = {}
    for project in service.projects:
        try:
            out[project["id"]] = service.ops.version(project["path"])
        except service.ops.OpsError as e:
            out[project["id"]] = {"error": status_of(e)[1]}
    return {"versions": out}


def _upload(service: Service, project: dict, row: dict, route: dict, params: dict, given: dict) -> tuple:
    """The file route: the body is {"name", "content_base64"}. The service writes the bytes to
    <data_dir>/uploads/<random>/<name> (a plain file name, mode 0600), hands that file to the operation and removes the
    folder, whatever the operation answers. A request never supplies the path."""
    if set(given) != {"name", "content_base64"} or not all(isinstance(v, str) for v in given.values()):
        raise Usage("this route takes name and content_base64, both text")
    if not UPLOAD_NAME.fullmatch(given["name"]):
        raise Usage("name is a plain file name: letters, digits, '.', '_' and '-', at most 100 characters, no separator")
    try:
        data = base64.b64decode(given["content_base64"], validate=True)
    except (binascii.Error, ValueError):
        raise Usage("content_base64 is not base64") from None
    if len(data) > UPLOAD_BYTES:
        return _error(413, "too_large", f"a file handed to a task is at most {UPLOAD_BYTES // (1024 * 1024)} MiB")
    arguments_ = arguments(row, route, params, {}, False)
    root = os.path.join(service.ops.config(project["path"])["data_dir"], UPLOADS)
    os.makedirs(root, mode=0o700, exist_ok=True)
    folder = os.path.join(root, secrets.token_hex(8))
    os.mkdir(folder, 0o700)
    try:
        target = os.path.join(folder, given["name"])
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        result = getattr(service.ops, row["call"])(project["path"], file=target, **arguments_)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return _json(200, result)


def _operation(service: Service, route: dict, params: dict, query: str, body: bytes) -> tuple:
    project = service.by_id.get(params.get("p"))
    if project is None:
        return _error(404, "not_found", "no such project")
    row = service.ops.operations.by_name(route["op"])
    if "page" not in row["channels"]:  # a route to an operation the page may not call is no route
        return _error(404, "not_found")
    from_query = route["method"] == "GET"
    if not from_query and query:
        raise Usage("this route takes no query")
    given = _query(route, query) if from_query else _body(body)
    if route["query_max"] is not None:
        for key, value in given.items():
            if len(str(value).encode("utf-8")) > route["query_max"]:
                raise Usage(f"the query value {key!r} is longer than {route['query_max']} bytes")
    if route["upload"]:
        return _upload(service, project, row, route, params, given)
    args = arguments(row, route, params, given, from_query)
    if row.get("channel_arg"):
        args["channel"] = "page"
    call = lambda: getattr(service.ops, row["call"])(project["path"], **args)  # noqa: E731
    if route["raw"]:  # the bytes of a file, answered with the media type the operation names, never as a page
        found = call()
        return 200, {**_headers(found["media_type"]), "Content-Security-Policy": CSP, "Referrer-Policy": "no-referrer",
                     "Content-Disposition": "inline"}, found["data"]
    if row.get("job"):
        try:
            return _json(202, service.start_job(project["id"], row["name"], call, queues=bool(row.get("queues")))[2])
        except Busy as e:
            return _error(409, "busy", str(e))
        except Stopping:
            return _error(503, "stopping")
    return _json(200, call())


def _token_file(service: Service, method: str, query: str) -> tuple:
    """GET /token-file: the token file's absolute path and the commands that read it, never the token. Both are null when
    the path has a control character (no safe command exists). The commands are the operations layer's text."""
    if method != "GET":
        return _error(405, "method")
    if service.token_file is None:
        return _error(404, "not_found")
    if query:
        return _error(400, "usage", "this route takes no query")
    commands = service.ops.operations.token_commands(service.token_file)
    return _json(200, {"token_file": service.token_file if commands else None, "commands": commands})


def _static(service: Service, method: str, bare: str) -> tuple:
    if method != "GET":
        return _error(405, "method")
    rel = urllib.parse.unquote(bare)
    if rel == "/":
        rel = "/index.html"
    elif rel == "/favicon.ico":                  # browsers ask for it by default; the page's icon is the svg
        rel = "/favicon.svg"
    parts = rel.split("/")[1:]
    if "\x00" in rel or "\\" in rel or not service.interface_dir \
            or any(p in ("", ".", "..") or p.startswith(".") for p in parts):
        return _error(404, "not_found")
    root = os.path.realpath(service.interface_dir)
    target = os.path.realpath(os.path.join(root, *parts))
    content_type = TYPES.get(os.path.splitext(target)[1].lower())
    if not target.startswith(root + os.sep) or content_type is None or not os.path.isfile(target):
        return _error(404, "not_found")
    try:
        if os.path.getsize(target) > STATIC_LIMIT:
            return _error(404, "not_found")
        with open(target, "rb") as f:
            data = f.read()
    except OSError:
        return _error(404, "not_found")
    return 200, _headers(content_type), data


def handle(service: Service, method: str, path: str, headers: dict, body: bytes) -> tuple:
    """The whole of one request without a socket: (status, headers, body bytes). The rules 2 to 5 (check_request), then
    the route, the project, the arguments, the one operation. A request that passes check_request and names no route is
    404 or 405; an operation's refusal is its documented status."""
    refused = check_request(method, path, headers, service.port, service.token)
    if refused:
        return _error(*refused)
    bare, _, query = path.partition("?")
    if bare == TOKEN_FILE_ROUTE:
        return _token_file(service, method, query)
    if not _is_api(bare):
        return _static(service, method, bare)
    found = match(method, bare)
    if found is None:
        return _error(405, "method") if known_path(bare) else _error(404, "not_found")
    route, params = found
    if len(body) > route["limit"]:
        return _error(413, "too_large")
    try:
        if route["own"] == "projects":
            if query:
                raise Usage("this route takes no query")
            return _json(200, service.projects_list())
        if route["own"] == "versions":
            if query:
                raise Usage("this route takes no query")
            return _json(200, _versions(service))
        if route["own"] == "job":
            if query:
                raise Usage("this route takes no query")
            return _job_get(service, params)
        return _operation(service, route, params, query, body)
    except Usage as e:
        return _error(400, "usage", str(e))
    except service.ops.OpsError as e:
        return _ops_error(e)
    except Exception:  # whatever else: the traceback stays on stderr, the body names nothing
        service.log("internal error:\n" + traceback.format_exc())
        return _error(500, "internal")


# --- the server ------------------------------------------------------------------------------------------------------

REASONS = {400: "usage", 414: "usage", 431: "usage", 501: "method", 505: "usage"}


def request_line(method: str, path: str, status: int, seconds: float) -> str:
    """The one log line of a request (rule 11): the method, the path without its query, the status and the duration.
    Nothing else of the request is in it: no header, no body, no query, so no token."""
    shown = CONTROL.sub(" ", str(path).partition("?")[0])[:200]
    return f"{CONTROL.sub(' ', str(method))[:16]} {shown} {int(status)} {int(seconds * 1000)}ms"


def make_handler(service: Service):
    """The request handler class of one service."""

    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "workbench-service"
        sys_version = ""
        timeout = 30

        def version_string(self):
            return self.server_version

        def log_message(self, format, *args):  # noqa: A002  (the service logs its own line, never the stdlib's)
            pass

        def log_error(self, format, *args):  # noqa: A002
            service.log("protocol error: a request the server could not read")

        def send_error(self, code, message=None, explain=None):
            status, word = (405, "method") if code == 501 else (code, REASONS.get(code, "usage"))
            self._send(*_error(status, word))

        def _send(self, status, headers, payload):
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)
            self.close_connection = True

        def _serve(self):
            started = time.monotonic()
            method, path = self.command, self.path
            headers = headers_of(self.headers.items())
            if headers is None:
                answer = _error(400, "usage", "a header that must appear once was repeated")
            else:
                refused = check_request(method, path, headers, service.port, service.token)
                if refused:
                    answer = _error(*refused)
                else:
                    length = int(headers["content-length"]) if method == "POST" else 0
                    try:
                        raw = self.rfile.read(length) if length else b""
                    except OSError:  # the client stalled or went away
                        raw = b""
                    if len(raw) != length:
                        answer = _error(400, "usage", "the body ended before its Content-Length")
                    else:
                        answer = handle(service, method, path, headers, raw)
            try:
                self._send(*answer)
            except (BrokenPipeError, ConnectionResetError):
                pass
            service.log(request_line(method, path, answer[0], time.monotonic() - started))

        do_GET = do_POST = do_HEAD = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _serve

    return Handler


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    # Every response closes its connection, so a page of dozens of modules and icons is dozens of new connections at
    # once. The class default (5) overflows the accept queue and some systems answer the overflow with a reset
    # (R4-C2). 128 is the usual system ceiling; the listening address is still 127.0.0.1 only.
    request_queue_size = 128


LABELS = (("secret_store", "secret store"), ("credential", "credential"), ("docker", "docker"), ("image", "image"),
          ("dispatch", "dispatch"))


def check_projects(ops_module, projects, dispatch_every, log) -> None:
    """What each project's check found at the start (the operation `service-check`, which also remembers it for
    `connections` and `status`), one line each on the log, which is standard error. When the secret store cannot be
    read, the first lines say how to start the service (`uv run --with keyring==...`); a project whose check fails is
    logged and the start goes on."""
    for project in projects:
        try:
            report = ops_module.service_check(project["path"], dispatch_every=dispatch_every or 0)
        except Exception as e:  # a check that fails never stops the service
            log(f"service check of {project['name']}: {type(e).__name__}: {CONTROL.sub(' ', str(e))[:300]}")
            continue
        if not isinstance(report, dict):
            continue
        shown = lambda key: CONTROL.sub(" ", str(report.get(key)))[:400]  # noqa: E731
        if report.get("secret_store") not in (None, "ok"):
            log(f"service check of {project['name']}: the secret store cannot be read from this interpreter, so no run "
                "starts from this service; start it with:")
            log("  " + shown("start"))
        log(f"service check of {project['name']}:")
        for key, label in LABELS:
            if key in report:
                log(f"  {label:<13}{shown(key)}")
        for problem in report.get("problems") or []:
            log("  problem      " + CONTROL.sub(" ", str(problem))[:300])


def serve(projects, port=8765, poll_every=60.0, dispatch_every=DISPATCH_EVERY, token_file=None, interface_dir=None,
          ops_module=None, stop=None, ready=None, log=None, out=None, server_class=None) -> int:
    """Check every project with the `config` operation, bind 127.0.0.1:<port>, write the token file, print the one
    JSON line, and serve until a signal (or `stop`, an Event, is set); then end the runs the jobs started
    (ops.stop_runs, which is waited for) and remove the token file. The `poll` loop runs every `poll_every` seconds
    (0: not at all), the `dispatch` loop every `dispatch_every` seconds (30 unless told; None or 0: not at all). After
    the JSON line it logs what each project's check found (check_projects). Returns the exit code.
    `ready(service)` is called once the socket listens, `server_class` replaces the HTTP server (both are the tests')."""
    ops_module = ops_module or ops
    log = log or shell_kit.default_log
    out = out or sys.stdout
    try:
        found = shell_kit.projects_of(projects, ops_module)
        if not found:
            raise ops_module.OpsError("no project was given", 2)
    except ops_module.OpsError as e:
        print(f"error: {e}", file=sys.stderr)
        return e.code
    token = new_token()
    target = token_file or os.path.join(found[0]["data_dir"], TOKEN_NAME)
    interface_dir = interface_dir if interface_dir is not None else os.path.join(ROOT, "interface")
    try:
        server = (server_class or Server)((HOST, int(port)), http.server.BaseHTTPRequestHandler)
    except OSError as e:
        print(f"error: cannot listen on {HOST}:{port}: {e.strerror}", file=sys.stderr)
        return 1
    service = Service(ops_module, [{k: p[k] for k in ("id", "name", "path")} for p in found], token,
                      server.server_address[1], interface_dir, log, token_file=os.path.abspath(target))
    service.address = tuple(server.server_address[:2])
    server.RequestHandlerClass = make_handler(service)
    try:
        write_token(target, token)
    except OSError as e:
        server.server_close()
        print(f"error: cannot write the token file {target}: {e.strerror}", file=sys.stderr)
        return 1
    stop = stop or threading.Event()
    previous = {}
    if threading.current_thread() is threading.main_thread():
        def on_signal(signum, _frame):
            if stop.is_set():
                log("stopping: waiting for the runs to end; the signal is ignored")
            stop.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, on_signal)
    serving = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
    threads = [serving]
    for every, op in ((poll_every, "poll"), (dispatch_every, "dispatch"),
                      (QUEUE_EVERY if hasattr(ops_module, "route_queued") else 0, "route_queued")):
        if every:
            threads.append(threading.Thread(target=dispatch_loop, args=(service, float(every), stop, op), daemon=True))
    try:
        for thread in threads:
            thread.start()
        print(json.dumps({"url": f"http://{HOST}:{service.port}/", "token_file": target,
                          "projects": [{"id": p["id"], "name": p["name"]} for p in found]}), file=out, flush=True)
        check_projects(ops_module, found, dispatch_every, log)
        if ready:
            ready(service)
        while not stop.wait(0.5):
            pass
    finally:
        stop.set()
        service.stopping.set()
        if serving.ident is not None:  # shutdown() waits for serve_forever, which must have been started
            server.shutdown()
        server.server_close()
        left = service.end_runs(threads)
        if left:
            log(f"stopped with {left} job thread(s) still ending")
        try:
            os.unlink(target)
        except OSError:
            pass
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return 0


# --- the command -----------------------------------------------------------------------------------------------------


class Refused(Exception):
    pass


def _number(text: str, flag: str, low: float, high: float) -> float:
    try:
        value = float(text)
    except ValueError:
        raise Refused(f"{flag} takes a number") from None
    if not low <= value <= high:
        raise Refused(f"{flag} is between {low:g} and {high:g}")
    return value


def parse(argv) -> dict:
    """The command line as {"projects", "port", "poll_every", "dispatch_every", "token_file"}. dispatch_every is
    DISPATCH_EVERY unless --dispatch-every gives another or --no-dispatch makes it None. Refused (Refused) for an
    unknown flag, a flag without its value, a number out of range, no project, or --no-dispatch with --dispatch-every.
    There is no flag for another address."""
    out = {"projects": [], "port": 8765, "poll_every": 60.0, "dispatch_every": DISPATCH_EVERY, "token_file": None}
    flags = {"--project", "--port", "--poll-every", "--dispatch-every", "--token-file"}
    args, said_every, no_dispatch = list(argv), False, False
    while args:
        flag = args.pop(0)
        if flag == "--no-dispatch":
            no_dispatch = True
            continue
        if flag not in flags:
            raise Refused(f"unknown argument {flag!r}")
        if not args:
            raise Refused(f"{flag} needs a value")
        value = args.pop(0)
        if flag == "--project":
            out["projects"].append(value)
        elif flag == "--port":
            out["port"] = int(_number(value, flag, 0, 65535))
        elif flag in ("--poll-every", "--dispatch-every"):
            seconds = _number(value, flag, 0, 86400)
            if 0 < seconds < 1:
                raise Refused(f"{flag} is 0 (off) or at least 1 second")
            out[flag[2:].replace("-", "_")] = seconds
            said_every = said_every or flag == "--dispatch-every"
        else:
            out["token_file"] = value
    if not out["projects"]:
        raise Refused("give at least one --project <dir>")
    if no_dispatch:
        if said_every:
            raise Refused("--no-dispatch and --dispatch-every exclude each other")
        out["dispatch_every"] = None
    return out


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or "--help" in argv or "-h" in argv:
        print(__doc__.strip(), file=sys.stdout if argv else sys.stderr)
        return 0 if argv else 2
    try:
        given = parse(argv)
    except Refused as e:
        print(f"error: {e}. See --help.", file=sys.stderr)
        return 2
    return serve(given["projects"], given["port"], given["poll_every"], given["dispatch_every"] or None,
                 given["token_file"])


if __name__ == "__main__":
    sys.exit(main())
