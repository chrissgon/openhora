#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The local service: the operations layer of runtime/ops.py served on this machine through an API, with a token and
an origin check, and the static files of the interface/ folder of the checkout. A shell like the terminal's: it parses
a request, calls one operation and returns what it returned. It holds no rule of its own about the work (which words a
decision takes, what a state leads to, what a hash must equal are the operations layer's and the store's), reads no
project file, and imports only the operations layer, the kit it shares with the MCP mode (shell_kit.py) and, for the
one option that starts a child process, service_bridge.py (standard library only).

The page's channel policy (contracts/runtime.md, "The channel policy"): before a route's operation runs, after its query is
read and before the bytes of an upload are written and before a job exists, the service asks `config` (a configuration
that is not accepted is left to the operation, which answers 412) and calls `operations.refusal` with the channel `page`,
the project's accepted `channels`, and, for approve, the decision's kind (read with `pending`) and whether it carries task
keys; a refusal is 409 with the sentence. A read returns before that. `GET /projects` adds per project `permissions` and the
`commands` answer leaves out what the policy refuses. The policy governs a person's requests, not the dispatch loop the
service runs on its own timer.

Usage:
  uv run --with keyring==25.7.0 python3 runtime/service.py --project <dir> [--project <dir>]... [--port 8765]
                             [--poll-every 60] [--dispatch-every 30 | --no-dispatch] [--token-file <path>] [--lan [<ip>]]
                             [--messaging <platform>[,<platform>]... [--notice-every 60]]
  python3 runtime/service.py --help

Start it with the `uv run --with keyring==25.7.0` form: the secret store is read through that library, and a service
started without it finds no credential and starts no task (it says so at its start). A plain `python3 runtime/service.py`
serves the pages and the reads all the same.

  --project        a project folder (runtime/project_config.py); repeat for several. Each is checked at start with the
                   `config` operation: a folder that is not a configured project ends the start (exit 3), a configuration
                   you did not accept yet does not (the project is listed with "accepted": false, and every route of it
                   answers 412 until `accept-config` is typed in the terminal)
  --port           the port on 127.0.0.1 (default 8765; 0 lets the system choose). The service listens on 127.0.0.1 only,
                   unless --lan is given: there is no option for any other address
  --poll-every     seconds between two runs of `poll` for each project (mirrors, expired approvals, releases by a mode; no
                   model); default 60; 0 turns it off
  --dispatch-every seconds between two rounds of `dispatch` for each project (the handlers' ticks, the releases by a mode,
                   the ready tasks the rules allow, each started as a process of its own: model calls); default 30; 0 turns
                   it off. A round starts the runs and returns; the loops reap the children on every tick, and the next round
                   reports what ended. A job that calls the router does not stop it (the router runs beside task runs); a
                   round of the project that is still running (a waiting round of the terminal) is skipped without a word.
                   The daily caps, the modes and the slots of the area agents are what limits it
  --no-dispatch    do not dispatch: nothing starts a task but `run-next` in the terminal; `status` then says `dispatch off`
                   for every ready task (this service's own fact: it does not know of a scheduler job that dispatches).
                   Give it when the project already has the scheduler's two jobs (contracts/runtime.md, "The
                   dispatcher's two jobs"), so that two dispatchers do not run. It cannot be given with --dispatch-every
  --token-file     where the token is written (default: service.token in the data folder of the first project)
  --lan [<ip>]     off by default; a risk the person accepts, to open the page on a phone on the same wifi. The service also
                   listens on one private LAN address (the IPv4 address of the default route, found without sending a packet,
                   or the <ip> given: only 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16 and 169.254.0.0/16 are taken; a public
                   address, 0.0.0.0, the loopback and an address ending in .0 or .255 are refused, exit 2), on the same port, as plain HTTP: the page and the
                   token cross the network unencrypted. At its start it prints a warning on standard error, then the address
                   to open (never with the token in it). Anyone on the network who reads the token can approve effects and
                   read the documents of the projects: use it to test on a phone on a network you trust, and stop the
                   service when you are done. Host and Origin are then the loopback's on the loopback socket and
                   that address's on the LAN socket, and GET /token-file answers the path to the loopback socket only (rules
                   2, 3 and "Before the token")
  --messaging <platform>[,<platform>]...
                   off by default: after the sockets are bound and the line below is printed, start the messaging bridge
                   (runtime/messaging.py, for the platform, with every --project given here) as a child process, so that
                   one start brings up the page and the bridge. Several platforms start several bridges from one start:
                   give a comma list (--messaging telegram,whatsapp-twilio) or repeat the option; at most 6, no name twice
                   (a duplicate or a malformed name is exit 2), one child per platform in the order given, each as described
                   here; every app gets its own card, a decision resolved in one app is refused in the others, conversations
                   are per app, and the bridges share the router's lock (writing in two apps at once may answer "busy" in
                   one). Two official WhatsApp providers both listen on port 8787 by default: give them different ports in
                   `setup`; a bridge whose provider cannot bind its port exits with a reason, reported for that child only.
                   Each child's exit is reported with its platform and the others keep running; "messaging" in GET /projects
                   is then a list of the objects below, and the start line's "messaging" a list of platforms.
                   The child has its own session, its standard input is a pipe this service holds open (the bridge stops
                   when it closes: --stop-on-stdin-eof), its standard output goes to /dev/null and its standard error is
                   this service's; its environment is the one this service had at the very start of main (a key written
                   later into this process never reaches it). When it exits, at any time, one line on standard error gives
                   the code and its meaning (4 another bridge serves the platform, 3 the messenger is not configured or
                   another program reads the bot, 2 usage) and the service goes on serving the page; nothing restarts it.
                   GET /api/v1/projects then has a top-level "messaging":
                   {"platform", "state": "running" | "stopped", "exit_code"} (null without the option). When the service
                   stops it closes the child's input, sends SIGTERM to the child's process group, and after it ended its
                   own runs waits up to 150 s (one bound for all the children together) before SIGKILL to the group of
                   each one left. The service and the bridge each have their own model slot:
                   only the project's file locks keep two router runs apart (contracts/runtime.md, "The messaging bridge")
  --notice-every   seconds between two looks of the bridge at what waits for the person (passed to the bridge only; default
                   60, at least 5); it needs --messaging

It prints one JSON line, {"url", "token_file", "projects": [{"id", "name"}]} ("lan_url" too, after "url", with --lan;
"messaging": "<platform>" last, with --messaging; a list of platforms when several), and never the token. After it, on
standard error, it says what it found at its start for each project (operation `service-check`: the secret store, the
credential, docker, the eval image, whether it dispatches); when the secret store cannot be read, the first lines give
the `uv run --with keyring==25.7.0` command that starts the service. The token is
`secrets.token_hex(32)`, new at every start, in a file readable by its owner only, removed when the service stops. The page
asks the person to paste it once per browser session; it is never in a URL, a log line or a page.

The rules of a request, in this order, each a refusal unless the request satisfies it:
  1. The socket is bound to 127.0.0.1, listening with a backlog of 128. With --lan a second socket is bound to the one
     private LAN address, on the same port; never 0.0.0.0.
  2. Host is 127.0.0.1:<port> or localhost:<port>, else 403 "host". With --lan the socket a request came in on decides: on
     the LAN socket only <lan-ip>:<port> is valid, on the loopback socket only the two above (a name that resolves to the
     LAN address, a DNS-rebinding name, another address or port is refused on both).
  3. Origin, when present, is http://<a valid Host>, else 403 "origin"; a POST without an Origin is refused the same way.
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
a terminal. It never holds the token. With --lan it is answered to the loopback socket only (a request that arrived on the
LAN socket gets the 404 of a service with no token file, so that a device on the network cannot learn the machine's paths
without the token). A path with a control character has no safe command: both values are then null. A
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
--no-dispatch leaves it on) and answers or routes the oldest entry when the router is free (a run of a task never holds it).

Not exposed, on purpose: accept-config (a configuration hash is accepted in the terminal only, so a page can never accept
the change that widens what an agent may do), run-next (the dispatcher decides what runs), deps, proof, the standing
approvals, contained-run, poll, route-queued, handler, pin and service-check (the service calls it itself, at its start). An effect is
approved from here with the hash the page showed, as the channel "page" (the service passes it itself; a request cannot
name a channel). The route of set-mode may narrow autonomy and never widen it: a move down the order of the modes
(stopped < supervised < milestones < autonomous < autonomous-with-policy) is accepted by code at once, a move up leaves
the configuration unaccepted (every route then answers 412 with the command that accepts it, in the terminal). The route takes
the mode and nothing else: `accept` is the terminal's (set-mode --accept), so a body that carries it is a 400, and the operation
refuses it from any channel but the terminal besides. The route of set-model is the same: a model id, auto or default; fixing a
model on an agent in an autonomous mode is the person's consent and carries `consent`, which only the terminal gives there (it is
distinct from `accept`, and both are refused in a body). The page gives that consent on its own route, give-consent: the model,
the mode, the hash of the configuration it read and the sha256 of the warning it showed; the operation checks all four and
records that consent only (messaging and the MCP mode have no such operation).

When it stops (SIGINT or SIGTERM) it ends the runs a job started (ops.stop_runs) and does not exit before that returns;
a second signal while it stops is ignored.

Exit codes: 0 stopped by a signal, 1 the port (or the LAN address) could not be bound, 2 usage error (a refused --lan address
included), 3 a project is not configured.
Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import base64
import binascii
import hmac
import http.server
import ipaddress
import json
import os
import re
import secrets
import shutil
import signal
import socket
import sys
import threading
import time
import traceback
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import ops  # noqa: E402  (the same folder: the operations layer)
import shell_kit  # noqa: E402  (the same folder: what this shell shares with the MCP mode)
import service_bridge  # noqa: E402  (the same folder: the child process of --messaging; standard library only)
from shell_kit import EXPOSED_KINDS, Busy, Stopping, project_id, status_of  # noqa: E402,F401

HOST = "127.0.0.1"
# --lan takes an address in one of these networks and no other (RFC 1918 and link-local): never a public one.
LAN_NETWORKS = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16"))
LAN_PROBE = ("10.254.254.254", 9)         # detection connects a UDP socket here; connect on UDP sends nothing (it only picks the route)
IPV4 = re.compile(r"(?:(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])\.){3}(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])")
# What --lan prints on standard error before the address (the one text the contract and the readme quote).
LAN_WARNING = (
    "WARNING: --lan opens this service to your local network.",
    "  The page and the token cross the network as plain HTTP, unencrypted.",
    "  Anyone on the network who reads the token can approve effects and read the documents of the projects.",
    "  Use it only to test on a phone on a network you trust, and stop the service (Ctrl-C) when you are done.",
)
DISPATCH_EVERY = 30.0                     # seconds between two rounds of `dispatch` unless --dispatch-every or --no-dispatch says otherwise
QUEUE_EVERY = 5.0                         # seconds between two looks of `route_queued` at the lines and requests that wait for the end of a run
MODEL_LOOPS = ("route_queued",)  # the loops that hold the project's model slot while they run (`dispatch` starts processes and holds none)
PLATFORM = re.compile(r"[a-z0-9][a-z0-9-]*")  # --messaging names a lock and a ledger file: a lowercase word
MAX_MESSAGING = 6  # platforms one service starts bridges for
MIN_NOTICE_EVERY = 5
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
DEMO_DIR = "demo"  # interface/demo/: the demo mode of the page, never served by this service
PAGE_TYPES = ("text/html", "image/svg+xml")  # a document the browser can run: it carries the policy headers
WORDS = {
    "host": "the Host header must be 127.0.0.1:<port> or localhost:<port> (or the LAN address, when the service was started with --lan)",
    "origin": "the Origin must be this service's own (http://127.0.0.1:<port> or http://localhost:<port>, or the LAN address with --lan); a POST needs one",
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
FAULT_MAX = 300         # characters of an error that the log keeps
WHOLE_MAX = 6000        # characters of the refusal "the configuration is not accepted" that the log keeps: a path, two hashes, the widening lines and the command, never a line or a secret


def fault_text(error) -> str:
    """An error as the log shows it: one line, cut at FAULT_MAX characters, except the refusal of a configuration that is not accepted (ops_core.NotAccepted, code 3), which is kept
    whole up to WHOLE_MAX: cut at 300 it lost the end of the command (S12)."""
    text = CONTROL.sub(" ", str(error))
    return text[:WHOLE_MAX] if type(error).__name__ == "NotAccepted" and getattr(error, "code", None) == 3 else text[:FAULT_MAX]


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
    _route("GET", "/projects/{p}/flows/{name}/check", "flow-check", bind={"flow": "name"}, take=()),
    _route("POST", "/projects/{p}/flows", "flow-save"),
    _route("GET", "/projects/{p}/routines", "routines", take=("routine_id",)),
    _route("POST", "/projects/{p}/routines", "routine-create"),
    _route("POST", "/projects/{p}/routines/{id}/change", "routine-change", bind={"routine_id": "id"}),
    _route("POST", "/projects/{p}/routines/{id}/approve", "routine-approve", bind={"routine_id": "id"}),
    _route("POST", "/projects/{p}/routines/{id}/pause", "routine-pause", bind={"routine_id": "id"}),
    _route("POST", "/projects/{p}/routines/{id}/resume", "routine-resume", bind={"routine_id": "id"}),
    _route("POST", "/projects/{p}/routines/{id}/cancel", "routine-cancel", bind={"routine_id": "id"}),
    _route("GET", "/projects/{p}/instructions", "instructions", take=()),
    _route("POST", "/projects/{p}/instructions", "instructions-set"),
    _route("POST", "/projects/{p}/instructions/add", "instructions-add"),
    _route("POST", "/projects/{p}/requests/{id}/files", "stage-file", bind={"request_id": "id"}, hidden=("file",), upload=True),
    _route("POST", "/projects/{p}/requests", "request"),
    _route("POST", "/projects/{p}/requests/{id}/route", "route", bind={"request_id": "id"}),
    _route("POST", "/projects/{p}/requests/{id}/cancel", "cancel", bind={"request_id": "id"}),
    _route("GET", "/projects/{p}/tasks/{id}", "task", bind={"task_id": "id"}, take=()),
    _route("POST", "/projects/{p}/tasks/{id}/retry", "retry", bind={"task_id": "id"}),
    _route("POST", "/projects/{p}/tasks/{id}/stop", "stop-task", bind={"task_id": "id"}),
    _route("POST", "/projects/{p}/tasks/{id}/go-ahead", "go-ahead", bind={"task_id": "id"}),
    _route("POST", "/projects/{p}/tasks/{id}/files", "hand-over", bind={"task_id": "id"}, hidden=("file",), upload=True),
    _route("POST", "/projects/{p}/runs/{id}/verdict", "verdict", bind={"run_id": "id"}),
    _route("POST", "/projects/{p}/agents/{name}/mode", "set-mode", bind={"agent": "name"}, take=("mode",)),
    _route("POST", "/projects/{p}/agents/{name}/model", "set-model", bind={"agent": "name"}, take=("model",)),
    _route("POST", "/projects/{p}/agents/{name}/consent", "give-consent", bind={"agent": "name"},
           take=("model", "mode", "config_sha256", "warning_sha256")),
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
    _route("POST", "/projects/{p}/ask", "ask"),
    _route("POST", "/projects/{p}/sync", "sync"),
    _route("GET", "/projects/{p}/sources", "sources", take=()),
    _route("POST", "/projects/{p}/sources", "source-add"),
    _route("POST", "/projects/{p}/sources/{name}/files", "source-import", bind={"source_id": "name"},
           hidden=("file", "url", "origin", "description"), upload=True),
    _route("POST", "/projects/{p}/sources/{name}/import", "source-import", bind={"source_id": "name"}, take=("url", "origin", "description"),
           hidden=("file",)),
    _route("POST", "/projects/{p}/sources/{name}/refresh", "source-refresh", bind={"source_id": "name"}, take=(), hidden=("file",)),
    _route("POST", "/projects/{p}/sources/{name}/refresh/files", "source-refresh", bind={"source_id": "name"}, hidden=("file",), upload=True),
    _route("POST", "/projects/{p}/sources/{name}/description", "source-describe", bind={"source_id": "name"}, take=("description",)),
    _route("GET", "/projects/{p}/attachments", "attachments", take=()),
    _route("GET", "/projects/{p}/items", "items", take=("source",)),
    _route("POST", "/projects/{p}/attachments/{id}/add", "attachment-add", bind={"attachment_id": "id"}),
    _route("POST", "/projects/{p}/attachments/{id}/discard", "attachment-discard", bind={"attachment_id": "id"}),
    _route("GET", "/projects/{p}/reminders", "reminders", take=()),
    _route("POST", "/projects/{p}/reminders", "remind"),
    _route("POST", "/projects/{p}/reminders/{id}/forget", "reminder-forget", bind={"reminder_id": "id"}),
    _route("POST", "/projects/{p}/reminders/{id}/restore", "reminder-restore", bind={"reminder_id": "id"}),
    _route("POST", "/projects/{p}/events", "event-create"),
    _route("POST", "/projects/{p}/events/change", "event-change"),
    _route("POST", "/projects/{p}/events/cancel", "event-cancel"),
    _route("POST", "/projects/{p}/files", "file-create", take=("account", "file_name", "content", "from_path", "folder")),      # W4a: each only prepares a card
    _route("POST", "/projects/{p}/files/replace", "file-replace", take=("account", "file", "content", "from_path")),
    _route("POST", "/projects/{p}/files/save", "file-save", take=("account", "attachment", "file_name", "folder")),
    _route("POST", "/projects/{p}/files/trash", "file-trash", take=("file", "account", "folder")),      # R2-A: prepares the card of a file found by its name; a POST so that a name is never in a URL
    _route("POST", "/projects/{p}/tasks/list", "todo-list", take=("account",)),      # CB-5: the open tasks of the person's own lists, read live (a POST, like file-read: a read of the person's own data is no URL); the two writes below only prepare a card
    _route("POST", "/projects/{p}/tasks", "todo-add", take=("account", "title", "list")),
    _route("POST", "/projects/{p}/tasks/done", "todo-done", take=("account", "item", "list")),
    _route("POST", "/projects/{p}/files/read", "file-read", take=("file", "account")),      # S8: the text of a file found by its name in the configured folders; a POST so that a name is never in a URL
    _route("POST", "/projects/{p}/files/ask", "file-ask", take=("file", "question", "account")),      # FA-1: a question about one file found by its name; a POST so that a name or a question is never in a URL
    _route("POST", "/projects/{p}/mail/read", "mail-read", take=("message", "number", "match", "day", "account")),      # CB-3: the text of one message of the mail snapshots, behind the group read-mail-body; a POST so that a word of a sender or a subject is never in a URL
    _route("POST", "/projects/{p}/mail/send", "mail-send"),
    _route("POST", "/projects/{p}/mail/reply", "mail-reply"),
    _route("POST", "/projects/{p}/mail/draft", "mail-draft"),
    _route("POST", "/projects/{p}/mail/archive", "mail-archive"),
    _route("POST", "/projects/{p}/mail/move", "mail-move"),
    _route("POST", "/projects/{p}/mail/mark", "mail-mark"),
    _route("POST", "/projects/{p}/mail/trash", "mail-trash"),
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


def allowed_hosts(port: int, lan_ip=None, on_lan=None) -> tuple:
    """The Host values a request may carry. On the LAN socket of --lan (`on_lan` true) only `<lan-ip>:<port>`; on the
    loopback socket (`on_lan` false) the loopback's two; when the socket is not told (None: a caller with no socket) the
    loopback's two and, with a `lan_ip`, that address too. Nothing else, ever."""
    if on_lan:
        return (f"{lan_ip}:{port}",) if lan_ip else ()
    names = [f"{HOST}:{port}", f"localhost:{port}"]
    if lan_ip and on_lan is None:
        names.append(f"{lan_ip}:{port}")
    return tuple(names)


def check_request(method: str, path: str, headers: dict, port: int, token: str, lan_ip=None, on_lan=None):
    """None when the request may proceed, else (status, error word): the rules 2 to 5 in order. It reads nothing but its
    arguments (no file, no socket); `path` may carry its query, which is not looked at here. `lan_ip` is the LAN address
    of a service started with --lan (None otherwise: the Host and the Origin are then the loopback's alone); `on_lan` says
    which socket the request came in on (allowed_hosts)."""
    h = {str(k).lower(): v for k, v in headers.items()}
    host = h.get("host")
    hosts = allowed_hosts(port, lan_ip, on_lan)
    if not isinstance(host, str) or host.lower() not in hosts:
        return 403, "host"
    origin = h.get("origin")
    if origin is not None:
        if not isinstance(origin, str) or origin.lower() not in tuple(f"http://{x}" for x in hosts):
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

    def __init__(self, ops_module, projects, token: str, port: int, interface_dir=None, log=None, token_file=None,
                 lan_ip=None):
        if not isinstance(token, str) or len(token) < 32:
            raise ValueError("the token is at least 32 characters")
        super().__init__(ops_module, projects, log)
        self.token = token
        self.port = int(port)
        self.interface_dir = interface_dir
        self.token_file = token_file   # the absolute path of the token file, or None (then GET /token-file is not a route)
        self.address = None      # (host, port) the socket is bound to, set by serve()
        self.lan_ip = lan_ip     # the private address of --lan (a second socket, the same port), or None: the default
        self.bridge = None       # the child of --messaging (service_bridge.Child; service_bridge.Bridges for several), or None

    def messaging_state(self):
        """The service's own field of GET /projects: the bridge child's state, or None without --messaging."""
        return self.bridge.state() if self.bridge is not None else None

    def __repr__(self) -> str:
        return f"<Service port={self.port} projects={len(self.projects)}>"


def dispatch_loop(service: Service, every: float, stop, op: str = "dispatch") -> None:
    """Call the operation `op` (`dispatch`, `route_queued`, or `poll` for the short job) for each project, every `every`
    seconds until `stop` is set, and reap the children of the dispatcher on every tick of every loop (ops.reap). `dispatch`
    is called without waiting (the runs it starts are processes of their own), holds no model slot, and is not stopped by a
    job that runs (the router runs beside task runs); a project whose dispatch lock is held is skipped without a word.
    `route_queued` holds the project's model slot during the call, so a job that calls a model waits (a job that queues does
    not), and is not stopped by a dispatch job; `poll` skips a project that has a job running. An error is logged (once,
    while it repeats) and the loop goes on."""
    last = {}
    busy = getattr(service.ops, "DispatchBusy", ())
    while not stop.wait(every):
        try:
            getattr(service.ops, "reap", lambda: None)()
        except Exception as e:  # a tick that cannot reap leaves the children for the next one
            service.log(f"reap: {type(e).__name__}: {CONTROL.sub(' ', str(e))[:300]}")
        for project in service.projects:
            if service.stopping.is_set():
                return
            if op != "dispatch" and service.running(project["id"], ignoring=("dispatch",)):
                continue
            if op in MODEL_LOOPS:
                with service.lock:
                    if project["id"] in service.exclusive:
                        continue
                    service.exclusive[project["id"]] = f"the {op} loop"
            try:
                if op == "dispatch":
                    service.ops.dispatch(project["path"], wait=False)
                else:
                    getattr(service.ops, op)(project["path"])
                last.pop((op, project["id"]), None)
            except busy:
                continue
            except Exception as e:  # the loop survives whatever one round raises
                text = f"{op} of {project['id']}: {type(e).__name__}: {fault_text(e)}"
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


def _policy_refusal(service: Service, project: dict, row: dict, route: dict, params: dict, given: dict, from_query: bool) -> None:
    """The page's channel policy (decisions M-8, M-13), checked for a route before anything runs: before the bytes of an
    upload are written and before a job exists, so a refused route takes no model slot. The configuration is asked
    first (`config` never refuses): one that is not accepted is left to the operation, which answers 412 as it does today;
    otherwise the `channels` of that answer are the project's policy. A read returns at once (a page policy lists `read`).
    For approve the decision's kind is read here (`pending`), and with task keys the group `go-ahead` is needed too.
    Raises the operations layer's OpsError (code 1, so 409 "refused") with the sentence of operations.not_enabled.
    The check is also made inside the operations (ops_waits.only_on_plans, ops_config.set_mode), which stay the authority.
    The policy governs a person's requests, not the dispatch loop the service runs on its own timer."""
    operations = service.ops.operations
    if operations.is_read(row["name"]):
        return
    found = service.ops.config(project["path"])
    if not found.get("accepted"):
        return
    kind, go_ahead = None, False
    if row["name"] == "approve":
        args = arguments(row, route, params, given, from_query)
        go_ahead = bool(args.get("go_ahead"))
        decision = service.ops.pending(project["path"], pending_id=args["pending_id"])
        kind = decision["kind"]
        if kind == "effect" and decision.get("effect_word"):
            kind = "effect:" + decision["effect_word"]    # POL-1: the policy covers an effect by its word
    refused = operations.refusal(row["name"], "page", found.get("channels"), kind, go_ahead)
    if refused:
        raise service.ops.OpsError(refused, 1)


def _permissions(service: Service, entry: dict):
    """The page's permissions of one project of GET /projects: {"channel": "page", "allowed": [...]} (operations.permissions),
    or None when the configuration is not accepted now (nothing is permitted yet) or cannot be read."""
    if not (entry.get("config") or {}).get("accepted"):
        return None
    try:
        found = service.ops.config(entry["folder"])
    except service.ops.OpsError:
        return None
    if not found.get("accepted"):
        return None
    out = {"channel": "page", "allowed": service.ops.operations.permissions("page", found.get("channels"))}
    table = service.ops.operations
    grants = [{"channel": c, "group": g, "text": table.GRANT_TEXT.get(f"{c}:{g}", g)} for c, g in table.grants(found.get("channels"))]
    held = {(g["channel"], g["group"]) for g in grants}
    grants += [{"channel": "messaging", "group": g, "text": table.GRANT_TEXT.get(f"messaging:{g}", g) + " (to a listed sender whose profile lists it)"}
               for g in dict.fromkeys(g for _, g in table.sender_grants(found.get("channels"))) if ("messaging", g) not in held]   # POL-2: a sender's profile widens too; the page names the group, never the sender
    return {**out, "grants": grants} if grants else out     # POL-1: what the project widened (for the line the page shows); the key is there only when something is


def _shown_commands(service: Service, project: dict, result: dict) -> dict:
    """The `commands` answer without the commands the page's policy refuses (permitted under the page; `/new` follows
    `say` (the group talk), `/help` stays): the page lists what it may do."""
    operations = service.ops.operations
    policy = service.ops.config(project["path"]).get("channels")
    names = {"new": "say"}
    keep = [c for c in result["commands"]
            if c["command"] == "/help" or operations.permitted(names.get(c["command"][1:], c["command"][1:]), "page", policy)]
    return {**result, "commands": keep}


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
    _policy_refusal(service, project, row, route, params, given, from_query)
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
    if row["name"] == "commands":
        return _json(200, _shown_commands(service, project, call()))
    return _json(200, call())


def _token_file(service: Service, method: str, query: str, loopback: bool = True) -> tuple:
    """GET /token-file: the token file's absolute path and the commands that read it, never the token. Both are null when
    the path has a control character (no safe command exists). The commands are the operations layer's text. `loopback`
    is false for a request that arrived on the LAN socket or names a Host that is not a loopback one: it gets the 404 of
    a service with no token file, so a device on the network cannot learn the machine's paths without the token."""
    if method != "GET":
        return _error(405, "method")
    if service.token_file is None or not loopback:
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
    # The demo mode's files (interface/demo/: a world of fictional data that answers in place of the service) are for the built copy of the
    # page only (scripts/build_demo.py): a running service never serves them, by any spelling of the path (the check is on the resolved file,
    # compared without regard to case, since a file system may fold it).
    if target.lower().startswith(os.path.join(root, DEMO_DIR).lower() + os.sep):
        return _error(404, "not_found")
    try:
        if os.path.getsize(target) > STATIC_LIMIT:
            return _error(404, "not_found")
        with open(target, "rb") as f:
            data = f.read()
    except OSError:
        return _error(404, "not_found")
    return 200, _headers(content_type), data


def handle(service: Service, method: str, path: str, headers: dict, body: bytes, lan: bool = False) -> tuple:
    """The whole of one request without a socket: (status, headers, body bytes). The rules 2 to 5 (check_request), then
    the route, the project, the arguments, the one operation. A request that passes check_request and names no route is
    404 or 405; an operation's refusal is its documented status. `lan` is true when the request arrived on the LAN
    socket of --lan (the handler decides it from the address the connection was reached on); only GET /token-file reads it."""
    refused = check_request(method, path, headers, service.port, service.token, service.lan_ip, lan if service.lan_ip else None)
    if refused:
        return _error(*refused)
    bare, _, query = path.partition("?")
    if bare == TOKEN_FILE_ROUTE:
        host = {str(k).lower(): v for k, v in headers.items()}.get("host")
        loopback_host = str(host).lower() in allowed_hosts(service.port)
        return _token_file(service, method, query, loopback=loopback_host and not lan)
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
            listed = service.projects_list()
            listed["projects"] = [{**entry, "permissions": _permissions(service, entry)} for entry in listed["projects"]]
            return _json(200, {**listed, "messaging": service.messaging_state()})
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


def _on_lan(connection) -> bool:
    """Whether a request came in on the LAN socket of --lan: true unless the address this connection was reached on is a
    loopback one. It fails closed: an address it cannot read, or one that is not an IP address, counts as the LAN's."""
    try:
        address = connection.getsockname()[0]
        ip = ipaddress.ip_address(str(address).partition("%")[0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        return not ip.is_loopback
    except Exception:  # noqa: BLE001  (any failure to tell is the safe answer)
        return True


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
                lan = _on_lan(self.connection) if service.lan_ip else False  # without --lan the old path, untouched
                refused = check_request(method, path, headers, service.port, service.token, service.lan_ip,
                                        lan if service.lan_ip else None)
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
                        answer = handle(service, method, path, headers, raw, lan=lan)
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
    # (R4-C2). 128 is the usual system ceiling; the listening address is 127.0.0.1, and with --lan one private address too.
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
            log(f"service check of {project['name']}: {type(e).__name__}: {fault_text(e)}")
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
          ops_module=None, stop=None, ready=None, log=None, out=None, server_class=None, lan=None, messaging=None,
          notice_every=None, environment=None, bridge_argv=None, bridge_stop_wait=service_bridge.BRIDGE_STOP_WAIT) -> int:
    """Check every project with the `config` operation, bind 127.0.0.1:<port> (and, with `lan` -- "auto" or a private
    address -- that one address on the same port, after the warning of LAN_WARNING is logged; a refused address is exit 2),
    write the token file, print the one JSON line, and serve until a signal (or `stop`, an Event, is set); then end the runs the jobs started
    (ops.stop_runs, which is waited for) and remove the token file. The `poll` loop runs every `poll_every` seconds
    (0: not at all), the `dispatch` loop every `dispatch_every` seconds (30 unless told; None or 0: not at all). After
    the JSON line it logs what each project's check found (check_projects). Returns the exit code.
    `ready(service)` is called once the socket listens, `server_class` replaces the HTTP server (both are the tests').
    `messaging` (a platform name, or a list of names) starts the bridge child after the JSON line (service_bridge.py) with `environment`, the snapshot
    of the environment main() took before any thread (None: the environment now), and `notice_every` for the bridge only;
    at the top of the final block the child's stop begins (its input closed, SIGTERM to its group), and after the runs are
    ended it is waited for up to `bridge_stop_wait` seconds, then killed. `bridge_argv` (the interpreter and script the
    child runs instead of the bridge) and `bridge_stop_wait` are the tests' parameters, read from nothing else."""
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
    lan_ip = None
    if lan:
        try:
            lan_ip = lan_address(lan)
        except Refused as e:
            print(f"error: --lan: {e}", file=sys.stderr)
            return 2
    token = new_token()
    target = token_file or os.path.join(found[0]["data_dir"], TOKEN_NAME)
    interface_dir = interface_dir if interface_dir is not None else os.path.join(ROOT, "interface")
    try:
        server = (server_class or Server)((HOST, int(port)), http.server.BaseHTTPRequestHandler)
    except OSError as e:
        print(f"error: cannot listen on {HOST}:{port}: {e.strerror}", file=sys.stderr)
        return 1
    lan_server = None
    if lan_ip:  # the second socket: the one LAN address, the port the first one got; never 0.0.0.0
        try:
            lan_server = (server_class or Server)((lan_ip, server.server_address[1]), http.server.BaseHTTPRequestHandler)
        except OSError as e:
            server.server_close()
            print(f"error: cannot listen on {lan_ip}:{server.server_address[1]}: {e.strerror}", file=sys.stderr)
            return 1
    servers = [s for s in (server, lan_server) if s is not None]
    service = Service(ops_module, [{k: p[k] for k in ("id", "name", "path")} for p in found], token,
                      server.server_address[1], interface_dir, log, token_file=os.path.abspath(target), lan_ip=lan_ip)
    service.address = tuple(server.server_address[:2])
    child = None
    if messaging:
        platforms = [messaging] if isinstance(messaging, str) else list(messaging)
        messaging = platforms[0] if len(platforms) == 1 else platforms  # one platform keeps its string everywhere
        make = service_bridge.Child if len(platforms) == 1 else service_bridge.Bridges
        child = make(platforms[0] if len(platforms) == 1 else platforms, [p["path"] for p in found],
                     environment if environment is not None else dict(os.environ),
                     log, notice_every=notice_every, program=bridge_argv, stop_wait=bridge_stop_wait)
        service.bridge = child
    for one in servers:
        one.RequestHandlerClass = make_handler(service)
    try:
        write_token(target, token)
    except OSError as e:
        for one in servers:
            one.server_close()
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
    serving_lan = None
    if lan_server is not None:
        serving_lan = threading.Thread(target=lan_server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
        threads.append(serving_lan)
    for every, op in ((poll_every, "poll"), (dispatch_every, "dispatch"),
                      (QUEUE_EVERY if hasattr(ops_module, "route_queued") else 0, "route_queued")):
        if every:
            threads.append(threading.Thread(target=dispatch_loop, args=(service, float(every), stop, op), daemon=True))
    try:
        shown = {"url": f"http://{HOST}:{service.port}/"}
        if lan_ip:  # the warning first, before any thread listens, then the address to open, then the one JSON line
            for line in LAN_WARNING:
                log(line)
            lan_url = f"http://{lan_ip}:{service.port}/"
            log(f"Open on the phone: {lan_url}")
            log("The token is never in the address: paste it on the phone when the page asks for it. To read it on this "
                f"machine, open http://{HOST}:{service.port}/ for the command that copies it; its file is {os.path.abspath(target)}")
            shown["lan_url"] = lan_url
        for thread in threads:
            thread.start()
        print(json.dumps({**shown, "token_file": target,
                          "projects": [{"id": p["id"], "name": p["name"]} for p in found],
                          **({"messaging": messaging} if messaging else {})}), file=out, flush=True)
        if child is not None:  # after the sockets are bound and the line is printed
            child.start()
        check_projects(ops_module, found, dispatch_every, log)
        if ready:
            ready(service)
        while not stop.wait(0.5):
            pass
    finally:
        if child is not None:  # for any exit: the child's stop starts now, and is waited for after the runs end
            child.begin_stop()
        stop.set()
        service.stopping.set()
        for one, thread in ((server, serving), (lan_server, serving_lan)):
            if one is not None and thread.ident is not None:  # shutdown() waits for serve_forever, which must have been started
                one.shutdown()
        for one in servers:
            one.server_close()
        left = service.end_runs(threads)
        if left:
            log(f"stopped with {left} job thread(s) still ending")
        if child is not None:
            child.finish_stop()
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


def check_lan_address(text) -> str:
    """The address `--lan` may listen on, or Refused. Only an IPv4 address of 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16 or
    169.254.0.0/16 is taken; 0.0.0.0 (every interface), the loopback, a public address and anything else is refused."""
    if text == "0.0.0.0":
        raise Refused("0.0.0.0 would listen on every interface; give the one private LAN address of this machine")
    if not isinstance(text, str) or not IPV4.fullmatch(text):
        raise Refused(f"{str(text)[:40]!r} is not a dotted IPv4 address")
    ip = ipaddress.ip_address(text)
    if text.endswith((".0", ".255")):
        raise Refused(f"{text} is a network or broadcast address, not the address of this machine; give the machine's own")
    if not any(ip in network for network in LAN_NETWORKS):
        raise Refused(f"{text} is not a private address (10.x.x.x, 172.16-31.x.x, 192.168.x.x or 169.254.x.x); "
                      "only a private LAN address is taken, never a public one or the loopback")
    return text


def detect_lan_ip():
    """The IPv4 address this machine uses on its default route, or None when it has no route. A UDP socket is connected
    to a private address and asked for its own: connecting a UDP socket sends no packet, so no other host is contacted."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(LAN_PROBE)
        return probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()


def lan_address(requested) -> str:
    """The address `--lan` listens on: the one given, or, for "auto", the one found on the default route; both checked."""
    if requested != "auto":
        return check_lan_address(requested)
    found = detect_lan_ip()
    if found is None:
        raise Refused("no LAN address was found (the machine has no route to a private network); give it: --lan <ip>")
    try:
        return check_lan_address(found)
    except Refused as e:
        raise Refused(f"the address of the default route is not a private LAN address ({e}); give the right one: --lan <ip>") from None


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
    DISPATCH_EVERY unless --dispatch-every gives another or --no-dispatch makes it None. The keys "messaging" (the platform, or
    the list of platforms when several are given: a comma list or the option repeated, at most 6, no name twice)
    and "notice_every" are there only when --messaging (and --notice-every) is given, as "lan" is only when --lan is given
     ("auto" alone, else the private address that follows it, which is checked here). Refused (Refused) for an unknown flag,
    a flag without its value, a number out of range, no project, --no-dispatch with --dispatch-every, or an address --lan
    may not take. There is no other flag for an address."""
    out = {"projects": [], "port": 8765, "poll_every": 60.0, "dispatch_every": DISPATCH_EVERY, "token_file": None}
    flags = {"--project", "--port", "--poll-every", "--dispatch-every", "--token-file", "--messaging", "--notice-every"}
    args, said_every, no_dispatch, platforms = list(argv), False, False, []
    while args:
        flag = args.pop(0)
        if flag == "--no-dispatch":
            no_dispatch = True
            continue
        if flag == "--lan":  # its value is optional: a following word that is not a flag is the address
            out["lan"] = check_lan_address(args.pop(0)) if args and not args[0].startswith("--") else "auto"
            continue
        if flag not in flags:
            raise Refused(f"unknown argument {flag!r}")
        if not args:
            raise Refused(f"{flag} needs a value")
        value = args.pop(0)
        if flag == "--messaging":
            names = value.split(",")
            if not all(PLATFORM.fullmatch(n) for n in names):
                raise Refused("--messaging takes platforms: lowercase words of letters, digits and hyphens, such as telegram, "
                              "or a comma list such as telegram,whatsapp-twilio")
            platforms += names
        elif flag == "--notice-every":
            if not (value.isascii() and value.isdigit()) or int(value) < MIN_NOTICE_EVERY:
                raise Refused(f"--notice-every is a whole number of seconds, {MIN_NOTICE_EVERY} or more")
            out["notice_every"] = int(value)
        elif flag == "--project":
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
    if platforms:
        if len(set(platforms)) != len(platforms):
            raise Refused("--messaging names a platform twice: one bridge serves one platform")
        if len(platforms) > MAX_MESSAGING:
            raise Refused(f"--messaging takes at most {MAX_MESSAGING} platforms")
        out["messaging"] = platforms[0] if len(platforms) == 1 else platforms
    if "notice_every" in out and "messaging" not in out:
        raise Refused("--notice-every is for the bridge: it needs --messaging <platform>")
    if no_dispatch:
        if said_every:
            raise Refused("--no-dispatch and --dispatch-every exclude each other")
        out["dispatch_every"] = None
    return out


def main(argv=None) -> int:
    snapshot = dict(os.environ)  # first of all, before any thread or run: what the bridge child will get (--messaging)
    argv = sys.argv[1:] if argv is None else argv
    if not argv or "--help" in argv or "-h" in argv:
        print(__doc__.strip(), file=sys.stdout if argv else sys.stderr)
        return 0 if argv else 2
    try:
        given = parse(argv)
    except Refused as e:
        print(f"error: {e}. See --help.", file=sys.stderr)
        return 2
    extra = {}  # only what was asked for: without the option the call is the one it always was
    if given.get("lan"):
        extra["lan"] = given["lan"]
    if given.get("messaging"):
        extra.update(messaging=given["messaging"], environment=snapshot)
        if "notice_every" in given:
            extra["notice_every"] = given["notice_every"]
    return serve(given["projects"], given["port"], given["poll_every"], given["dispatch_every"] or None,
                 given["token_file"], **extra)


if __name__ == "__main__":
    sys.exit(main())
