"""The closed-host fetch of the class `stock:media` (package V9b-1, decision D4): the one place a stock provider opens a socket.

The provider's own standard-library code calls its library's API host and downloads from the media hosts its source file lists. Nothing here
decodes what it downloads: bytes go to a file and into a hash. The rules, each with a test:

  * https on port 443 only, no user info, no proxy variable read (http.client reads none and nothing here adds one), no cookie jar;
  * the host is checked against the source file's list, after the host-name regex and before any lookup;
  * every address the host resolves to is global (private, loopback, link-local, NAT64, 6to4, Teredo and IPv4-mapped private are refused);
  * the connection opens the address that was checked, never a second lookup;
  * a request that carries a credential (the API) follows no redirect; a download follows at most one, only to a host of `redirect_hosts`;
  * a download's `Content-Length` is known and under the cap before a byte is read; the partial file is removed on any failure.

An error here is a NetError whose message is its code: it never holds a URL, a query, an address or a key. Every socket and the clock are seams
(SEAMS) that a test replaces. Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import time
import urllib.parse

HOST_RE = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+")   # the same expression as the reference fetcher's proxy
MAX_HOST = 253
MAX_REDIRECTS = 1
USER_AGENT = "openhora-stock/1"
REDIRECTS = (301, 302, 303, 307, 308)
CHUNK = 64 * 1024
CODES = ("host_refused", "address_refused", "redirect_refused", "status", "no_length", "too_large", "type_refused", "rate_limited", "network",
         "out_refused")
SIGNATURES = {"image/png": lambda b: b.startswith(b"\x89PNG\r\n\x1a\n"), "image/jpeg": lambda b: b.startswith(b"\xff\xd8\xff"),
              "video/mp4": lambda b: len(b) >= 12 and b[4:8] == b"ftyp"}      # a check of the first bytes against the declared type; nothing is decoded
EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "video/mp4": "mp4"}
NAT64 = ipaddress.ip_network("64:ff9b::/96")
MARKER = ".openhora-reference"      # a reference store's marker file; a test reads runtime/references.py as text and compares

# The seams a test replaces: the name lookup, the connection opener and the clock.
SEAMS = {"resolve": socket.getaddrinfo, "opener": None, "clock": time.monotonic}


class NetError(Exception):
    """A refusal; `code` is one of CODES. The message is the code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def valid_host(host) -> bool:
    """A host name: HOST_RE (lower case, no trailing dot), at most 253 characters, and not an IP literal (its last label is not all digits)."""
    return (isinstance(host, str) and len(host) <= MAX_HOST and bool(HOST_RE.fullmatch(host)) and not host.rsplit(".", 1)[-1].isdigit())


def check_host(host, allowed) -> str:
    """The lower-case host when it matches HOST_RE (no IP literal, no trailing dot, at most 253 characters) and is in `allowed`; else host_refused.
    Called before any lookup."""
    if not isinstance(host, str) or len(host) > MAX_HOST:
        raise NetError("host_refused")
    host = host.lower()
    if not valid_host(host) or host not in [h.lower() for h in allowed or ()]:
        raise NetError("host_refused")
    return host


def _embedded_v4(ip):
    """The IPv4 address an IPv6 one carries (mapped, NAT64 64:ff9b::/96, 6to4 2002::/16), else None."""
    if ip.version != 6:
        return None
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    value = int(ip)
    if ip in NAT64:
        return ipaddress.IPv4Address(value & 0xFFFFFFFF)
    if value >> 112 == 0x2002:
        return ipaddress.IPv4Address((value >> 80) & 0xFFFFFFFF)
    return None


def _global(ip) -> bool:
    inner = _embedded_v4(ip)
    if inner is not None:
        ip = inner
    return bool(ip.is_global) and not ip.is_multicast


def check_address(host: str, resolve=None) -> str:
    """The first address of `host`, when every address `resolve(host, 443, type=SOCK_STREAM)` gives is global. None, or one that is not an address,
    is address_refused."""
    resolve = resolve or SEAMS["resolve"]
    try:
        infos = resolve(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        raise NetError("network") from None
    addresses = []
    for info in infos or ():
        try:
            addresses.append(str(info[4][0]))
        except (IndexError, TypeError):
            raise NetError("address_refused") from None
    if not addresses:
        raise NetError("address_refused")
    for text in addresses:
        try:
            ip = ipaddress.ip_address(text.split("%", 1)[0])
        except ValueError:
            raise NetError("address_refused") from None
        if not _global(ip):
            raise NetError("address_refused")
    return addresses[0]


class _Pinned(http.client.HTTPSConnection):
    """An https connection that opens the socket to the address it was given and checks the certificate against the host name."""

    def __init__(self, host: str, address: str, timeout: float, context=None):
        super().__init__(host, 443, timeout=timeout, context=context or ssl.create_default_context())
        self._address = address

    def connect(self):
        sock = socket.create_connection((self._address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def connect(host: str, address: str, timeout: float):
    """An HTTPSConnection to `host` whose socket is opened to `address` (the one checked) and wrapped with the default context."""
    return _Pinned(host, address, timeout)


def split_url(url, allowed, code="host_refused"):
    """(host, target) of an https URL whose host is in `allowed`; NetError(code) for any other scheme, a port, user info or a host off the list."""
    refused = NetError(code)
    if not isinstance(url, str) or len(url) > 4096:
        raise refused
    try:
        parts = urllib.parse.urlsplit(url)
        host, port = parts.hostname, parts.port
    except ValueError:
        raise refused from None
    if parts.scheme != "https" or not host or "@" in parts.netloc or port not in (None, 443):
        raise refused
    try:
        host = check_host(host, allowed)
    except NetError:
        raise refused from None
    return host, (parts.path or "/") + ("?" + parts.query if parts.query else ""), parts.path or "/"


def _open(host: str, headers: dict, target: str, timeout: float, resolve, opener):
    """Check the address, connect to it and send one GET; returns (connection, response). Network trouble is NetError('network')."""
    address = check_address(host, resolve)
    conn = (opener or SEAMS["opener"] or connect)(host, address, timeout)
    try:
        sent = {"User-Agent": USER_AGENT, "Accept": "*/*", "Accept-Encoding": "identity"}
        sent.update(headers or {})
        conn.request("GET", target, headers=sent)
        return conn, conn.getresponse()
    except (OSError, ssl.SSLError, http.client.HTTPException, ValueError):      # a library's own text can hold the value of a header: nothing of it is kept
        _close(conn)
        raise NetError("network") from None
    except BaseException:
        _close(conn)
        raise


def _close(conn):
    try:
        conn.close()
    except (OSError, AttributeError):
        pass


def _left(deadline, clock) -> float:
    left = deadline - clock()
    if left <= 0:
        raise NetError("network")
    return left


def get_json(url: str, headers: dict, cap: int, secret_in_url: bool = False, *, allowed_hosts, timeout: float = 15.0, resolve=None,
             opener=None) -> object:
    """The JSON answer of one API call: https, a host of `allowed_hosts`, no redirect (the request may carry a credential), the answer at most
    `cap` bytes (read up to cap + 1, no `Content-Length` needed). 429 is rate_limited, any other status but 200 is `status`. `secret_in_url` says the
    URL holds a key: nothing about it is ever put in an error. Returns the parsed JSON."""
    clock = SEAMS["clock"]
    deadline = clock() + timeout
    host, target, _ = split_url(url, allowed_hosts)
    conn, response = _open(host, headers, target, _left(deadline, clock), resolve, opener)
    try:
        status = response.status
        if status == 429:
            raise NetError("rate_limited")
        if status in REDIRECTS:
            raise NetError("redirect_refused")
        if status != 200:
            raise NetError("status")
        size = (response.getheader("Content-Length") or "").strip()
        if size.isascii() and size.isdigit() and int(size) > cap:
            raise NetError("too_large")
        try:
            body = response.read(cap + 1)
        except (OSError, ssl.SSLError, http.client.HTTPException):
            raise NetError("network") from None
        if len(body) > cap:
            raise NetError("too_large")
        _left(deadline, clock)
        try:
            return json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise NetError("status") from None
    finally:
        _close(conn)


def download(url: str, cap: int, dest: str, types, *, allowed_hosts, redirect_hosts=(), path_pattern=None, timeout: float = 60.0, resolve=None,
             opener=None) -> dict:
    """Download one file from a media host into `dest`'s folder, as `dest` + the extension of its type, and return {"file", "bytes", "sha256",
    "type"}. The first URL's host is in `allowed_hosts` and its path fullmatches `path_pattern` (a compiled regular expression); at most one
    redirect, to a host of `redirect_hosts`. The response is 200, its `Content-Type` (parameters dropped) is one of `types`, its `Content-Length`
    is known and at most `cap`, the body is exactly that long and begins with the signature of its type. The file is written 0600 under a temporary
    name and renamed; a failure removes it. No key is sent."""
    clock = SEAMS["clock"]
    deadline = clock() + timeout
    folder = os.path.dirname(dest)
    host, target, path = split_url(url, allowed_hosts)
    if path_pattern is not None and not path_pattern.fullmatch(path):
        raise NetError("host_refused")
    redirects = 0
    while True:
        conn, response = _open(host, {}, target, _left(deadline, clock), resolve, opener)
        try:
            status = response.status
            if status in REDIRECTS:
                location = response.getheader("Location")
                if redirects >= MAX_REDIRECTS or not location:
                    raise NetError("redirect_refused")
                redirects += 1
                host, target, _ = split_url(urllib.parse.urljoin("https://%s%s" % (host, target), location), redirect_hosts, "redirect_refused")
                continue
            return _save(conn, response, cap, dest, folder, types, deadline, clock)
        finally:
            _close(conn)


def _save(conn, response, cap, dest, folder, types, deadline, clock) -> dict:
    if response.status == 429:
        raise NetError("rate_limited")
    if response.status != 200:
        raise NetError("status")
    kind = (response.getheader("Content-Type") or "").split(";", 1)[0].strip().lower()
    if kind not in types or kind not in EXTENSIONS:
        raise NetError("type_refused")
    size = (response.getheader("Content-Length") or "").strip()
    if not (size.isascii() and size.isdigit()):
        raise NetError("no_length")
    length = int(size)
    if length > cap:
        raise NetError("too_large")
    temp = os.path.join(folder, ".part-%s" % hashlib.sha256(os.urandom(16)).hexdigest()[:16])
    final = dest + "." + EXTENSIONS[kind]
    digest, total, head = hashlib.sha256(), 0, b""
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except OSError:
        raise NetError("out_refused") from None
    try:
        with os.fdopen(fd, "wb") as handle:
            while True:
                _left(deadline, clock)
                try:
                    block = response.read(min(CHUNK, cap + 1 - total))
                except (OSError, ssl.SSLError, http.client.HTTPException):
                    raise NetError("network") from None
                if not block:
                    break
                total += len(block)
                if total > cap or total > length:
                    raise NetError("too_large")
                if len(head) < 16:
                    head = (head + block)[:16]
                digest.update(block)
                handle.write(block)
        if total != length:
            raise NetError("network")
        if not SIGNATURES[kind](head):
            raise NetError("type_refused")
        os.replace(temp, final)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise
    return {"file": final, "bytes": total, "sha256": digest.hexdigest(), "type": kind}


def reference_folder(path: str) -> bool:
    """True when `path` (real) or any folder above it holds a regular file named MARKER: a path inside a reference store."""
    import stat as _stat
    here = os.path.realpath(path)
    while True:
        try:
            if _stat.S_ISREG(os.lstat(os.path.join(here, MARKER)).st_mode):
                return True
        except OSError:
            pass
        parent = os.path.dirname(here)
        if parent == here:
            return False
        here = parent


def check_out(path) -> str:
    """The folder a verb may write into: a real folder (not a link), this user's, closed to the group and others, not inside a reference store; else
    out_refused."""
    import stat as _stat
    if not isinstance(path, str) or not path:
        raise NetError("out_refused")
    try:
        info = os.lstat(path)
    except OSError:
        raise NetError("out_refused") from None
    if not _stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077 or not info.st_mode & 0o700 == 0o700:
        raise NetError("out_refused")
    if reference_folder(path):
        raise NetError("out_refused")
    return os.path.abspath(path)
