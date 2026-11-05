#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Mailer provider (class sender:email) over SMTP, with an optional read-only IMAP lookup in the Sent folder: send one e-mail from the
machine's outbox account, to exactly the recipients it is given, once.

Standard library only (smtplib, imaplib, email). Any mailbox with SMTP, IMAP and a password works: an app password where the host
requires one. The Gmail API (OAuth) is a later second implementation of the same class. The rules of the connection are in
providers/_email.py: TLS before any password (SMTP 465, or 587 with a required STARTTLS; IMAP 993), the certificate verified.

The rules of the class (providers/CONTRACT.md) as this provider keeps them:
- Nothing is sent without --confirmed. --dry-run prints the headers, the envelope, the body and the name, size and sha256 of each
  attachment; it reads no credential, opens no connection and writes nothing.
- The recipients are exactly the flags: the envelope is To + Cc + Bcc, the headers have To and Cc only (a Bcc is never a header), and
  every header is built here from checked parts. A display name, a comment, a line break or a control character, a second @, a
  duplicate address, or more than 20 recipients in all, is a usage error (exit 2).
- All or nothing: one RCPT the server refuses means RSET, nothing sent, the key released, exit 1 naming the address.
- At most one e-mail per idempotency key. The key is recorded `pending` in the ledger, under a file lock, before the first connection
  and `done` after the server's 250 to DATA. A refusal before or at DATA releases the key. An answer lost after DATA (a drop, a
  timeout) leaves it `pending`: the next send with that key first runs `lookup` (the Message-ID in the Sent folder). Found: the e-mail
  was sent (`"replayed": true`). Not found, or no Sent folder configured: blocked (exit 1) until `resolve` records what the person found.
- One outbox account per machine: the from address of settings.json. Another --from is exit 3.

The ledger and settings live in <state>/mailer-smtp/ (0700; the files 0600), where <state> is $OPENHORA_STATE_DIR, else
$XDG_STATE_HOME/openhora, else ~/.local/state/openhora. The password is the secret MAILER_SMTP_PASSWORD (store username mailer-smtp), read
by providers/secrets/resolver.py; it is never printed, logged or put in an error.

Exit codes: 0 ok; 1 the service or the ledger refuses and NOTHING was sent (a caller may rely on it); 2 usage error; 3 not configured (no
settings, no password, a login the server refuses, another outbox account); 4 the outcome is not known (the answer to the message was lost,
or an earlier attempt's was and the Sent folder does not say): the e-mail may or may not have been sent, and the key stays pending.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import fcntl
import hashlib
import imaplib
import importlib.util
import json
import os
import re
import smtplib
import socket
import ssl
import stat
import sys
import time

EXIT_OK, EXIT_SERVICE, EXIT_USAGE, EXIT_NOT_CONFIGURED, EXIT_UNKNOWN = 0, 1, 2, 3, 4
PASSWORD_NAME = "MAILER_SMTP_PASSWORD"
STORE_USERNAME = "mailer-smtp"
FOLDER = "mailer-smtp"
SETTINGS, LEDGER, LOCK = "settings.json", "ledger.json", "ledger.lock"
STATE_ENV = "OPENHORA_STATE_DIR"
MAX_RECIPIENTS = 20
BODY_MAX = 100 * 1024
ATTACH_TOTAL_MAX = 18 * 1024 * 1024
MESSAGE_MAX = 25 * 1024 * 1024      # what most servers accept, encoding included
SUBJECT_MAX = 998
KEY = re.compile(r"[A-Za-z0-9._-]{1,128}")
FOLDER_NAME = re.compile(r"[A-Za-z0-9\[][A-Za-z0-9 ._/\[\]&,+-]{0,99}")      # `[` first: [Gmail]/Sent Mail; `& , +`: a name IMAP writes in modified UTF-7
APP_PASSWORD_DISPLAY = re.compile(r"[A-Za-z]{4}( [A-Za-z]{4}){3}")      # how a host shows an app password: four groups of four letters
LOCK_SECONDS = 10.0
TIMEOUT_ENV = "MAILER_SMTP_TIMEOUT"       # tests only: seconds before a connection or a read gives up


class ProviderError(Exception):
    def __init__(self, message: str, code: int = EXIT_SERVICE):
        super().__init__(message)
        self.code = code


def log(message: str) -> None:
    print(message, file=sys.stderr)


def helpers():
    """providers/_email.py, by path: next to this folder's parent first (the workbench), then next to this file (a copy)."""
    here = os.path.abspath(__file__)
    candidates = (os.path.join(os.path.dirname(os.path.dirname(here)), "_email.py"), os.path.join(os.path.dirname(here), "_email.py"))
    path = next((c for c in candidates if os.path.isfile(c)), None)
    if path is None:
        raise ProviderError("providers/_email.py is not next to this script's folder", EXIT_NOT_CONFIGURED)
    cached = sys.modules.get("providers_email")
    if cached is not None and getattr(cached, "__file__", None) == path:
        return cached
    spec = importlib.util.spec_from_file_location("providers_email", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def secret_resolver():
    """The workbench's secret resolver, by path: next to this file first (a copy), then providers/secrets/resolver.py."""
    here = os.path.abspath(__file__)
    folder = os.path.dirname(here)
    candidates = (os.path.join(folder, "resolver.py"), os.path.join(os.path.dirname(folder), "secrets", "resolver.py"))
    path = next((c for c in candidates if os.path.isfile(c)), None)
    if path is None:
        raise ProviderError("providers/secrets/resolver.py is not next to this script nor in the workbench", EXIT_NOT_CONFIGURED)
    spec = importlib.util.spec_from_file_location("workbench_secret_resolver", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_password() -> str:
    """The outbox password, or a not-configured ProviderError that names how to store it (never its value)."""
    hit = secret_resolver().resolve(PASSWORD_NAME)
    value = hit[0] if hit else ""
    if APP_PASSWORD_DISPLAY.fullmatch(value):      # the display form of an app password (four groups of four letters): the password is the letters
        value = value.replace(" ", "")
    if not value or not re.fullmatch(r"[\x21-\x7e]{1,512}", value):
        raise ProviderError(f"no usable {PASSWORD_NAME}: export it, or uv run --with keyring==25.7.0 keyring set openhora {STORE_USERNAME}",
                            EXIT_NOT_CONFIGURED)
    return value


def timeout() -> float:
    try:
        return float(os.environ.get(TIMEOUT_ENV) or 30.0)
    except ValueError:
        return 30.0


# --- the state folder --------------------------------------------------------------------------------------------------------------


def state_dir() -> str:
    chosen = os.environ.get(STATE_ENV)
    if chosen:
        return os.path.abspath(chosen)
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg and os.path.isabs(xdg):
        return os.path.join(xdg, "openhora")
    return os.path.join(os.path.expanduser("~"), ".local", "state", "openhora")


def private_dir(path: str, what: str) -> str:
    """Make `path` (0700) when missing and check it: a real directory, this user's, closed to the group and others."""
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
        found = os.lstat(path)
    except OSError as e:
        raise ProviderError(f"the {what} {path} cannot be made ({e.strerror or e.__class__.__name__})", EXIT_NOT_CONFIGURED) from None
    if not stat.S_ISDIR(found.st_mode):
        raise ProviderError(f"the {what} {path} is not a real directory (a link or a file); remove it", EXIT_NOT_CONFIGURED)
    if found.st_uid != os.getuid():
        raise ProviderError(f"the {what} {path} is not owned by this user", EXIT_NOT_CONFIGURED)
    if found.st_mode & 0o077:
        raise ProviderError(f"the {what} {path} is open to other users (mode {stat.S_IMODE(found.st_mode):04o}); run chmod 700 on it",
                            EXIT_NOT_CONFIGURED)
    return path


def folder(create: bool = True):
    """<state>/mailer-smtp, made and checked; None when it does not exist and `create` is False (a dry run makes nothing)."""
    base = state_dir()
    path = os.path.join(base, FOLDER)
    if not create and not os.path.isdir(path):
        return None
    private_dir(base, "state folder")
    return private_dir(path, "mailer state folder")


def write_private_json(path: str, value) -> None:
    temporary = f"{path}.tmp-{os.getpid()}"
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


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- the settings and the ledger ----------------------------------------------------------------------------------------------------


SETTING_KEYS = ("from", "username", "smtp_host", "smtp_port", "smtp_security", "imap_host", "imap_port", "sent_folder")


def load_settings() -> dict:
    """The outbox account of this machine (settings.json), or not-configured with the command that makes it."""
    found = folder(create=False)
    settings = read_json(os.path.join(found, SETTINGS), {}) if found else {}
    if not settings.get("from") or not settings.get("smtp_host"):
        raise ProviderError("no outbox account is set up on this machine: python3 providers/mailer/smtp.py setup --from <address> "
                            "--smtp-host <host> [--imap-host <host> --sent-folder <name>]", EXIT_NOT_CONFIGURED)
    return settings


@contextlib.contextmanager
def ledger_locked():
    """The ledger under an exclusive file lock: yields the dict, written back when the block ends without an error."""
    base = folder()
    fd = os.open(os.path.join(base, LOCK), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        deadline = time.monotonic() + LOCK_SECONDS
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise ProviderError("the ledger is locked by another send; try again", EXIT_SERVICE) from None
                time.sleep(0.05)
        path = os.path.join(base, LEDGER)
        data = read_json(path, {"keys": {}})
        data.setdefault("keys", {})
        yield data
        write_private_json(path, data)
    finally:
        os.close(fd)


def ledger_peek(key: str):
    """The entry of a key, read without writing anything or making any folder (a dry run)."""
    found = folder(create=False)
    if not found:
        return None
    return (read_json(os.path.join(found, LEDGER), {"keys": {}}).get("keys") or {}).get(key)


# --- the arguments, checked ---------------------------------------------------------------------------------------------------------


def read_regular(path: str, what: str, limit: int) -> bytes:
    """The bytes of a regular file that is not a link (opened without following one), at most `limit`; else a usage error."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise ProviderError(f"{what}: {path} cannot be read (missing, or a link)", EXIT_USAGE) from None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ProviderError(f"{what}: {path} is not a regular file", EXIT_USAGE)
        with os.fdopen(fd, "rb", closefd=False) as f:
            data = f.read(limit + 1)
    finally:
        os.close(fd)
    if len(data) > limit:
        raise ProviderError(f"{what} is over {limit} bytes", EXIT_USAGE)
    return data


def read_text_file(path: str, what: str, limit: int) -> str:
    data = read_regular(path, what, limit)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise ProviderError(f"{what} is not UTF-8 text", EXIT_USAGE) from None


def read_attachment(spec: str, mail) -> tuple:
    """(name, media type, bytes) of one `--attach <path>=<name>`: a regular file that is not a link, a plain name with an extension of the
    closed list."""
    path, sep, name = spec.rpartition("=")
    if not sep or not path:
        raise ProviderError("--attach is <path>=<name>", EXIT_USAGE)
    try:
        name = mail.attachment_name(name)
    except mail.EmailError as e:
        raise ProviderError(e.reason, EXIT_USAGE) from None
    return name, mail.media_type(name), read_regular(path, f"the attachment {name}", ATTACH_TOTAL_MAX)


def addresses(values, what: str, mail) -> list:
    out = []
    for value in values or []:
        try:
            out.append(mail.normalize_address(value))
        except mail.EmailError as e:
            raise ProviderError(f"{what}: {e.reason}", EXIT_USAGE) from None
    return out


def plan_of(args, mail) -> dict:
    """The e-mail the flags describe, checked whole: nothing is read from the network or a credential. Returns the message and its preview."""
    key = args.idempotency_key
    if not isinstance(key, str) or not KEY.fullmatch(key):
        raise ProviderError("--idempotency-key is letters, digits, dots, hyphens and underscores, at most 128 characters", EXIT_USAGE)
    try:
        sender = mail.normalize_address(args.sender)
    except mail.EmailError as e:
        raise ProviderError(f"--from: {e.reason}", EXIT_USAGE) from None
    to, cc, bcc = addresses(args.to, "--to", mail), addresses(args.cc, "--cc", mail), addresses(args.bcc, "--bcc", mail)
    everyone = to + cc + bcc
    if not to:
        raise ProviderError("--to needs at least one address", EXIT_USAGE)
    if len(everyone) > MAX_RECIPIENTS:
        raise ProviderError(f"{len(everyone)} recipients: at most {MAX_RECIPIENTS} in all (To, Cc and Bcc)", EXIT_USAGE)
    seen = set()
    for address in everyone:
        if mail.address_key(address) in seen:
            raise ProviderError(f"the address {address} is listed twice", EXIT_USAGE)
        seen.add(mail.address_key(address))
    subject = read_text_file(args.subject_file, "the subject", SUBJECT_MAX * 4).rstrip("\n")
    body = read_text_file(args.body_file, "the body", BODY_MAX)
    try:
        subject = mail.header_text(subject, "the subject")
        mid = args.message_id
        if not isinstance(mid, str) or not mail.MESSAGE_ID.fullmatch(mid):
            raise mail.EmailError("--message-id is <oh.<32 hex>@domain>")
        reply = mail.reference_id(args.in_reply_to) if args.in_reply_to else None
    except mail.EmailError as e:
        raise ProviderError(e.reason, EXIT_USAGE) from None
    if not body.strip() or "\x00" in body or "\r" in body:
        raise ProviderError("the body is non-empty text without a NUL character and with line breaks written \\n (no \\r)", EXIT_USAGE)
    attachments = [read_attachment(spec, mail) for spec in args.attach or []]
    if sum(len(a[2]) for a in attachments) > ATTACH_TOTAL_MAX:
        raise ProviderError(f"the attachments are over {ATTACH_TOTAL_MAX} bytes together", EXIT_USAGE)
    if len({a[0].lower() for a in attachments}) != len(attachments):
        raise ProviderError("two attachments have the same name", EXIT_USAGE)
    plan = {"key": key, "sender": sender, "to": to, "cc": cc, "bcc": bcc, "everyone": everyone, "subject": subject, "body": body,
            "message_id": mid, "in_reply_to": reply, "attachments": attachments}
    message_bytes(plan, mail, None)      # the message is built and read back now: a text that would not arrive as approved is refused here
    would = {
        "envelope": {"from": sender, "to": everyone},
        "headers": {"From": sender, "To": ", ".join(to), "Cc": ", ".join(cc) if cc else None, "Subject": subject, "Message-ID": mid,
                    "In-Reply-To": reply},
        "body": body, "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(), "body_bytes": len(body.encode("utf-8")),
        "attachments": [{"name": n, "media_type": t, "bytes": len(d), "sha256": hashlib.sha256(d).hexdigest()} for n, t, d in attachments],
        "idempotency_key": key,
        "wire": expected_view(plan),
    }
    return {**plan, "would": would, "would_sha256": mail.digest(would)}


def expected_view(plan: dict) -> dict:
    """What the built message must say when it is read back (providers/_email.py inspect_message): the headers, the text and the attachments."""
    headers = {"From": plan["sender"], "To": ", ".join(plan["to"]), "Subject": plan["subject"], "Message-ID": plan["message_id"]}
    if plan["cc"]:
        headers["Cc"] = ", ".join(plan["cc"])
    if plan["in_reply_to"]:
        headers["In-Reply-To"] = headers["References"] = plan["in_reply_to"]
    return {"headers": headers, "text_sha256": hashlib.sha256(plan["body"].rstrip("\n").encode("utf-8")).hexdigest(),
            "attachments": [[name, kind, hashlib.sha256(data).hexdigest()] for name, kind, data in plan["attachments"]]}


def message_bytes(plan: dict, mail, date) -> bytes:
    """The message as it goes on the wire: built from the checked plan, with the Date `date` (None: none, for the dry run). No Bcc header.
    The bytes are read back as a receiving library reads them, and they must say exactly what the plan says (the headers, the text, the
    attachments) and hold no other header, part or line end: a mail library decodes some texts (an encoded word) into more than was
    approved, and this is the check that no such text goes out. ProviderError usage otherwise."""
    try:
        msg = mail.build_message(from_addr=plan["sender"], to=plan["to"], cc=plan["cc"], subject=plan["subject"], body=plan["body"],
                                 attachments=plan["attachments"], message_id_value=plan["message_id"], in_reply_to=plan["in_reply_to"],
                                 date=date)
        data = msg.as_bytes()
        view = mail.inspect_message(data)
    except (mail.EmailError, ValueError, TypeError, UnicodeError) as e:
        raise ProviderError(f"the message cannot be built: {getattr(e, 'reason', e.__class__.__name__)}", EXIT_USAGE) from None
    if view != expected_view(plan):
        wanted = expected_view(plan)
        if {k: v for k, v in view["headers"].items() if k != "Subject"} == {k: v for k, v in wanted["headers"].items() if k != "Subject"} \
                and view["text_sha256"] == wanted["text_sha256"] and view["attachments"] == wanted["attachments"]:
            raise ProviderError("the subject could not be encoded exactly (read back, it differs from the one approved): write it with fewer special "
                                "characters or spaces in a row, or shorter; nothing is sent", EXIT_USAGE)
        raise ProviderError("the message built is not the message approved (read back, its headers, text or attachments differ): nothing is sent",
                            EXIT_USAGE)
    if len(data) > MESSAGE_MAX:
        raise ProviderError(f"the message is {len(data)} bytes, over the {MESSAGE_MAX} most servers take", EXIT_USAGE)
    return data


# --- send ----------------------------------------------------------------------------------------------------------------------------


def short(text, limit: int = 700) -> str:
    return " ".join(str(text or "").split())[:limit]


def connect_smtp(settings: dict, mail, password: str):
    """A logged-in SMTP connection. The password is sent only after TLS. A refused login is not-configured (exit 3)."""
    try:
        security = mail.security_for("smtp", settings["smtp_host"], int(settings.get("smtp_port") or 465), settings.get("smtp_security"))
    except (mail.EmailError, ValueError) as e:
        raise ProviderError(str(getattr(e, "reason", e)), EXIT_USAGE) from None
    try:
        server = mail.smtp_connect(settings["smtp_host"], int(settings.get("smtp_port") or 465), security, timeout())
    except mail.TlsError as e:
        raise ProviderError(e.reason, EXIT_NOT_CONFIGURED) from None
    except (OSError, smtplib.SMTPException) as e:
        raise ProviderError(f"cannot reach the SMTP server ({e.__class__.__name__})", EXIT_SERVICE) from None
    try:
        server.login(settings.get("username") or settings["from"], password)
    except smtplib.SMTPAuthenticationError:
        close(server)
        raise ProviderError("the SMTP server refused the login of the outbox account: check the app password", EXIT_NOT_CONFIGURED) from None
    except (OSError, smtplib.SMTPException) as e:
        close(server)
        raise ProviderError(f"the SMTP login failed ({e.__class__.__name__})", EXIT_SERVICE) from None
    return server


def close(server) -> None:
    try:
        server.quit()
    except Exception:
        try:
            server.close()
        except Exception:
            pass


def connect_imap(settings: dict, mail, password: str):
    if not settings.get("imap_host") or not settings.get("sent_folder"):
        raise ProviderError("no Sent folder is configured (setup --imap-host and --sent-folder): the earlier attempt cannot be looked up",
                            EXIT_NOT_CONFIGURED)
    try:
        port = int(settings.get("imap_port") or 993)
        security = mail.security_for("imap", settings["imap_host"], port, "plain" if mail.test_plain() else None)
    except (mail.EmailError, ValueError) as e:
        raise ProviderError(str(getattr(e, "reason", e)), EXIT_USAGE) from None
    try:
        imap = mail.imap_connect(settings["imap_host"], port, security, timeout())
        imap.login(settings.get("username") or settings["from"], password)
    except mail.TlsError as e:
        raise ProviderError(e.reason, EXIT_NOT_CONFIGURED) from None
    except imaplib.IMAP4.error:
        raise ProviderError("the IMAP server refused the login of the outbox account: check the app password", EXIT_NOT_CONFIGURED) from None
    except (OSError, ssl.SSLError) as e:
        raise ProviderError(f"cannot reach the IMAP server ({e.__class__.__name__})", EXIT_SERVICE) from None
    return imap


def lookup_message(settings: dict, mail, password: str, message_id: str) -> int:
    """How many messages of the configured Sent folder carry this Message-ID: EXAMINE (read only), UID SEARCH, LOGOUT. Nothing is changed."""
    imap = connect_imap(settings, mail, password)
    try:
        if not FOLDER_NAME.fullmatch(settings["sent_folder"]):
            raise ProviderError("the Sent folder name is plain letters, digits, spaces and . _ / [ ] -", EXIT_USAGE)
        kind, _ = imap.select('"' + settings["sent_folder"] + '"', readonly=True)
        if kind != "OK":
            raise ProviderError("the Sent folder cannot be opened", EXIT_SERVICE)
        kind, found = imap.uid("SEARCH", None, "HEADER", "Message-ID", '"' + message_id + '"')
        if kind != "OK":
            raise ProviderError("the Sent folder search failed", EXIT_SERVICE)
        return len((found[0] or b"").split()) if found else 0
    except ProviderError:
        raise
    except Exception as e:
        raise ProviderError(f"the Sent folder lookup failed ({e.__class__.__name__})", EXIT_SERVICE) from None
    finally:
        try:
            imap.logout()
        except Exception:
            pass


def result(plan: dict, replayed: bool, size: int = 0) -> dict:
    return {"sent": True, "replayed": replayed, "message_id": plan["message_id"], "idempotency_key": plan["key"],
            "recipients": len(plan["everyone"]), "attachments": len(plan["attachments"]), "bytes": size}


def claim(plan: dict) -> str:
    """Record the key `pending` before the first connection. "new", "done" (sent already) or "pending" (an earlier attempt's outcome is
    not known). A key used for another message is a usage error."""
    with ledger_locked() as ledger:
        entry = ledger["keys"].get(plan["key"])
        if entry is None:
            ledger["keys"][plan["key"]] = {"status": "pending", "message_id": plan["message_id"], "payload_sha256": plan["would_sha256"],
                                           "recipients": len(plan["everyone"]), "created_at": now_iso()}
            return "new"
        if entry.get("payload_sha256") != plan["would_sha256"]:
            raise ProviderError(f"the key {plan['key']} was used for another e-mail: a key is one e-mail", EXIT_USAGE)
        return "done" if entry.get("status") == "done" else "pending"


def settle(key: str, status: str) -> None:
    """done: record the send. released: forget the key (nothing was sent), so the same e-mail may be tried again."""
    with ledger_locked() as ledger:
        entry = ledger["keys"].get(key)
        if entry is None:
            return
        if status == "done":
            entry["status"], entry["done_at"] = "done", now_iso()
        else:
            del ledger["keys"][key]


def record_done(key: str) -> None:
    """Record the key done after the e-mail was sent. A ledger that cannot be written then does not turn a sent e-mail into a failure
    (exit 1 means nothing was sent): the key stays pending, and the next send with it finds the message in the Sent folder."""
    try:
        settle(key, "done")
    except (ProviderError, OSError) as e:
        log(f"warning: the e-mail was sent, and the ledger could not record it ({short(e, 200)}): the key {key} stays pending")


def cmd_send(args) -> int:
    mail = helpers()
    plan = plan_of(args, mail)
    data = message_bytes(plan, mail, None if args.dry_run else datetime.datetime.now(datetime.timezone.utc))      # built and read back before anything is recorded or opened
    if args.dry_run:
        print(json.dumps({"dry_run": True, "would": plan["would"], "would_sha256": plan["would_sha256"],
                          "ledger": (ledger_peek(plan["key"]) or {}).get("status", "absent")}, sort_keys=True))
        return EXIT_OK
    settings = load_settings()
    if mail.address_key(plan["sender"]) != mail.address_key(settings["from"]):
        raise ProviderError("this machine has one outbox account and --from is not it: run setup again to change it", EXIT_NOT_CONFIGURED)
    password = load_password()
    state = claim(plan)
    if state == "done":
        print(json.dumps(result(plan, True), sort_keys=True))
        return EXIT_OK
    if state == "pending":
        try:
            found = lookup_message(settings, mail, password, plan["message_id"])
        except ProviderError as e:
            raise ProviderError(f"an earlier attempt with this key did not say whether the e-mail was sent, and it cannot be looked up "
                                f"({e}): look in the Sent folder, then run resolve --idempotency-key {plan['key']} --sent or --not-sent",
                                EXIT_UNKNOWN) from None
        if not found:
            raise ProviderError("an earlier attempt with this key did not say whether the e-mail was sent, and it is not in the Sent folder: "
                                "nothing is sent again until you settle the key. Some hosts do not file mail sent over SMTP in the Sent folder, and "
                                "then 'not found' says nothing: check with a recipient or the host's log before you run "
                                f"resolve --idempotency-key {plan['key']} --not-sent, which can lead to a second copy; --sent records it as delivered",
                                EXIT_UNKNOWN)
        record_done(plan["key"])
        print(json.dumps(result(plan, True), sort_keys=True))
        return EXIT_OK
    try:
        server = connect_smtp(settings, mail, password)
    except ProviderError:
        settle(plan["key"], "released")
        raise
    except Exception as e:      # nothing was handed to a server: the key is free again
        settle(plan["key"], "released")
        raise ProviderError(f"the SMTP connection failed ({e.__class__.__name__}): nothing was sent", EXIT_SERVICE) from None
    started = False
    try:
        code, reply = server.mail(plan["sender"])
        if code != 250:
            raise ProviderError(f"the server refused the sender ({code}): nothing was sent", EXIT_SERVICE)
        for address in plan["everyone"]:
            code, reply = server.rcpt(address)
            if code not in (250, 251):
                try:
                    server.rset()
                except Exception:
                    pass
                raise ProviderError(f"the server refused the recipient {address} ({code}): nothing was sent", EXIT_SERVICE)
        started = True
        code, reply = server.data(data)
        if code != 250:
            raise ProviderError(f"the server did not accept the message ({code}): nothing was sent", EXIT_SERVICE)
    except smtplib.SMTPDataError as e:      # refused at DATA, before any byte of the message
        settle(plan["key"], "released")
        close(server)
        raise ProviderError(f"the server refused to take the message ({e.smtp_code}): nothing was sent", EXIT_SERVICE) from None
    except ProviderError:
        settle(plan["key"], "released")
        close(server)
        raise
    except Exception as e:      # smtplib.SMTPException, OSError, ssl.SSLError, a timeout, or anything else
        if not started:
            settle(plan["key"], "released")
            close(server)
            raise ProviderError(f"the SMTP exchange failed before the message was sent ({e.__class__.__name__}): nothing was sent",
                                EXIT_SERVICE) from None
        # The message was handed over and the answer was lost: the key stays pending, and the next send looks in the Sent folder first.
        raise ProviderError(f"the answer to the message was lost ({e.__class__.__name__}): the e-mail may or may not have been sent. "
                            f"Sending again with the same key looks in the Sent folder first; or resolve --idempotency-key {plan['key']}",
                            EXIT_UNKNOWN) from None
    record_done(plan["key"])
    close(server)
    print(json.dumps(result(plan, False, len(data)), sort_keys=True))
    return EXIT_OK


# --- resolve, lookup, setup, check ---------------------------------------------------------------------------------------------------


def cmd_resolve(args) -> int:
    key = args.idempotency_key
    if not KEY.fullmatch(key or ""):
        raise ProviderError("--idempotency-key is letters, digits, dots, hyphens and underscores", EXIT_USAGE)
    status = "done" if args.sent else "released"
    if args.dry_run:
        entry = ledger_peek(key)
        if not entry or entry.get("status") != "pending":
            raise ProviderError(f"the key {key} is not pending: nothing to resolve", EXIT_USAGE)
        print(json.dumps({"dry_run": True, "would": {"idempotency_key": key, "record": "sent" if args.sent else "not sent"}}, sort_keys=True))
        return EXIT_OK
    with ledger_locked() as ledger:
        entry = ledger["keys"].get(key)
        if not entry or entry.get("status") != "pending":
            raise ProviderError(f"the key {key} is not pending: nothing to resolve", EXIT_USAGE)
        if status == "done":
            entry["status"], entry["done_at"], entry["resolved_by"] = "done", now_iso(), "person"
        else:
            del ledger["keys"][key]
    print(json.dumps({"resolved": True, "idempotency_key": key, "recorded": "sent" if args.sent else "not sent"}, sort_keys=True))
    return EXIT_OK


def cmd_lookup(args) -> int:
    mail = helpers()
    if not mail.MESSAGE_ID.fullmatch(args.message_id or ""):
        raise ProviderError("--message-id is <oh.<32 hex>@domain>", EXIT_USAGE)
    settings = load_settings()
    found = lookup_message(settings, mail, load_password(), args.message_id)
    print(json.dumps({"found": found > 0, "count": found, "folder": settings["sent_folder"], "message_id": args.message_id}, sort_keys=True))
    return EXIT_OK


def cmd_setup(args) -> int:
    mail = helpers()
    try:
        sender = mail.normalize_address(args.sender)
        smtp_port = args.smtp_port or 465
        imap_port = args.imap_port or 993
        security = mail.security_for("smtp", args.smtp_host, smtp_port, args.smtp_security)
        settings = {"from": sender, "username": args.username or sender, "smtp_host": args.smtp_host, "smtp_port": smtp_port,
                    "smtp_security": security}
        if args.imap_host:
            mail.security_for("imap", args.imap_host, imap_port, "plain" if mail.test_plain() else None)
            if not args.sent_folder or not FOLDER_NAME.fullmatch(args.sent_folder):
                raise mail.EmailError("--sent-folder names the Sent folder (plain letters, digits, spaces and . _ / [ ] -)")
            settings.update(imap_host=args.imap_host, imap_port=imap_port, sent_folder=args.sent_folder)
        if args.username:
            mail.header_text(args.username, "--username")
    except mail.EmailError as e:
        raise ProviderError(e.reason, EXIT_USAGE) from None
    write_private_json(os.path.join(folder(), SETTINGS), settings)
    print(json.dumps({"ok": True, "settings": settings}, sort_keys=True))
    return EXIT_OK


def cmd_check() -> int:
    mail = helpers()
    settings = load_settings()
    password = load_password()
    server = connect_smtp(settings, mail, password)
    close(server)
    imap_ok = False
    if settings.get("imap_host"):
        imap = connect_imap(settings, mail, password)
        try:
            if imap.select('"' + settings["sent_folder"] + '"', readonly=True)[0] != "OK":
                raise ProviderError("the Sent folder cannot be opened", EXIT_SERVICE)
            imap_ok = True
        finally:
            try:
                imap.logout()
            except Exception:
                pass
    print(json.dumps({"ok": True, "from": settings["from"], "smtp": True, "imap": imap_ok}, sort_keys=True))
    return EXIT_OK


VERBS = {"send": cmd_send, "resolve": cmd_resolve, "lookup": cmd_lookup, "setup": cmd_setup}

HELP_EPILOG = """\
verbs:
  send     send one e-mail: --from <a> --to <a>... [--cc <a>...] [--bcc <a>...] --subject-file <f> --body-file <f>
           [--attach <path>=<name>]... [--in-reply-to <id>] --message-id <oh.hex@domain> --idempotency-key <k>
           (--dry-run | --confirmed). The recipients are exactly the flags (at most 20 in all); a Bcc is never a header.
  resolve  settle a key left pending: --idempotency-key <k> (--sent | --not-sent) (--dry-run | --confirmed)
  lookup   is this Message-ID in the configured Sent folder? --message-id <id> (read only)
  setup    --from <a> --smtp-host <h> [--smtp-port 465|587] [--imap-host <h> --sent-folder <name>] [--username <u>]
  --check  log in to SMTP (and IMAP, when set up) and print {"ok": true, ...}; sends nothing

environment: MAILER_SMTP_PASSWORD (or the OS secret store, store username mailer-smtp), OPENHORA_STATE_DIR.
Tests only: OPENHORA_MAIL_TEST_PLAIN=1 allows a connection without TLS to a loopback host.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="smtp.py", description=__doc__.split("\n\n")[0], epilog=HELP_EPILOG,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="verify the settings and the logins; send nothing")
    verbs = parser.add_subparsers(dest="verb")
    send = verbs.add_parser("send", help="send one e-mail")
    send.add_argument("--from", dest="sender", required=True)
    send.add_argument("--to", nargs="+", required=True)
    send.add_argument("--cc", nargs="+", default=[])
    send.add_argument("--bcc", nargs="+", default=[])
    send.add_argument("--subject-file", required=True)
    send.add_argument("--body-file", required=True)
    send.add_argument("--attach", action="append", default=[])
    send.add_argument("--in-reply-to")
    send.add_argument("--message-id", required=True)
    send.add_argument("--idempotency-key", required=True)
    mode = send.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--confirmed", action="store_true")
    settle_parser = verbs.add_parser("resolve", help="settle a key left pending")
    settle_parser.add_argument("--idempotency-key", required=True)
    outcome = settle_parser.add_mutually_exclusive_group(required=True)
    outcome.add_argument("--sent", action="store_true")
    outcome.add_argument("--not-sent", action="store_true")
    mode = settle_parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--confirmed", action="store_true")
    find = verbs.add_parser("lookup", help="is this Message-ID in the Sent folder")
    find.add_argument("--message-id", required=True)
    setup = verbs.add_parser("setup", help="write the settings of this machine's outbox account")
    setup.add_argument("--from", dest="sender", required=True)
    setup.add_argument("--smtp-host", required=True)
    setup.add_argument("--smtp-port", type=int)
    setup.add_argument("--smtp-security", choices=("ssl", "starttls", "plain"))
    setup.add_argument("--imap-host")
    setup.add_argument("--imap-port", type=int)
    setup.add_argument("--sent-folder")
    setup.add_argument("--username")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return EXIT_OK if e.code in (0, None) else EXIT_USAGE
    try:
        if args.check:
            if args.verb:
                raise ProviderError("--check takes no verb", EXIT_USAGE)
            return cmd_check()
        if args.verb in VERBS:
            return VERBS[args.verb](args)
        parser.print_usage(sys.stderr)
        return EXIT_USAGE
    except ProviderError as e:
        log(f"error: {short(e)}")
        return e.code


if __name__ == "__main__":
    sys.exit(main())
