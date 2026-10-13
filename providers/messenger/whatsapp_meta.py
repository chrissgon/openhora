# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Shared code of the two official WhatsApp providers (whatsapp-cloud.py, Meta directly, and whatsapp-twilio.py, through
Twilio). A name with an underscore is never listed as an implementation by providers/resolve.py, so this file is a module
the two providers load by path (next to themselves), not a provider.

It holds what does not depend on who carries the messages: the neutral errors, the state folder and its private files, the
store of handled ids, windows and identities, the rendering of the bridge's Markdown for WhatsApp, the local HTTP server and
its limits, the send gate (the 24-hour window and the reminder template), the listen mode's process wiring and the verbs'
shell. A provider supplies its webhook (the signature and the payload), its API client, its sender and its settings.

Standard library only, Python 3.9 or later. Nothing here reads a credential: the providers hand their secrets in.
"""
from __future__ import annotations

import collections
import hmac
import importlib.util
import json
import os
import queue
import re
import shutil
import signal
import socket
import socketserver
import stat
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

EXIT_OK, EXIT_SERVICE, EXIT_USAGE, EXIT_NOT_CONFIGURED = 0, 1, 2, 3
STATE_ENV = "OPENHORA_STATE_DIR"
LOCK = "messaging-{platform}.lock"
SETTINGS, SEEN, WINDOW, IDENTITIES = "settings.json", "seen.json", "window.json", "identities.json"
DEFAULT_PORT = 8787
LOOPBACK = "127.0.0.1"
PHONE = re.compile(r"[1-9][0-9]{5,14}")        # the same shape as phonePattern in the Go program of the other WhatsApp provider
BSUID = re.compile(r"[A-Za-z0-9._-]{1,64}")
WEBHOOK_PATH = re.compile(r"[0-9a-f]{32}")
SECRET_SHAPE = re.compile(r"[\x21-\x7e]{1,512}")
LONG_WORD = re.compile(r"[A-Za-z0-9_|-]{40,}")
DIGIT_RUN = re.compile(r"[0-9]{8,}")         # a phone number; the platforms' error codes have fewer digits and stay readable

MAX_BODY = 3 * 1024 * 1024                      # the largest webhook body either provider accepts by default
REQUEST_DEADLINE = 10.0                         # seconds for a whole webhook request, not for one read
MAX_HANDLERS = 8                                # concurrent webhook requests; the next one gets 503
MAX_ANSWER = 1_000_000
MAX_REQUEST_LINE = 1_048_576                    # the longest line of the listen protocol, either way
WINDOW_SECONDS = 24 * 3600
WINDOW_GATE = 23 * 3600 + 1800                  # a card is sent only while the last message of the person is younger than this
NO_TEMPLATE_LOG = 24 * 3600                    # without a template, the log line for a chat repeats at most this often
TEMPLATE_REPEAT = 7 * 24 * 3600                 # the template is sent again, at most this often, while the window stays closed
SEEN_KEEP, IDENTITY_KEEP, WINDOW_KEEP = 8 * 86400, 30 * 86400, 30 * 86400
SEEN_MAX, WINDOW_MAX, IDENTITY_MAX, SENT_MAX = 50000, 1000, 2000, 2000
RATE_WAIT = 5.0                                 # a pause after a rate-limit answer, before the next send
CLOCK_SKEW = 300                                # a message timestamp this far ahead of now is read as now
TITLE_LIMIT = 20
BUTTONS_LINE = "Choose an action for the card above."
PRUNE_EVERY = 86400.0                           # seconds between two prunings of the state while running
LOG_EVERY = 60.0                                # a diagnostic of one class is written at most this often


class ProviderError(Exception):
    def __init__(self, message: str, code: int = EXIT_SERVICE, kind: str = "failed"):
        super().__init__(message)
        self.code = code
        self.kind = kind


class ApiError(ProviderError):
    """A call to the platform's API that failed. `status` is the HTTP status (0: no answer), `error_code` the platform's own
    code. A provider's subclass builds the text from these two numbers only, never from the answer."""

    def __init__(self, text: str, status: int, error_code, refused: bool):
        super().__init__(text, EXIT_NOT_CONFIGURED if refused else EXIT_SERVICE, "not-configured" if refused else "failed")
        self.status, self.error_code = status, error_code


class Deferred(Exception):
    """The window is closed: the card is kept by the bridge and sent again after the person writes."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


KNOWN_LABELS = set()      # names that are not secrets but look like one (a store username of 40 characters); a provider adds its own


def redact(text, secrets=()) -> str:
    """The text with each secret, anything shaped like a token and any run of eight digits (a phone number) replaced. The names
    in KNOWN_LABELS (the providers' variable names and store usernames) are kept: they tell the person what to store."""
    out = str(text)
    labels = sorted(KNOWN_LABELS, key=len, reverse=True)
    for i, label in enumerate(labels):
        out = out.replace(label, f"\x00{i}\x00")
    for value in secrets:
        if value:
            out = out.replace(value, "<secret>")
    out = LONG_WORD.sub("<secret>", out)
    out = DIGIT_RUN.sub("<digits>", out)
    for i, label in enumerate(labels):
        out = out.replace(f"\x00{i}\x00", label)
    return out


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


def load_secrets(names, usernames, resolver=None, by_username=False) -> dict:
    """{name: value} for each name; a ProviderError (not-configured) naming every missing or malformed one. With `by_username` the
    sentence leads with the store username: redact() replaces a name of 40 characters or more, which some variable names are."""
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
        if by_username:
            hows = "; ".join(f"{usernames[n]}: uv run --with keyring==25.7.0 keyring set openhora {usernames[n]}, or export {n}"
                             for n in missing)
        else:
            hows = "; ".join(f"{n}: export it, or uv run --with keyring==25.7.0 keyring set openhora {usernames[n]}" for n in missing)
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



def provider_folder(name: str, what: str) -> str:
    """<state folder>/<name>, made and checked like the state folder itself."""
    state = private_dir(state_dir(), "state folder")
    return private_dir(os.path.join(state, name), what)


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

    def seen_max(self) -> int:
        """How many ids are kept; a provider module may read its own constant here."""
        return SEEN_MAX

    def save(self, *which) -> None:
        if not self.folder:
            return
        names = {"seen": (SEEN, self.seen), "window": (WINDOW, self.window), "identities": (IDENTITIES, self.identities)}
        with self.lock:
            for key in which:
                name, data = names[key]
                if key == "seen" and len(data) > self.seen_max():
                    keep = sorted(data.items(), key=lambda kv: kv[1])[-self.seen_max():]
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
RENDER_LIMIT = 4096        # the limit of the Cloud API; a provider with a lower one passes it to render_whatsapp
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


def cut_rendered(s: str, limit: int = RENDER_LIMIT) -> str:
    """The rendered text within `limit` characters, ending with the note that the rest is on the page. It cuts at a line
    boundary, so a code span (one line) is never cut; a fenced block that would be cut is closed. Only a single line longer
    than the limit is cut inside the line, and then before any code span that the cut would have split."""
    if len(s) <= limit:
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
        if need > limit:
            break
        used, kept, in_fence, kept_fence = used + add, i + 1, fence, fence
    if kept == 0:
        first = lines[0]
        cut = before_span(first, len(first[:limit - len(note)]))
        return first[:cut].rstrip(" \t") + note
    out = "\n".join(lines[:kept])
    if kept_fence:
        out += closer
    return out + note


def render_whatsapp(text: str, limit: int = RENDER_LIMIT) -> str:
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
    return cut_rendered("\n".join(out), limit)


# --- buttons and messages ----------------------------------------------------------------------------------------------------


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


# --- the webhook server -----------------------------------------------------------------------------------------------------


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


class Handler(BaseHTTPRequestHandler):
    """One webhook request. HTTP/1.0 (one request per connection), a total deadline, and nothing from the request in any log.
    The server's `hook` supplies `path`, `methods`, `note`, `handle_get(query)` -> (status, body) and
    `handle_post(headers, query, body)` -> (status, body, content type or None)."""

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

    def log_message(self, *args):    # the default line holds the request: the secret path and the query
        pass

    log_error = log_request = log_message

    def __getattr__(self, name):
        if name.startswith("do_"):
            return self.other_method
        raise AttributeError(name)

    def answer(self, status: int, body: bytes = b"", extra=None, content_type=None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type or "text/plain; charset=utf-8")
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
            self.answer(405, extra={"Allow": ", ".join(self.server.hook.methods)})

    def do_GET(self):
        found, query = self.target()
        if not found:
            self.server.hook.note("path", "webhook: a request for another path (404)")
            return self.answer(404)
        if "GET" not in self.server.hook.methods:
            return self.other_method()
        status, body = self.server.hook.handle_get(query)
        self.answer(status, body)

    def do_POST(self):
        found, query = self.target()
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
        status, answer, content_type = self.server.hook.handle_post(self.headers, query, bytes(body))
        self.answer(status, answer, content_type=content_type)


class Server(ThreadingHTTPServer):
    """Bound to 127.0.0.1 only. At most `limit` requests at once; the next one gets 503."""

    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 16

    def __init__(self, port: int, hook, deadline: float = REQUEST_DEADLINE, limit: int = MAX_HANDLERS,
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



def check_message(message, *, max_text: int, max_buttons: int, id_limit: int, documents: bool = True,
                  document_limit: int = 1_000_000) -> dict:
    """The neutral message, checked against the capabilities: a usage error (exit 2) when it does not fit."""
    if not isinstance(message, dict):
        raise ProviderError("the message must be a JSON object", EXIT_USAGE, "usage")
    text = message.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ProviderError("the message needs a text", EXIT_USAGE, "usage")
    if len(text) > max_text:
        raise ProviderError(f"the text is {len(text)} characters; this provider takes {max_text}", EXIT_USAGE, "usage")
    actions = message.get("actions") or []
    if not isinstance(actions, list) or len(actions) > max_buttons:
        raise ProviderError(f"a message takes at most {max_buttons} actions", EXIT_USAGE, "usage")
    for action in actions:
        if not isinstance(action, dict) or not isinstance(action.get("id"), str) or not isinstance(action.get("label"), str) \
                or not action["id"] or not action["label"].strip():
            raise ProviderError("an action is {\"id\": text, \"label\": text}", EXIT_USAGE, "usage")
        if len(action["id"]) > id_limit:
            raise ProviderError(f"an action id is at most {id_limit} characters", EXIT_USAGE, "usage")
    if message.get("link") is not None:
        raise ProviderError("this platform has no link buttons: the bridge folds a link into the text", EXIT_USAGE, "usage")
    document = message.get("document")
    if document is not None and not documents:
        raise ProviderError("this platform takes no document: the bridge folds it into the text", EXIT_USAGE, "usage")
    if document is not None and (not isinstance(document, dict) or not isinstance(document.get("name"), str)
                                 or not isinstance(document.get("text"), str) or not document["text"]
                                 or len(document["text"]) > document_limit):
        raise ProviderError("a document is {\"name\": text, \"text\": text}", EXIT_USAGE, "usage")
    reply_to = message.get("reply_to")
    if reply_to is not None and (not isinstance(reply_to, str) or not reply_to or len(reply_to) > 512):
        raise ProviderError("reply_to is the id of a WhatsApp message", EXIT_USAGE, "usage")
    return message


# --- sending: the window gate and the reminder -----------------------------------------------------------------------------


class BaseSender:
    """The send side every provider shares: the window gate, the reminder template, the ids sent. A provider's sender adds the
    messages themselves and `post_template(to)`. `sent` remembers the ids this process sent, to match a late failure report
    (the API accepts a message and the platform reports a closed window afterwards)."""

    platform = "whatsapp"

    def __init__(self, store, log, clock=time.time):
        self.store, self.log, self.clock = store, log, clock
        self.sent = collections.OrderedDict()
        self.aliases = collections.OrderedDict()     # id of a buttons message -> id of the text it follows (the card's answered id)
        self.sent_lock = threading.Lock()
        self.noted = {}                              # chat -> when "no template" was last logged for it (once per chat per 24 hours)

    def remember_sent(self, wamid: str, chat: str, when: float) -> None:
        with self.sent_lock:
            self.sent[wamid] = (chat, when)
            while len(self.sent) > SENT_MAX:
                self.sent.popitem(last=False)

    def alias_of(self, wamid):
        """The card's answered id for a reply to its buttons message, else the id itself: a reply to either binds to the card."""
        with self.sent_lock:
            return self.aliases.get(wamid, wamid)

    def set_alias(self, got: str, first: str) -> None:
        with self.sent_lock:
            self.aliases[got] = first
            while len(self.aliases) > SENT_MAX:
                self.aliases.popitem(last=False)

    def sent_info(self, wamid: str):
        with self.sent_lock:
            return self.sent.get(wamid)

    def recipient(self, chat: str) -> str:
        """The phone digits of the chat; a business-scoped id is known only through the pairs learned."""
        if PHONE.fullmatch(chat):
            return chat
        digits = self.store.digits_for(chat) if BSUID.fullmatch(chat) else None
        if not digits:
            raise ProviderError("this contact is known only by a business-scoped user id and its phone number has not been "
                                f"seen yet: list the person's digits in messaging.senders.{self.platform}", EXIT_SERVICE, "failed")
        return digits

    def persist(self) -> None:
        try:
            self.store.flush()
        except OSError as e:
            self.log(f"the state could not be written ({e.__class__.__name__})")

    def post_template(self, to: str) -> str:
        raise NotImplementedError

    def has_template(self) -> bool:
        """True when setup recorded a reminder template. A provider's sender answers from its settings."""
        return True

    def note_no_template(self, chat: str, now: float) -> None:
        """One log line per chat per 24 hours: the card waits for the person to write."""
        with self.sent_lock:
            if now - self.noted.get(chat, -NO_TEMPLATE_LOG) < NO_TEMPLATE_LOG:
                return
            self.noted[chat] = now
        self.log("outside the 24-hour window and no reminder template is configured; the card waits until you write")

    def remind(self, chat: str, to: str) -> bool:
        """The template, when this closed window has not had it (or it is a week old). True when it went out. Without a
        template nothing is sent."""
        now = self.clock()
        if not self.has_template():
            self.note_no_template(chat, now)
            return False
        if not self.store.may_remind(chat, now):
            return False
        try:
            self.post_template(to)
        except ApiError as e:
            if e.kind == "not-configured":
                raise
            self.log(f"the reminder template could not be sent ({e.status}, {e.error_code})")
            return False
        self.store.reminded(chat, now)
        self.persist()
        return True

    def defer(self, chat: str, to: str):
        sent = self.remind(chat, to)
        if not self.has_template():
            raise Deferred("outside the 24-hour window; no reminder template is configured, so the card waits until the person writes")
        raise Deferred("outside the 24-hour window; a reminder was sent" if sent else
                       "outside the 24-hour window; the reminder was sent already or could not be sent")

    def late_failure(self, wamid: str) -> None:
        """The platform said the window was closed for a message this process sent: close it here and send the template."""
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


# --- the webhook's common part ---------------------------------------------------------------------------------------------


def as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def as_list(value) -> list:
    return value if isinstance(value, list) else []


def resolve_identity(store, digits, uid):
    """(chat, business-scoped id) of a sender: the phone digits when valid, else the digits remembered for the id, else the id
    itself; (None, None) when neither is valid. The pair is learned whenever both arrive together."""
    digits = digits if isinstance(digits, str) and PHONE.fullmatch(digits) else None
    uid = uid if isinstance(uid, str) and BSUID.fullmatch(uid) else None
    if digits and uid:
        store.remember(uid, digits)
    if digits:
        return digits, uid
    if uid:
        return (store.digits_for(uid) or uid), uid
    return None, None


class HookBase:
    """What the server does with a call, the part both providers share. `emit(update, uid)` takes an update; `late` takes the
    id of a message this process sent that the platform reports as failed for a closed window."""

    methods = ("GET", "POST")

    def __init__(self, settings: dict, secrets: dict, store, emit, late=None, sent_info=None, note=None, clock=time.time,
                 alias=None):
        self.settings, self.secrets, self.store, self.emit = settings, secrets, store, emit
        self.late, self.sent_info, self.clock = late or (lambda wamid: None), sent_info or (lambda wamid: None), clock
        self.note = note or (lambda key, text=None: None)
        self.alias = alias or (lambda wamid: wamid)
        self.accepting = True      # a Listener switches it off until it is ready
        self.path = "/" + settings["webhook_path"]

    def identity_of(self, digits, uid):
        return resolve_identity(self.store, digits, uid)


# --- the listen mode --------------------------------------------------------------------------------------------------


class Listener:
    """One listen process: the webhook server, the sender thread and the stdin reader share this object. A provider's subclass
    sets `self.sender` (a BaseSender), `make_hook()`, `check(message)` and `startup()` (which ends with `begin()`), and the
    sentences below."""

    refused_reason = "the platform refused the credentials"          # the answer to the bridge's request
    refused_fatal = "the platform refused the credentials: store new ones"
    rate_codes = ()                                                  # error codes after which the sender pauses

    def __init__(self, settings: dict, secrets: dict, store, *, out, stdin, clock=time.time, rate_wait=RATE_WAIT,
                 deadline=REQUEST_DEADLINE, limit=MAX_HANDLERS, log=None, prune_every=PRUNE_EVERY, max_body=MAX_BODY):
        self.settings, self.secrets, self.store, self.out, self.stdin, self.clock = settings, secrets, store, out, stdin, clock
        self.rate_wait, self.deadline, self.limit, self.prune_every, self.max_body = rate_wait, deadline, limit, prune_every, max_body
        self.known = tuple(secrets.values())
        self.log = log or (lambda text: print(redact(text, self.known), file=sys.stderr, flush=True))
        self.note = Notes(self.log)
        self.sender = None
        self.requests = queue.Queue()
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.code = None
        self.server = None
        self.port = None
        self.hook = None

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

    def make_hook(self):
        raise NotImplementedError

    def start_server(self) -> None:
        hook = self.make_hook()
        hook.accepting = False
        self.hook = hook
        try:
            self.server = Server(self.settings["port"], hook, self.deadline, self.limit, self.max_body)
        except OSError as e:
            raise ProviderError(f"the webhook server cannot listen on {LOOPBACK}:{self.settings['port']} "
                                f"({e.strerror or e.__class__.__name__}); change the port with setup", EXIT_NOT_CONFIGURED,
                                "not-configured") from None
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True).start()

    def startup(self) -> None:
        raise NotImplementedError

    def begin(self) -> None:
        """Ready: the sender and the pruning threads start, the server accepts calls, the bridge is told."""
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

    def check(self, message) -> dict:
        raise NotImplementedError

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
            except ApiError as e:
                if e.kind == "not-configured":
                    self.fatal(EXIT_NOT_CONFIGURED, "not-configured", self.refused_fatal)
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
            message = self.check(request.get("message"))
            message_id = self.sender.send(chat, message)
        except Deferred as d:
            self.answer(rid, False, kind="deferred", reason=d.reason)
        except ApiError as e:
            if e.kind == "not-configured":
                self.answer(rid, False, kind="not-configured", reason=self.refused_reason)
                raise
            pause = e.error_code in self.rate_codes
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


def serve(make_listener, *, install_signals: bool = True) -> int:
    """The process wiring: the protocol on a copy of fd 1, fd 1 pointed at stderr so that no print reaches the bridge.
    `make_listener(out, stdin)` builds the provider's Listener."""
    protocol = os.fdopen(os.dup(1), "wb")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    hook = threading.excepthook
    threading.excepthook = lambda args: print(f"error: a thread failed ({args.exc_type.__name__})", file=sys.stderr, flush=True)
    try:
        listener = make_listener(Out(protocol), sys.stdin.buffer)
        if install_signals:
            signal.signal(signal.SIGTERM, lambda *_: listener.finish(EXIT_OK))
            signal.signal(signal.SIGINT, lambda *_: listener.finish(EXIT_OK))
        return listener.run()
    finally:
        threading.excepthook = hook


# --- verbs ------------------------------------------------------------------------------------------------------------


def say(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def take_lock(state: str, platform: str):
    """The platform's lock, non-blocking, held while whoami runs (a bridge holds it for its life). The descriptor, or None."""
    import fcntl
    path = os.path.join(state, LOCK.format(platform=platform))
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
        say(f"a messaging bridge for {platform} is running on this machine (it holds {path}); stop it first, then run whoami")
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


def run_cli(build_parser, argv=None) -> int:
    """The verbs' shell: parse, run, and turn every failure into an exit code with a redacted sentence."""
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


def shared_names() -> tuple:
    """The names a provider takes over from this module into its own namespace (its tests reach them through the provider).
    They are COPIES of the globals: a test that replaces a name to change what shared code does must patch it on `whatsapp_meta`
    (sys.modules["whatsapp_meta"]), not on the provider, whose own functions and classes are the ones it defines itself."""
    skip = {"annotations", "SHARED"}
    return tuple(sorted(n for n, v in globals().items()
                        if not n.startswith("_") and n not in skip and not isinstance(v, type(sys))))
