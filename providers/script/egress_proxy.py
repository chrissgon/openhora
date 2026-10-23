#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The per-step egress proxy of a project script (package P9, finding S8). One runs for one step, built from the step's hashed
declaration, and it is the only member of the script's internal network that has a way out.

  python3 /opt/script/egress_proxy.py --listen 0.0.0.0:3128 --allow <host>:<port> [--allow ...] [--max-bytes N] [--max-seconds N]
                                       [--allow-private]

What it does, and the only thing it does:

  1. At its start it RESOLVES every declared name, once, with the resolver of the network it sits on, and keeps the addresses for the
     whole life of the step. A name that does not resolve, or any of whose addresses is not a global one (loopback, link-local,
     private, carrier-grade, multicast, unspecified, reserved), ends it before it listens (`refused` on standard output, exit 3):
     a name that points at the host or at a local network is never reached. `--allow-private` turns the last rule off and exists only
     for the tests of this repository, which have no public host to call; the host module never passes it from a request, a step
     argument or a configuration.
  2. It answers `CONNECT <authority> HTTP/1.x` and nothing else (any other method: 405). It never forwards a plain HTTP request, so
     it never reads or rewrites what a script sends.
  3. A CONNECT is allowed only when its authority is, after lowercasing and dropping one trailing dot,
       - a declared name with a declared port, or
       - an IP literal that is one of the addresses frozen at the start for a declared name, with that name's port.
     Any other name is refused BY NAME (403 `undeclared`); any other IP literal is refused BY ADDRESS (403 `address`). The authority
     is compared as text and as an address object, never passed to a resolver, so a decimal, hexadecimal or octal spelling of an
     address (`2130706433`, `0x7f000001`) is an undeclared name, not a way in.
  4. An allowed CONNECT dials one of the frozen addresses (never a fresh lookup, so a name that changes its answer later changes
     nothing), answers 200, and copies bytes both ways until one side closes, an idle timeout, or the byte cap of the step.
  5. It ends by itself after `--max-seconds` (the step's time limit and a margin), so that a proxy the host could not remove (the host
     process was killed) does not outlive its step.

Every decision is one line on standard error (`allow <host>:<port>` or `deny <reason>`); the first byte of a script's traffic is never
logged. Standard library only; runs on the interpreter of the image (Python 3.11).
"""
from __future__ import annotations

import ipaddress
import os
import re
import select
import socket
import socketserver
import sys
import threading

HEAD_MAX = 8192
CONNECT_TIMEOUT = 10
IDLE_TIMEOUT = 60
MAX_CONNECTIONS = 16
DEFAULT_MAX_BYTES = 512 * 1024 * 1024
DEFAULT_MAX_SECONDS = 1800
NAME = re.compile(r"(?=.{1,253}\Z)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*")
DECLARED = re.compile(r"(?=.{1,253}\Z)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+")
TOP_LABEL = re.compile(r"[a-z][a-z0-9-]*")
REQUEST_LINE = re.compile(rb"CONNECT ([^ \r\n]{1,300}) HTTP/1\.[01]\r\n")
EXIT_REFUSED = 3


class Refused(Exception):
    """A declaration the proxy will not serve: a closed word and the declared name it is about."""

    def __init__(self, code: str, what: str):
        super().__init__(f"{code} {what}")
        self.code, self.what = code, what


def normal(host: str) -> str:
    """A host as text: lowercase, one trailing dot dropped."""
    host = host.lower()
    return host[:-1] if host.endswith(".") else host


def parse_declared(items) -> dict:
    """{(name, port)} from `host:port` words: a lowercase DNS name with at least two labels and a top label that starts with a letter (so no
    wildcard, no single-label name, no IP literal, and no decimal, hexadecimal or octal spelling of an address) and a port from 1 to 65535."""
    out = set()
    for item in items:
        host, sep, port = item.rpartition(":")
        host = normal(host)
        if not sep or not DECLARED.fullmatch(host) or not TOP_LABEL.fullmatch(host.rsplit(".", 1)[1]) or not port.isdigit() \
                or len(port) > 5 or not 1 <= int(port) <= 65535:
            raise Refused("bad_declaration", item[:80])
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise Refused("bad_declaration", item[:80])
        out.add((host, int(port)))
    if not out:
        raise Refused("bad_declaration", "none")
    return out


def public(ip) -> bool:
    """Whether an address is a public one: global, and none of the kinds `is_global` lets through (multicast, reserved, unspecified).
    An IPv4 address written as IPv6 (`::ffff:a.b.c.d`) is judged as the IPv4 address."""
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not (ip.is_multicast or ip.is_reserved or ip.is_unspecified or ip.is_loopback or ip.is_link_local
                                 or ip.is_private)


def freeze(declared, allow_private: bool = False, resolver=None) -> dict:
    """{(name, port): [address, ...]}: every declared name resolved once. Refused when a name does not resolve, or when any address of
    it is not a global one (unless allow_private)."""
    resolver = resolver or (lambda host, port: [info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)])
    frozen = {}
    for name, port in sorted(declared):
        try:
            found = sorted(set(resolver(name, port)))
        except OSError:
            raise Refused("unresolvable", name) from None
        if not found:
            raise Refused("unresolvable", name)
        for address in found:
            ip = ipaddress.ip_address(address.split("%")[0])
            if not allow_private and not public(ip):
                raise Refused("not_public", name)
        frozen[(name, port)] = found
    return frozen


def decide(authority: str, frozen: dict):
    """(allowed, reason, addresses): whether a CONNECT to `authority` (`host:port`) may be served. The reason is a closed word
    (`declared`, `address_declared`, `undeclared`, `address`, `malformed`); the addresses are the frozen ones to dial."""
    host, sep, port = authority.rpartition(":")
    if not sep or not port.isdigit() or not 1 <= int(port) <= 65535 or not host:
        return False, "malformed", []
    port = int(port)
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    host = normal(host)
    literal = None
    try:
        literal = ipaddress.ip_address(host.split("%")[0])
    except ValueError:
        pass
    if literal is not None:
        for (name, declared_port), addresses in frozen.items():
            if declared_port == port and str(literal) in [str(ipaddress.ip_address(a.split("%")[0])) for a in addresses]:
                return True, "address_declared", [str(literal)]
        return False, "address", []
    if (host, port) in frozen:
        return True, "declared", list(frozen[(host, port)])
    return False, "undeclared", []


class Budget:
    """The bytes the step may move through the proxy, counted across connections."""

    def __init__(self, cap: int):
        self.cap, self.used, self.lock = cap, 0, threading.Lock()

    def take(self, n: int) -> bool:
        with self.lock:
            self.used += n
            return self.used <= self.cap


def tunnel(client: socket.socket, remote: socket.socket, budget: Budget) -> None:
    """Copy bytes both ways until one side closes, the idle timeout passes or the budget is spent."""
    sockets = [client, remote]
    while True:
        ready, _, broken = select.select(sockets, [], sockets, IDLE_TIMEOUT)
        if broken or not ready:
            return
        for source in ready:
            data = source.recv(65536)
            if not data or not budget.take(len(data)):
                return
            (remote if source is client else client).sendall(data)


def read_head(client: socket.socket):
    """The request head (up to the blank line) or None when it is cut, too long, or followed by more bytes."""
    data = b""
    client.settimeout(IDLE_TIMEOUT)
    while b"\r\n\r\n" not in data:
        if len(data) > HEAD_MAX:
            return None
        chunk = client.recv(2048)
        if not chunk:
            return None
        data += chunk
    head, _, rest = data.partition(b"\r\n\r\n")
    return None if rest or len(head) > HEAD_MAX else head + b"\r\n\r\n"


def reply(client: socket.socket, code: int, reason: str) -> None:
    try:
        client.sendall(b"HTTP/1.1 %d %s\r\nConnection: close\r\nContent-Length: 0\r\n\r\n" % (code, reason.encode("ascii")))
    except OSError:
        pass


def make_handler(frozen: dict, budget: Budget, gate: threading.Semaphore, log):
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            client = self.request
            if not gate.acquire(blocking=False):
                reply(client, 503, "Busy")
                return
            try:
                head = read_head(client)
                if head is None:
                    reply(client, 400, "Bad Request")
                    return
                matched = REQUEST_LINE.match(head)
                if matched is None:
                    if head.startswith(b"CONNECT ") or not re.match(rb"[A-Z]{3,10} ", head):
                        reply(client, 400, "Bad Request")
                    else:
                        log("deny method")
                        reply(client, 405, "Method Not Allowed")
                    return
                authority = matched.group(1).decode("ascii", errors="replace")
                allowed, reason, addresses = decide(authority, frozen)
                if not allowed:
                    log(f"deny {reason}")
                    reply(client, 403, "Forbidden")
                    return
                port = int(authority.rpartition(":")[2])
                remote = None
                for address in addresses:
                    try:
                        remote = socket.create_connection((address, port), timeout=CONNECT_TIMEOUT)
                        break
                    except OSError:
                        continue
                if remote is None:
                    log("deny unreachable")
                    reply(client, 502, "Bad Gateway")
                    return
                log(f"allow {normal(authority.rpartition(':')[0])}:{port}")
                try:
                    client.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
                    tunnel(client, remote, budget)
                finally:
                    remote.close()
            except OSError:
                return
            finally:
                gate.release()
    return Handler


class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 32


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip(), file=sys.stdout if argv else sys.stderr)
        return 0 if argv else 2
    listen, allow, cap, private, seconds, i = "0.0.0.0:3128", [], DEFAULT_MAX_BYTES, False, DEFAULT_MAX_SECONDS, 0
    while i < len(argv):
        word = argv[i]
        if word == "--allow-private":
            private, i = True, i + 1
        elif word in ("--listen", "--allow", "--max-bytes", "--max-seconds") and i + 1 < len(argv):
            value = argv[i + 1]
            if word == "--listen":
                listen = value
            elif word == "--allow":
                allow.append(value)
            elif value.isdigit() and word == "--max-bytes":
                cap = int(value)
            elif value.isdigit():
                seconds = int(value)
            else:
                print("error: --max-bytes and --max-seconds are whole numbers", file=sys.stderr)
                return 2
            i += 2
        else:
            print(f"error: unknown argument {word[:40]!r}", file=sys.stderr)
            return 2
    host, _, port = listen.rpartition(":")
    try:
        frozen = freeze(parse_declared(allow), allow_private=private)
    except Refused as e:
        print(f"refused {e.code} {e.what}", flush=True)
        return EXIT_REFUSED
    lock = threading.Lock()

    def log(line: str) -> None:
        with lock:
            print(line, file=sys.stderr, flush=True)

    server = Server((host or "0.0.0.0", int(port)), make_handler(frozen, Budget(cap), threading.Semaphore(MAX_CONNECTIONS), log))
    ender = threading.Timer(seconds, lambda: os._exit(0))
    ender.daemon = True
    ender.start()
    print("ready " + " ".join(f"{n}:{p}={','.join(a)}" for (n, p), a in sorted(frozen.items())), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
