#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The MCP mode: the operations layer of runtime/ops.py served as tools of a Model Context Protocol server over
standard input and output. A shell like the terminal's and the local service's: it parses a message, calls one
operation and returns what it returned. It holds no rule of its own about the work (which words a decision takes, what
a state leads to, what a hash must equal, which channel may approve an effect are the operations layer's and the
store's), reads no project file, and imports only the operations layer and the kit it shares with the local service
(shell_kit.py). It is a client's tool, not a person's: the
messaging apps an MCP client brings are the weaker trust surface the channel rule exists for.

Usage:
  python3 runtime/mcp.py --project <dir> [--project <dir>]...
  python3 runtime/mcp.py --help

  --project   a project folder (runtime/project_config.py); repeat for several. Each is checked at start with the
              `config` operation exactly as the local service does: a folder that is not a configured project ends the
              start (exit 3); a configuration you did not accept yet does not (the project is listed with
              "accepted": false, and every tool of it is refused with the status 412 "not_configured" until
              `accept-config` is typed in the terminal)

The client starts this process and speaks to it on its standard input and output: one JSON-RPC 2.0 message per line,
UTF-8, no line break inside a message (the protocol's stdio transport). Nothing but those messages is ever written to
standard output; the log goes to standard error and holds the method, the tool, the outcome and the duration of a call,
no argument and no result, and, when an operation fails in a way it did not expect (an internal failure), that failure's
traceback, which may name a path or quote the failing value; it holds no secret of the shell, which has none. There is no token: the client that started the process is the only reader of its
pipes. The process runs no background loop (`poll`, `dispatch`): the local service does, when the person starts it.

What a client gets. The methods `initialize`, `ping`, `tools/list` and `tools/call`; the notifications it sends
(`notifications/initialized`, `notifications/cancelled`, any other `notifications/...`) are accepted and need no
answer; any other method is -32601. The tools are, in the table's order, one per operation of runtime/operations.py
whose row lists the channel `mcp`, then two of the shell's own: `projects` (the projects served, with whether each
configuration is accepted) and `job` (a job asked for again). Every operation tool takes the operation's arguments by
name and `project` (the id `projects` shows: the first 12 hexadecimal characters of the sha256 of the project's real
path; optional when one project is served). The result is the operation's result as JSON in one text content; text
from the project (a document, a reply, a comment) is inside that JSON as a string and is never interpreted. An
operation that calls a model or a platform (the row's `job`) is started in a thread and answers at once with a job,
{"job", "op", "project", "state": "running", "result", "error", "started_at", "ended_at", "poll"}; the tool `job` with
{"job": <n>} returns it again, "state" "done" or "failed" at the end. A job that ends within one second is returned
ended. A job that calls a model is refused with "busy" while another such job of the project runs.

What is refused. A client of this channel may request, route, answer, release a draft and say, and read; nothing else.
An operation whose row does not list `mcp` has no tool (the table is read, nothing is spelled here): approve, reject,
cancel, retry, accept-config, run-next, the standing approvals and the others are done in the terminal or on the page,
where the person is. The same holds for a command typed into the tool `say`: the tool is called as the channel `mcp`
(a client cannot name another) and the operations layer does a command of a line only when its row lists that channel,
so "/approve", "/reject", "/retry" and "/cancel" in a line are refused with "/<command> is done in the terminal or on the
page". A model client must not authorise runs on its own request chain, and the hash of an effect is typed in the terminal
or clicked on the page, never sent from here.

A refusal of the operations layer (409 "refused", 412 "not_configured", "busy") is a tool result with "isError": true and
the sentence as its text content, as the protocol's tool-execution error. The protocol's error object is for the rest: its
message is the text and `data` is {"error": <word>, "status": <n>}, the words and statuses of the local service: 400
"usage" (code 2 of the operations layer, also an argument that does not fit the tool, with the code -32602), 404
"not_found", 500 "internal" (-32603; the traceback on standard error only). A message that is not JSON is -32700, one that
is not a request is -32600 (a batch is accepted, though the 2025-06-18 version dropped batches), an unknown method -32601,
an unknown tool or a bad argument -32602, a request before `initialize` -32002.

When it stops (standard input closed, SIGINT or SIGTERM) it ends the runs a job started (ops.stop_runs) and does not exit
before that returns; a second signal while it stops is ignored.

Exit codes: 0 stopped (input closed or a signal), 2 usage error, 3 a project is not configured.
Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import io
import json
import os
import signal
import sys
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ops  # noqa: E402  (the same folder: the operations layer)
import shell_kit  # noqa: E402  (the same folder: what this shell shares with the local service; with ops, the only modules of the runtime this one imports)
from shell_kit import EXPOSED_KINDS, project_id, projects_of as _projects_of  # noqa: E402,F401

CHANNEL = "mcp"
SERVER_NAME = "workbench-runtime"
SERVER_VERSION = "1"
PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")  # newest first; the client's is answered when it is one of these
LINE_LIMIT = 1024 * 1024                                # bytes of one message (the service's body limit)
GRACE = 1.0                                             # seconds a started job is waited for before the job is returned
OWN_TOOLS = ("projects", "job")
INSTRUCTIONS = (
    "Tools of the openhora task runtime. Read the project with status, pending, task, progress and the others; "
    "request, route, say, answer and release change the work. A tool that returns a job is polled with the tool job. "
    "Approvals, rejections, cancellations and retries are made in the terminal or on the local page, where the person is "
    "(an effect, a publication, a pull request or a message sent, only with the hash of its content): none is a tool "
    "here, and a command of that kind typed into say is refused."
)
REFUSAL_WORDS = ("refused", "not_configured", "busy")  # returned as a tool result with isError, not as an error object
WORDS = {
    "usage": "the request is malformed", "refused": "the operation refused", "not_configured": "the project is not configured",
    "not_found": "no such tool, project or job", "busy": "a job that calls a model is running for this project",
    "stopping": "the server is stopping", "internal": shell_kit.INTERNAL,
}
# JSON-RPC error codes (the specification's), and the one the MCP specification adds.
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603
SERVER_ERROR, NOT_INITIALIZED = -32000, -32002
NO_ID = object()  # a message without an id is a notification: it is never answered


class Stop(BaseException):
    """A signal asked the server to stop."""


ENDING = threading.Event()  # set once the server is ending its runs: a signal after that is ignored


class Fail(Exception):
    """A request that ends in the protocol's error object: the code, the text and, for a tool, the service's word and
    status."""

    def __init__(self, code: int, message: str, word: str | None = None, status: int | None = None):
        super().__init__(message)
        self.code, self.word, self.status = code, word, status

    def error(self) -> dict:
        out = {"code": self.code, "message": str(self)}
        if self.word:
            out["data"] = {"error": self.word, "status": self.status}
        return out


def usage(message: str) -> Fail:
    return Fail(INVALID_PARAMS, message, "usage", 400)


# --- the tools, read from the table ----------------------------------------------------------------------------------


def operation_rows(ops_module=None) -> tuple:
    """The rows of the table of operations that list the channel `mcp`, in the table's order: the tools of this shell."""
    return tuple(r for r in (ops_module or ops).operations.OPERATIONS if CHANNEL in r["channels"])


def _property(arg: dict) -> dict:
    kind = arg["kind"]
    if kind == "int":
        return {"type": "integer", "minimum": 0}
    if kind == "flag":
        return {"type": "boolean"}
    if kind == "choice":
        return {"type": "string", "enum": list(arg["choices"])}
    return {"type": "string"}


def tool_of(row: dict, ids: list) -> dict:
    """The tool's description for `tools/list`: its name is the verb of the row, its text the row's `help`, its input the
    row's arguments (and the project)."""
    properties = {"project": {"type": "string", "description": "the project's id, from the tool projects"
                              + ("" if len(ids) > 1 else "; optional: one project is served")}}
    if len(ids) > 1:
        properties["project"]["enum"] = list(ids)
    required = ["project"] if len(ids) > 1 else []
    for arg in row["args"]:
        if arg["kind"] not in EXPOSED_KINDS:
            continue
        properties[arg["name"]] = _property(arg)
        if arg.get("required"):
            required.append(arg["name"])
    text = row["help"]
    if row.get("job"):
        text += ". Starts a job and returns it: poll it with the tool job"
    if row.get("channel_arg"):
        text += ". Called as the channel mcp"
        if row["name"] == "say":
            text += ": a command typed in the line (approve, reject, retry, cancel) is refused, it is done in the terminal or on the page"
        if row.get("queues"):
            text += "; while a run of the project is in progress the call is refused, not queued (only the local service drains the queue)"
    return {"name": row["name"], "description": text, "inputSchema": {"type": "object", "properties": properties,
                                                                      "required": required, "additionalProperties": False}}


def own_tools() -> list:
    return [
        {"name": "projects", "description": "the projects this server serves, with whether each configuration is accepted, "
                                            "the number of decisions that wait and the task that runs",
         "inputSchema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}},
        {"name": "job", "description": "a job a tool returned, asked for again: state running, done or failed; the result "
                                       "or the error when it ended",
         "inputSchema": {"type": "object", "properties": {"job": {"type": "integer", "minimum": 0}}, "required": ["job"],
                         "additionalProperties": False}},
    ]


# --- the server object, the jobs -------------------------------------------------------------------------------------


class Server(shell_kit.Jobs):
    """What a message is served from: the operations object (the module ops, or a stand-in), the projects, the jobs
    (shell_kit.Jobs). Holds no token: a pipe has one reader."""

    def __init__(self, ops_module, projects, log=None, grace: float = GRACE):
        super().__init__(ops_module, projects, log)
        self.grace = grace
        self.initialized = False

    def __repr__(self) -> str:
        return f"<McpServer projects={len(self.projects)}>"

    def public(self, job: dict) -> dict:
        out = super().public(job)
        if job["state"] == "running":
            out["poll"] = {"tool": "job", "arguments": {"job": job["job"]}}
        return out

    def ids(self) -> list:
        return [p["id"] for p in self.projects]

    def tools(self) -> list:
        ids = self.ids()
        return [tool_of(r, ids) for r in operation_rows(self.ops)] + own_tools()


# --- one tool call ---------------------------------------------------------------------------------------------------


def _coerce(arg: dict, value):
    kind, name = arg["kind"], arg["name"]
    if kind == "int":
        if type(value) is int and value >= 0:
            return value
        raise usage(f"{name} must be a whole number of 0 or more")
    if kind == "flag":
        if type(value) is not bool:
            raise usage(f"{name} must be true or false")
        return value
    if not isinstance(value, str):
        raise usage(f"{name} must be text")
    if kind == "choice" and value not in arg["choices"]:
        raise usage(f"{name} must be one of {', '.join(arg['choices'])}")
    return value


def arguments(row: dict, given: dict) -> dict:
    """The keyword arguments of the operation, built from its row: each key by the row argument's name and kind. A key the
    tool does not take, a missing required argument and a value of the wrong type are a usage error. The channel is never
    an argument: this shell passes its own."""
    args = {a["name"]: a for a in row["args"] if a["kind"] in EXPOSED_KINDS}
    unknown = sorted(set(given) - set(args))
    if unknown:
        raise usage("this tool takes " + (", ".join(args) or "no argument") + f"; not {', '.join(map(repr, unknown))}")
    out = {}
    for name, arg in args.items():
        if given.get(name) is not None:
            out[name] = _coerce(arg, given[name])
        elif arg.get("required"):
            raise usage(f"{name} is required")
    return out


def _project_of(server: Server, given: dict) -> dict:
    wanted = given.pop("project", None)
    if wanted is None:
        if len(server.projects) == 1:
            return server.projects[0]
        raise usage("project is required: one of " + ", ".join(server.ids()))
    if not isinstance(wanted, str):
        raise usage("project must be text")
    if wanted not in server.by_id:
        raise Fail(SERVER_ERROR, "no such project", "not_found", 404)
    return server.by_id[wanted]


def _fail_of(word: str, status: int, message: str) -> Fail:
    """The protocol error of a word of the service: usage is an invalid parameter, internal an internal error, any other
    refusal a server error; the word and the status travel in `data`."""
    if word == "internal":
        return Fail(INTERNAL_ERROR, WORDS["internal"], word, status)
    return Fail(INVALID_PARAMS if word == "usage" else SERVER_ERROR, message, word, status)


def call_tool(server: Server, name, given) -> dict:
    """The result of one `tools/call`: the operation's result as JSON text, or a Fail."""
    if not isinstance(given, dict):
        raise usage("arguments must be an object")
    given = dict(given)
    if name == "projects":
        if given:
            raise usage("this tool takes no argument")
        return _text(server.projects_list())
    if name == "job":
        if set(given) != {"job"}:
            raise usage("this tool takes job, a whole number")
        number = given["job"]
        if type(number) is not int or number < 0:
            raise usage("job must be a whole number of 0 or more")
        shown = server.job_shown(number)
        if shown is None:
            raise Fail(SERVER_ERROR, "no such job", "not_found", 404)
        return _text(shown)
    rows = {r["name"]: r for r in operation_rows(server.ops)}
    row = rows.get(name) if isinstance(name, str) else None
    if row is None:
        raise Fail(INVALID_PARAMS, f"unknown tool {name!r}" if isinstance(name, str) else "name must be text",
                   "not_found", 404)
    project = _project_of(server, given)
    args = arguments(row, given)
    if row.get("channel_arg"):
        args["channel"] = CHANNEL
    function = getattr(server.ops, row["call"])
    call = lambda: function(project["path"], **args)  # noqa: E731
    try:
        try:
            if not row.get("job"):
                return _text(call())
            try:
                job, thread, _ = server.start_job(project["id"], row["name"], call)
            except shell_kit.Stopping:
                raise Fail(SERVER_ERROR, WORDS["stopping"], "stopping", 503) from None
            except shell_kit.Busy as e:
                raise Fail(SERVER_ERROR, str(e), "busy", 409) from None
            thread.join(server.grace)
            shown = server.job_shown(job["job"])
            if shown is None:  # the registry pruned it already (it ended long ago): the job itself holds its final state
                with server.lock:
                    shown = server.public(job)
            if shown["state"] == "failed":  # refused at once (a refusal of the rule, a wrong hash): the refusal itself
                e = shown["error"]
                raise _fail_of(e["error"], e["status"], e["message"])
            return _text(shown)
        except server.ops.OpsError as e:
            status, word = shell_kit.status_of(e)
            raise _fail_of(word, status, str(e)) from None
    except Fail as refusal:
        if refusal.word in REFUSAL_WORDS:  # the operation's "no" is a result the model reads, not a fault of the protocol
            return {"content": [{"type": "text", "text": str(refusal)}], "isError": True}
        raise


def _text(value) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, default=str)}], "isError": False}


# --- the protocol ----------------------------------------------------------------------------------------------------


def _initialize(server: Server, params) -> dict:
    if not isinstance(params, dict) or not isinstance(params.get("protocolVersion"), str) \
            or not isinstance(params.get("capabilities", {}), dict) or not isinstance(params.get("clientInfo", {}), dict):
        raise Fail(INVALID_PARAMS, "initialize takes protocolVersion, capabilities and clientInfo")
    wanted = params["protocolVersion"]
    server.initialized = True
    return {"protocolVersion": wanted if wanted in PROTOCOLS else PROTOCOLS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION}, "instructions": INSTRUCTIONS}


def _dispatch(server: Server, method: str, params):
    if method == "initialize":
        return _initialize(server, params)
    if method == "ping":
        return {}
    if not server.initialized:
        raise Fail(NOT_INITIALIZED, "the server is not initialized: send initialize first")
    if method == "tools/list":
        if params is not None and not isinstance(params, dict):
            raise Fail(INVALID_PARAMS, "params must be an object")
        return {"tools": server.tools()}
    if method == "tools/call":
        if not isinstance(params, dict) or set(params) - {"name", "arguments", "_meta"} or "name" not in params:
            raise Fail(INVALID_PARAMS, "tools/call takes name and arguments")
        return call_tool(server, params["name"], params.get("arguments", {}))
    raise Fail(METHOD_NOT_FOUND, f"no such method {method!r}")


def _reply(ident, result=None, error=None) -> dict:
    out = {"jsonrpc": "2.0", "id": ident}
    if error is not None:
        out["error"] = error
    else:
        out["result"] = result
    return out


def handle(server: Server, message):
    """The answer to one decoded message: a dict, or None when none is due (a notification, or a response of the client).
    A list is a batch: the list of the answers, None when there are none."""
    if isinstance(message, list):
        if not message:
            return _reply(None, error={"code": INVALID_REQUEST, "message": "an empty batch"})
        answers = [a for a in (handle(server, m) for m in message) if a is not None]
        return answers or None
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _reply(None, error={"code": INVALID_REQUEST, "message": "not a JSON-RPC 2.0 message"})
    ident = message["id"] if "id" in message else NO_ID
    if ident is not NO_ID and (isinstance(ident, bool) or not isinstance(ident, (str, int))):
        return _reply(None, error={"code": INVALID_REQUEST, "message": "id must be a string or a whole number"})
    method = message.get("method")
    if method is None and ("result" in message or "error" in message):
        return None  # the client's answer to nothing we asked
    if not isinstance(method, str):
        return _reply(None if ident is NO_ID else ident, error={"code": INVALID_REQUEST, "message": "method must be text"})
    started = time.monotonic()
    outcome = "ok"
    try:
        result = _dispatch(server, method, message.get("params"))
        answer = None if ident is NO_ID else _reply(ident, result=result)
    except Fail as e:
        outcome = f"error {e.code}" + (f" {e.word} {e.status}" if e.word else "")
        answer = None if ident is NO_ID else _reply(ident, error=e.error())
    except Exception:  # whatever else: the traceback stays on standard error, the answer names nothing
        server.log("internal error:\n" + traceback.format_exc())
        outcome = "error internal"
        answer = None if ident is NO_ID else _reply(ident, error={"code": INTERNAL_ERROR, "message": WORDS["internal"],
                                                                  "data": {"error": "internal", "status": 500}})
    shown = method
    if method == "tools/call" and isinstance(message.get("params"), dict):
        called = message["params"].get("name")
        shown += " " + (called if isinstance(called, str) and called in _names(server) else "?")
    server.log(f"{shown[:80]} {outcome} {int((time.monotonic() - started) * 1000)}ms")
    return answer


def _names(server: Server) -> set:
    return {r["name"] for r in operation_rows(server.ops)} | set(OWN_TOOLS)


def decode(line: bytes):
    """The message of one line, or a Fail for the parse error."""
    try:
        return json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise Fail(PARSE_ERROR, "the line is not JSON") from None


def encode(answer) -> str:
    """One line of output: ASCII only, so that no line separator of any kind is inside a message."""
    return json.dumps(answer, ensure_ascii=True, default=str, separators=(",", ":"))


def read_line(stream):
    """The next line of the input as bytes, b"" at its end, or the string "too large" for a line over LINE_LIMIT (the rest
    of that line is read and dropped)."""
    line = stream.readline(LINE_LIMIT + 1)
    if len(line) > LINE_LIMIT and not line.endswith(b"\n"):
        while True:
            rest = stream.readline(LINE_LIMIT)
            if not rest or rest.endswith(b"\n"):
                break
        return "too large"
    return line


def serve_stream(server: Server, stdin, stdout) -> None:
    """Read messages from `stdin` (a binary stream) and write the answers to `stdout` (a text stream) until the input ends.
    Every line written is one JSON-RPC message."""
    while True:
        line = read_line(stdin)
        if line == b"":
            return
        if line == "too large":
            answer = _reply(None, error={"code": INVALID_REQUEST, "message": f"a message is at most {LINE_LIMIT} bytes"})
        elif not line.strip():
            continue
        else:
            try:
                answer = handle(server, decode(line))
            except Fail as e:
                answer = _reply(None, error=e.error())
        if answer is not None:
            stdout.write(encode(answer) + "\n")
            stdout.flush()


# --- the process -----------------------------------------------------------------------------------------------------


def serve(projects, stdin=None, stdout=None, ops_module=None, log=None, grace: float = GRACE) -> int:
    """Check every project with the `config` operation, then answer messages from `stdin` on `stdout` until the input ends
    or a signal arrives (Stop); then end the runs the jobs started (ops.stop_runs, which is waited for). Returns the exit
    code. Nothing is written to `stdout` but JSON-RPC messages."""
    ops_module = ops_module or ops
    log = log or shell_kit.default_log
    try:
        found = _projects_of(projects, ops_module)
        if not found:
            raise ops_module.OpsError("no project was given", 2)
    except ops_module.OpsError as e:
        print(f"error: {e}", file=sys.stderr)
        return e.code
    server = Server(ops_module, found, log, grace)
    log(f"serving {len(found)} project(s) over standard input and output")
    try:
        serve_stream(server, stdin if stdin is not None else sys.stdin.buffer, stdout if stdout is not None else sys.stdout)
    except Stop:
        pass
    finally:
        ENDING.set()
        server.stopping.set()
        left = server.end_runs()
        if left:
            log(f"stopped with {left} job thread(s) still ending")
    return 0


class Refused(Exception):
    pass


def parse(argv) -> list:
    """The project folders of the command line. Refused for an unknown argument, a flag without its value or no project."""
    projects, args = [], list(argv)
    while args:
        flag = args.pop(0)
        if flag != "--project":
            raise Refused(f"unknown argument {flag!r}")
        if not args:
            raise Refused("--project needs a value")
        projects.append(args.pop(0))
    if not projects:
        raise Refused("give at least one --project <dir>")
    return projects


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or "--help" in argv or "-h" in argv:
        print(__doc__.strip(), file=sys.stdout if argv else sys.stderr)
        return 0 if argv else 2
    try:
        projects = parse(argv)
    except Refused as e:
        print(f"error: {e}. See --help.", file=sys.stderr)
        return 2
    # The protocol owns the real standard output: it is copied aside, and descriptor 1 (and sys.stdout) becomes standard
    # error, so that nothing a library or a program the operations start prints can ever be taken for a message.
    protocol = io.TextIOWrapper(os.fdopen(os.dup(1), "wb"), encoding="utf-8", newline="\n", write_through=True)
    os.dup2(2, 1)
    sys.stdout = sys.stderr

    def on_signal(signum, _frame):
        if ENDING.is_set() or getattr(on_signal, "seen", False):
            return
        on_signal.seen = True
        raise Stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, on_signal)
    return serve(projects, sys.stdin.buffer, protocol)


if __name__ == "__main__":
    sys.exit(main())
