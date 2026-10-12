"""No network but loopback for the provider test suites: a test of a provider talks only to a stand-in service on
this machine, never to a live one (the architecture map's gap A13; until now each provider guarded only its own
base address).

Every suite's conftest.py (providers/<class>/tests/conftest.py) applies guard() to each of its tests, through an
autouse fixture: a connection, a datagram or a name lookup to an address that is not loopback raises NetworkRefused;
Unix sockets and loopback (127.0.0.0/8, ::1, `localhost`) pass. The same fixture puts a folder first on PYTHONPATH
whose sitecustomize.py (write_site(), once per session in a temporary folder) installs the guard in a provider the
test starts as a subprocess with the test's environment. A subprocess given an environment of its own is not covered: there the provider's own refusal of a
base address that is not loopback stays the guard.

Standard library only; nothing outside the provider test suites imports this file.
"""
from __future__ import annotations

import ipaddress
import os
import socket

HERE = os.path.abspath(__file__)
SITE_CODE = """\
# Written by providers/loopback_only.py: a provider a test starts reaches no network but loopback.
import importlib.util
_spec = importlib.util.spec_from_file_location("providers_loopback_only", {path!r})
_guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_guard)
_guard.install()
"""
LOCAL_NAMES = ("localhost", "localhost.")


class NetworkRefused(OSError):
    """A provider test tried to reach an address that is not loopback."""


def is_loopback(host) -> bool:
    """True for None (a passive socket), `localhost` and a loopback address, IPv4 or IPv6."""
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", errors="replace")
    host = str(host).strip("[]").split("%", 1)[0]
    if host.lower() in LOCAL_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _refuse(what: str, host) -> None:
    raise NetworkRefused(f"a provider test {what} {host!r}: only loopback is allowed (providers/loopback_only.py)")


def _check(address) -> None:
    if isinstance(address, tuple) and address and not is_loopback(address[0]):
        _refuse("reached", address[0])


def guarded(connect, connect_ex, sendto, getaddrinfo) -> dict:
    """The four guarded functions, wrapping the originals given."""
    def guarded_connect(self, address):
        _check(address)
        return connect(self, address)

    def guarded_connect_ex(self, address):
        _check(address)
        return connect_ex(self, address)

    def guarded_sendto(self, data, *args):
        _check(args[-1] if args else None)
        return sendto(self, data, *args)

    def guarded_getaddrinfo(host, *args, **kwargs):
        if not is_loopback(host):
            _refuse("looked up", host)
        return getaddrinfo(host, *args, **kwargs)

    return {"connect": guarded_connect, "connect_ex": guarded_connect_ex, "sendto": guarded_sendto,
            "getaddrinfo": guarded_getaddrinfo}


def write_site(folder: str) -> str:
    """Write folder/sitecustomize.py, which installs the guard in the process Python starts with folder on its
    PYTHONPATH. Returns folder."""
    with open(os.path.join(folder, "sitecustomize.py"), "w", encoding="utf-8") as f:
        f.write(SITE_CODE.format(path=HERE))
    return folder


def guard(monkeypatch, site: str) -> None:
    """Guard one test (undone after it by monkeypatch): this process, and the subprocesses it starts with its
    environment (site: the folder write_site() wrote)."""
    made = guarded(socket.socket.connect, socket.socket.connect_ex, socket.socket.sendto, socket.getaddrinfo)
    for name in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, name, made[name])
    monkeypatch.setattr(socket, "getaddrinfo", made["getaddrinfo"])
    paths = [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p and p != site]
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([site, *paths]))


def install() -> None:
    """Guard this whole process: what the sitecustomize.py of write_site() calls in a subprocess."""
    made = guarded(socket.socket.connect, socket.socket.connect_ex, socket.socket.sendto, socket.getaddrinfo)
    for name in ("connect", "connect_ex", "sendto"):
        setattr(socket.socket, name, made[name])
    socket.getaddrinfo = made["getaddrinfo"]
