#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Messenger provider for the official WhatsApp Cloud API: an implementation of the class messenger:<platform> for the
platform whatsapp-cloud (providers/messenger/README.md holds the interface every messenger implements and the section
"WhatsApp Cloud API" holds the setup, the Funnel facts, the privacy and the costs). It works only in the listen mode.

Inbound messages reach a small HTTP server on 127.0.0.1 as webhook calls from Meta; the person exposes that one path with
Tailscale Funnel (TLS ends on this machine). Outbound messages go to the Graph API. Standard library only.

Verbs (JSON on stdout, diagnostics on stderr, input by flags, no prompt):
  capabilities --platform whatsapp-cloud
  setup --phone-number-id <id> --template <name> --template-language <code> [--port 8787] [--new-path]
                                      write the settings, print the callback URL and the Funnel command
  whoami [--seconds 120]              print, in the terminal, the phone digits and the business-scoped user id of whoever
                                      writes to the number meanwhile; refuses while a bridge runs
  listen --platform whatsapp-cloud    the long-lived verb (the protocol of providers/messenger/README.md)
  receive, send, ack                  exit 2: whatsapp-cloud works only in listen mode

Secrets (read only through providers/secrets/resolver.py, never in an argument, a log, an output or an exception):
  MESSENGER_WHATSAPP_CLOUD_TOKEN         the system user's permanent token (store username messenger-whatsapp-cloud)
  MESSENGER_WHATSAPP_CLOUD_APP_SECRET    the app secret, used only to check the signature of a webhook call
  MESSENGER_WHATSAPP_CLOUD_VERIFY_TOKEN  the string typed in the app's webhook settings, used only for the handshake

State, under the state folder (OPENHORA_STATE_DIR, else an absolute XDG_STATE_HOME with /openhora, else
~/.local/state/openhora; the rule is written again here because a provider may not import runtime/), in whatsapp-cloud/
(mode 0700, every file 0600): settings.json (phone_number_id, port, template, template_language, webhook_path),
seen.json (the ids of messages already handled, 8 days), window.json (per chat: last_inbound and template_sent_at),
identities.json (business-scoped user id to phone digits, 30 days). The folder holds phone numbers: keep it out of backups.

Sources, read 2026-10-13: Meta's developer documentation for WhatsApp Business Platform (webhooks: create-webhook-endpoint,
overview, components; messages; business-scoped user ids; error codes; pricing; template categorization) and Tailscale's
(kb/1223 Funnel, kb/1153 HTTPS certificates, kb/1311 Serve and Funnel CLI).

Exit codes: 0 ok (also the end of stdin or SIGTERM in listen), 1 failed, 2 usage, 3 not configured (a secret or the settings
are missing, the token is refused, the port is taken).
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import hmac
import http.client
import importlib.util
import json
import os
import queue
import re
import secrets as randomness
import shutil
import signal
import socket
import socketserver
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# The platforms this implementation serves. providers/resolve.py reads this one line as text, without importing the
# file, to choose among the implementations of messenger:<platform> (providers/CONTRACT.md).
PLATFORMS = ("whatsapp-cloud",)

EXIT_OK, EXIT_SERVICE, EXIT_USAGE, EXIT_NOT_CONFIGURED = 0, 1, 2, 3
SECRET_TOKEN, SECRET_APP, SECRET_VERIFY = ("MESSENGER_WHATSAPP_CLOUD_TOKEN", "MESSENGER_WHATSAPP_CLOUD_APP_SECRET",
                                           "MESSENGER_WHATSAPP_CLOUD_VERIFY_TOKEN")   # the names the resolver registers
KEYRING_USERNAMES = dict(zip((SECRET_TOKEN, SECRET_APP, SECRET_VERIFY),
                             ("messenger-whatsapp-cloud", "messenger-whatsapp-cloud-app-secret", "messenger-whatsapp-cloud-verify-token")))
GRAPH_BASE = "https://graph.facebook.com/v25.0"
CAPABILITIES = {"max_text": 4096, "buttons": True, "max_buttons": 3, "max_button_label": 20, "lists": False,
                "max_list_rows": 0, "url_buttons": False, "reply_context": True, "documents": True, "listen": True}
STATE_ENV = "OPENHORA_STATE_DIR"
FOLDER = "whatsapp-cloud"
LOCK = "messaging-{platform}.lock"
SETTINGS, SEEN, WINDOW, IDENTITIES = "settings.json", "seen.json", "window.json", "identities.json"
DEFAULT_PORT = 8787
LOOPBACK = "127.0.0.1"
PHONE = re.compile(r"[1-9][0-9]{5,14}")        # the same shape as phonePattern in the Go program of the other WhatsApp provider
BSUID = re.compile(r"[A-Za-z0-9._-]{1,64}")
PHONE_NUMBER_ID = re.compile(r"[0-9]{5,25}")
TEMPLATE_NAME = re.compile(r"[a-z0-9_]{1,512}")
TEMPLATE_LANGUAGE = re.compile(r"[a-z]{2,3}(?:_[A-Za-z]{2,4})?")
WEBHOOK_PATH = re.compile(r"[0-9a-f]{32}")
SECRET_SHAPE = re.compile(r"[\x21-\x7e]{1,512}")
LONG_WORD = re.compile(r"[A-Za-z0-9_|-]{40,}")
DIGIT_RUN = re.compile(r"[0-9]{8,}")         # a phone number; Meta's error codes have six digits and stay readable

MAX_BODY = 3 * 1024 * 1024                      # Meta documents batches up to 3 MB
REQUEST_DEADLINE = 10.0                         # seconds for a whole webhook request, not for one read
MAX_HANDLERS = 8                                # concurrent webhook requests; the next one gets 503
GRAPH_TIMEOUT, UPLOAD_TIMEOUT = 10.0, 20.0
MAX_ANSWER = 1_000_000
MAX_REQUEST_LINE = 1_048_576                    # the longest line of the listen protocol, either way
WINDOW_SECONDS = 24 * 3600
WINDOW_GATE = 23 * 3600 + 1800                  # a card is sent only while the last message of the person is younger than this
TEMPLATE_REPEAT = 7 * 24 * 3600                 # the template is sent again, at most this often, while the window stays closed
SEEN_KEEP, IDENTITY_KEEP, WINDOW_KEEP = 8 * 86400, 30 * 86400, 30 * 86400
SEEN_MAX, WINDOW_MAX, IDENTITY_MAX, SENT_MAX = 50000, 1000, 2000, 2000
RATE_WAIT = 5.0                                 # a pause after a rate-limit answer, before the next send
CLOCK_SKEW = 300                                # a message timestamp this far ahead of now is read as now
TEXT_LIMIT, BODY_LIMIT, TITLE_LIMIT, ID_LIMIT = 4096, 1024, 20, 256
BUTTONS_LINE = "Choose an action for the card above."
DOCUMENT_LIMIT = 1_000_000
PRUNE_EVERY = 86400.0                           # seconds between two prunings of the state while running
LOG_EVERY = 60.0                                # a diagnostic of one class is written at most this often
CODE_WINDOW, CODE_RATE, CODE_RATE_2 = 131047, 130429, 131056
CODE_TOKEN = (190, 0)                           # the token expired or is refused (0 is an authentication exception)
NOT_LISTEN = "whatsapp-cloud works only in listen mode"


class ProviderError(Exception):
    def __init__(self, message: str, code: int = EXIT_SERVICE, kind: str = "failed"):
        super().__init__(message)
        self.code = code
        self.kind = kind


class GraphError(ProviderError):
    """A Graph API call that failed. `status` is the HTTP status (0: no answer), `code` Meta's error code. The text is built
    from these two numbers only, never from the answer."""

    def __init__(self, status: int, code=None, what: str = ""):
        refused = status == 401 or code in CODE_TOKEN
        text = what or (f"WhatsApp answered {status}" + (f" (error {code})" if code is not None else ""))
        super().__init__(text, EXIT_NOT_CONFIGURED if refused else EXIT_SERVICE, "not-configured" if refused else "failed")
        self.status, self.error_code = status, code


class Deferred(Exception):
    """The window is closed: the card is kept by the bridge and sent again after the person writes."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def redact(text, secrets=()) -> str:
    """The text with each secret, anything shaped like a token and any run of eight digits (a phone number) replaced."""
    out = str(text)
    for value in secrets:
        if value:
            out = out.replace(value, "<secret>")
    out = LONG_WORD.sub("<secret>", out)
    return DIGIT_RUN.sub("<digits>", out)


# --- secrets ----------------------------------------------------------------------------------------------------------


def secret_resolver():
    """The workbench's secret resolver, by path: next to this file first (a copy), then providers/secrets/resolver.py."""
    here = os.path.abspath(__file__)
    folder = os.path.dirname(here)
    candidates = (os.path.join(folder, "resolver.py"), os.path.join(os.path.dirname(folder), "secrets", "resolver.py"))
    path = next((c for c in candidates if os.path.isfile(c)), None)
    if path is None:
        raise ProviderError("providers/secrets/resolver.py is not next to this script nor in the workbench",
                            EXIT_NOT_CONFIGURED, "not-configured")
    spec = importlib.util.spec_from_file_location("workbench_secret_resolver", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_secrets(names=(SECRET_TOKEN, SECRET_APP, SECRET_VERIFY), resolver=None) -> dict:
    """{name: value} for each name; a ProviderError (not-configured) naming every missing or malformed one."""
    resolver = resolver or secret_resolver()
    found, missing = {}, []
    for name in names:
        hit = resolver.resolve(name)
        value = hit[0] if hit else ""
        if not value or not SECRET_SHAPE.fullmatch(value):
            missing.append(name)
        else:
            found[name] = value
    if missing:
        hows = "; ".join(f"{n}: export it, or uv run --with keyring==25.7.0 keyring set openhora {KEYRING_USERNAMES[n]}"
                         for n in missing)
        raise ProviderError("missing or malformed: " + hows, EXIT_NOT_CONFIGURED, "not-configured")
    return found


# --- the state folder (the rule of runtime/messaging_ledger.py, written again: a provider may not import runtime/) ------------


def state_dir() -> str:
    chosen = os.environ.get(STATE_ENV)
    if chosen:
        return os.path.abspath(chosen)
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg and os.path.isabs(xdg):
        return os.path.join(xdg, "openhora")
    return os.path.join(os.path.expanduser("~"), ".local", "state", "openhora")


def private_dir(path: str, what: str) -> str:
    """Make `path` (0700) when it is missing and check it: a real directory (not a link), owned by this user, with no access
    for the group or others. A not-configured ProviderError naming the path otherwise."""
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
        found = os.lstat(path)
    except OSError as e:
        raise ProviderError(f"the {what} {path} cannot be made ({e.strerror or e.__class__.__name__})",
                            EXIT_NOT_CONFIGURED, "not-configured") from None
    if not stat.S_ISDIR(found.st_mode):
        raise ProviderError(f"the {what} {path} is not a real directory (a link or a file); remove it",
                            EXIT_NOT_CONFIGURED, "not-configured")
    if found.st_uid != os.getuid():
        raise ProviderError(f"the {what} {path} is not owned by this user", EXIT_NOT_CONFIGURED, "not-configured")
    if found.st_mode & 0o077:
        raise ProviderError(f"the {what} {path} is open to other users (mode {stat.S_IMODE(found.st_mode):04o}); run chmod 700 on it",
                            EXIT_NOT_CONFIGURED, "not-configured")
    return path


def own_folder() -> str:
    state = private_dir(state_dir(), "state folder")
    return private_dir(os.path.join(state, FOLDER), "WhatsApp Cloud folder")


def write_private_json(path: str, value) -> None:
    tmp = f"{path}.tmp-{os.getpid()}-{threading.get_ident()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            found = json.load(f)
    except (OSError, ValueError):
        return default
    return found if isinstance(found, type(default)) else default


# --- the settings -----------------------------------------------------------------------------------------------------


def check_settings(found) -> dict:
    """The settings, validated; a not-configured ProviderError naming the first thing wrong."""
    if not isinstance(found, dict):
        raise ProviderError("settings.json is not an object; run setup again", EXIT_NOT_CONFIGURED, "not-configured")
    port = found.get("port")
    checks = (("phone_number_id", isinstance(found.get("phone_number_id"), str) and PHONE_NUMBER_ID.fullmatch(found["phone_number_id"])),
              ("port", type(port) is int and 1 <= port <= 65535),
              ("template", isinstance(found.get("template"), str) and TEMPLATE_NAME.fullmatch(found["template"])),
              ("template_language", isinstance(found.get("template_language"), str)
               and TEMPLATE_LANGUAGE.fullmatch(found["template_language"])),
              ("webhook_path", isinstance(found.get("webhook_path"), str) and WEBHOOK_PATH.fullmatch(found["webhook_path"])))
    for name, ok in checks:
        if not ok:
            raise ProviderError(f"settings.json has a missing or malformed {name}; run setup again", EXIT_NOT_CONFIGURED,
                                "not-configured")
    return {k: found[k] for k in ("phone_number_id", "port", "template", "template_language", "webhook_path")}


def load_settings(folder: str) -> dict:
    path = os.path.join(folder, SETTINGS)
    if not os.path.isfile(path):
        raise ProviderError(f"no settings; run: python3 providers/messenger/whatsapp-cloud.py setup (see the README)",
                            EXIT_NOT_CONFIGURED, "not-configured")
    return check_settings(read_json(path, {}))


# --- the state --------------------------------------------------------------------------------------------------------


class Store:
    """What survives a restart: the ids handled, the windows and the identities. `folder` None keeps it all in memory.
    One lock guards it; a file is replaced whole, mode 0600."""

    def __init__(self, folder=None, clock=time.time):
        self.folder, self.clock = folder, clock
        self.lock = threading.RLock()
        self.seen, self.window, self.identities = {}, {}, {}
        self.dirty = set()
        if folder:
            self.seen = {k: v for k, v in read_json(os.path.join(folder, SEEN), {}).items()
                         if isinstance(k, str) and type(v) in (int, float)}
            self.window = {k: v for k, v in read_json(os.path.join(folder, WINDOW), {}).items()
                           if isinstance(k, str) and isinstance(v, dict)}
            self.identities = {k: v for k, v in read_json(os.path.join(folder, IDENTITIES), {}).items()
                               if isinstance(k, str) and isinstance(v, dict) and isinstance(v.get("digits"), str)
                               and type(v.get("seen")) in (int, float)}
            self.prune()

    def prune(self) -> None:
        now = self.clock()
        with self.lock:
            self.seen = {k: v for k, v in self.seen.items() if now - v < SEEN_KEEP}
            self.identities = {k: v for k, v in self.identities.items() if now - v["seen"] < IDENTITY_KEEP}
            self.window = {k: v for k, v in self.window.items()
                           if now - max(self.stamp(v, "last_inbound"), self.stamp(v, "template_sent_at")) < WINDOW_KEEP}
            self.save("seen", "window", "identities")

    @staticmethod
    def stamp(entry, key) -> float:
        value = entry.get(key) if isinstance(entry, dict) else None
        return float(value) if type(value) in (int, float) else 0.0

    def flush(self) -> None:
        """Write what changed since the last write."""
        with self.lock:
            changed, self.dirty = tuple(sorted(self.dirty)), set()
        try:
            self.save(*changed)
        except OSError:
            with self.lock:
                self.dirty.update(changed)
            raise

    def save(self, *which) -> None:
        if not self.folder:
            return
        names = {"seen": (SEEN, self.seen), "window": (WINDOW, self.window), "identities": (IDENTITIES, self.identities)}
        with self.lock:
            for key in which:
                name, data = names[key]
                if key == "seen" and len(data) > SEEN_MAX:
                    keep = sorted(data.items(), key=lambda kv: kv[1])[-SEEN_MAX:]
                    self.seen = data = dict(keep)
                if key == "window" and len(data) > WINDOW_MAX:
                    keep = sorted(data.items(), key=lambda kv: self.stamp(kv[1], "last_inbound"))[-WINDOW_MAX:]
                    self.window = data = dict(keep)
                if key == "identities" and len(data) > IDENTITY_MAX:
                    keep = sorted(data.items(), key=lambda kv: kv[1]["seen"])[-IDENTITY_MAX:]
                    self.identities = data = dict(keep)
                write_private_json(os.path.join(self.folder, name), data)

    # ids handled
    def is_seen(self, wamid: str) -> bool:
        with self.lock:
            return wamid in self.seen

    def mark_seen(self, wamid: str) -> None:
        with self.lock:
            self.seen[wamid] = self.clock()
            self.dirty.add("seen")

    # identities
    def remember(self, bsuid: str, digits: str) -> None:
        with self.lock:
            self.identities[bsuid] = {"digits": digits, "seen": self.clock()}
            self.dirty.update(("identities", "window"))
            old = self.window.pop(bsuid, None)      # what was recorded under the id alone now belongs to the number
            if old:
                mine = self.window.setdefault(digits, {})
                for key in ("last_inbound", "template_sent_at"):
                    mine[key] = max(self.stamp(mine, key), self.stamp(old, key))

    def digits_for(self, bsuid: str):
        with self.lock:
            found = self.identities.get(bsuid)
            return found["digits"] if found else None

    # windows
    def keys_for(self, chat: str) -> list:
        keys = [chat]
        if not PHONE.fullmatch(chat):
            digits = self.digits_for(chat)
            if digits:
                keys.append(digits)
        return keys

    def entry(self, chat: str) -> tuple:
        """(last_inbound, template_sent_at) of the chat, the newest over its keys; 0.0 for none."""
        with self.lock:
            rows = [self.window.get(k, {}) for k in self.keys_for(chat)]
            return (max(self.stamp(r, "last_inbound") for r in rows), max(self.stamp(r, "template_sent_at") for r in rows))

    def note_inbound(self, chat: str, when: float) -> None:
        with self.lock:
            row = self.window.setdefault(chat, {})
            row["last_inbound"] = max(self.stamp(row, "last_inbound"), when)
            self.dirty.add("window")

    def window_open(self, chat: str, now: float) -> bool:
        last = self.entry(chat)[0]
        return last > 0 and now - last < WINDOW_GATE

    def close_window(self, chat: str, now: float) -> None:
        """The API said the window is closed (error 131047): the next send waits for a message of the person."""
        with self.lock:
            for key in self.keys_for(chat):
                row = self.window.setdefault(key, {})
                row["last_inbound"] = min(self.stamp(row, "last_inbound"), now - WINDOW_SECONDS - 60)
            self.dirty.add("window")

    def may_remind(self, chat: str, now: float) -> bool:
        """The template goes out once for each closed window, and again at most every seven days while it stays closed."""
        last, sent = self.entry(chat)
        return sent <= 0 or sent < last + WINDOW_GATE or now - sent >= TEMPLATE_REPEAT

    def reminded(self, chat: str, now: float) -> None:
        with self.lock:
            row = self.window.setdefault(chat, {})
            row["template_sent_at"] = now
            self.dirty.add("window")


# --- rendering --------------------------------------------------------------------------------------------------------
# The same rules as renderWhatsApp in providers/messenger/whatsapp/render.go, on a shared corpus (tests/whatsapp_render_corpus.json).
# Go's regular expressions are ASCII for \s ([\t\n\f\r ], no vertical tab), so classes are written out and re.ASCII is set.

_SP = r"\t\n\f\r "
GO_SPACE = "".join(map(chr, (0x20, 0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x85, 0xa0, 0x1680, *range(0x2000, 0x200b), 0x2028, 0x2029, 0x202f, 0x205f, 0x3000)))   # unicode.IsSpace of Go
HEADING = re.compile(r"^ {0,3}#{1,6}[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*\Z", re.ASCII)
LINK = re.compile(r"!?\[([^\[\]]*)\]\([ \t]*<?((?:[^()" + _SP + r"<>]|\([^()" + _SP + r"<>]*\))+)>?(?:[ \t]+\"[^\"]*\")?[ \t]*\)",
                  re.ASCII)
BOLD = re.compile(r"\*\*([^" + _SP + r"*](?:[^\n]*?[^" + _SP + r"*])??)\*\*", re.ASCII)
STRIKE = re.compile(r"~~([^" + _SP + r"~](?:[^\n]*?[^" + _SP + r"~])??)~~", re.ASCII)
ZERO_WIDTH_SPACE = chr(0x200B)   # breaks a fence inside a table cell; written as a number so the source holds no invisible character
RENDER_LIMIT = 4096
CUT_NOTE = "(continues on the page)"


def go_strip(text: str) -> str:
    """strings.TrimSpace of Go: Python's strip() also trims the four separators U+001C to U+001F, Go's does not."""
    return text.strip(GO_SPACE)


def opens_fence(line: str) -> bool:
    t = line.lstrip(" ")
    return t.startswith("```") and "```" not in t[3:]


def closing_fence(lines: list, start: int) -> int:
    for j in range(start, len(lines)):
        if go_strip(lines[j]) == "```":
            return j
    return -1


def is_table_line(line: str) -> bool:
    t = go_strip(line)
    return len(t) >= 2 and t.startswith("|") and t.endswith("|")


def closing_run(line: str, start: int, n: int) -> int:
    """The end (exclusive) of the next run of exactly n backticks at or after start, or -1."""
    i = start
    while i < len(line):
        if line[i] != "`":
            i += 1
            continue
        m = 0
        while i + m < len(line) and line[i + m] == "`":
            m += 1
        if m == n:
            return i + m
        i += m
    return -1


def _link(match) -> str:
    label, url = match.group(1).strip(GO_SPACE), match.group(2)
    return url if label == "" or label == url else f"{label} ({url})"


def inline(line: str, in_heading: bool) -> str:
    """The marks of one line outside its code spans; the spans are lifted out and put back byte for byte."""
    spans, out, i = [], [], 0
    while i < len(line):
        if line[i] != "`":
            out.append(line[i])
            i += 1
            continue
        n = 0
        while i + n < len(line) and line[i + n] == "`":
            n += 1
        end = closing_run(line, i + n, n)
        if end >= 0:
            spans.append(line[i:end])
            out.append("\x00" + str(len(spans) - 1) + "\x00")
            i = end
            continue
        out.append(line[i:i + n])
        i += n
    s = "".join(out)
    s = LINK.sub(_link, s)
    s = BOLD.sub((lambda m: m.group(1)) if in_heading else (lambda m: "*" + m.group(1) + "*"), s)
    s = STRIKE.sub(lambda m: "~" + m.group(1) + "~", s)
    for k in range(len(spans) - 1, -1, -1):
        s = s.replace("\x00" + str(k) + "\x00", spans[k], 1)
    return s


def render_line(line: str) -> str:
    m = HEADING.match(line)
    if m and m.group(1) != "":
        return "*" + inline(m.group(1), True) + "*"
    return inline(line, False)


def before_span(line: str, cut: int) -> int:
    """A cut position moved back to the start of the code span that contains it, if any."""
    i = 0
    while i < len(line):
        if line[i] != "`":
            i += 1
            continue
        n = 0
        while i + n < len(line) and line[i + n] == "`":
            n += 1
        end = closing_run(line, i + n, n)
        if end >= 0:
            if i < cut < end:
                return i
            i = end
            continue
        i += n
    return cut


def cut_rendered(s: str) -> str:
    """The rendered text within RENDER_LIMIT characters, ending with the note that the rest is on the page. It cuts at a line
    boundary, so a code span (one line) is never cut; a fenced block that would be cut is closed. Only a single line longer
    than the limit is cut inside the line, and then before any code span that the cut would have split."""
    if len(s) <= RENDER_LIMIT:
        return s
    note, closer = "\n" + CUT_NOTE, "\n```"
    lines = s.split("\n")
    used = kept = 0
    in_fence = kept_fence = False
    for i, line in enumerate(lines):
        add = len(line) + (1 if i > 0 else 0)
        fence = in_fence
        if in_fence and go_strip(line) == "```":
            fence = False
        elif not in_fence and opens_fence(line):
            fence = True
        need = used + add + len(note) + (len(closer) if fence else 0)
        if need > RENDER_LIMIT:
            break
        used, kept, in_fence, kept_fence = used + add, i + 1, fence, fence
    if kept == 0:
        first = lines[0]
        cut = before_span(first, len(first[:RENDER_LIMIT - len(note)]))
        return first[:cut].rstrip(" \t") + note
    out = "\n".join(lines[:kept])
    if kept_fence:
        out += closer
    return out + note


def render_whatsapp_cloud(text: str) -> str:
    """The bridge's Markdown as WhatsApp shows it: **x** to *x*, ~~x~~ to ~x~, a heading to *text*, a masked link to
    `text (url)`, a run of table lines in a fenced block; bullets, quotes, fences and code spans stay byte for byte."""
    text = text.replace("\r\n", "\n").replace("\x00", "")
    lines = text.split("\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        if opens_fence(line):
            j = closing_fence(lines, i + 1)
            if j >= 0:
                out.extend(lines[i:j + 1])
                i = j + 1
                continue
        if is_table_line(line):
            j = i
            while j < len(lines) and is_table_line(lines[j]):
                j += 1
            if j - i >= 2:
                out.append("```")
                out.extend(row.replace("```", "``" + ZERO_WIDTH_SPACE + "`") for row in lines[i:j])
                out.append("```")
                i = j
                continue
        out.append(render_line(line))
        i += 1
    return cut_rendered("\n".join(out))


# --- the Graph API ----------------------------------------------------------------------------------------------------


class RefuseRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: urllib would forward the Authorization header to wherever it points."""

    def redirect_request(self, req, fp, code, msg, hdrs, newurl):
        fp.close()
        raise GraphError(code, None, f"refusing to follow a {code} redirect: the request carries the token")


OPENER = urllib.request.build_opener(RefuseRedirect)


class Graph:
    """The Graph API with the standard library. Every failure is a GraphError built from numbers only."""

    def __init__(self, token: str, phone_number_id: str, opener=None, base: str = GRAPH_BASE):
        self.token, self.phone, self.opener, self.base = token, phone_number_id, opener or OPENER, base

    def call(self, method: str, path: str, body=None, raw=None, content_type="application/json", timeout=GRAPH_TIMEOUT):
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode("utf-8"))
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with self.opener.open(request, timeout=timeout) as response:
                answer = response.read(MAX_ANSWER)
        except urllib.error.HTTPError as e:
            code = None
            try:
                parsed = json.loads(e.read(65536).decode("utf-8"))
                found = parsed.get("error", {}).get("code") if isinstance(parsed, dict) and isinstance(parsed.get("error"), dict) else None
                code = found if type(found) is int else None
            except Exception:  # an unreadable body is only a missing code
                pass
            raise GraphError(e.code, code) from None
        except GraphError:
            raise
        except urllib.error.URLError as e:
            raise GraphError(0, None, f"WhatsApp could not be reached ({type(getattr(e, 'reason', e)).__name__})") from None
        except (OSError, ValueError, http.client.HTTPException) as e:
            raise GraphError(0, None, f"the call to WhatsApp failed ({type(e).__name__})") from None
        try:
            parsed = json.loads(answer.decode("utf-8")) if answer else {}
        except ValueError:
            raise GraphError(0, None, "WhatsApp's answer was not JSON") from None
        return parsed if isinstance(parsed, dict) else {}

    def post_message(self, body: dict) -> str:
        sent = self.call("POST", f"/{self.phone}/messages", body)
        messages = sent.get("messages")
        found = messages[0].get("id") if isinstance(messages, list) and messages and isinstance(messages[0], dict) else None
        if not isinstance(found, str) or not found:
            raise GraphError(0, None, "WhatsApp did not return the id of the message")
        return found

    def check(self) -> None:
        self.call("GET", f"/{self.phone}?fields=id")

    def upload(self, name: str, text: str) -> str:
        boundary = "wb" + uuid.uuid4().hex
        parts = [(f'--{boundary}\r\nContent-Disposition: form-data; name="messaging_product"\r\n\r\nwhatsapp\r\n'
                  f'--{boundary}\r\nContent-Disposition: form-data; name="type"\r\n\r\ntext/plain\r\n'
                  f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
                  "Content-Type: text/plain\r\n\r\n").encode("utf-8"), text.encode("utf-8"),
                 f"\r\n--{boundary}--\r\n".encode("utf-8")]
        done = self.call("POST", f"/{self.phone}/media", raw=b"".join(parts),
                         content_type=f"multipart/form-data; boundary={boundary}", timeout=UPLOAD_TIMEOUT)
        media = done.get("id")
        if not isinstance(media, str) or not media:
            raise GraphError(0, None, "WhatsApp did not return the id of the document")
        return media


def text_body(to: str, text: str, reply_to=None) -> dict:
    body = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, "type": "text",
            "text": {"body": text, "preview_url": False}}
    if reply_to:
        body["context"] = {"message_id": reply_to}
    return body


def button_titles(actions: list) -> list:
    """The titles of the buttons: cut to 20 characters, stripped, never empty (a blank one becomes "Option n") and different from
    one another (a repeat gets " 2", " 3" ... inside the 20)."""
    titles, taken = [], set()
    for n, action in enumerate(actions, 1):
        base = " ".join(action["label"].split())[:TITLE_LIMIT].strip() or f"Option {n}"
        title, k = base, 1
        while title.casefold() in taken:
            k += 1
            tail = f" {k}"
            title = base[:TITLE_LIMIT - len(tail)].rstrip() + tail
        taken.add(title.casefold())
        titles.append(title)
    return titles


def buttons_body(to: str, text: str, actions: list, reply_to=None) -> dict:
    body = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, "type": "interactive",
            "interactive": {"type": "button", "body": {"text": text},
                            "action": {"buttons": [{"type": "reply", "reply": {"id": a["id"], "title": t}}
                                                   for a, t in zip(actions, button_titles(actions))]}}}
    if reply_to:
        body["context"] = {"message_id": reply_to}
    return body


def template_body(to: str, name: str, language: str) -> dict:
    return {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, "type": "template",
            "template": {"name": name, "language": {"code": language}}}


def document_body(to: str, media: str, filename: str, reply_to=None) -> dict:
    body = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, "type": "document",
            "document": {"id": media, "filename": filename}}
    if reply_to:
        body["context"] = {"message_id": reply_to}
    return body


def document_name(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:60] or "document"
    return safe if safe.endswith((".txt", ".md")) else safe + ".txt"


def check_message(message) -> dict:
    """The neutral message, checked against the capabilities: a usage error (exit 2) when it does not fit."""
    if not isinstance(message, dict):
        raise ProviderError("the message must be a JSON object", EXIT_USAGE, "usage")
    text = message.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ProviderError("the message needs a text", EXIT_USAGE, "usage")
    if len(text) > CAPABILITIES["max_text"]:
        raise ProviderError(f"the text is {len(text)} characters; this provider takes {CAPABILITIES['max_text']}", EXIT_USAGE, "usage")
    actions = message.get("actions") or []
    if not isinstance(actions, list) or len(actions) > CAPABILITIES["max_buttons"]:
        raise ProviderError(f"a message takes at most {CAPABILITIES['max_buttons']} actions", EXIT_USAGE, "usage")
    for action in actions:
        if not isinstance(action, dict) or not isinstance(action.get("id"), str) or not isinstance(action.get("label"), str) \
                or not action["id"] or not action["label"].strip():
            raise ProviderError("an action is {\"id\": text, \"label\": text}", EXIT_USAGE, "usage")
        if len(action["id"]) > ID_LIMIT:
            raise ProviderError(f"an action id is at most {ID_LIMIT} characters", EXIT_USAGE, "usage")
    if message.get("link") is not None:
        raise ProviderError("this platform has no link buttons: the bridge folds a link into the text", EXIT_USAGE, "usage")
    document = message.get("document")
    if document is not None and (not isinstance(document, dict) or not isinstance(document.get("name"), str)
                                 or not isinstance(document.get("text"), str) or not document["text"]
                                 or len(document["text"]) > DOCUMENT_LIMIT):
        raise ProviderError("a document is {\"name\": text, \"text\": text}", EXIT_USAGE, "usage")
    reply_to = message.get("reply_to")
    if reply_to is not None and (not isinstance(reply_to, str) or not reply_to or len(reply_to) > 512):
        raise ProviderError("reply_to is the id of a WhatsApp message", EXIT_USAGE, "usage")
    return message


# --- sending ----------------------------------------------------------------------------------------------------------


class Sender:
    """The send side: the window gate, the template, the messages. `sent` remembers the ids this process sent, to match a
    late failure report (error 131047 arrives in a webhook status, usually after the API accepted the message)."""

    def __init__(self, graph: Graph, store: Store, settings: dict, log, clock=time.time):
        self.graph, self.store, self.settings, self.log, self.clock = graph, store, settings, log, clock
        self.sent = collections.OrderedDict()
        self.aliases = collections.OrderedDict()     # id of a buttons message -> id of the text it follows (the card's answered id)
        self.sent_lock = threading.Lock()

    def remember_sent(self, wamid: str, chat: str, when: float) -> None:
        with self.sent_lock:
            self.sent[wamid] = (chat, when)
            while len(self.sent) > SENT_MAX:
                self.sent.popitem(last=False)

    def alias_of(self, wamid):
        """The card's answered id for a reply to its buttons message, else the id itself: a reply to either binds to the card."""
        with self.sent_lock:
            return self.aliases.get(wamid, wamid)

    def sent_info(self, wamid: str):
        with self.sent_lock:
            return self.sent.get(wamid)

    def recipient(self, chat: str) -> str:
        if PHONE.fullmatch(chat):
            return chat
        digits = self.store.digits_for(chat) if BSUID.fullmatch(chat) else None
        if not digits:
            raise ProviderError("this contact is known only by a business-scoped user id and its phone number has not been "
                                "seen yet: list the person's digits in messaging.senders.whatsapp-cloud", EXIT_SERVICE, "failed")
        return digits

    def persist(self) -> None:
        try:
            self.store.flush()
        except OSError as e:
            self.log(f"the state could not be written ({e.__class__.__name__})")

    def remind(self, chat: str, to: str) -> bool:
        """The template, when this closed window has not had it (or it is a week old). True when it went out."""
        now = self.clock()
        if not self.store.may_remind(chat, now):
            return False
        try:
            self.graph.post_message(template_body(to, self.settings["template"], self.settings["template_language"]))
        except GraphError as e:
            if e.kind == "not-configured":
                raise
            self.log(f"the reminder template could not be sent ({e.status}, {e.error_code})")
            return False
        self.store.reminded(chat, now)
        self.persist()
        return True

    def defer(self, chat: str, to: str):
        sent = self.remind(chat, to)
        raise Deferred("outside the 24-hour window; a reminder was sent" if sent else
                       "outside the 24-hour window; the reminder was sent already or could not be sent")

    def late_failure(self, wamid: str) -> None:
        """A webhook status said error 131047 for a message this process sent: the window was closed after all."""
        info = self.sent_info(wamid)
        if info is None:
            return
        chat, when = info
        if self.store.entry(chat)[0] > when:
            return                      # the person wrote after that message: the window is open again
        now = self.clock()
        self.store.close_window(chat, now)
        self.persist()
        try:
            self.remind(chat, self.recipient(chat))
        except ProviderError as e:
            if e.kind == "not-configured":
                raise

    def send(self, chat: str, message: dict) -> str:
        """Send the card or text; the id of the message that carries the text. Raises Deferred when the window is closed."""
        to = self.recipient(chat)
        now = self.clock()
        if not self.store.window_open(chat, now):
            self.defer(chat, to)
        rendered = render_whatsapp_cloud(message["text"])
        actions = message.get("actions") or []
        reply_to = message.get("reply_to")
        try:
            if actions and len(rendered) <= BODY_LIMIT:
                first = self.graph.post_message(buttons_body(to, rendered, actions, reply_to))
                follow = []
            else:
                first = self.graph.post_message(text_body(to, rendered, reply_to))
                follow = [("buttons", lambda: self.graph.post_message(buttons_body(to, BUTTONS_LINE, actions, first)))] if actions else []
        except GraphError as e:
            if e.error_code == CODE_WINDOW:
                self.store.close_window(chat, now)
                self.persist()
                self.defer(chat, to)
            raise
        self.remember_sent(first, chat, now)
        document = message.get("document")
        if document:
            follow.append(("document", lambda: self.graph.post_message(
                document_body(to, self.graph.upload(document_name(document["name"]), document["text"]),
                              document_name(document["name"]), first))))
        for what, step in follow:
            try:
                got = step()
                self.remember_sent(got, chat, now)
                if what == "buttons":
                    with self.sent_lock:
                        self.aliases[got] = first
                        while len(self.aliases) > SENT_MAX:
                            self.aliases.popitem(last=False)
            except GraphError as e:
                if e.kind == "not-configured":
                    raise
                # the text is delivered: failing the send would make the bridge send it twice
                self.log(f"the {what} after the text could not be sent ({e.status}, {e.error_code})")
        return first


# --- the webhook ------------------------------------------------------------------------------------------------------


def as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def as_list(value) -> list:
    return value if isinstance(value, list) else []


def signature_ok(app_secret: str, body: bytes, header) -> bool:
    """X-Hub-Signature-256 is `sha256=` and the HMAC-SHA256 of the raw body in hex. Compared on bytes, in constant time."""
    if not isinstance(header, str):
        return False
    expected = b"sha256=" + hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest().encode("ascii")
    return hmac.compare_digest(expected, header.encode("latin-1", "replace"))


class Notes:
    """Diagnostics by class, each at most once a minute: nothing from a request ever reaches them."""

    def __init__(self, write, clock=time.monotonic):
        self.write, self.clock, self.last, self.lock = write, clock, {}, threading.Lock()

    def __call__(self, key: str, text: str = None) -> None:
        now = self.clock()
        with self.lock:
            if key in self.last and now - self.last[key] < LOG_EVERY:
                return
            self.last[key] = now
        self.write(text or key)


class Webhook:
    """What the server does with a call: the handshake, the signature, the payload. `emit(update)` takes an update; `late`
    takes the id of a message this process sent that Meta reports as failed for a closed window."""

    def __init__(self, settings: dict, secrets: dict, store: Store, emit, late=None, sent_info=None, note=None, clock=time.time,
                 alias=None):
        self.settings, self.secrets, self.store, self.emit = settings, secrets, store, emit
        self.late, self.sent_info, self.clock = late or (lambda wamid: None), sent_info or (lambda wamid: None), clock
        self.note = note or (lambda key, text=None: None)
        self.alias = alias or (lambda wamid: wamid)
        self.accepting = True      # a Listener switches it off until the token check has passed
        self.path = "/" + settings["webhook_path"]

    # GET: the handshake
    def handshake(self, query: str):
        """(status, body): 200 with the challenge when the mode is subscribe and the verify token is right, else 403."""
        found = urllib.parse.parse_qs(query, keep_blank_values=True, max_num_fields=20)
        one = lambda k: (found.get(k) or [None])[0] if len(found.get(k) or []) == 1 else None
        mode, token, challenge = one("hub.mode"), one("hub.verify_token"), one("hub.challenge")
        good = isinstance(token, str) and hmac.compare_digest(token.encode("utf-8", "replace"),
                                                              self.secrets[SECRET_VERIFY].encode("utf-8"))
        if mode != "subscribe" or not good:
            self.note("handshake", "webhook: a handshake was refused")
            return 403, b""
        if not isinstance(challenge, str) or not re.fullmatch(r"[A-Za-z0-9._~-]{1,256}", challenge):
            return 400, b""
        return 200, challenge.encode("ascii")

    # POST: a signed payload
    def post(self, body: bytes, header) -> int:
        if not self.accepting:
            return 503           # not ready: nothing is marked seen, so Meta's retry is handled after the token check
        if not signature_ok(self.secrets[SECRET_APP], body, header):
            self.note("signature", "webhook: a call with a missing or wrong signature was refused")
            return 401
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            self.note("unparsable", "webhook: a signed call was not JSON; ignored")
            return 200
        try:
            self.process(payload)
        except Exception as e:  # Meta retries on a 500; what was emitted is deduplicated by id (in memory as well as on disk)
            self.note("processing", f"webhook: processing failed ({type(e).__name__})")
            return 500
        return 200

    def process(self, payload) -> None:
        for entry in as_list(as_dict(payload).get("entry")):
            for change in as_list(as_dict(entry).get("changes")):
                value = as_dict(as_dict(change).get("value"))
                if as_dict(value.get("metadata")).get("phone_number_id") != self.settings["phone_number_id"]:
                    continue
                for status in as_list(value.get("statuses")):
                    self.status(as_dict(status))
                for message in as_list(value.get("messages")):
                    self.message(as_dict(message))
        self.store.flush()      # a failure is an OSError: the caller answers 500 and Meta retries (the retry is deduplicated in memory)

    def status(self, status: dict) -> None:
        if status.get("status") != "failed":
            return
        wamid = status.get("id")
        if not isinstance(wamid, str) or self.sent_info(wamid) is None:
            return
        if any(as_dict(e).get("code") == CODE_WINDOW for e in as_list(status.get("errors"))):
            self.late(wamid)

    def identity(self, message: dict):
        digits, uid = message.get("from"), message.get("from_user_id")
        digits = digits if isinstance(digits, str) and PHONE.fullmatch(digits) else None
        uid = uid if isinstance(uid, str) and BSUID.fullmatch(uid) else None
        if digits and uid:
            self.store.remember(uid, digits)
        if digits:
            return digits, uid
        if uid:
            return (self.store.digits_for(uid) or uid), uid
        return None, None

    def when(self, message: dict) -> float:
        now = self.clock()
        stamp = message.get("timestamp")
        if isinstance(stamp, str) and stamp.isascii() and stamp.isdigit() and len(stamp) <= 12:
            return min(float(stamp), now + CLOCK_SKEW)
        return now

    def message(self, message: dict) -> None:
        wamid = message.get("id")
        if not isinstance(wamid, str) or not wamid or len(wamid) > 512 or self.store.is_seen(wamid):
            return
        kind = message.get("type")
        text = action = None
        if kind == "text":
            body = as_dict(message.get("text")).get("body")
            if not isinstance(body, str) or not body.strip():
                return
            text = body
        elif kind == "interactive":
            reply = as_dict(message.get("interactive"))
            if reply.get("type") != "button_reply" or not isinstance(as_dict(reply.get("button_reply")).get("id"), str):
                return
            action = reply["button_reply"]["id"]
        elif kind == "button":
            text = "/pending"        # a tap on the template's quick reply: the person wants the cards
        else:
            return
        chat, uid = self.identity(message)
        if chat is None:
            return
        context = as_dict(message.get("context")).get("id")
        reply_to = self.alias(context) if isinstance(context, str) and context and kind != "button" else None
        self.store.note_inbound(chat, self.when(message))        # before the update: the bridge's reply must find the window open
        self.emit({"update_id": wamid, "sender": chat, "chat": chat, "private": True, "text": text, "action": action,
                   "action_ref": None, "reply_to": reply_to}, uid)
        self.store.mark_seen(wamid)


class Handler(BaseHTTPRequestHandler):
    """One webhook request. HTTP/1.0 (one request per connection), a total deadline, and nothing from the request in any log."""

    protocol_version = "HTTP/1.0"
    server_version = "openhora"
    sys_version = ""
    timeout = REQUEST_DEADLINE     # one read; the timer in setup() bounds the whole request

    def setup(self):
        super().setup()
        self.timeout_timer = threading.Timer(self.server.deadline, self.expire)
        self.timeout_timer.daemon = True
        self.timeout_timer.start()

    def expire(self):
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def finish(self):
        getattr(self, "timeout_timer").cancel()
        try:
            super().finish()
        except OSError:
            pass

    def log_message(self, *args):    # the default line holds the request: the secret path and hub.verify_token
        pass

    log_error = log_request = log_message

    def __getattr__(self, name):
        if name.startswith("do_"):
            return self.other_method
        raise AttributeError(name)

    def answer(self, status: int, body: bytes = b"", extra=None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def target(self):
        """(path matches, query) of the request line."""
        path, _, query = self.path.partition("?")      # the raw request target, before any parsing or decoding
        want = self.server.hook.path.encode("utf-8")
        return hmac.compare_digest(path.encode("utf-8", "surrogateescape"), want), query

    def other_method(self):
        found, _ = self.target()
        if not found:
            self.answer(404)
        else:
            self.answer(405, extra={"Allow": "GET, POST"})

    def do_GET(self):
        found, query = self.target()
        if not found:
            self.server.hook.note("path", "webhook: a request for another path (404)")
            return self.answer(404)
        status, body = self.server.hook.handshake(query)
        self.answer(status, body)

    def do_POST(self):
        found, _ = self.target()
        if not found:
            self.server.hook.note("path", "webhook: a request for another path (404)")
            return self.answer(404)
        lengths = self.headers.get_all("Content-Length") or []
        if self.headers.get("Transfer-Encoding") is not None or not lengths:
            return self.answer(411)
        if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit() or len(lengths[0]) > 12:
            return self.answer(400)
        size = int(lengths[0])
        if size > self.server.max_body:
            self.server.hook.note("large", "webhook: a body over the limit was refused")
            return self.answer(413)
        body = bytearray()
        while len(body) < size:
            try:
                chunk = self.rfile.read(min(65536, size - len(body)))
            except OSError:
                return
            if not chunk:
                return self.answer(400)
            body.extend(chunk)
        status = self.server.hook.post(bytes(body), self.headers.get("X-Hub-Signature-256"))
        self.answer(status)


class Server(ThreadingHTTPServer):
    """Bound to 127.0.0.1 only. At most `limit` requests at once; the next one gets 503."""

    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 16

    def __init__(self, port: int, hook: Webhook, deadline: float = REQUEST_DEADLINE, limit: int = MAX_HANDLERS,
                 max_body: int = MAX_BODY):
        self.hook, self.deadline, self.max_body = hook, deadline, max_body
        self.slots = threading.BoundedSemaphore(limit)
        super().__init__((LOOPBACK, port), Handler)

    def server_bind(self):                    # HTTPServer.server_bind looks the host name up; this machine needs no name
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = LOOPBACK, self.server_address[1]

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            try:
                request.settimeout(1.0)
                request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):     # the default prints a traceback with the request's details
        self.hook.note("handler", f"webhook: a request failed ({type(sys.exc_info()[1]).__name__})")


# --- the listen mode --------------------------------------------------------------------------------------------------


class Out:
    """The bridge's protocol descriptor: one JSON line, ASCII, flushed, under one lock."""

    def __init__(self, stream):
        self.stream, self.lock = stream, threading.Lock()

    def write(self, line: dict) -> None:
        data = json.dumps(line, ensure_ascii=True).encode("ascii") + b"\n"
        with self.lock:
            try:
                self.stream.write(data)
                self.stream.flush()
            except (OSError, ValueError):
                pass  # the bridge is gone: stdin ends too, and that stops everything


class Listener:
    """One listen process: the webhook server, the sender thread and the stdin reader share this object."""

    def __init__(self, settings: dict, secrets: dict, store: Store, *, out, stdin, graph=None, clock=time.time, rate_wait=RATE_WAIT,
                 deadline=REQUEST_DEADLINE, limit=MAX_HANDLERS, log=None, prune_every=PRUNE_EVERY):
        self.settings, self.secrets, self.store, self.out, self.stdin, self.clock = settings, secrets, store, out, stdin, clock
        self.rate_wait, self.deadline, self.limit, self.prune_every = rate_wait, deadline, limit, prune_every
        self.known = tuple(secrets.values())
        self.log = log or (lambda text: print(redact(text, self.known), file=sys.stderr, flush=True))
        self.note = Notes(self.log)
        self.graph = graph or Graph(secrets[SECRET_TOKEN], settings["phone_number_id"])
        self.sender = Sender(self.graph, store, settings, self.log, clock)
        self.requests = queue.Queue()
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.code = None
        self.server = None
        self.port = None

    def finish(self, code: int) -> None:
        with self.lock:
            if self.code is None:
                self.code = code
        self.stop.set()

    def error_event(self, kind: str, reason: str) -> None:
        self.out.write({"event": "error", "kind": kind, "reason": redact(reason, self.known)})

    def fatal(self, exit_code: int, kind: str, sentence: str) -> None:
        self.error_event(kind, sentence)
        self.finish(exit_code)

    # the webhook
    def emit(self, update: dict, uid=None) -> None:
        self.out.write({"event": "update", "update": update})

    def start_server(self) -> None:
        hook = Webhook(self.settings, self.secrets, self.store, self.emit, late=lambda wamid: self.requests.put(("late", wamid)),
                       sent_info=self.sender.sent_info, note=self.note, clock=self.clock, alias=self.sender.alias_of)
        hook.accepting = False
        self.hook = hook
        try:
            self.server = Server(self.settings["port"], hook, self.deadline, self.limit)
        except OSError as e:
            raise ProviderError(f"the webhook server cannot listen on {LOOPBACK}:{self.settings['port']} "
                                f"({e.strerror or e.__class__.__name__}); change the port with setup", EXIT_NOT_CONFIGURED,
                                "not-configured") from None
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True).start()

    def startup(self) -> None:
        """The token is checked while the server already listens; `ready` is written when it works."""
        try:
            self.graph.check()
        except GraphError as e:
            if e.kind == "not-configured" or e.status in (400, 403):
                self.fatal(EXIT_NOT_CONFIGURED, "not-configured", "WhatsApp refused the token or the phone number id: check "
                           f"{SECRET_TOKEN} and the settings (error {e.error_code if e.error_code is not None else e.status})")
            else:
                self.fatal(EXIT_SERVICE, "failed", "could not check the token with WhatsApp; the bridge will start this again")
            return
        if self.stop.is_set():
            return
        threading.Thread(target=self.work, daemon=True).start()
        threading.Thread(target=self.prune_daily, daemon=True).start()
        self.hook.accepting = True
        self.out.write({"event": "ready"})

    def prune_daily(self) -> None:
        """Identities (30 days), windows and seen ids (8 days) are pruned at the start and once a day while running."""
        while not self.stop.wait(self.prune_every):
            try:
                self.store.prune()
            except OSError as e:
                self.log(f"the state could not be pruned ({e.__class__.__name__})")

    # stdin
    def read_stdin(self) -> None:
        try:
            while not self.stop.is_set():
                line = self.stdin.readline(MAX_REQUEST_LINE + 1)
                if not line:
                    break
                if len(line) > MAX_REQUEST_LINE:
                    while line and not line.endswith(b"\n"):
                        line = self.stdin.readline(MAX_REQUEST_LINE)
                    self.log("dropped a request line over 1 MiB")
                    continue
                try:
                    request = json.loads(line.decode("utf-8"))
                except ValueError:
                    self.log("dropped a request line that is not JSON")
                    continue
                self.requests.put(("send", request))
        except (OSError, ValueError):
            pass
        self.finish(EXIT_OK)

    # the sender
    def answer(self, rid, ok: bool, **fields) -> None:
        self.out.write({"id": rid, "ok": ok, **fields})

    def work(self) -> None:
        while not self.stop.is_set():
            try:
                kind, item = self.requests.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                if kind == "late":
                    self.sender.late_failure(item)
                else:
                    self.handle(item)
            except GraphError as e:
                if e.kind == "not-configured":
                    self.fatal(EXIT_NOT_CONFIGURED, "not-configured", "WhatsApp refused the token: store a new one")
            except Exception as e:  # nothing else may print a traceback
                self.log(f"a request failed unexpectedly ({type(e).__name__})")
                if kind == "send" and isinstance(item, dict) and type(item.get("id")) is int:
                    self.answer(item["id"], False, kind="failed", reason="the send failed unexpectedly")

    def handle(self, request) -> None:
        rid = request.get("id") if isinstance(request, dict) else None
        if type(rid) is not int:
            self.log("dropped a request with no integer id")
            return
        pause = False
        try:
            if request.get("op") != "send":
                raise ProviderError("the only request is send", EXIT_USAGE, "usage")
            chat = request.get("chat")
            if not isinstance(chat, str) or not chat or len(chat) > 64:
                raise ProviderError("chat is a phone number as digits", EXIT_USAGE, "usage")
            message = check_message(request.get("message"))
            message_id = self.sender.send(chat, message)
        except Deferred as d:
            self.answer(rid, False, kind="deferred", reason=d.reason)
        except GraphError as e:
            if e.kind == "not-configured":
                self.answer(rid, False, kind="not-configured", reason="WhatsApp refused the token")
                raise
            pause = e.error_code in (CODE_RATE, CODE_RATE_2)
            self.answer(rid, False, kind="failed", reason=redact(e, self.known))
        except ProviderError as e:
            self.answer(rid, False, kind=e.kind, reason=redact(e, self.known))
        else:
            self.answer(rid, True, message_id=message_id)
        if pause:
            self.stop.wait(self.rate_wait)

    def run(self) -> int:
        try:
            self.start_server()
        except ProviderError as e:
            self.fatal(e.code, e.kind, str(e))
            return self.code
        for target in (self.read_stdin, self.startup):
            threading.Thread(target=target, daemon=True).start()
        self.stop.wait()
        self.shutdown_server()
        return self.code or EXIT_OK

    def shutdown_server(self) -> None:
        if self.server is not None:
            closer = threading.Thread(target=self.server.shutdown, daemon=True)
            closer.start()
            closer.join(2.0)
            try:
                self.server.server_close()
            except OSError:
                pass


def run_listen(*, install_signals: bool = True, folder=None, secrets=None, **options) -> int:
    """The process wiring: the protocol on a copy of fd 1, fd 1 pointed at stderr so that no print reaches the bridge."""
    folder = folder or own_folder()
    settings = load_settings(folder)
    secrets = secrets or load_secrets()
    protocol = os.fdopen(os.dup(1), "wb")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    hook = threading.excepthook
    threading.excepthook = lambda args: print(f"error: a thread failed ({args.exc_type.__name__})", file=sys.stderr, flush=True)
    try:
        listener = Listener(settings, secrets, Store(folder), out=Out(protocol), stdin=sys.stdin.buffer, **options)
        if install_signals:
            signal.signal(signal.SIGTERM, lambda *_: listener.finish(EXIT_OK))
            signal.signal(signal.SIGINT, lambda *_: listener.finish(EXIT_OK))
        return listener.run()
    finally:
        threading.excepthook = hook


# --- verbs ------------------------------------------------------------------------------------------------------------


def say(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def take_lock(state: str):
    """The platform's lock, non-blocking, held while whoami runs (a bridge holds it for its life). The descriptor, or None."""
    import fcntl
    path = os.path.join(state, LOCK.format(platform="whatsapp-cloud"))
    try:
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    except OSError as e:
        say(f"the lock file {path} cannot be opened ({e.strerror or e.__class__.__name__})")
        return None
    try:
        found = os.fstat(fd)
        if not stat.S_ISREG(found.st_mode) or found.st_uid != os.getuid():
            raise OSError("not a regular file of this user")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        os.close(fd)
        say(f"a messaging bridge for whatsapp-cloud is running on this machine (it holds {path}); stop it first, then run whoami")
        return None
    return fd


def funnel_host(run=subprocess.run, which=shutil.which):
    """The machine's Funnel hostname from `tailscale status --json` (Self.DNSName), or None."""
    tool = which("tailscale")
    if not tool:
        return None
    try:
        done = run([tool, "status", "--json"], capture_output=True, text=True, timeout=5, check=False)
        name = json.loads(done.stdout)["Self"]["DNSName"]
    except Exception:  # best effort: a missing, stopped or newer tailscale only means the placeholder sentence
        return None
    name = name.rstrip(".") if isinstance(name, str) else ""
    return name if re.fullmatch(r"[A-Za-z0-9.-]{3,253}", name) else None


def funnel_command(settings: dict) -> str:
    path = settings["webhook_path"]
    return f"tailscale funnel --bg --https=443 --set-path=/{path} http://{LOOPBACK}:{settings['port']}/{path}"


def cmd_setup(args) -> int:
    if args.port is not None and not 1 <= args.port <= 65535:
        say("--port is a number from 1 to 65535")
        return EXIT_USAGE
    folder = own_folder()
    path = os.path.join(folder, SETTINGS)
    current = read_json(path, {})
    chosen = {"phone_number_id": args.phone_number_id or current.get("phone_number_id"),
              "port": args.port if args.port is not None else current.get("port", DEFAULT_PORT),
              "template": args.template or current.get("template"),
              "template_language": args.template_language or current.get("template_language"),
              "webhook_path": current.get("webhook_path")}
    if args.new_path or not (isinstance(chosen["webhook_path"], str) and WEBHOOK_PATH.fullmatch(chosen["webhook_path"])):
        chosen["webhook_path"] = randomness.token_hex(16)
    try:
        settings = check_settings(chosen)
    except ProviderError as e:
        say(str(e).replace("; run setup again", "") + ": give --phone-number-id, --template and --template-language")
        return EXIT_USAGE
    write_private_json(path, settings)
    host = funnel_host()
    url = f"https://{host}/{settings['webhook_path']}" if host else (
        f"https://<your machine's Funnel hostname, shown by `tailscale status`>/{settings['webhook_path']}")
    print(f"Settings written to {path} (mode 0600).\n"
          f"Callback URL for the app's webhook settings: {url}\n"
          f"Verify token: the value of {SECRET_VERIFY} (type the same string in the app's webhook settings).\n"
          "Before the command below, in the Tailscale admin console: MagicDNS and HTTPS certificates must be on, and this node "
          "must have the funnel attribute (kb/1223). On macOS the App Store or Standalone app is needed.\n"
          f"Then run:\n  {funnel_command(settings)}\n"
          "Funnel exposes only that path. Subscribe the app to `messages` in the webhook settings.")
    return EXIT_OK


def cmd_whoami(args) -> int:
    if not sys.stdout.isatty():
        say("whoami prints phone numbers and so writes only to a terminal; run it in one, not into a pipe, a file or a log")
        return EXIT_USAGE
    if not 1 <= args.seconds <= 600:
        say("--seconds is a number from 1 to 600")
        return EXIT_USAGE
    folder = own_folder()
    settings = load_settings(folder)
    secrets = load_secrets((SECRET_APP, SECRET_VERIFY))
    lock = take_lock(state_dir())
    if lock is None:
        return EXIT_USAGE
    stop = threading.Event()

    def show(update, uid):
        print(f"digits: {update['sender'] if PHONE.fullmatch(update['sender']) else '-'}   business-scoped user id: {uid or '-'}",
              flush=True)
    hook = Webhook(settings, secrets, Store(None), show, note=Notes(say))
    try:
        server = Server(settings["port"], hook)
    except OSError as e:
        say(f"the webhook server cannot listen on {LOOPBACK}:{settings['port']} ({e.strerror or e.__class__.__name__})")
        os.close(lock)
        return EXIT_NOT_CONFIGURED
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True).start()
    say(f"Listening for {args.seconds} seconds. Send a message to the business number from your own WhatsApp.")
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, lambda *_: stop.set())
    stop.wait(args.seconds)
    closer = threading.Thread(target=server.shutdown, daemon=True)
    closer.start()
    closer.join(2.0)
    server.server_close()
    os.close(lock)
    return EXIT_OK


def cmd_capabilities(args) -> int:
    print(json.dumps(CAPABILITIES))
    return EXIT_OK


def cmd_listen(args) -> int:
    return run_listen()


def cmd_one_shot(args) -> int:
    say(NOT_LISTEN)
    return EXIT_USAGE


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="verb", required=True)
    for name, func in (("capabilities", cmd_capabilities), ("listen", cmd_listen)):
        sub.add_parser(name).set_defaults(func=func)
    setup = sub.add_parser("setup")
    setup.add_argument("--phone-number-id")
    setup.add_argument("--port", type=int)
    setup.add_argument("--template")
    setup.add_argument("--template-language")
    setup.add_argument("--new-path", action="store_true")
    setup.set_defaults(func=cmd_setup)
    who = sub.add_parser("whoami")
    who.add_argument("--seconds", type=int, default=120)
    who.set_defaults(func=cmd_whoami)
    for name in ("receive", "send", "ack"):
        one = sub.add_parser(name)
        one.set_defaults(func=cmd_one_shot)
        for flag in ("--offset", "--timeout", "--chat", "--message-file", "--action-ref"):
            one.add_argument(flag)
    for parser in sub.choices.values():
        parser.add_argument("--platform", default="whatsapp-cloud", choices=PLATFORMS)
    return p


def main(argv=None) -> int:
    os.umask(0o077)   # every file of the state folder is made 0600
    args = None
    try:
        args = build_parser().parse_args(argv)
        return args.func(args)
    except ProviderError as e:
        if getattr(args, "verb", None) == "listen":
            print(json.dumps({"event": "error", "kind": e.kind, "reason": redact(e)}, ensure_ascii=True), flush=True)
        else:
            say(f"error: {redact(e)}")
        return e.code
    except SystemExit:
        raise
    except BaseException as e:  # nothing else may print a traceback: a request's text can hold a secret
        say(f"error: unexpected failure ({type(e).__name__})")
        return EXIT_SERVICE


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)  # daemon threads may still be in a network call; the process ends now, within the 5 seconds
