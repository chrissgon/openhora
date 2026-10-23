#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""model:text over HTTP: one chat-completions request, one reply.

The runtime sends one JSON object on standard input and reads one JSON object on standard output. This
provider holds no prompt, no route table and no key of its own: the key arrives in the child's environment as
MODEL_TEXT_KEY, the route arrives in the request, and a route runs only when the sha256 of its canonical form
is in the request's `accepted` list.

Usage:
  chat-http.py --help
  chat-http.py --check                  exit 0 when MODEL_TEXT_KEY is set (no network), else exit 3 (E_KEY)
  chat-http.py complete [--dry-run]     read one request on standard input, print one reply

The request (version 1), one JSON object:
  {"v": 1,
   "route": {"id", "base_url", "model", "pin": str|null, "allow_fallbacks": false, "data_collection": "deny",
             "zdr": bool, "cache_breakpoint": bool},
   "accepted": [sha256 of a route, ...],
   "key_prefix": str,
   "params": {"temperature": number, "max_tokens": int, "reasoning": "off"|"on"},
   "system": str, "user": str, "deadline_ms": int}
The sha256 is over json.dumps(route, ensure_ascii=False, sort_keys=True, separators=(",", ":")) in UTF-8.
`key_prefix` (4 to 32 printable characters) is the start every key of this service has: the caller sends it, this provider names
no vendor. A MODEL_TEXT_KEY that does not start with it is refused before any connection (E_KEY, exit 3), so a credential of
another service never reaches this one. It is not part of the route, of the route's hash or of the request body sent upstream.

The reply on standard output (exit 0):
  {"v": 1, "text", "finish": "stop"|"length"|"other",
   "usage": {"input", "output", "cache_read", "cache_write"} (each an int or null),
   "latency_ms": int, "upstream": the provider that served it, lower case, or null}
With --dry-run: {"would": {"method", "url", "body"}, "would_sha256"}; no key is read and no connection is made.

Refused before any connection (exit 3, E_ROUTE): a route whose hash is not in `accepted`; a base_url that is not
https (an http loopback address is accepted only when MODEL_TEXT_LOOPBACK_TEST=1, for the test stand-in);
allow_fallbacks other than false; data_collection other than "deny". No redirect is followed.

On failure the only output is one line on standard error, `chat-http: <CODE>`: no request, no reply body, no
URL and no key is ever printed, not even inside an exception. Codes and exits:
  E_USAGE 2 | E_KEY 3, E_ROUTE 3 | E_TIMEOUT, E_NETWORK, E_RATE (429), E_UPSTREAM (5xx), E_HTTP (any other status),
  E_PIN (the reply names another provider than the pin, or a `model` that does not start with the route's model), E_RESPONSE (not JSON, over 65,536 bytes, no text), E_INTERNAL: 1.

Standard library only; runs on Python 3.9.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import signal
import socket
import ssl
import sys
import time
from urllib.parse import urlsplit

SERVES = "model:text"
VERBS = ("complete",)      # read as text by scripts/architecture_tables.py; --check and --help are flags
KEY_VARIABLE = "MODEL_TEXT_KEY"
LOOPBACK_VARIABLE = "MODEL_TEXT_LOOPBACK_TEST"
LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")
MAX_REQUEST_BYTES = 1048576        # the request on standard input
MAX_RESPONSE_BYTES = 65536
MAX_DEADLINE_MS = 600000
MAX_TOKENS_LIMIT = 32768
ROUTE_KEYS = ("id", "base_url", "model", "pin", "allow_fallbacks", "data_collection", "zdr", "cache_breakpoint")
REQUEST_KEYS = ("v", "route", "accepted", "key_prefix", "params", "system", "user", "deadline_ms")
KEY_PREFIX_LENGTH = (4, 32)
EXITS = {"E_USAGE": 2, "E_KEY": 3, "E_ROUTE": 3}


class Fail(Exception):
    """A failure that is only a code: nothing else of it is ever printed."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def canonical(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_of(obj) -> str:
    return hashlib.sha256(canonical(obj)).hexdigest()


def is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def read_request() -> dict:
    raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    if len(raw) > MAX_REQUEST_BYTES:
        raise Fail("E_USAGE")
    try:
        req = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise Fail("E_USAGE") from None
    if not isinstance(req, dict) or set(req) != set(REQUEST_KEYS) or req["v"] != 1 or not is_int(req["v"]):
        raise Fail("E_USAGE")
    route, params = req["route"], req["params"]
    if not isinstance(route, dict) or set(route) != set(ROUTE_KEYS):
        raise Fail("E_USAGE")
    ok = (all(isinstance(route[k], str) and route[k] for k in ("id", "base_url", "model", "data_collection"))
          and (route["pin"] is None or (isinstance(route["pin"], str) and route["pin"]))
          and all(isinstance(route[k], bool) for k in ("allow_fallbacks", "zdr", "cache_breakpoint")))
    ok = ok and isinstance(req["accepted"], list) and all(isinstance(x, str) for x in req["accepted"])
    prefix = req["key_prefix"]
    ok = ok and isinstance(prefix, str) and KEY_PREFIX_LENGTH[0] <= len(prefix) <= KEY_PREFIX_LENGTH[1] and prefix.isprintable()
    ok = ok and isinstance(params, dict) and set(params) == {"temperature", "max_tokens", "reasoning"}
    ok = ok and is_number(params["temperature"]) and 0 <= params["temperature"] <= 2
    ok = ok and is_int(params["max_tokens"]) and 1 <= params["max_tokens"] <= MAX_TOKENS_LIMIT
    ok = ok and params["reasoning"] in ("off", "on")
    ok = ok and isinstance(req["system"], str) and isinstance(req["user"], str)
    ok = ok and is_int(req["deadline_ms"]) and 1 <= req["deadline_ms"] <= MAX_DEADLINE_MS
    if not ok:
        raise Fail("E_USAGE")
    try:
        (req["system"] + req["user"]).encode("utf-8")      # a lone surrogate cannot be sent: refused here, as a usage error
    except UnicodeEncodeError:
        raise Fail("E_USAGE") from None
    return req


def check_route(route: dict, accepted) -> tuple:
    """Refuse a route that was not accepted or that widens what the person agreed to. Returns (loopback, host, port, base path)."""
    if sha256_of(route) not in accepted:
        raise Fail("E_ROUTE")
    if route["allow_fallbacks"] is not False or route["data_collection"] != "deny":
        raise Fail("E_ROUTE")
    try:
        parts = urlsplit(route["base_url"])
        host, port = parts.hostname, parts.port
    except ValueError:
        raise Fail("E_ROUTE") from None
    if not host or parts.username is not None or parts.password is not None or parts.query or parts.fragment:
        raise Fail("E_ROUTE")
    loopback = parts.scheme == "http" and os.environ.get(LOOPBACK_VARIABLE) == "1" and host in LOOPBACK_HOSTS
    if parts.scheme != "https" and not loopback:
        raise Fail("E_ROUTE")
    return loopback, host, port, parts.path.rstrip("/")


def build_body(req: dict) -> dict:
    route, params = req["route"], req["params"]
    system = {"role": "system", "content": req["system"]}
    if route["cache_breakpoint"]:
        system["content"] = [{"type": "text", "text": req["system"], "cache_control": {"type": "ephemeral"}}]
    # The provider object is always sent: the "no data kept" and "no other provider" limits do not depend on a pin.
    provider = {"allow_fallbacks": False, "data_collection": "deny", "zdr": route["zdr"]}
    if route["pin"]:
        provider["order"] = [route["pin"]]
    body = {"model": route["model"], "messages": [system, {"role": "user", "content": req["user"]}],
            "temperature": params["temperature"], "max_tokens": params["max_tokens"], "stream": False,
            "provider": provider, "usage": {"include": True}}
    if params["reasoning"] == "off":
        body["reasoning"] = {"enabled": False}
    return body


def finish_of(value) -> str:
    return value if value in ("stop", "length") else "other"


def count(obj, *path):
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj if is_int(obj) else None


def post(req: dict, loopback: bool, host: str, port, base: str) -> dict:
    key = os.environ.get(KEY_VARIABLE, "")
    if not key or not key.isprintable() or any(c.isspace() for c in key) or not key.startswith(req["key_prefix"]):
        raise Fail("E_KEY")        # before any connection: a key of another service is never sent here
    start = time.monotonic()
    deadline = start + req["deadline_ms"] / 1000.0

    def remaining() -> float:
        left = deadline - time.monotonic()
        if left <= 0:
            raise Fail("E_TIMEOUT")
        return left

    data = json.dumps(build_body(req), ensure_ascii=False).encode("utf-8")      # a lone surrogate was refused at read_request
    headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json", "Accept": "application/json",
               "Content-Length": str(len(data))}
    conn = None
    fired = []
    armed = hasattr(signal, "setitimer")
    if armed:     # a hard deadline for the whole exchange: a service that sends a byte at a time cannot keep the call past it
        def on_deadline(signum, frame):
            fired.append(True)
            raise Fail("E_TIMEOUT")
        previous = signal.signal(signal.SIGALRM, on_deadline)
        signal.setitimer(signal.ITIMER_REAL, req["deadline_ms"] / 1000.0)
    try:
        if loopback:
            conn = http.client.HTTPConnection(host, port, timeout=remaining())
        else:
            conn = http.client.HTTPSConnection(host, port, timeout=remaining(), context=ssl.create_default_context())
        conn.request("POST", base + "/chat/completions", body=data, headers=headers)
        sock = conn.sock          # kept here: http.client drops conn.sock when the server closes the connection
        sock.settimeout(remaining())
        resp = conn.getresponse()
        status = resp.status
        if status == 429:
            raise Fail("E_RATE")
        if status >= 500:
            raise Fail("E_UPSTREAM")
        if status != 200:     # any other status, a redirect included, is final: no redirect is followed and no body is read
            raise Fail("E_HTTP")
        chunks, size = [], 0
        while True:
            sock.settimeout(remaining())
            chunk = resp.read(8192)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise Fail("E_RESPONSE")
            chunks.append(chunk)
    except Fail:
        raise
    except (socket.timeout, TimeoutError):
        raise Fail("E_TIMEOUT") from None
    except (OSError, http.client.HTTPException, ssl.SSLError, ValueError, AttributeError):
        raise Fail("E_TIMEOUT" if fired else "E_NETWORK") from None
    finally:
        if armed:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)
        if conn is not None:
            try:
                conn.close()
            except Exception:   # noqa: BLE001 - closing must never replace the code
                pass
    return {"raw": b"".join(chunks), "latency_ms": int((time.monotonic() - start) * 1000)}


def parse_reply(raw: bytes, latency_ms: int, pin, model) -> dict:
    try:
        doc = json.loads(raw.decode("utf-8"))
        choice = doc["choices"][0]
        text = choice["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise Fail("E_RESPONSE") from None
    if not isinstance(text, str):
        raise Fail("E_RESPONSE")
    upstream = doc.get("provider")
    upstream = upstream.lower() if isinstance(upstream, str) and upstream else None
    if pin and upstream is not None and upstream != pin.lower():
        raise Fail("E_PIN")
    if "model" in doc and not (isinstance(doc["model"], str) and doc["model"].lower().startswith(model.lower())):
        raise Fail("E_PIN")        # a service that answers with another model than the route names (an alias, a preset, a router) is refused
    usage = doc.get("usage")
    return {"v": 1, "text": text, "finish": finish_of(choice.get("finish_reason")),
            "usage": {"input": count(usage, "prompt_tokens"), "output": count(usage, "completion_tokens"),
                      "cache_read": count(usage, "prompt_tokens_details", "cached_tokens"),
                      "cache_write": count(usage, "prompt_tokens_details", "cache_write_tokens")},
            "latency_ms": latency_ms, "upstream": upstream}


def complete(dry_run: bool) -> dict:
    req = read_request()
    loopback, host, port, base = check_route(req["route"], req["accepted"])
    if dry_run:
        url = req["route"]["base_url"].rstrip("/") + "/chat/completions"
        would = {"method": "POST", "url": url, "body": build_body(req)}
        return {"would": would, "would_sha256": sha256_of(would)}
    got = post(req, loopback, host, port, base)
    return parse_reply(got["raw"], got["latency_ms"], req["route"]["pin"], req["route"]["model"])


def run(argv) -> int:
    if argv == ["--help"]:
        sys.stdout.write(__doc__)
        return 0
    if argv == ["--check"]:
        if not os.environ.get(KEY_VARIABLE):
            raise Fail("E_KEY")
        sys.stdout.write(json.dumps({"ok": True}) + "\n")
        return 0
    if argv in (["complete"], ["complete", "--dry-run"]):
        sys.stdout.write(json.dumps(complete(argv[-1] == "--dry-run")) + "\n")      # ASCII-escaped: no text can fail to encode
        return 0
    raise Fail("E_USAGE")


def main(argv=None) -> int:
    try:
        return run(sys.argv[1:] if argv is None else argv)
    except Fail as failure:
        code = failure.code
    except BaseException:    # noqa: BLE001 - whatever it is, only a code leaves
        code = "E_INTERNAL"
    sys.stderr.write("chat-http: " + code + "\n")
    return EXITS.get(code, 1)


if __name__ == "__main__":
    sys.exit(main())
