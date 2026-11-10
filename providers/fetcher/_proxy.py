"""The fetcher's proxy: the one container with a way out, and the network hard limit in code (principle 11).

It accepts only `CONNECT <host>:443` and tunnels to a host that is on its list, at an address that is global, whose TLS name (the
ClientHello's server_name) is that same host. What it cannot see: an HTTP Host header inside the encrypted stream (a front behind a
shared suffix) and an encrypted inner ClientHello; the narrow suffixes of the platform's fetch file are the guard there.

  - the host: lowercased, then matched against HOST_RE (no IP literal, no trailing dot, at most 253 characters) BEFORE the list check;
    the list is exact names (`--allow-host`) and suffixes that start with a dot (`--allow-suffix`);
  - the address: every address the name resolves to must be global and not multicast, and none may be NAT64, 6to4 or an IPv4-mapped
    private address; the proxy connects to the address it checked (no second lookup);
  - the TLS name: after the 200, the first TLS record of the client (at most 16 KiB, 10 s) is read, its server_name is compared with the
    CONNECT host, and the record is then forwarded; absent or different closes the tunnel;
  - bounds: at most MAX_TUNNELS tunnels, `--max-bytes` for the whole run (both directions), `--deadline` (an epoch), IDLE_SECONDS idle
    per tunnel; the host asks it to end by creating the file `stop` in the folder of `--out`.

On exit it writes `proxy.json` in that folder: counts and at most 50 host names that matched HOST_RE, never a path or a byte of content.
It writes the file `ready` when it listens. Standard library only; run by `_fetcher_inner.py proxy` inside the container.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import struct
import threading
import time

HOST_RE = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+")
MAX_HOST = 253
MAX_TUNNELS = 8
IDLE_SECONDS = 30
HEADER_SECONDS = 10
MAX_HEADER = 8192
MAX_RECORD = 16384
MAX_REFUSED_HOSTS = 50
REFUSED_NETWORKS = tuple(ipaddress.ip_network(n) for n in ("64:ff9b::/96", "64:ff9b:1::/48", "2002::/16"))


def host_ok(host: str) -> bool:
    """The closed shape of a host name: lowercase letters, digits and hyphens in dotted labels, at least two labels, no IP literal."""
    if not isinstance(host, str) or len(host) > MAX_HOST or not HOST_RE.fullmatch(host):
        return False
    return not host.rsplit(".", 1)[1].isdigit()     # a top label of digits only is an IPv4 literal


def host_listed(host: str, hosts, suffixes) -> bool:
    """`host` (already lowercase and host_ok) is an exact name of `hosts` or ends with one of `suffixes` (each starts with a dot)."""
    return host in hosts or any(s.startswith(".") and host.endswith(s) and len(host) > len(s) for s in suffixes)


def address_ok(text: str) -> bool:
    """True for a global unicast address that is not NAT64, 6to4 or an IPv4-mapped private address."""
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return False
    if ip.version == 6:
        if any(ip in net for net in REFUSED_NETWORKS):
            return False
        if ip.ipv4_mapped is not None:
            return address_ok(str(ip.ipv4_mapped))
    if ip.is_multicast or ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified:
        return False
    return bool(ip.is_global)


def parse_connect(head: bytes):
    """(host, port) of a request whose first line is `CONNECT host:port HTTP/1.x`, else None. The host is lowercased."""
    try:
        line = head.split(b"\r\n", 1)[0].decode("ascii")
    except UnicodeDecodeError:
        return None
    parts = line.split(" ")
    if len(parts) != 3 or parts[0] != "CONNECT" or not parts[2].startswith("HTTP/1."):
        return None
    host, _, port = parts[1].rpartition(":")
    if not host or not port.isdigit():
        return None
    return host.lower(), int(port)


def parse_sni(record: bytes):
    """The server_name of a ClientHello held whole in one TLS record, lowercased, or None when there is none or the record is not one."""
    try:
        if len(record) < 9 or record[0] != 0x16 or record[5] != 0x01:
            return None
        pos = 5 + 4 + 2 + 32                                  # record header, handshake header, client_version, random
        pos += 1 + record[pos]                                # session id
        pos += 2 + struct.unpack(">H", record[pos:pos + 2])[0]  # cipher suites
        pos += 1 + record[pos]                                # compression methods
        end = pos + 2 + struct.unpack(">H", record[pos:pos + 2])[0]
        pos += 2
        while pos + 4 <= end:
            kind, size = struct.unpack(">HH", record[pos:pos + 4])
            pos += 4
            if kind == 0:
                data = record[pos:pos + size]
                length = struct.unpack(">H", data[0:2])[0]
                if data[2] == 0 and len(data) >= 5:
                    name_len = struct.unpack(">H", data[3:5])[0]
                    return data[5:5 + name_len].decode("ascii").lower() if length >= 3 and name_len else None
                return None
            pos += size
    except (IndexError, struct.error, UnicodeDecodeError):
        return None
    return None


def _default_resolve(host: str):
    return sorted({info[4][0] for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})


def _default_connect(address: str, port: int, timeout: float):
    return socket.create_connection((address, port), timeout=timeout)


class Proxy:
    """One run of the proxy. `resolve(host) -> [address]` and `connect(address, port, timeout) -> socket` are seams for the tests."""

    def __init__(self, hosts, suffixes, max_bytes, deadline, out_dir, port=8888, bind="0.0.0.0", resolve=None, connect=None, clock=None):
        self.hosts = {h.lower() for h in hosts}
        self.suffixes = [s.lower() for s in suffixes]
        self.max_bytes, self.deadline, self.out_dir = int(max_bytes), float(deadline), out_dir
        self.resolve, self.connect, self.clock = resolve or _default_resolve, connect or _default_connect, clock or time.time
        self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(MAX_TUNNELS)
        self.allowed = self.refused = self.sni_refused = self.bytes = 0
        self.refused_hosts = []
        self.sockets = set()
        self.threads = []
        self.over = threading.Event()
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind((bind, port))
        self.listener.listen(16)
        self.port = self.listener.getsockname()[1]

    # --- accounting -----------------------------------------------------------------------------------------------------

    def _refuse(self, host=None, sni=False):
        with self.lock:
            self.refused += 1
            self.sni_refused += 1 if sni else 0
            if isinstance(host, str) and host_ok(host) and host not in self.refused_hosts and len(self.refused_hosts) < MAX_REFUSED_HOSTS:
                self.refused_hosts.append(host)

    def _count(self, n: int) -> bool:
        with self.lock:
            self.bytes += n
            if self.bytes > self.max_bytes:
                self.over.set()
            return not self.over.is_set()

    def _track(self, sock, add: bool):
        with self.lock:
            (self.sockets.add if add else self.sockets.discard)(sock)

    # --- one connection ---------------------------------------------------------------------------------------------------

    def _read_head(self, conn) -> bytes:
        conn.settimeout(HEADER_SECONDS)
        head = b""
        began = time.monotonic()
        while b"\r\n\r\n" not in head:
            if len(head) > MAX_HEADER or time.monotonic() - began > HEADER_SECONDS:
                return b""
            chunk = conn.recv(1024)
            if not chunk:
                return b""
            head += chunk
        return head

    def _read_record(self, conn):
        """The first TLS record the client sends, whole (header and body), at most 16 KiB; None when it is not one."""
        conn.settimeout(HEADER_SECONDS)
        header = b""
        while len(header) < 5:
            chunk = conn.recv(5 - len(header))
            if not chunk:
                return None
            header += chunk
        length = struct.unpack(">H", header[3:5])[0]
        if header[0] != 0x16 or length > MAX_RECORD:
            return None
        body = b""
        while len(body) < length:
            chunk = conn.recv(length - len(body))
            if not chunk:
                return None
            body += chunk
        return header + body

    def _pump(self, a, b):
        a.settimeout(IDLE_SECONDS)
        try:
            while not self.over.is_set() and self.clock() < self.deadline:
                data = a.recv(65536)
                if not data or not self._count(len(data)):
                    break
                b.sendall(data)
        except OSError:
            pass
        finally:
            for s in (a, b):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def _tunnel(self, conn):
        upstream = None
        try:
            head = self._read_head(conn)
            target = parse_connect(head) if head else None
            if target is None:
                conn.sendall(b"HTTP/1.1 405 Method Not Allowed\r\nConnection: close\r\n\r\n")
                return self._refuse()
            host, port = target
            if port != 443 or not host_ok(host) or not host_listed(host, self.hosts, self.suffixes):
                conn.sendall(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
                return self._refuse(host)
            try:
                addresses = self.resolve(host)
            except OSError:
                addresses = []
            if not addresses or not all(address_ok(a) for a in addresses):
                conn.sendall(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
                return self._refuse(host)
            for address in addresses:
                try:
                    upstream = self.connect(address, 443, 15)
                    break
                except OSError:
                    continue
            if upstream is None:
                conn.sendall(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
                return None
            self._track(upstream, True)
            conn.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            record = self._read_record(conn)
            if record is None or parse_sni(record) != host:
                return self._refuse(host, sni=True)
            with self.lock:
                self.allowed += 1
            if not self._count(len(record)):
                return None
            upstream.sendall(record)
            other = threading.Thread(target=self._pump, args=(upstream, conn), daemon=True)
            other.start()
            self._pump(conn, upstream)
            other.join(2)
        except OSError:
            pass
        finally:
            for s in (conn, upstream):
                if s is not None:
                    self._track(s, False)
                    try:
                        s.close()
                    except OSError:
                        pass
            self.slots.release()

    # --- the run ------------------------------------------------------------------------------------------------------------

    def _stop_requested(self) -> bool:
        return os.path.exists(os.path.join(self.out_dir, "stop"))

    def serve(self) -> None:
        """Listen until the deadline, the byte cap or the stop file; then close every tunnel and write proxy.json."""
        self.listener.settimeout(0.2)
        with open(os.path.join(self.out_dir, "ready"), "w") as f:
            f.write("1")
        try:
            while self.clock() < self.deadline and not self.over.is_set() and not self._stop_requested():
                try:
                    conn, _ = self.listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not self.slots.acquire(blocking=False):
                    self._refuse()
                    conn.close()
                    continue
                self._track(conn, True)
                thread = threading.Thread(target=self._tunnel, args=(conn,), daemon=True)
                self.threads.append(thread)
                thread.start()
        finally:
            self.close()

    def close(self) -> None:
        self.over.set()
        try:
            self.listener.close()
        except OSError:
            pass
        with self.lock:
            open_sockets = list(self.sockets)
        for s in open_sockets:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        for thread in self.threads:
            thread.join(2)
        self.write_report()

    def report(self) -> dict:
        with self.lock:
            return {"allowed": self.allowed, "refused": self.refused, "refused_hosts": list(self.refused_hosts),
                    "sni_refused": self.sni_refused, "bytes": self.bytes}

    def write_report(self) -> None:
        tmp = os.path.join(self.out_dir, "proxy.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.report(), f)
        os.replace(tmp, os.path.join(self.out_dir, "proxy.json"))
