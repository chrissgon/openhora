#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Messenger provider for the platform `email` (class messenger:email): the messaging bridge talks to a person through a dedicated
mailbox. Standard library only (imaplib, smtplib, email); any mailbox with IMAP, SMTP and a password works (an app password where the host
requires one). It works only in the listen mode (providers/messenger/README.md, "The listen mode").

E-mail is hostile input: an address is trivial to forge, so the allowlist of the project never admits a message by itself. The provider
emits an update only when ALL of these hold (each one is code):
  1. The topmost Authentication-Results header whose authserv-id is the configured one (the receiving server's own; any other, lower down,
     is ignored, since anyone can add one) says dmarc=pass for the From domain (header.from, when it names one, equal to it), or no DMARC
     result passes and none fails and a dkim=pass has header.d EQUAL to the From domain. SPF alone never admits. No such header: dropped.
  2. One From address (no group, no encoded word in the address); Sender, when present, equal to it; no Resent-* header; never the
     mailbox's own address.
  3. Private: the mailbox's address is the only recipient in To and Cc.
  4. Not automatic: Auto-Submitted absent or no; no Precedence bulk, list or junk; no List-Id or List-Unsubscribe; not a delivery report.
  5. Under 1 MiB, and at most 30 updates for one sender in an hour.
A message that fails is dropped with one log line by class and no reply (no backscatter); the log holds no address, subject or text.

What an update is: the text/plain part, else the text of the HTML part (the quoted blocks of the HTML dropped, hidden text and invisible
characters removed; HTML is never rendered, a link never followed, an attachment never opened). Quoted history is cut at the first `>` line,
a `-- ` signature line, or an attribution or forward marker of a closed list (English, Portuguese, Spanish), so only the sender's own words
reach the bridge. When the first line is a command (`/approve 12`), that line alone is the text, so a signature a phone adds cannot turn it
into a typed hash. At most 8,000 characters. `reply_to` is the In-Reply-To of the message, only when it is a Message-ID this provider sent to
that chat. `action` and `action_ref` are null, `private` is true.

The mailbox is never changed: IMAP EXAMINE (read only), UID SEARCH, UID FETCH with BODY.PEEK and RFC822.SIZE, NOOP, LOGOUT; no flag, move,
copy or delete, ever. TLS is code: IMAP 993 from the first byte, SMTP 465 or 587 with a required STARTTLS, the certificate verified, no
password before TLS (providers/_email.py); plain only to a loopback host with the test variable set.

Cards. One text/plain message, no HTML, no attachment (the capabilities say `documents` false: the whole text of a decision travels in the
body, and a card that does not fit is cut and cannot be approved here). `Auto-Submitted: auto-generated`, a random Message-ID that is
returned to the bridge and remembered (sent.json, the last 1,000 for each chat). `actions_need_reply` is true: the bridge acts on a typed
approve, reject or release only in reply to the card of that decision, and that reply also proves the card reached the person's mailbox.

State: <state>/messenger-email/ (0700; files 0600), where <state> is $OPENHORA_STATE_DIR, else $XDG_STATE_HOME/openhora, else
~/.local/state/openhora: settings.json (no secret), cursor.json (uidvalidity and last uid), sent.json (Message-IDs, no text), listen.lock.
The password is the secret MESSENGER_EMAIL_PASSWORD (store username messenger-email), read by providers/secrets/resolver.py; it is never
printed, logged or put in an error.

Verbs: capabilities, listen, setup, whoami; --check (log in to both servers and look at the authentication of the newest messages).
receive, send and ack exit 2: e-mail works only in listen mode. Exit codes: 0 ok, 1 the service failed, 2 usage, 3 not configured (no
settings or password, a refused login, no authserv-id, another program reading this mailbox, a server that does not record sender
authentication).

The file name has a hyphen on purpose: a script's own folder is first on its sys.path, so a file named email.py in this folder would be imported
in place of the standard library's email package by every script run from it (http.client, urllib and smtplib import it).
"""
import argparse
import collections
import fcntl
import imaplib
import importlib.util
import json
import os
import queue
import re
import signal
import smtplib
import ssl
import stat
import sys
import threading
import time
from datetime import datetime, timezone
from email import message_from_bytes, policy

# The platforms this implementation serves. providers/resolve.py reads this one line as text, without importing the file.
PLATFORMS = ("email",)

SECRET = "MESSENGER_EMAIL_PASSWORD"
KEYRING_USERNAME = "messenger-email"
FOLDER = "messenger-email"
SETTINGS, CURSOR, SENT, LOCK = "settings.json", "cursor.json", "sent.json", "listen.lock"
STATE_ENV = "OPENHORA_STATE_DIR"
EXIT_OK, EXIT_SERVICE, EXIT_USAGE, EXIT_NOT_CONFIGURED = 0, 1, 2, 3
CAPABILITIES = {"max_text": 20000, "buttons": False, "max_buttons": 0, "max_button_label": 0, "lists": False,
                "max_list_rows": 0, "url_buttons": False, "reply_context": True, "documents": False, "listen": True,
                "actions_need_reply": True}
MAX_SIZE = 1 << 20                 # a message over this is skipped without being fetched
MAX_TEXT = 8000                    # characters of an update's text
CUT_LINE = "[The message was cut at 8,000 characters.]"
PER_SENDER = 30                    # updates for one sender in PER_WINDOW
PER_WINDOW = 3600.0
SENT_KEEP = 1000                   # Message-IDs remembered for each chat
POLL_DEFAULT, POLL_MIN = 30, 15
SUBJECT_MAX = 78
LINK_MAX = 512
MAX_REQUEST_LINE = 1 << 20
TIMEOUT = 30.0
AUTHSERV = re.compile(r"[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?")
CONTROLS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")      # every control character but a tab and a line end
AUTO_PRECEDENCE = ("bulk", "list", "junk", "auto_reply")
SLASH_WHOLE = ("/answer",)         # a command that takes the rest of the message; every other command is its first line alone
TYPED_LINE = re.compile(r"^Send (/(?:approve|reject|release) \d+)$", re.M)
ALLOWED_IMAP = ("CAPABILITY", "LOGIN", "EXAMINE", "UID", "NOOP", "LOGOUT")      # what this file may ever cause to be sent to a mailbox


class ProviderError(Exception):
    def __init__(self, message: str, code: int = EXIT_SERVICE, kind: str = "failed"):
        super().__init__(message)
        self.code = code
        self.kind = kind


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _load(name: str, candidates):
    path = next((c for c in candidates if os.path.isfile(c)), None)
    if path is None:
        raise ProviderError(f"{os.path.basename(candidates[0])} is not next to this script's folder", EXIT_NOT_CONFIGURED, "not-configured")
    cached = sys.modules.get(name)
    if cached is not None and getattr(cached, "__file__", None) == path:
        return cached
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def helpers():
    """providers/_email.py, by path: next to this folder's parent first (the workbench), then next to this file (a copy)."""
    here = os.path.abspath(__file__)
    return _load("providers_email", (os.path.join(os.path.dirname(os.path.dirname(here)), "_email.py"),
                                     os.path.join(os.path.dirname(here), "_email.py")))


def text_helpers():
    here = os.path.abspath(__file__)
    return _load("providers_email_text", (os.path.join(os.path.dirname(os.path.dirname(here)), "_email_text.py"),
                                          os.path.join(os.path.dirname(here), "_email_text.py")))


def secret_resolver():
    """The workbench's secret resolver, by path: next to this file first (a copy), then providers/secrets/resolver.py."""
    here = os.path.abspath(__file__)
    folder = os.path.dirname(here)
    path = next((c for c in (os.path.join(folder, "resolver.py"), os.path.join(os.path.dirname(folder), "secrets", "resolver.py"))
                 if os.path.isfile(c)), None)
    if path is None:
        raise ProviderError("providers/secrets/resolver.py is not next to this script nor in the workbench", EXIT_NOT_CONFIGURED,
                            "not-configured")
    spec = importlib.util.spec_from_file_location("workbench_secret_resolver", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


APP_PASSWORD_DISPLAY = re.compile(r"[A-Za-z]{4}( [A-Za-z]{4}){3}")      # how a host shows an app password: four groups of four letters


def load_password() -> str:
    """The mailbox password, or a not-configured ProviderError that names how to store it (never its value)."""
    hit = secret_resolver().resolve(SECRET)
    value = hit[0] if hit else ""
    if APP_PASSWORD_DISPLAY.fullmatch(value):
        value = value.replace(" ", "")
    if not value or not re.fullmatch(r"[\x21-\x7e]{1,512}", value):
        raise ProviderError(f"no usable {SECRET}: export it, or uv run --with keyring==25.7.0 keyring set openhora {KEYRING_USERNAME}",
                            EXIT_NOT_CONFIGURED, "not-configured")
    return value


def redact(text, password: str = "") -> str:
    out = str(text)
    return out.replace(password, "<password>") if password else out


# --- the state folder ---------------------------------------------------------------------------------------------------------------


def state_dir() -> str:
    chosen = os.environ.get(STATE_ENV)
    if chosen:
        return os.path.abspath(chosen)
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg and os.path.isabs(xdg):
        return os.path.join(xdg, "openhora")
    return os.path.join(os.path.expanduser("~"), ".local", "state", "openhora")


def private_dir(path: str, what: str) -> str:
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
        found = os.lstat(path)
    except OSError as e:
        raise ProviderError(f"the {what} {path} cannot be made ({e.strerror or e.__class__.__name__})", EXIT_NOT_CONFIGURED,
                            "not-configured") from None
    if not stat.S_ISDIR(found.st_mode):
        raise ProviderError(f"the {what} {path} is not a real directory (a link or a file); remove it", EXIT_NOT_CONFIGURED, "not-configured")
    if found.st_uid != os.getuid():
        raise ProviderError(f"the {what} {path} is not owned by this user", EXIT_NOT_CONFIGURED, "not-configured")
    if found.st_mode & 0o077:
        raise ProviderError(f"the {what} {path} is open to other users (mode {stat.S_IMODE(found.st_mode):04o}); run chmod 700 on it",
                            EXIT_NOT_CONFIGURED, "not-configured")
    return path


def folder(create: bool = True):
    base = state_dir()
    path = os.path.join(base, FOLDER)
    if not create and not os.path.isdir(path):
        return None
    private_dir(base, "state folder")
    return private_dir(path, "e-mail channel state folder")


def write_private_json(path: str, value) -> None:
    temporary = f"{path}.tmp-{os.getpid()}-{threading.get_ident()}"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, sort_keys=True)
            f.write("\n")
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
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


def take_lock(base: str) -> int:
    """One program reads this mailbox at a time (the cursor is shared): an exclusive lock for the life of the process."""
    fd = os.open(os.path.join(base, LOCK), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        raise ProviderError("another program is reading this mailbox (a second bridge on the same state folder)", EXIT_NOT_CONFIGURED,
                            "not-configured") from None
    return fd


# --- the settings -------------------------------------------------------------------------------------------------------------------


def load_settings() -> dict:
    found = folder(create=False)
    settings = read_json(os.path.join(found, SETTINGS), {}) if found else {}
    if not settings.get("address") or not settings.get("imap_host") or not settings.get("smtp_host"):
        raise ProviderError("no e-mail channel is set up on this machine: python3 providers/messenger/email-imap.py setup --platform email "
                            "--address <a> --imap-host <h> --smtp-host <h> [--authserv-id <id>]", EXIT_NOT_CONFIGURED, "not-configured")
    return settings


def authserv_of(settings: dict) -> str:
    value = settings.get("authserv_id")
    if not isinstance(value, str) or not AUTHSERV.fullmatch(value):
        raise ProviderError("no authserv-id is set: it is the id the receiving server writes at the head of its Authentication-Results "
                            "header, and without it no sender can be told from a forgery. Run setup without --authserv-id to see the ids "
                            "on the newest message, then setup --authserv-id <id>", EXIT_NOT_CONFIGURED, "not-configured")
    return value.lower()


def timeout_seconds() -> float:
    try:
        return float(os.environ.get("MESSENGER_EMAIL_TIMEOUT") or TIMEOUT)
    except ValueError:
        return TIMEOUT


# --- Authentication-Results (RFC 8601), read and not trusted beyond the topmost header of the receiving server --------------------


def strip_comments(text):
    """The text with its RFC 5322 comments (nested parentheses, backslash escapes, quoted strings respected) replaced by a space; None when
    a comment or a quoted string is not closed (the header cannot be read, and an unreadable result admits nothing)."""
    out, depth, quoted, i, n = [], 0, False, 0, len(text)
    while i < n:
        c = text[i]
        if depth:
            if c == "\\":
                i += 1
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if not depth:
                    out.append(" ")
        elif quoted:
            out.append(c)
            if c == "\\" and i + 1 < n:
                i += 1
                out.append(text[i])
            elif c == '"':
                quoted = False
        elif c == "(":
            depth = 1
        else:
            if c == '"':
                quoted = True
            out.append(c)
        i += 1
    return None if depth or quoted else "".join(out)


def split_semicolons(text) -> list:
    """The parts of `text` between semicolons that are not inside a quoted string."""
    parts, current, quoted, i, n = [], [], False, 0, len(text)
    while i < n:
        c = text[i]
        if quoted:
            current.append(c)
            if c == "\\" and i + 1 < n:
                i += 1
                current.append(text[i])
            elif c == '"':
                quoted = False
        elif c == ";":
            parts.append("".join(current))
            current = []
        else:
            if c == '"':
                quoted = True
            current.append(c)
        i += 1
    parts.append("".join(current))
    return parts


PAIR = re.compile(r'([A-Za-z][A-Za-z0-9-]*(?:/\d+)?(?:\.[A-Za-z0-9_-]+)?)\s*=\s*("(?:[^"\\]|\\.)*"|[^\s;"]*)')


def parse_auth_results(raw: str):
    """(authserv-id lower case, [{"method", "result", "props": {"header.d": ...}}]) of one Authentication-Results value, or None when it
    cannot be read. A resinfo is `method=result` and then `ptype.property=value` pairs; a `none` (no results) gives no entry."""
    clean = strip_comments(" ".join(raw.split()))
    if clean is None:
        return None
    parts = split_semicolons(clean)
    head = parts[0].split()
    if not head or len(head) > 2 or (len(head) == 2 and not head[1].isdigit()):
        return None
    results = []
    for part in parts[1:]:
        pairs = PAIR.findall(part)
        if not pairs or "." in pairs[0][0]:
            continue
        method, result = pairs[0][0].split("/", 1)[0].lower(), pairs[0][1].strip('"').lower()
        props = {}
        for key, value in pairs[1:]:
            props.setdefault(key.lower(), value.strip('"').lower())
        results.append({"method": method, "result": result, "props": props})
    return head[0].lower(), results


def topmost_results(msg, authserv: str):
    """The results of the topmost Authentication-Results header whose authserv-id is `authserv`, as parse_auth_results gives them: None
    when there is no such header or it cannot be read. Headers of other ids, and every one below the first of this id, are ignored."""
    for name, value in msg.raw_items():
        if name.lower() != "authentication-results":
            continue
        head = " ".join(str(value).split()).split(";", 1)[0].split()
        if not head or head[0].lower() != authserv:
            continue
        found = parse_auth_results(str(value))
        return found[1] if found else None
    return None


def authenticated(results, domain: str):
    """(True, "") when `results` admit a From domain, else (False, the class). dmarc=pass admits (header.from, when given, equal to the
    domain); a dmarc result that is not pass or none refuses; with no dmarc result or only none, a dkim=pass whose header.d EQUALS the domain
    admits. SPF never admits, and the organisational domain is never guessed."""
    if results is None:
        return False, "unauthenticated"
    dmarc = [r for r in results if r["method"] == "dmarc"]
    if any(r["result"] not in ("pass", "none") for r in dmarc):
        return False, "unauthenticated"
    if any(r["result"] == "pass" and r["props"].get("header.from", domain) == domain for r in dmarc):
        return True, ""
    if any(r["method"] == "dkim" and r["result"] == "pass" and r["props"].get("header.d") == domain for r in results) \
            and not any(r["result"] == "pass" for r in dmarc):
        return True, ""
    return False, "unauthenticated"


# --- the text of a message ----------------------------------------------------------------------------------------------------------

_text = text_helpers()


class QuoteFreeText(_text.HTMLText):
    """The text of an HTML body without the quoted blocks (blockquote): the history of a reply is never the sender's words."""

    SKIP = _text.HTMLText.SKIP | {"blockquote"}


def html_text(html: str) -> str:
    parser = QuoteFreeText()
    parser.feed(html)
    parser.close()
    return parser.result()[0]


ATTRIBUTION = re.compile(
    r"^(?:on|em|el)\b.{1,400}\b(?:wrote|escreveu|escribi[oó]):$",      # validate: allow english-only -- attribution forms of Portuguese and Spanish mail clients
    re.I)
MARKERS = re.compile(
    r"^(?:[-_=]{10,}|[-_=* ]{0,40}(?:"
    r"original message|forwarded message|begin forwarded message:?|"
    r"mensagem original|mensagem encaminhada|mensagem reenviada|in[ií]cio da mensagem (?:reenviada|encaminhada):?|"      # validate: allow english-only -- forward markers of Portuguese mail clients
    r"mensaje original|mensaje reenviado|mensaje remitido|inicio del mensaje reenviado:?"      # validate: allow english-only -- forward markers of Spanish mail clients
    r")[-_=* ]{0,40})$", re.I)
HEADER_START = re.compile(r"^(?:from|de|von):", re.I)
HEADER_FOLLOW = re.compile(r"^(?:sent|date|to|cc|subject|enviado|enviada|enviado el|data|para|assunto|asunto|fecha):", re.I)


def strip_quoted(text: str) -> str:
    """The text before the first quoted line (`>`), signature delimiter (`-- `), attribution ("On ... wrote:", "Em ... escreveu:",
    "El ... escribio:", on one line or two), forward or original-message marker, or Outlook header block (From: then Sent:/To:/Subject:)."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        bare = line.strip()
        joined = (bare + " " + lines[i + 1].strip()).strip() if i + 1 < len(lines) else bare
        if bare.startswith(">") or bare == "--" or MARKERS.match(bare) or ATTRIBUTION.match(bare) \
                or (bare.lower().split(" ", 1)[0] in ("on", "em", "el") and ATTRIBUTION.match(joined)) \
                or (HEADER_START.match(bare) and any(HEADER_FOLLOW.match(n.strip()) for n in lines[i + 1:i + 5])):
            return "\n".join(lines[:i]).strip("\n")
    return text.strip("\n")


def command_only(text: str) -> str:
    """When the first non-blank line is a command (starts with `/`), that line alone is the text, except /answer, which takes the rest: a
    signature or a greeting after `/approve 12` must not become a typed hash (the bridge reads what follows the number as one)."""
    for line in text.split("\n"):
        if not line.strip():
            continue
        first = line.strip()
        if first.startswith("/") and first.split(" ", 1)[0].lower().split("@", 1)[0] not in SLASH_WHOLE:
            return first
        break
    return text


def message_text(msg) -> str:
    """The sender's own words: text/plain, else the HTML part's text; quoted history cut; controls removed; the first-line command alone;
    at most MAX_TEXT characters."""
    plain = msg.get_body(preferencelist=("plain",))
    text = _text.clean_block(_text.part_text(plain), keep_blank_lines=True) if plain is not None else ""
    if not text.strip():
        html = msg.get_body(preferencelist=("html",))
        text = _text.clean_block(html_text(_text.part_text(html)), keep_blank_lines=True) if html is not None else ""
    text = command_only(strip_quoted(CONTROLS.sub("", text)))
    text = text.strip()
    return text[:MAX_TEXT].rstrip() + "\n" + CUT_LINE if len(text) > MAX_TEXT else text


# --- one message in: the update, or why not -----------------------------------------------------------------------------------------


def one_address(msg, name: str, mail):
    """The one plain address of a header, normalised, or None: one header, one address, no group, no defect, no encoded word."""
    headers = msg.get_all(name) or []
    if len(headers) != 1:
        return None
    header = headers[0]
    try:
        if getattr(header, "defects", ()) or len(header.addresses) != 1 or len(header.groups) != 1 \
                or header.groups[0].display_name is not None:
            return None
        found = header.addresses[0]
        return mail.normalize_address(f"{found.username}@{found.domain}")
    except (mail.EmailError, AttributeError, ValueError):
        return None


def recipient_set(msg, mail):
    """The addresses of every To and Cc header as a set of lower-case keys, or None when one cannot be read plainly."""
    found = set()
    for name in ("To", "Cc"):
        for header in msg.get_all(name) or []:
            try:
                if getattr(header, "defects", ()):
                    return None
                for item in header.addresses:
                    found.add(mail.address_key(mail.normalize_address(f"{item.username}@{item.domain}")))
            except (mail.EmailError, AttributeError, ValueError):
                return None
    return found


def automatic(msg) -> bool:
    names = {name.lower() for name in msg.keys()}
    auto = str(msg.get("Auto-Submitted") or "").strip().lower().split(";", 1)[0].strip()
    precedence = str(msg.get("Precedence") or "").strip().lower()
    return bool(auto and auto != "no") or precedence in AUTO_PRECEDENCE or "list-id" in names or "list-unsubscribe" in names \
        or msg.get_content_type() == "multipart/report" or str(msg.get("Return-Path") or "").strip() == "<>"


def inspect_message(raw: bytes, own: str, authserv: str, sent_ids, mail):
    """(update, None) for a message that is admitted, else (None, the class of the refusal): size, unparsable, sender, self, not-private,
    automatic, unauthenticated, empty. `sent_ids(chat)` is the set of Message-IDs this provider sent to that chat."""
    if len(raw) > MAX_SIZE:
        return None, "size"
    try:
        msg = message_from_bytes(raw, policy=policy.default)
        sender = one_address(msg, "From", mail)
        if sender is None:
            return None, "sender"
        key = mail.address_key(sender)
        if key == mail.address_key(own):
            return None, "self"
        if any(name.lower().startswith("resent-") for name in msg.keys()):
            return None, "sender"
        if msg.get_all("Sender"):
            other = one_address(msg, "Sender", mail)
            if other is None or mail.address_key(other) != key:
                return None, "sender"
        if recipient_set(msg, mail) != {mail.address_key(own)}:
            return None, "not-private"
        if automatic(msg):
            return None, "automatic"
        ok, why = authenticated(topmost_results(msg, authserv), mail.domain_of(key))
        if not ok:
            return None, why
        text = message_text(msg)
        if not text:
            return None, "empty"
        reply_to = None
        found = re.search(r"<[^<>\s]+>", str(msg.get("In-Reply-To") or ""))
        if found and found.group(0) in sent_ids(key):
            reply_to = found.group(0)
        return {"sender": key, "chat": key, "private": True, "text": text, "action": None, "action_ref": None,
                "reply_to": reply_to}, None
    except Exception:       # a message the parser cannot read admits nothing, and never ends the process
        return None, "unparsable"


# --- the mailbox: read only ---------------------------------------------------------------------------------------------------------


def connect_imap(settings: dict, mail, password: str):
    """A logged-in IMAP connection, TLS before the password. A refused login is not-configured (exit 3)."""
    try:
        port = int(settings.get("imap_port") or 993)
        security = mail.security_for("imap", settings["imap_host"], port, settings.get("imap_security"))
    except (mail.EmailError, ValueError) as e:
        raise ProviderError(str(getattr(e, "reason", e)), EXIT_USAGE, "usage") from None
    try:
        imap = mail.imap_connect(settings["imap_host"], port, security, timeout_seconds())
        imap.login(settings.get("username") or settings["address"], password)
    except mail.TlsError as e:
        raise ProviderError(e.reason, EXIT_NOT_CONFIGURED, "not-configured") from None
    except imaplib.IMAP4.error:
        raise ProviderError("the IMAP server refused the login: check the address and the app password", EXIT_NOT_CONFIGURED,
                            "not-configured") from None
    except (OSError, ssl.SSLError) as e:
        raise ProviderError(f"cannot reach the IMAP server ({e.__class__.__name__})", EXIT_SERVICE) from None
    return imap


class Mailbox:
    """The INBOX, opened with EXAMINE. Nothing here changes it; the only commands are those of ALLOWED_IMAP."""

    def __init__(self, imap):
        self.imap = imap

    def examine(self):
        """(uidvalidity, highest uid now) of the INBOX."""
        typ, _ = self.imap.select("INBOX", readonly=True)       # EXAMINE
        if typ != "OK":
            raise ProviderError("the IMAP server would not open the INBOX")
        validity = self._number("UIDVALIDITY")
        if validity is None:
            raise ProviderError("the IMAP server did not say its UIDVALIDITY")
        following = self._number("UIDNEXT")
        highest = following - 1 if following else max(self.search("1:*") or [0])
        return validity, highest

    def _number(self, name: str):
        try:
            found = self.imap.response(name)[1]
            return int(found[0]) if found and found[0] is not None else None
        except (ValueError, TypeError, IndexError):
            return None

    def noop(self) -> None:
        self.imap.noop()

    def search(self, spec: str) -> list:
        typ, data = self.imap.uid("SEARCH", "UID", spec)
        if typ != "OK":
            raise ProviderError("the IMAP search failed")
        return sorted(int(n) for n in (data[0] or b"").split() if n.isdigit())

    def new_uids(self, after: int) -> list:
        """The uids above `after`: a range `n:*` always includes the highest message, even below n, so it is filtered."""
        return [uid for uid in self.search(f"{after + 1}:*") if uid > after]

    def size(self, uid: int):
        typ, data = self.imap.uid("FETCH", str(uid), "(RFC822.SIZE)")
        found = re.search(rb"RFC822\.SIZE (\d+)", b" ".join(x if isinstance(x, bytes) else x[0] for x in data if x)) if typ == "OK" else None
        return int(found.group(1)) if found else None

    def fetch(self, uid: int, part: str = "BODY.PEEK[]"):
        typ, data = self.imap.uid("FETCH", str(uid), f"({part})")
        if typ != "OK":
            return None
        for item in data:
            if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], bytes):
                return item[1]
        return None

    def logout(self) -> None:
        try:
            self.imap.logout()
        except Exception:
            pass


def authserv_ids_seen(box: Mailbox, count: int = 5):
    """(the authserv-ids on the headers of the newest `count` messages, in the order first seen; one set of ids for each message looked
    at)."""
    ids, per_message = [], []
    for uid in box.search("1:*")[-count:]:
        head = box.fetch(uid, "BODY.PEEK[HEADER]")
        if head is None:
            continue
        found = set()
        for name, value in message_from_bytes(head, policy=policy.default).raw_items():
            first = " ".join(str(value).split()).split(";", 1)[0].split() if name.lower() == "authentication-results" else []
            if first:
                found.add(first[0].lower())
                if first[0].lower() not in ids:
                    ids.append(first[0].lower())
        per_message.append(found)
    return ids, per_message


# --- the mailbox: sending a card ----------------------------------------------------------------------------------------------------


def connect_smtp(settings: dict, mail, password: str):
    """A logged-in SMTP connection. The password is sent only after TLS. A refused login is not-configured (exit 3)."""
    try:
        port = int(settings.get("smtp_port") or 587)
        security = mail.security_for("smtp", settings["smtp_host"], port, settings.get("smtp_security"))
    except (mail.EmailError, ValueError) as e:
        raise ProviderError(str(getattr(e, "reason", e)), EXIT_USAGE, "usage") from None
    try:
        server = mail.smtp_connect(settings["smtp_host"], port, security, timeout_seconds())
    except mail.TlsError as e:
        raise ProviderError(e.reason, EXIT_SERVICE) from None
    except (OSError, smtplib.SMTPException) as e:
        raise ProviderError(f"cannot reach the SMTP server ({e.__class__.__name__})", EXIT_SERVICE) from None
    try:
        server.login(settings.get("username") or settings["address"], password)
    except smtplib.SMTPAuthenticationError:
        close_smtp(server)
        raise ProviderError("the SMTP server refused the login: check the address and the app password", EXIT_NOT_CONFIGURED,
                            "not-configured") from None
    except (OSError, smtplib.SMTPException) as e:
        close_smtp(server)
        raise ProviderError(f"the SMTP login failed ({e.__class__.__name__})", EXIT_SERVICE) from None
    return server


def close_smtp(server) -> None:
    try:
        server.quit()
    except Exception:
        try:
            server.close()
        except Exception:
            pass


def subject_of(text: str, mail) -> str:
    """The Subject: the first non-blank line of the card, controls removed, `=?` broken (a mail library would decode it), at most 78
    characters. Never refused: the card is text from a project, and a subject is only a label."""
    line = next((l for l in text.split("\n") if l.strip()), "")
    line = CONTROLS.sub(" ", line).replace("\u2028", " ").replace("\u2029", " ").replace("=?", "= ?").strip()
    line = " ".join(line.split())[:SUBJECT_MAX].rstrip() or "openhora"
    return mail.header_text(line, "the subject")


def render_body(message: dict) -> str:
    """The body: the card's text with the typed lines turned into what an e-mail reply says, and the link as a line."""
    body = TYPED_LINE.sub(lambda m: "Reply to this e-mail with: " + m.group(1), message["text"])
    link = message.get("link")
    if link:
        label, url = str(link.get("label") or "Link"), str(link.get("url") or "")
        if not re.fullmatch(r"https?://[^\s\x00-\x1f\x7f]{1,%d}" % LINK_MAX, url) or CONTROLS.search(label):
            raise ProviderError("the link of a message is an http(s) address with no space", EXIT_USAGE, "usage")
        body += f"\n\n{label}: {url}"
    return body


def check_message(message, mail) -> dict:
    """The neutral message, or a usage ProviderError: text within the capabilities, no action, no document."""
    if not isinstance(message, dict) or not isinstance(message.get("text"), str) or not message["text"].strip():
        raise ProviderError("a message has text", EXIT_USAGE, "usage")
    if len(message["text"]) > CAPABILITIES["max_text"]:
        raise ProviderError(f"the text is {len(message['text'])} characters; this provider takes {CAPABILITIES['max_text']}", EXIT_USAGE,
                            "usage")
    if message.get("actions"):
        raise ProviderError("e-mail has no buttons: the bridge folds actions into typed lines", EXIT_USAGE, "usage")
    if message.get("document"):
        raise ProviderError("e-mail takes no document: the whole text of a decision is in the body", EXIT_USAGE, "usage")
    return message


class SentLedger:
    """The Message-IDs sent to each chat (the last SENT_KEEP): what a reply may name. No text, no subject."""

    def __init__(self, base: str):
        self.path = os.path.join(base, SENT)
        self.lock = threading.Lock()
        self.data = {k: [x for x in v if isinstance(x, str)] for k, v in (read_json(self.path, {"chats": {}}).get("chats") or {}).items()
                     if isinstance(v, list)}

    def ids(self, chat: str) -> set:
        with self.lock:
            return set(self.data.get(chat, ()))

    def add(self, chat: str, message_id: str) -> None:
        with self.lock:
            kept = (self.data.get(chat, []) + [message_id])[-SENT_KEEP:]
            self.data[chat] = kept
            write_private_json(self.path, {"chats": self.data})


def send_card(settings: dict, password: str, mail, chat: str, message: dict, ledger: SentLedger, when=None) -> str:
    """Send one card: a plain-text message to `chat`. The Message-ID is random, remembered, and returned. SMTP acceptance is all this can
    know: the delivery of a card is proved later, by a reply that names its Message-ID."""
    try:
        recipient = mail.normalize_address(chat)
    except mail.EmailError as e:
        raise ProviderError(f"chat: {e.reason}", EXIT_USAGE, "usage") from None
    own = mail.normalize_address(settings["address"])
    if mail.address_key(recipient) == mail.address_key(own):
        raise ProviderError("a card is never sent to the mailbox's own address", EXIT_USAGE, "usage")
    check_message(message, mail)
    subject = subject_of(message["text"], mail)
    body = render_body(message)
    message_id = mail.message_id(mail.domain_of(own))
    built = mail.build_message(from_addr=own, to=[recipient], cc=[], subject=subject, body=body, attachments=[],
                               message_id_value=message_id, date=when or datetime.now(timezone.utc))
    built["Auto-Submitted"] = "auto-generated"
    data = built.as_bytes()
    server = connect_smtp(settings, mail, password)
    try:
        server.sendmail(own, [recipient], data)
    except smtplib.SMTPAuthenticationError:
        raise ProviderError("the SMTP server refused the login", EXIT_NOT_CONFIGURED, "not-configured") from None
    except smtplib.SMTPRecipientsRefused:
        raise ProviderError("the server refused the recipient: the card was not sent", EXIT_SERVICE) from None
    except (smtplib.SMTPException, OSError) as e:
        raise ProviderError(f"the SMTP exchange failed ({e.__class__.__name__}): the card may not have been sent", EXIT_SERVICE) from None
    finally:
        close_smtp(server)
    try:
        ledger.add(mail.address_key(recipient), message_id)
    except OSError:
        log("the sent record could not be written")
    return message_id


# --- the listen process -------------------------------------------------------------------------------------------------------------


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
                pass


class Listener:
    """One listen process: the mailbox reader, the sender and the stdin reader share this object."""

    def __init__(self, settings: dict, password: str, *, out, stdin, mail=None, poll_seconds=None, clock=time.monotonic):
        self.settings, self.password, self.out, self.stdin = settings, password, out, stdin
        self.mail = mail or helpers()
        self.own = self.mail.normalize_address(settings["address"])
        self.authserv = authserv_of(settings)
        self.poll = float(poll_seconds if poll_seconds is not None else max(POLL_MIN, int(settings.get("poll_seconds") or POLL_DEFAULT)))
        self.clock = clock
        self.stop = threading.Event()
        self.code = None
        self.lock = threading.Lock()
        self.requests = queue.Queue()
        self.base = folder()
        self.sent = SentLedger(self.base)
        self.cursor_path = os.path.join(self.base, CURSOR)
        self.seen = {}                  # sender -> deque of the times of its updates
        self.threads = []

    def finish(self, code: int) -> None:
        with self.lock:
            if self.code is None:
                self.code = code
        self.stop.set()

    def error_event(self, kind: str, reason: str) -> None:
        self.out.write({"event": "error", "kind": kind, "reason": redact(reason, self.password)})

    def fatal(self, code: int, kind: str, reason: str) -> None:
        self.error_event(kind, reason)
        self.finish(code)

    # stdin: the bridge's requests
    def read_stdin(self) -> None:
        try:
            while not self.stop.is_set():
                line = self.stdin.readline(MAX_REQUEST_LINE + 1)
                if not line:
                    break
                if len(line) > MAX_REQUEST_LINE:
                    while line and not line.endswith(b"\n"):
                        line = self.stdin.readline(MAX_REQUEST_LINE)
                    log("dropped a request line over 1 MiB")
                    continue
                try:
                    self.requests.put(json.loads(line.decode("utf-8")))
                except ValueError:
                    log("dropped a request line that is not JSON")
        except (OSError, ValueError):
            pass
        self.finish(EXIT_OK)

    def answer(self, rid, ok: bool, **fields) -> None:
        self.out.write({"id": rid, "ok": ok, **fields})

    def work(self) -> None:
        while not self.stop.is_set():
            try:
                request = self.requests.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self.handle_request(request)
            except Exception as e:
                log(f"a send failed unexpectedly ({e.__class__.__name__})")
                if isinstance(request, dict) and isinstance(request.get("id"), int):
                    self.answer(request["id"], False, kind="failed", reason="the send failed unexpectedly")

    def handle_request(self, request) -> None:
        rid = request.get("id") if isinstance(request, dict) else None
        if not isinstance(rid, int) or isinstance(rid, bool):
            log("dropped a request with no integer id")
            return
        try:
            if request.get("op") != "send":
                raise ProviderError("the only request is send", EXIT_USAGE, "usage")
            chat = request.get("chat")
            if not isinstance(chat, str):
                raise ProviderError("chat is an e-mail address", EXIT_USAGE, "usage")
            message_id = send_card(self.settings, self.password, self.mail, chat, request.get("message"), self.sent)
        except ProviderError as e:
            self.answer(rid, False, kind=e.kind, reason=redact(e, self.password))
            if e.kind == "not-configured":
                self.fatal(EXIT_NOT_CONFIGURED, "not-configured", str(e))
        else:
            self.answer(rid, True, message_id=message_id)

    # the mailbox
    def cursor(self, validity: int, highest: int) -> int:
        """The last uid already handled. No cursor, or another UIDVALIDITY (the uids mean something else now): from now on, never the whole
        mailbox."""
        saved = read_json(self.cursor_path, {})
        if saved.get("uidvalidity") == validity and isinstance(saved.get("last_uid"), int):
            return saved["last_uid"]
        write_private_json(self.cursor_path, {"uidvalidity": validity, "last_uid": highest})
        return highest

    def save(self, validity: int, last: int) -> None:
        write_private_json(self.cursor_path, {"uidvalidity": validity, "last_uid": last})

    def throttled(self, sender: str) -> bool:
        now = self.clock()
        times = self.seen.setdefault(sender, collections.deque())
        while times and now - times[0] > PER_WINDOW:
            times.popleft()
        if len(times) >= PER_SENDER:
            return True
        times.append(now)
        return False

    def handle_uid(self, box: Mailbox, uid: int) -> None:
        size = box.size(uid)
        if size is None or size > MAX_SIZE:
            log("dropped a message: " + ("size" if size else "unreadable"))
            return
        raw = box.fetch(uid)
        if raw is None:
            log("dropped a message: unreadable")
            return
        update, why = inspect_message(raw, self.own, self.authserv, self.sent.ids, self.mail)
        if update is None:
            log(f"dropped a message: {why}")
        elif self.throttled(update["sender"]):
            log("dropped a message: rate")
        else:
            self.out.write({"event": "update", "update": update})

    def run_mailbox(self) -> None:
        box = None
        try:
            box = Mailbox(connect_imap(self.settings, self.mail, self.password))
            close_smtp(connect_smtp(self.settings, self.mail, self.password))      # a refused SMTP login stops here, not at the first card
            validity, highest = box.examine()
            last = self.cursor(validity, highest)
            self.out.write({"event": "ready"})
            while not self.stop.is_set():
                for uid in box.new_uids(last):
                    if self.stop.is_set():
                        break
                    try:
                        self.handle_uid(box, uid)
                    except ProviderError:
                        raise
                    except Exception as e:      # one message never ends the process
                        log(f"dropped a message: unreadable ({e.__class__.__name__})")
                    last = uid
                    try:
                        self.save(validity, last)
                    except OSError:
                        log("the cursor could not be written")
                if self.stop.wait(self.poll):
                    break
                box.noop()
        except ProviderError as e:
            self.fatal(e.code, e.kind, str(e))
        except (imaplib.IMAP4.error, OSError, ssl.SSLError, EOFError) as e:
            self.fatal(EXIT_SERVICE, "failed", f"the mailbox connection was lost ({e.__class__.__name__}); the bridge starts this again")
        finally:
            if box is not None:
                box.logout()

    def run(self) -> int:
        lock_fd = take_lock(self.base)
        try:
            self.threads = threads = [threading.Thread(target=self.run_mailbox, daemon=True),
                                      threading.Thread(target=self.work, daemon=True),
                                      threading.Thread(target=self.read_stdin, daemon=True)]
            for thread in threads:
                thread.start()
            self.stop.wait()
            threads[0].join(3.0)
            return self.code or EXIT_OK
        finally:
            os.close(lock_fd)


def listen(settings: dict, password: str, *, out, stdin, install_signals: bool = False, **options) -> int:
    listener = Listener(settings, password, out=out, stdin=stdin, **options)
    if install_signals:
        signal.signal(signal.SIGTERM, lambda *_: listener.finish(EXIT_OK))
        signal.signal(signal.SIGINT, lambda *_: listener.finish(EXIT_OK))
    return listener.run()


def run_listen(settings: dict, password: str) -> int:
    """The process wiring: the protocol on a copy of fd 1, fd 1 pointed at stderr so that no print reaches the bridge."""
    protocol = os.fdopen(os.dup(1), "wb")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    hook = threading.excepthook
    threading.excepthook = lambda args: print(f"error: a thread failed ({args.exc_type.__name__})", file=sys.stderr, flush=True)
    try:
        return listen(settings, password, out=Out(protocol), stdin=sys.stdin.buffer, install_signals=True)
    finally:
        threading.excepthook = hook


# --- setup, whoami, check -----------------------------------------------------------------------------------------------------------


def cmd_setup(args) -> int:
    mail = helpers()
    try:
        address = mail.normalize_address(args.address)
        username = args.username or None
        if username is not None:
            mail.header_text(username, "the username")
        imap = mail.security_for("imap", args.imap_host, args.imap_port, args.imap_security)
        smtp = mail.security_for("smtp", args.smtp_host, args.smtp_port, args.smtp_security)
    except mail.EmailError as e:
        raise ProviderError(e.reason, EXIT_USAGE, "usage") from None
    if args.poll_seconds < POLL_MIN:
        raise ProviderError(f"--poll-seconds is at least {POLL_MIN}", EXIT_USAGE, "usage")
    authserv = args.authserv_id
    if authserv is not None:
        authserv = authserv.lower()
        if not AUTHSERV.fullmatch(authserv):
            raise ProviderError("--authserv-id is the host name the receiving server writes first in its Authentication-Results header", EXIT_USAGE,
                                "usage")
    settings = {"address": address, "username": username, "imap_host": args.imap_host, "imap_port": args.imap_port, "imap_security": imap,
                "smtp_host": args.smtp_host, "smtp_port": args.smtp_port, "smtp_security": smtp, "authserv_id": authserv,
                "poll_seconds": args.poll_seconds}
    write_private_json(os.path.join(folder(), SETTINGS), settings)
    out = {"saved": True, "address": address, "authserv_id": authserv}
    if authserv is None:
        out["authserv_ids_seen"], out["next"] = None, ("run setup again with --authserv-id <one of the ids seen>; the provider never picks it for you")
        try:
            box = Mailbox(connect_imap(settings, mail, load_password()))
            try:
                box.examine()
                ids, per_message = authserv_ids_seen(box)
            finally:
                box.logout()
            out["authserv_ids_seen"] = ids
            if not per_message:
                out["note"] = "the INBOX is empty: send a message from a listed address to this mailbox, then run setup again"
            elif not ids:
                out["note"] = "none of the newest messages carries an Authentication-Results header: this server cannot tell a forged sender"
        except ProviderError as e:
            out["note"] = f"the newest message could not be read: {e}"
    print(json.dumps(out))
    return EXIT_OK


def cmd_whoami(args) -> int:
    settings = load_settings()
    print(json.dumps({"address": settings["address"], "authserv_id": settings.get("authserv_id"), "imap_host": settings["imap_host"],
                      "smtp_host": settings["smtp_host"]}))
    return EXIT_OK


def cmd_check(args) -> int:
    mail = helpers()
    settings = load_settings()
    authserv = authserv_of(settings)
    password = load_password()
    close_smtp(connect_smtp(settings, mail, password))
    box = Mailbox(connect_imap(settings, mail, password))
    try:
        box.examine()
        ids, per_message = authserv_ids_seen(box)
    finally:
        box.logout()
    looked, with_header = len(per_message), sum(1 for found in per_message if authserv in found)
    if looked and not with_header:
        raise ProviderError("this mailbox's server does not record sender authentication under the authserv-id " + authserv
                            + (" (ids seen: " + ", ".join(ids) + ")" if ids else " (no Authentication-Results header on the newest messages)")
                            + ": the e-mail channel cannot tell a forged sender", EXIT_NOT_CONFIGURED, "not-configured")
    print(json.dumps({"ok": True, "address": settings["address"], "authserv_id": authserv, "messages_checked": looked,
                      "with_authentication": with_header}))
    return EXIT_OK


# --- the command line ---------------------------------------------------------------------------------------------------------------


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--check", action="store_true", help="log in to both servers and look at the authentication of the newest messages")
    p.add_argument("--platform")
    sub = p.add_subparsers(dest="verb")
    for name in ("capabilities", "listen", "receive", "send", "ack", "whoami"):
        s = sub.add_parser(name)
        s.add_argument("--platform", default=argparse.SUPPRESS)
    s = sub.add_parser("setup", help="write settings.json (no secret)")
    s.add_argument("--platform", default=argparse.SUPPRESS)
    s.add_argument("--address", required=True)
    s.add_argument("--imap-host", required=True)
    s.add_argument("--smtp-host", required=True)
    s.add_argument("--imap-port", type=int, default=993)
    s.add_argument("--smtp-port", type=int, default=587)
    s.add_argument("--imap-security", default=None)
    s.add_argument("--smtp-security", default=None)
    s.add_argument("--username", default=None)
    s.add_argument("--authserv-id", default=None)
    s.add_argument("--poll-seconds", type=int, default=POLL_DEFAULT)
    return p


def run(argv) -> int:
    args, _ = parser().parse_known_args(argv)       # receive, send and ack take arguments this provider refuses anyway
    if args.platform != "email":
        raise ProviderError("this implementation serves --platform email", EXIT_USAGE, "usage")
    if not args.check and not args.verb:
        raise ProviderError("give a verb: capabilities, listen, setup or whoami (see --help)", EXIT_USAGE, "usage")
    if args.verb == "capabilities":
        print(json.dumps(CAPABILITIES))
        return EXIT_OK
    if args.verb in ("receive", "send", "ack"):
        raise ProviderError("email works only in listen mode", EXIT_USAGE, "usage")
    if args.verb == "setup":
        return cmd_setup(args)
    if args.verb == "whoami":
        return cmd_whoami(args)
    if args.check:
        return cmd_check(args)
    settings = load_settings()
    authserv_of(settings)
    return run_listen(settings, load_password())


def main(argv=None) -> int:
    try:
        return run(sys.argv[1:] if argv is None else argv)
    except ProviderError as e:
        print(f"error: {redact(e)}", file=sys.stderr)
        return e.code
    except SystemExit:
        raise
    except BaseException as e:      # nothing else may print a traceback: a message could be in it
        print(f"error: unexpected failure ({e.__class__.__name__})", file=sys.stderr)
        return EXIT_SERVICE


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)      # daemon threads may still be in a network call; the process ends now, within the 5 seconds
