#!/usr/bin/env python3
"""The key proxy of the eval network: one proxy runs per run, serves the one model of that run and holds the one key its provider route names, so that a run never does.

evals/executor.py starts one in a container of its own for each run that is passed a held key, named after the
run's container, on an internal network of its own where only the run and its key proxy sit (a run on the web
gets a network that is not internal, also its own), with its key in its environment and the folder where it
writes its meter mounted. The route file (route-<provider>.json) describes the provider; the model, its pin and
the model names it may send come from the gate file's entry of the run's model, as arguments. A run container
gets a placeholder in the key's variable and, in the variable its route names ("base_url_env"), the base URL of
its proxy. The run's runner sends its calls there over plain HTTP, and the proxy forwards each to the one
provider host the route names, over HTTPS, with an Authorization header made from the key it alone holds. It:
  - forwards only a request whose target is a path under the route's prefix (/api/v1/ for OpenRouter, /v1/ for
    Anthropic), in origin form, and whose path (the query is not part of it) is one of the route's "paths", the
    model endpoints the runner uses; an absolute URL, another path, a path with a "." or ".." segment and CONNECT
    are refused, and nothing of them is forwarded;
  - serves one model: it reads the JSON body of every POST to a model endpoint and refuses (403, with the reason)
    a request whose "model" is not one of the names given with --upstream-model, or that has none; a body that is
    not a JSON object is refused (400), and so is any other method on a model endpoint (405);
  - never routes by the Host header: the upstream is fixed when the proxy starts;
  - removes every header that can carry a credential a run sends or makes up (Authorization,
    Proxy-Authorization, x-api-key, api-key, x-goog-api-key, anthropic-auth-token, cookie, and any header
    whose name has auth, api-key (or api_key), token, secret, cookie, credential or password in it), forwards
    every other header unchanged (a session id or an idempotency key is not a credential), and adds one Authorization of its own;
  - when started with --pin, sets "provider": {"only": [that name], "allow_fallbacks": false} in the body of every POST to a path that ends in /chat/completions;
  - counts the tokens of every response of its run by the four kinds the runtime prices (input, output,
    cache_read, cache_write) from the "usage" the provider reports (the Anthropic Messages response, streamed or
    not; the OpenRouter chat completion, streamed or not: a streamed one reports its usage in its last chunk),
    and writes the count to the file --meter names, after each response, in a folder that only this container
    mounts: a run never sees it. A response it cannot read is counted as unknown and named there, never guessed.
    Counting never logs or keeps content: only the usage object is read out of a response as it passes;
  - answers every request to a model endpoint with 429 and a body that names the budget once the tokens counted
    reach --budget-tokens (a request already under way is not cut off: the count can pass the budget by one response);
  - passes the response through as it arrives, so a streamed answer streams, with the route's timeout
    ("timeout_seconds", the egress proxy's own) on the run's side and on the provider's;
  - logs one line per request (method, path without its query, status, bytes, milliseconds): never a
    header, never a body and never the text of an upstream error.
Egress: when HTTPS_PROXY is set (the executor sets the eval network's egress proxy), the connection to the
provider is a CONNECT tunnel through it, so the egress proxy's allow list still applies.

Usage:
  keyproxy.py --route <route-provider.json> --upstream-model <name> [--upstream-model <name> ...]
              [--model <id>] [--pin <provider>] [--run <id>] [--meter <file>] [--budget-tokens <n>]
              [--listen <address>] [--port <n>] [--upstream <https URL>] [--cafile <pem>]
The key is read from the environment variable the route names ("secret"); without it the proxy does not
start (exit 2). --upstream and --cafile put a test's stand-in in the provider's place; the executor passes
them only when its caller does, and a real run never does.
"""
import argparse
import http.client
import http.server
import json
import os
import re
import signal
import ssl
import sys
import threading
import time
import urllib.parse
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
# Hop-by-hop headers (RFC 9110, section 7.6.1), and the old proxy ones: they describe one connection.
HOP = frozenset(("connection", "keep-alive", "proxy-connection", "proxy-authenticate", "proxy-authorization", "te",
                 "trailer", "trailers", "transfer-encoding", "upgrade"))
NOT_FORWARDED = HOP | {"authorization", "host", "content-length", "expect"}
# A header that can carry a credential is never forwarded: the run holds a placeholder and the proxy adds the
# only credential a call carries. A name in the explicit set, or a name with one of these words anywhere in it,
# is dropped; every other header is forwarded unchanged, so that the call reaching the provider is the one the
# runner made, apart from its credentials. A block list and a pattern, not an allow list, by decision
# (docs/decisions.md, 2026-10-15): an allow list would change the request a runner sends whenever a runner adds a
# harmless header. The pattern leaves out "key" and "session" alone: the measured runners send a session id
# (X-Claude-Code-Session-Id, X-Session-Id, x-session-affinity, x-parent-session-id) and an idempotency key on
# every call, and none of them is a credential.
CREDENTIAL_HEADERS = frozenset(("x-api-key", "api-key", "x-goog-api-key", "anthropic-auth-token", "cookie",
                                "proxy-authorization", "authorization"))
CREDENTIAL_NAME = re.compile(r"auth|api[-_]?key|token|secret|cookie|credential|password")
NOT_RETURNED = HOP | {"content-length"}
BLOCK = 65536
USAGE_STYLES = ("anthropic-messages", "openrouter-chat")  # how a route's responses report their usage
KINDS = ("input", "output", "cache_read", "cache_write")  # the four kinds runtime/costs.py prices
BODY_LIMIT = 32 * 1024 * 1024  # the most of one non-streamed response the meter will read to find its usage
EVENT_LIMIT = 8 * 1024 * 1024  # the most of one streamed event it will hold
UNKNOWN_LISTED = 20  # the unreadable responses the meter file names one by one (the count is always whole)


class RouteError(ValueError):
    pass


class BodyError(Exception):
    def __init__(self, status, why):
        super().__init__(why)
        self.status = status


def credential_header(name):
    """True when a request header can carry a credential, by its name (the rule is above CREDENTIAL_HEADERS)."""
    name = name.lower()
    return name in CREDENTIAL_HEADERS or CREDENTIAL_NAME.search(name) is not None


def load_route(path, upstream=None):
    """The route of a provider's route file (route-<provider>.json); upstream replaces its provider (a test's
    stand-in). A route describes a provider and never a model or a pin: those come from the gate file's entry of
    the model and reach the proxy as arguments. Raises RouteError."""
    with open(path, encoding="utf-8") as f:
        route = json.load(f)
    if upstream:
        route = {**route, "upstream": upstream}
    if "provider_only" in route:
        raise RouteError("a route has no provider_only: the pin of a model is the gate file's entry of that model")
    u = urllib.parse.urlsplit(route["upstream"])
    if u.scheme != "https" or not u.hostname or u.path not in ("", "/") or u.query or u.fragment or u.username or u.password:
        raise RouteError("the upstream must be https://<host>[:<port>] with nothing after it")
    prefix = route["prefix"]
    if not (isinstance(prefix, str) and prefix.startswith("/") and prefix.endswith("/") and len(prefix) > 1):
        raise RouteError("the prefix must be a path that starts and ends with /")
    for key in ("port", "timeout_seconds", "max_body_bytes"):
        if not (isinstance(route.get(key), int) and route[key] > 0):
            raise RouteError(f"{key} must be a positive number")
    if not (isinstance(route.get("secret"), str) and route["secret"]):
        raise RouteError("secret must name the variable that holds the key")
    paths = route.get("paths")
    if not (isinstance(paths, list) and paths and all(isinstance(p, str) for p in paths)):
        raise RouteError("paths must be a non-empty list of the paths the route forwards")
    for p in paths:
        if not (allowed(p, prefix) and p != prefix and "?" not in p and not p.endswith("/")):
            raise RouteError(f"the path {p!r} must be a path under the prefix, without a query and without a trailing /")
    if route.get("usage") not in USAGE_STYLES:
        raise RouteError(f"usage must be one of {', '.join(USAGE_STYLES)}: how the provider's responses report their tokens")
    metered = route.get("metered")
    if not (isinstance(metered, list) and metered and all(p in paths for p in metered)):
        raise RouteError("metered must list the paths, among the route's paths, whose responses carry the usage to count")
    base_path = route.get("base_path")
    if base_path is not None and not (isinstance(base_path, str) and (base_path == "" or base_path.startswith("/"))):
        raise RouteError("base_path must be empty or a path that starts with /")
    return route


def allowed(target, prefix):
    """True when a request target is a path under prefix, in origin form, with no "." or ".." segment."""
    if not target.startswith(prefix) or any(c in target for c in "\\#") or any(ord(c) < 33 or ord(c) > 126 for c in target):
        return False
    path = urllib.parse.urlsplit(target).path
    for form in (path, urllib.parse.unquote(path)):
        if any(segment in (".", "..") for segment in form.split("/")):
            return False
    return True


def egress_of(value):
    """(host, port) of an http:// egress proxy URL, or None."""
    if not value:
        return None
    u = urllib.parse.urlsplit(value)
    if u.scheme != "http" or not u.hostname:
        raise RouteError("HTTPS_PROXY must be http://<host>:<port>")
    return u.hostname, u.port or 80


# --- the meter ----------------------------------------------------------------------------------------------


def whole(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def anthropic_usage(usage):
    """({kind: tokens}, None) from the usage object of an Anthropic Messages response, or (None, why). The input
    count is the provider's own: it leaves out the tokens read from and written to the cache."""
    if not isinstance(usage, dict):
        return None, "the response has no usage object"
    read, written = usage.get("cache_read_input_tokens") or 0, usage.get("cache_creation_input_tokens") or 0
    if not (whole(usage.get("input_tokens")) and whole(usage.get("output_tokens")) and whole(read) and whole(written)):
        return None, "the usage object lacks a count of input or output tokens, or holds one that is not a whole number"
    return {"input": usage["input_tokens"], "output": usage["output_tokens"], "cache_read": read, "cache_write": written}, None


def openrouter_usage(usage):
    """({kind: tokens}, None) from the usage object of an OpenRouter chat completion, or (None, why). The provider's
    prompt count includes the cached tokens, so the input is what is left after the cache reads and writes."""
    if not isinstance(usage, dict):
        return None, "the response has no usage object"
    details = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), dict) else {}
    read, written = details.get("cached_tokens") or 0, details.get("cache_write_tokens") or 0
    prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
    if not (whole(prompt) and whole(completion) and whole(read) and whole(written)):
        return None, "the usage object lacks a count of prompt or completion tokens, or holds one that is not a whole number"
    if read + written > prompt:
        return None, "the usage object counts more cached tokens than prompt tokens"
    return {"input": prompt - read - written, "output": completion, "cache_read": read, "cache_write": written}, None


class UsageReader:
    """Reads the usage out of one response as its bytes pass, keeping nothing else of it. feed() every block;
    finish() returns ({kind: tokens}, None) or (None, why). A response it cannot read (an encoding it does not
    decode, a stream that ends before its usage, a usage of another shape) is never guessed."""

    def __init__(self, style, content_type, content_encoding):
        self.style, self.problem, self.decoder = style, None, None
        kind = (content_type or "").lower()
        self.stream = "text/event-stream" in kind
        if not (self.stream or "json" in kind):
            self.problem = "the response is neither JSON nor an event stream"
        encoding = (content_encoding or "identity").strip().lower()
        if encoding in ("gzip", "x-gzip"):
            self.decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        elif encoding == "deflate":
            self.decoder = zlib.decompressobj()
        elif encoding not in ("", "identity"):
            self.problem = self.problem or "the response uses a content encoding the key proxy does not decode"
        self.buffer = bytearray()
        self.start = self.delta = self.last = None

    def feed(self, block):
        if self.problem:
            return
        try:
            data = self.decoder.decompress(block) if self.decoder else block
        except zlib.error:
            self.problem = "the response could not be decoded"
            return
        self.take(data)

    def take(self, data):
        if self.stream:
            self.buffer += data
            while True:
                end = self.buffer.find(b"\n")
                if end < 0:
                    break
                line = bytes(self.buffer[:end])
                del self.buffer[:end + 1]
                self.line(line)
            if len(self.buffer) > EVENT_LIMIT:
                self.problem = "an event of the stream is larger than the key proxy reads"
                self.buffer.clear()
        else:
            self.buffer += data
            if len(self.buffer) > BODY_LIMIT:
                self.problem = "the response is larger than the key proxy reads"
                self.buffer.clear()

    def line(self, line):
        line = line.strip()
        if not line.startswith(b"data:"):
            return
        text = line[5:].strip()
        if not text or text == b"[DONE]":
            return
        try:
            event = json.loads(text)
        except ValueError:
            return
        if not isinstance(event, dict):
            return
        if self.style == "anthropic-messages":
            kind = event.get("type")
            if kind == "message_start":
                message = event.get("message")
                self.start = message.get("usage") if isinstance(message, dict) else None
            elif kind == "message_delta" and isinstance(event.get("usage"), dict):
                self.delta = {**(self.delta or {}), **{k: v for k, v in event["usage"].items() if v is not None}}
            elif kind == "error":
                self.problem = "the stream carried an error event"
        elif isinstance(event.get("usage"), dict):
            self.last = event["usage"]

    def finish(self, complete=True):
        if self.decoder and not self.problem:
            try:
                self.take(self.decoder.flush())
            except zlib.error:
                self.problem = "the response could not be decoded"
        if self.problem:
            return None, self.problem
        if not complete:
            return None, "the response was cut off before its usage"
        convert = anthropic_usage if self.style == "anthropic-messages" else openrouter_usage
        if self.stream:
            if self.buffer:
                self.line(bytes(self.buffer))
            if self.style == "anthropic-messages":
                if not isinstance(self.start, dict) or self.delta is None:
                    return None, "the stream has no message_start or no final message_delta usage"
                return convert({**self.start, **self.delta})
            return convert(self.last) if self.last is not None else (None, "the stream has no usage in any chunk")
        try:
            body = json.loads(bytes(self.buffer))
        except ValueError:
            return None, "the response is not JSON"
        return convert(body.get("usage") if isinstance(body, dict) else None)


class Meter:
    """The count of one run: the tokens of every response by the four kinds, the responses it could not read, the
    requests it refused, and the budget. write() leaves it in the meter file after every change; the runner reads
    that file when the run ends, from a folder the run container never mounts."""

    def __init__(self, path=None, run=None, model=None, budget=None):
        self.path, self.run, self.model, self.budget = path, run, model, budget
        self.counts = {kind: 0 for kind in KINDS}
        self.responses, self.unknown, self.unknown_responses = 0, [], 0
        self.refused = {"model": 0, "budget": 0}
        self.lock = threading.Lock()
        self.failed = False

    def total(self):
        return sum(self.counts.values())

    def exhausted(self):
        return self.budget is not None and self.total() >= self.budget

    def add(self, usage):
        with self.lock:
            self.responses += 1
            for kind in KINDS:
                self.counts[kind] += usage[kind]
            self.write()

    def add_unknown(self, path, why):
        with self.lock:
            self.responses += 1
            self.unknown_responses += 1
            if len(self.unknown) < UNKNOWN_LISTED:
                self.unknown.append({"path": path[:200], "why": why})
            self.write()

    def refuse(self, kind):
        with self.lock:
            self.refused[kind] += 1
            self.write()

    def snapshot(self):
        return {"run": self.run, "model": self.model, "responses": self.responses, **self.counts, "total": self.total(),
                "unknown_responses": self.unknown_responses, "unknown": self.unknown, "refused": self.refused,
                "budget_tokens": self.budget, "budget_reached": self.exhausted()}

    def write(self):
        """The meter file, replaced whole (a reader never sees half of it). Returns False when it could not be written."""
        if not self.path:
            return True
        try:
            temporary = self.path + ".tmp"
            with open(temporary, "w", encoding="utf-8") as f:
                json.dump(self.snapshot(), f)
            os.replace(temporary, self.path)
            return True
        except OSError:
            self.failed = True
            return False


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "keyproxy"
    sys_version = ""

    def setup(self):
        self.timeout = self.server.route["timeout_seconds"]  # the run's side: a silent client is dropped
        super().setup()

    def log_message(self, format, *args):  # noqa: A002 - the base class's name
        """The base class's own lines are not written: every line this proxy writes is note()'s."""

    def note(self, status, sent, started):
        path = urllib.parse.urlsplit(self.path).path if self.path.startswith("/") else "(not a path)"
        self.server.log(f"keyproxy: {self.command} {path[:200]} {status} {sent}B {int((time.monotonic() - started) * 1000)}ms")

    def refuse(self, status, why, started, body=None, kind="text/plain; charset=utf-8"):
        body = body if body is not None else (why + "\n").encode("utf-8")
        self.send_response_only(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        self.close_connection = True
        self.note(status, len(body), started)

    def do_CONNECT(self):  # noqa: N802 - the base class's naming
        self.refuse(405, "the key proxy is not a forward proxy", time.monotonic())

    def read_body(self, limit):
        """The request body (None when the request has none), at most limit bytes."""
        encoding = (self.headers.get("Transfer-Encoding") or "").strip().lower()
        if encoding:
            if encoding != "chunked":
                raise BodyError(501, "only the chunked transfer encoding is accepted")
            data = bytearray()
            while True:
                try:
                    size = int(self.rfile.readline(1024).split(b";")[0].strip(), 16)
                except ValueError:
                    raise BodyError(400, "a chunk of the request body is malformed") from None
                if size == 0:
                    while self.rfile.readline(8192) not in (b"\r\n", b"\n", b""):
                        pass
                    return bytes(data)
                if size < 0 or len(data) + size > limit:
                    raise BodyError(413, "the request body is larger than the key proxy accepts")
                chunk = self.rfile.read(size)
                if len(chunk) != size:
                    raise BodyError(400, "the request body ended early")
                data += chunk
                self.rfile.readline(8)
        length = self.headers.get("Content-Length")
        if length is None:
            return None
        try:
            n = int(length)
        except ValueError:
            raise BodyError(400, "Content-Length is not a number") from None
        if n < 0:
            raise BodyError(400, "Content-Length is not a number")
        if n > limit:
            raise BodyError(413, "the request body is larger than the key proxy accepts")
        data = self.rfile.read(n)
        if len(data) != n:
            raise BodyError(400, "the request body ended early")
        return data

    def budget_error(self, started):
        meter = self.server.meter
        text = (f"the eval key proxy stopped this run: its budget of {meter.budget} tokens is reached "
                f"({meter.total()} counted)")
        body = json.dumps({"type": "error", "error": {"type": "rate_limit_error", "code": 429, "message": text}}).encode("utf-8")
        self.refuse(429, text, started, body=body, kind="application/json")

    def forward(self):
        started, route = time.monotonic(), self.server.route
        if not allowed(self.path, route["prefix"]):
            return self.refuse(403, f"the key proxy forwards {route['prefix']} of its one provider and nothing else", started)
        rpath = urllib.parse.urlsplit(self.path).path  # the query is not part of the path
        if rpath not in route["paths"]:
            return self.refuse(403, f"the key proxy forwards only {', '.join(route['paths'])} of its one provider", started)
        if self.command != "POST":
            return self.refuse(405, "the key proxy forwards POST only to a model endpoint", started)
        if (self.headers.get("Content-Encoding") or "identity").strip().lower() not in ("", "identity"):
            return self.refuse(415, "the key proxy reads the request body to check its model and accepts it unencoded only", started)
        try:
            body = self.read_body(route["max_body_bytes"])
        except BodyError as e:
            return self.refuse(e.status, str(e), started)
        try:
            doc = json.loads(body or b"")
            if not isinstance(doc, dict):
                raise ValueError("not an object")
        except ValueError:
            return self.refuse(400, "the key proxy could not read the request body as a JSON object", started)
        model = doc.get("model")
        if not (isinstance(model, str) and model in self.server.upstream_models):
            if self.server.meter:
                self.server.meter.refuse("model")
            return self.refuse(403, "the key proxy of this run serves one model; this request names another, or none", started)
        if self.server.meter and self.server.meter.exhausted():
            self.server.meter.refuse("budget")
            return self.budget_error(started)
        if self.server.pin and rpath.endswith("/chat/completions"):
            # The model's entry pins one upstream provider: the request says so, whatever the run asked for.
            doc["provider"] = {"only": [self.server.pin], "allow_fallbacks": False}
            body = json.dumps(doc).encode("utf-8")
        listed = {t.strip().lower() for v in self.headers.get_all("Connection") or [] for t in v.split(",")}
        headers = [(k, v) for k, v in self.headers.items()
                   if k.lower() not in NOT_FORWARDED and k.lower() not in listed and not credential_header(k)]
        conn = None
        try:
            conn = self.server.connect()
            conn.putrequest(self.command, self.path, skip_host=True, skip_accept_encoding=True)
            conn.putheader("Host", self.server.host_header)
            for k, v in headers:
                conn.putheader(k, v)
            conn.putheader("Authorization", self.server.authorization)
            if body is not None:
                conn.putheader("Content-Length", str(len(body)))
            conn.endheaders(body)
            resp = conn.getresponse()
        except (OSError, http.client.HTTPException, ValueError) as e:
            if conn:
                conn.close()
            return self.refuse(502, f"the key proxy could not reach the provider ({type(e).__name__})", started)
        reader = None
        if self.server.meter and rpath in route["metered"] and 200 <= resp.status < 300:
            reader = UsageReader(route["usage"], resp.getheader("Content-Type"), resp.getheader("Content-Encoding"))
        settled = []

        def settle(complete):
            """Count the response once, when its last byte is known and before the run is given it: a run that sends
            its next request the moment it has read this answer meets a budget that already includes it."""
            if reader is None or settled:
                return
            settled.append(complete)
            usage, why = reader.finish(complete)
            if usage is not None:
                self.server.meter.add(usage)
            else:
                self.server.meter.add_unknown(rpath, why)
        try:
            status, sent = self.relay(resp, reader, settle)
            self.note(status, sent, started)
        except (OSError, http.client.HTTPException) as e:  # the run went away, or the provider stopped mid-answer
            self.close_connection = True
            self.note(f"{resp.status} interrupted ({type(e).__name__})", 0, started)
        finally:
            conn.close()
            settle(False)  # a response that did not end is counted as one that was cut off

    def relay(self, resp, reader=None, settle=None):
        """Send the provider's answer to the run as it arrives. Returns (status, bytes of body sent). reader, when
        there is one, is shown each block on its way: what it does never delays or changes what the run receives.
        settle(True) is called once the answer has been read to its end: before the last block goes to the run when
        the length is known, before the closing chunk otherwise."""
        self.send_response_only(resp.status, resp.reason)
        for k, v in resp.getheaders():
            if k.lower() not in NOT_RETURNED:
                self.send_header(k, v)
        no_body = self.command == "HEAD" or resp.status in (204, 304) or 100 <= resp.status < 200
        length = None if resp.chunked else resp.getheader("Content-Length")
        if length is not None:
            self.send_header("Content-Length", length)
        elif not no_body:
            self.send_header("Transfer-Encoding", "chunked")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        sent = 0
        if no_body:
            return resp.status, 0
        expected = int(length) if length is not None and length.strip().isdigit() else None
        while True:
            block = resp.read1(BLOCK)
            if not block:
                break
            if reader is not None:
                try:
                    reader.feed(block)
                except Exception:  # noqa: BLE001 - counting must never break the run's answer
                    reader.problem = reader.problem or "the key proxy could not read the response"
            sent += len(block)
            if settle is not None and expected is not None and sent >= expected:
                settle(True)  # the last block: counted before the run has it
            self.wfile.write(block if length is not None else b"%x\r\n%s\r\n" % (len(block), block))
        if expected is not None and sent < expected:
            raise http.client.IncompleteRead(b"", expected - sent)
        if settle is not None:
            settle(True)  # a chunked answer ends here, before its closing chunk
        if length is None:
            self.wfile.write(b"0\r\n\r\n")
        return resp.status, sent

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = forward  # noqa: N815


class KeyProxy(http.server.ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128  # a run's runner may open many connections at once; the default backlog of 5 refuses them

    def __init__(self, address, route, key, cafile=None, egress=None, log=None, *, upstream_models, pin=None, meter=None):
        if not key or any(ord(c) < 33 or ord(c) > 126 for c in key):
            raise RouteError(f"{route['secret']} holds a character a header cannot carry")
        models = frozenset(upstream_models or ())
        if not models or not all(isinstance(m, str) and m for m in models):
            raise RouteError("the key proxy needs the names of the model it serves (upstream_models)")
        if pin is not None and not (isinstance(pin, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._/-]{0,79}", pin)):
            raise RouteError("the pin must name one upstream provider")
        self.route, self.authorization = route, "Bearer " + key
        self.upstream_models, self.pin, self.meter = models, pin, meter
        u = urllib.parse.urlsplit(route["upstream"])
        self.upstream_host, self.upstream_port, self.host_header = u.hostname, u.port or 443, u.netloc
        self.context = ssl.create_default_context(cafile=cafile)
        self.egress, self._log, self._lock = egress, log or sys.stderr, threading.Lock()
        super().__init__(address, Handler)

    def connect(self):
        """An HTTPS connection to the provider: through the egress proxy's tunnel when there is one."""
        timeout = self.route["timeout_seconds"]
        if self.egress:
            conn = http.client.HTTPSConnection(self.egress[0], self.egress[1], timeout=timeout, context=self.context)
            conn.set_tunnel(self.upstream_host, self.upstream_port)
            return conn
        return http.client.HTTPSConnection(self.upstream_host, self.upstream_port, timeout=timeout, context=self.context)

    def log(self, line):
        with self._lock:
            print(line, file=self._log, flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="keyproxy.py", description=__doc__.strip().split("\n\n")[0])
    parser.add_argument("--route", required=True, help="the provider's route file (route-<provider>.json)")
    parser.add_argument("--upstream-model", action="append", default=[], dest="upstream_models",
                        help="a model name the run may send in a request body (repeat; at least one)")
    parser.add_argument("--model", default=None, help="the run's model id, named in the meter file")
    parser.add_argument("--pin", default=None, help="the one upstream provider a chat completion is pinned to")
    parser.add_argument("--run", default=None, help="the run's id, named in the meter file")
    parser.add_argument("--meter", default=None, help="the file the count is written to after every response")
    parser.add_argument("--budget-tokens", type=int, default=None, help="answer 429 once this many tokens are counted")
    parser.add_argument("--listen", default="0.0.0.0", help="the address to listen on (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=None, help="the port to listen on (default: the route's)")
    parser.add_argument("--upstream", default=None, help="https://<host>[:<port>] in the provider's place (a test's stand-in)")
    parser.add_argument("--cafile", default=None, help="the certificates that verify the upstream (a test's stand-in)")
    args = parser.parse_args(argv)
    try:
        route = load_route(args.route, args.upstream)
        egress = egress_of(os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"))
    except (OSError, ValueError, KeyError) as e:
        print(f"keyproxy: the route is not valid: {e}", file=sys.stderr)
        return 2
    if not args.upstream_models:
        print("keyproxy: no --upstream-model: the key proxy serves one model and must be told which", file=sys.stderr)
        return 2
    if args.budget_tokens is not None and args.budget_tokens < 1:
        print("keyproxy: --budget-tokens must be a positive number", file=sys.stderr)
        return 2
    key = (os.environ.pop(route["secret"], "") or "").strip()
    if not key:
        print(f"keyproxy: {route['secret']} is not set: the key proxy holds no key and does not start", file=sys.stderr)
        return 2
    meter = Meter(args.meter, args.run, args.model, args.budget_tokens)
    if not meter.write():
        print("keyproxy: cannot write the meter file: the run's tokens could not be counted, so it does not start", file=sys.stderr)
        return 2
    try:
        server = KeyProxy((args.listen, args.port or route["port"]), route, key, args.cafile, egress,
                          upstream_models=args.upstream_models, pin=args.pin, meter=meter)
    except (OSError, ValueError) as e:
        print(f"keyproxy: cannot start: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    server.log(f"keyproxy: listening on port {server.server_address[1]}, forwarding {route['prefix']} to "
               f"{route['upstream']}" + (" through the egress proxy" if egress else ""))
    try:
        server.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
