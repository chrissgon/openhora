#!/usr/bin/env python3
"""The key proxy of the eval network: one proxy runs per route file and holds the one key that route names, so that a run never does.

evals/executor.py starts each in a container of its own, beside the egress proxy, with its key in its
environment: keyproxy.json routes the floor model's provider key, keyproxy-strong.json the strong model's.
A run container gets a placeholder in the key's variable and, in the variable its route names
("base_url_env"), the base URL of its proxy. The run's runner sends its calls there over plain HTTP, and
the proxy forwards each to the one provider host the route names, over HTTPS, with an Authorization
header made from the key it alone holds. It:
  - forwards only a request whose target is a path under the route's prefix (/api/v1/ for the floor
    model, /v1/ for the strong one), in origin form, and whose path (the query is not part of it) is one
    of the route's "paths", the model endpoints the runner uses (floor: /api/v1/chat/completions; strong:
    /v1/messages and /v1/messages/count_tokens); an absolute URL, another path, a path with a "." or ".."
    segment and CONNECT are refused, and nothing of them is forwarded;
  - never routes by the Host header: the upstream is fixed when the proxy starts;
  - removes every header that can carry a credential a run sends or makes up (Authorization,
    Proxy-Authorization, x-api-key, api-key, x-goog-api-key, anthropic-auth-token, cookie, and any header
    whose name has auth, api-key (or api_key), token, secret, cookie, credential or password in it), forwards
    every other header unchanged (a session id or an idempotency key is not a credential), and adds one Authorization of its own;
  - when the route names "provider_only", sets "provider": {"only": [that name], "allow_fallbacks": false} in the body of every POST to a path that ends in /chat/completions, and refuses a body it cannot read as a JSON object;
  - passes the response through as it arrives, so a streamed answer streams, with the route's timeout
    ("timeout_seconds", the egress proxy's own) on the run's side and on the provider's;
  - logs one line per request (method, path without its query, status, bytes, milliseconds): never a
    header, never a body and never the text of an upstream error.
Egress: when HTTPS_PROXY is set (the executor sets the eval network's egress proxy), the connection to the
provider is a CONNECT tunnel through it, so the egress proxy's allow list still applies.

Usage:
  keyproxy.py [--route <keyproxy.json>] [--listen <address>] [--port <n>] [--upstream <https URL>] [--cafile <pem>]
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

HERE = os.path.dirname(os.path.abspath(__file__))
ROUTE = os.path.join(HERE, "keyproxy.json")
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


def load_route(path=ROUTE, upstream=None):
    """The route of keyproxy.json; upstream replaces its provider (a test's stand-in). Raises RouteError."""
    with open(path, encoding="utf-8") as f:
        route = json.load(f)
    if upstream:
        route = {**route, "upstream": upstream}
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
    only = route.get("provider_only")
    if only is not None and not (isinstance(only, str) and only and all(c.isalnum() or c in " ._/-" for c in only) and len(only) <= 80):
        raise RouteError("provider_only must name one upstream provider")
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

    def refuse(self, status, why, started):
        body = (why + "\n").encode("utf-8")
        self.send_response_only(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
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

    def forward(self):
        started, route = time.monotonic(), self.server.route
        if not allowed(self.path, route["prefix"]):
            return self.refuse(403, f"the key proxy forwards {route['prefix']} of its one provider and nothing else", started)
        if urllib.parse.urlsplit(self.path).path not in route["paths"]:  # the query is not part of the path
            return self.refuse(403, f"the key proxy forwards only {', '.join(route['paths'])} of its one provider", started)
        try:
            body = self.read_body(route["max_body_bytes"])
        except BodyError as e:
            return self.refuse(e.status, str(e), started)
        only = route.get("provider_only")
        if only and self.command == "POST" and urllib.parse.urlsplit(self.path).path.endswith("/chat/completions"):
            # The route pins one upstream provider: the request says so, whatever the run asked for. A body that
            # cannot be read is refused, so that no call leaves unpinned.
            try:
                doc = json.loads(body or b"")
                if not isinstance(doc, dict):
                    raise ValueError("not an object")
            except ValueError:
                return self.refuse(400, "the key proxy pins the provider and could not read the request body as a JSON object", started)
            doc["provider"] = {"only": [only], "allow_fallbacks": False}
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
        try:
            status, sent = self.relay(resp)
            self.note(status, sent, started)
        except (OSError, http.client.HTTPException) as e:  # the run went away, or the provider stopped mid-answer
            self.close_connection = True
            self.note(f"{resp.status} interrupted ({type(e).__name__})", 0, started)
        finally:
            conn.close()

    def relay(self, resp):
        """Send the provider's answer to the run as it arrives. Returns (status, bytes of body sent)."""
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
        while True:
            block = resp.read1(BLOCK)
            if not block:
                break
            self.wfile.write(block if length is not None else b"%x\r\n%s\r\n" % (len(block), block))
            sent += len(block)
        if length is None:
            self.wfile.write(b"0\r\n\r\n")
        return resp.status, sent

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = forward  # noqa: N815


class KeyProxy(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, route, key, cafile=None, egress=None, log=None):
        if not key or any(ord(c) < 33 or ord(c) > 126 for c in key):
            raise RouteError(f"{route['secret']} holds a character a header cannot carry")
        self.route, self.authorization = route, "Bearer " + key
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
    parser.add_argument("--route", default=ROUTE, help="the route file (default: keyproxy.json beside this script)")
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
    key = (os.environ.pop(route["secret"], "") or "").strip()
    if not key:
        print(f"keyproxy: {route['secret']} is not set: the key proxy holds no key and does not start", file=sys.stderr)
        return 2
    try:
        server = KeyProxy((args.listen, args.port or route["port"]), route, key, args.cafile, egress)
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
