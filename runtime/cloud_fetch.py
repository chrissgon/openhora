#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The link reader and the fetch of a shared Google Drive file (package V1d-3, decision 14, limit L70): the one place the runtime opens a socket to fetch a
recording a listed sender linked to. The operation (runtime/ops_media_cloud.py) decides who may ask, the bound and what is kept; this module only reads a link
and fetches.

  file_id(text)                        the Drive file id of the first https link in a text, or None
  download_url(fid)                    the address the shared file's bytes are asked for
  check_address(host, resolve)         the first address of a host, when every address it has is global
  connect(host, address, timeout)      an https connection that opens the address given, never a second lookup
  fetch(url, receive, cap, ...)        the file at the link, handed to `receive(response, length)`, or a CloudError

The rules of `fetch`: only the hosts of HOSTS, only `https` on port 443, no user info in a link, only global addresses (the address checked is the address
connected, so a second lookup cannot give a private one), at most three redirects and each one is checked again as the first link was, and the size is
known (a `Content-Length` within `cap`) before a byte is read. An HTML answer is a sign-in or a confirmation page: the file is not shared. Nothing here
writes a file, reads the project or keeps a link; every socket is a seam (`resolve`, `opener`) a test replaces.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import http.client
import ipaddress
import re
import socket
import ssl
import sys
import urllib.parse

HOSTS = ("drive.google.com", "docs.google.com", "drive.usercontent.google.com")      # the closed list (plan OPEN-1; the third: spec OPEN-3)
LINK_HOSTS = ("drive.google.com", "docs.google.com")                                  # the hosts a person's link may name (the third is only reached by a redirect)
FILE_ID = re.compile(r"[A-Za-z0-9_-]{10,100}")      # runtime/sources.py DRIVE_FILE_ID; a test asserts the two patterns are equal
MAX_REDIRECTS = 3
TIMEOUT = 30                                          # seconds per connect and per read
USER_AGENT = "workbench-media/1"
REDIRECTS = (301, 302, 303, 307, 308)
LINK = re.compile(r"https://\S+")
TRAILING = ".,;:!?)]}>\"'"                        # what a sentence puts after a link
FILE_PATH = re.compile(r"/file/d/([^/]+)(?:/.*)?")
CODES = ("address", "redirect", "status", "no_length", "too_large", "not_shared", "network")


class CloudError(Exception):
    """A refusal of the fetch; `code` is one of CODES. The message is the code: it never holds a link, an address or a file id."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def file_id(text):
    """The Drive file id of the first `https://` link in `text`, or None. A link counts only on https, on `drive.google.com` or `docs.google.com` (no port, no
    user info), with the path `/file/d/<id>` (or below it), or `/open` or `/uc` with the query `id=<id>`; the id must match FILE_ID."""
    if not isinstance(text, str):
        return None
    found = LINK.search(text)
    if found is None:
        return None
    try:
        parts = urllib.parse.urlsplit(found.group(0).rstrip(TRAILING))
        host, port = parts.hostname, parts.port
    except ValueError:
        return None
    if parts.scheme != "https" or host not in LINK_HOSTS or port is not None or "@" in parts.netloc:
        return None
    fid = None
    matched = FILE_PATH.fullmatch(parts.path)
    if matched:
        fid = matched.group(1)
    elif parts.path in ("/open", "/uc"):
        ids = urllib.parse.parse_qs(parts.query).get("id") or []
        fid = ids[0] if len(ids) == 1 else None
    return fid if isinstance(fid, str) and FILE_ID.fullmatch(fid) else None


def download_url(fid: str) -> str:
    """The address a shared file's bytes are asked for."""
    return "https://drive.google.com/uc?export=download&id=" + fid


def check_address(host: str, resolve) -> str:
    """The first address of `host`, when every address `resolve(host, 443, type=SOCK_STREAM)` gives is global and not multicast (a private, loopback,
    link-local, documentation or reserved one is not). No address at all, or one that is not an address, is CloudError("address")."""
    infos = resolve(host, 443, type=socket.SOCK_STREAM)
    addresses = []
    for info in infos or ():
        try:
            addresses.append(str(info[4][0]))
        except (IndexError, TypeError):
            raise CloudError("address") from None
    if not addresses:
        raise CloudError("address")
    for text in addresses:
        try:
            ip = ipaddress.ip_address(text)
        except ValueError:
            raise CloudError("address") from None
        mapped = getattr(ip, "ipv4_mapped", None)
        if mapped is not None:
            ip = mapped
        if not ip.is_global or ip.is_multicast:
            raise CloudError("address")
    return addresses[0]


class _Pinned(http.client.HTTPSConnection):
    """An https connection that opens the socket to the address it was given and checks the certificate against the host name."""

    def __init__(self, host: str, address: str, timeout: float, context):
        super().__init__(host, 443, timeout=timeout, context=context)
        self._address = address

    def connect(self):
        sock = socket.create_connection((self._address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def connect(host: str, address: str, timeout: float):
    """An HTTPSConnection to `host` whose socket is opened to `address` (the one checked, never a second lookup) and wrapped with the default context
    (certificate and host name are checked)."""
    return _Pinned(host, address, timeout, ssl.create_default_context())


def _hop(url: str, first: bool):
    """(host, target) of a link the fetch may open, else CloudError: `address` for the first link, `redirect` for a later one."""
    refused = CloudError("address" if first else "redirect")
    try:
        parts = urllib.parse.urlsplit(url)
        host, port = parts.hostname, parts.port
    except ValueError:
        raise refused from None
    if parts.scheme != "https" or host not in HOSTS or "@" in parts.netloc or port not in (None, 443):
        raise refused
    target = (parts.path or "/") + ("?" + parts.query if parts.query else "")
    return host, target


def fetch(url: str, receive, cap: int, *, resolve=socket.getaddrinfo, opener=connect) -> dict:
    """Fetch `url` and return what `receive(response, length)` returns, the length being the response's `Content-Length`, within `cap` and known before a byte
    is read. At most MAX_REDIRECTS + 1 requests, each link checked as the first was. CloudError for every refusal (see CODES); the connection is closed."""
    current = url
    for hop in range(MAX_REDIRECTS + 1):
        host, target = _hop(current, hop == 0)
        conn = None
        try:
            try:
                address = check_address(host, resolve)
                conn = opener(host, address, TIMEOUT)
                conn.request("GET", target, headers={"User-Agent": USER_AGENT, "Accept": "*/*", "Accept-Encoding": "identity"})
                response = conn.getresponse()
                status = response.status
                location = response.getheader("Location")
                kind = response.getheader("Content-Type") or ""
                size = response.getheader("Content-Length")
            except (OSError, ssl.SSLError, http.client.HTTPException):
                raise CloudError("network") from None
            if status in REDIRECTS:
                if hop == MAX_REDIRECTS or not location:
                    raise CloudError("redirect")
                current = urllib.parse.urljoin(current, location)
                continue
            if status != 200:
                raise CloudError("status")
            if kind.strip().lower().startswith("text/html"):
                raise CloudError("not_shared")
            size = (size or "").strip()
            if not (size.isascii() and size.isdigit()):
                raise CloudError("no_length")
            length = int(size)
            if length > cap:
                raise CloudError("too_large")
            try:
                return receive(response, length)
            except http.client.HTTPException:
                raise CloudError("network") from None
        finally:
            if conn is not None:
                try:
                    conn.close()
                except OSError:
                    pass
    raise CloudError("redirect")


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
