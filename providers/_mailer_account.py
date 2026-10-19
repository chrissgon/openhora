#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""What the two mailers of the person's own account share (package W2, SPEC-SECRETARY-WRITES 3.2): the Gmail mailer (providers/mailer/gmail.py) and the
Outlook mailer (providers/mailer/outlook.py), the second and third implementations of the class sender:email beside the SMTP outbox
(providers/mailer/smtp.py). Each loads this file by path. A name with an underscore is never listed as an implementation by providers/resolve.py, so this
file is a module, not a provider.

The contract of the class (providers/CONTRACT.md, row `sender:email`) is the SMTP outbox's, and these two keep it: `send` with the same flags (plus
`--thread-id`, `--references` and `--reply-id`), `--dry-run` reads no credential and opens no connection, the recipients are exactly the flags (To + Cc + Bcc,
all or none, at most 20 in all), at most one e-mail per idempotency key, exit 1 guarantees nothing was sent, exit 4 says the outcome is not known. What differs
is the account: the From address must be the address of the account token (the record's `account`, and the service's own profile), and the lookup after a lost
answer proves identity by CONTENT: the Message-ID the message carries (Gmail: the one this code put in it; Outlook: the one the service assigned to the draft,
recorded in the ledger before the message is sent), never by size or by time.

  ProviderError, Lost            the error with an exit code; Lost is exit 4 (the request may have landed)
  hold, scrub, one_line          every credential this process held is replaced by <hidden> in any text it prints; third-party text on one line
  helpers                        providers/_email.py, by path
  ledger_peek, claim, mark, settle, ledger_state   the ledger of a mailer, `<state>/mailer-<implementation>/ledger.json` (folder 0700, file 0600): a key is
                                 `pending` (with a phase) before the first request that can send, and `done` after the answer
  plan_of                        the e-mail the flags describe, checked whole, and its preview: nothing is read from the network or a credential
  message_bytes                  the MIME message (Gmail): built from the checked plan, read back, the Date added at send
  cmd_resolve                    `resolve --idempotency-key <k> (--sent | --not-sent) (--dry-run | --confirmed)`
  add_send_flags, add_verb_flags the flags of `send`, `resolve` and `lookup`, once for both mailers

Standard library only; runs on Python 3.9. The service's errors, its addresses and its token are each mailer's own.
"""
from __future__ import annotations

import contextlib
import datetime
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
import time
from pathlib import Path

try:      # POSIX only: without it the ledger keeps its in-process rules and no file lock
    import fcntl
except ImportError:     # pragma: no cover (Windows)
    fcntl = None

EXIT_OK, EXIT_SERVICE, EXIT_USAGE, EXIT_NOT_CONFIGURED, EXIT_UNKNOWN = 0, 1, 2, 3, 4
STATE_ENV = "OPENHORA_STATE_DIR"
LEDGER, LOCK = "ledger.json", "ledger.lock"
IMPLEMENTATIONS = ("gmail", "outlook")
MAX_RECIPIENTS = 20
BODY_MAX = 100 * 1024
SUBJECT_MAX = 998
KEY = re.compile(r"[A-Za-z0-9._-]{1,128}")
THREAD_ID = re.compile(r"[A-Za-z0-9_=-]{1,200}")
PROVIDER_ID = re.compile(r"[A-Za-z0-9=_+-]{1,700}")
LOCK_SECONDS = 10.0
RETAKE_AFTER_SECONDS = 150      # a pending key in a phase before the send is taken again only when it has not moved for this long: two HTTP timeouts (60 s each) and a margin, so a live attempt is never run over
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
PHASES = ("claimed", "drafted", "sending")

_SECRET_VALUES: list = []     # every credential this process held: replaced by <hidden> in any text before it is printed


class ProviderError(Exception):
    """An error with an exit code and a one-line message (and, for an answer of the service, its status). The argument order is the one providers/_google.py
    gives its `error` class."""

    def __init__(self, message, code=EXIT_SERVICE, status=None):
        super().__init__(message)
        self.code = code
        self.status = status


class Lost(ProviderError):
    """The request may have reached the service and its answer was lost: exit 4."""

    def __init__(self, message, status=None):
        super().__init__(message, EXIT_UNKNOWN, status)


def hold(*values) -> None:
    """Remember credentials so that scrub() can remove them from any text this process prints."""
    for value in values:
        if isinstance(value, str) and value and value not in _SECRET_VALUES:
            _SECRET_VALUES.append(value)


def scrub(text) -> str:
    text = str(text)
    for value in sorted(_SECRET_VALUES, key=len, reverse=True):
        text = text.replace(value, "<hidden>")
    return text


def one_line(text, limit: int = 300) -> str:
    """Third-party text on one line: control characters removed, the space folded, cut at `limit`, no credential in it."""
    return scrub(" ".join(CONTROL_RE.sub(" ", str(text if text is not None else "")).split()))[:limit]


def log(message: str) -> None:
    print(message, file=sys.stderr)


def emit(obj: dict) -> int:
    print(json.dumps(obj, sort_keys=True, ensure_ascii=False))
    return EXIT_OK


def helpers():
    """providers/_email.py, by path: next to this file first (the workbench), so a test that copies both finds it."""
    path = Path(__file__).resolve().parent / "_email.py"
    if not path.is_file():
        raise ProviderError("providers/_email.py is not next to this file", EXIT_NOT_CONFIGURED)
    cached = sys.modules.get("providers_email_mailer_account")
    if cached is not None and getattr(cached, "__file__", None) == str(path):
        return cached
    spec = importlib.util.spec_from_file_location("providers_email_mailer_account", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha(data) -> str:
    return hashlib.sha256(data if isinstance(data, bytes) else str(data).encode("utf-8")).hexdigest()


# --- the state folder and the ledger -------------------------------------------------------------------------------------------------


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
        raise ProviderError(f"the {what} {path} is open to other users (mode {stat.S_IMODE(found.st_mode):04o}); run chmod 700 on it", EXIT_NOT_CONFIGURED)
    return path


def folder(implementation: str, create: bool = True):
    """<state>/mailer-<implementation>, made and checked; None when it does not exist and `create` is False (a dry run makes nothing)."""
    if implementation not in IMPLEMENTATIONS:
        raise ProviderError(f"{implementation!r} is not a mailer of the person's own account", EXIT_USAGE)
    base = state_dir()
    path = os.path.join(base, f"mailer-{implementation}")
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


@contextlib.contextmanager
def ledger_locked(implementation: str):
    """The ledger under an exclusive file lock: yields the dict, written back when the block ends without an error."""
    base = folder(implementation)
    fd = os.open(os.path.join(base, LOCK), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        if fcntl is not None:
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


def ledger_peek(implementation: str, key: str):
    """The entry of a key, read without writing anything or making any folder (a dry run)."""
    found = folder(implementation, create=False)
    if not found:
        return None
    return (read_json(os.path.join(found, LEDGER), {"keys": {}}).get("keys") or {}).get(key)


def ledger_state(implementation: str, key: str) -> str:
    """What a dry run prints under `ledger`: absent, pending or done."""
    entry = ledger_peek(implementation, key)
    return (entry or {}).get("status", "absent")


def _age(entry: dict) -> float:
    """Seconds since the entry was made or last moved (created_at, updated_at); a time that cannot be read is infinitely young, so that it is never taken over."""
    newest = None
    for name in ("created_at", "updated_at"):
        try:
            when = datetime.datetime.strptime(str(entry.get(name)), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            continue
        newest = when if newest is None or when > newest else newest
    return float("-inf") if newest is None else (datetime.datetime.now(datetime.timezone.utc) - newest).total_seconds()


def claim(implementation: str, plan: dict, phase: str) -> tuple:
    """Record the key `pending` (in `phase`) before the first request that can send. Returns (state, entry): "new" (the key is ours now), "done" (sent already),
    "pending" (an earlier attempt may have sent it: its outcome is not known) or "busy" (another attempt holds the key in a phase before the send and has moved
    within RETAKE_AFTER_SECONDS: this attempt does nothing). A pending key in a phase before the send (`claimed`, `drafted`) sent nothing and is taken again, but
    only once it has been still for RETAKE_AFTER_SECONDS: two live attempts never both hold it. A key used for another e-mail is a usage error."""
    with ledger_locked(implementation) as ledger:
        entry = ledger["keys"].get(plan["key"])
        fresh = {"status": "pending", "phase": phase, "message_id": plan["message_id"], "payload_sha256": plan["would_sha256"],
                 "recipients": len(plan["everyone"]), "created_at": now_iso()}
        if entry is None:
            ledger["keys"][plan["key"]] = fresh
            return "new", fresh
        if entry.get("payload_sha256") != plan["would_sha256"]:
            raise ProviderError(f"the key {plan['key']} was used for another e-mail: a key is one e-mail", EXIT_USAGE)
        if entry.get("status") == "done":
            return "done", dict(entry)
        if entry.get("phase") in ("claimed", "drafted"):
            if _age(entry) < RETAKE_AFTER_SECONDS:
                return "busy", dict(entry)
            ledger["keys"][plan["key"]] = fresh
            return "new", fresh
        return "pending", dict(entry)


def mark(implementation: str, key: str, **fields) -> None:
    """Add facts to a pending entry (its phase, the draft's id, the id the service gave the message)."""
    with ledger_locked(implementation) as ledger:
        entry = ledger["keys"].get(key)
        if entry is not None and entry.get("status") == "pending":
            entry.update({k: v for k, v in fields.items() if isinstance(v, str)})
            entry["updated_at"] = now_iso()


def settle(implementation: str, key: str, status: str, **fields) -> None:
    """done: record the send. released: forget the key (nothing was sent), so the same e-mail may be tried again."""
    with ledger_locked(implementation) as ledger:
        entry = ledger["keys"].get(key)
        if entry is None:
            return
        if status == "done":
            entry["status"], entry["done_at"] = "done", now_iso()
            entry.update({k: v for k, v in fields.items() if isinstance(v, str)})
        else:
            del ledger["keys"][key]


def record_done(implementation: str, key: str, **fields) -> None:
    """Record the key done after the e-mail was sent. A ledger that cannot be written then does not turn a sent e-mail into a failure (exit 1 means nothing
    was sent): the key stays pending, and the next send with it finds the message."""
    try:
        settle(implementation, key, "done", **fields)
    except (ProviderError, OSError) as e:
        log(f"warning: the e-mail was sent, and the ledger could not record it ({one_line(e, 200)}): the key {key} stays pending")


def cmd_resolve(args, implementation: str) -> int:
    key = args.idempotency_key
    if not KEY.fullmatch(key or ""):
        raise ProviderError("--idempotency-key is letters, digits, dots, hyphens and underscores", EXIT_USAGE)
    recorded = "sent" if args.sent else "not sent"
    if args.dry_run:
        entry = ledger_peek(implementation, key)
        if not entry or entry.get("status") != "pending":
            raise ProviderError(f"the key {key} is not pending: nothing to resolve", EXIT_USAGE)
        return emit({"dry_run": True, "would": {"idempotency_key": key, "record": recorded}})
    with ledger_locked(implementation) as ledger:
        entry = ledger["keys"].get(key)
        if not entry or entry.get("status") != "pending":
            raise ProviderError(f"the key {key} is not pending: nothing to resolve", EXIT_USAGE)
        if args.sent:
            entry["status"], entry["done_at"], entry["resolved_by"] = "done", now_iso(), "person"
        else:
            del ledger["keys"][key]
    return emit({"resolved": True, "idempotency_key": key, "recorded": recorded})


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


def read_attachment(spec: str, mail, total_max: int) -> tuple:
    """(name, media type, bytes) of one `--attach <path>=<name>`: a regular file that is not a link, a plain name with an extension of the closed list."""
    path, sep, name = spec.rpartition("=")
    if not sep or not path:
        raise ProviderError("--attach is <path>=<name>", EXIT_USAGE)
    try:
        name = mail.attachment_name(name)
    except mail.EmailError as e:
        raise ProviderError(e.reason, EXIT_USAGE) from None
    return name, mail.media_type(name), read_regular(path, f"the attachment {name}", total_max)


def addresses(values, what: str, mail) -> list:
    out = []
    for value in values or []:
        try:
            out.append(mail.normalize_address(value))
        except mail.EmailError as e:
            raise ProviderError(f"{what}: {e.reason}", EXIT_USAGE) from None
    return out


def plan_of(args, mail, *, total_max: int, with_wire: bool, reply_id_required: bool = False) -> dict:
    """The e-mail the flags describe, checked whole: nothing is read from the network or a credential. Returns the plan and its preview (`would`, and
    `would_sha256`, the hash the runtime compares). `total_max` is the most the attachments may weigh together for this service; `with_wire` says whether
    the plan is sent as a MIME message (Gmail), which is then built and read back here (a text that would not arrive as approved is refused)."""
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
        refs = [mail.reference_id(r) for r in (args.references or [])]
    except mail.EmailError as e:
        raise ProviderError(e.reason, EXIT_USAGE) from None
    if refs and not reply:
        raise ProviderError("--references names the chain of a reply: it needs --in-reply-to", EXIT_USAGE)
    if reply:
        refs = refs or [reply]
        if refs[-1] != reply:
            raise ProviderError("--references ends with the message --in-reply-to names", EXIT_USAGE)
    thread = args.thread_id
    if thread is not None and (not THREAD_ID.fullmatch(thread) or not reply):
        raise ProviderError("--thread-id is the id of the conversation a reply joins (letters, digits, = _ -), and goes with --in-reply-to", EXIT_USAGE)
    reply_id = args.reply_id
    if reply_id is not None and (not PROVIDER_ID.fullmatch(reply_id) or not reply):
        raise ProviderError("--reply-id is the service's id of the message being answered (letters, digits, = _ + -), and goes with --in-reply-to", EXIT_USAGE)
    if reply_id_required and reply and reply_id is None:
        raise ProviderError("a reply needs --reply-id, the service's id of the message being answered", EXIT_USAGE)
    if not body.strip() or "\x00" in body or "\r" in body:
        raise ProviderError("the body is non-empty text without a NUL character and with line breaks written \\n (no \\r)", EXIT_USAGE)
    attachments = [read_attachment(spec, mail, total_max) for spec in args.attach or []]
    if sum(len(a[2]) for a in attachments) > total_max:
        raise ProviderError(f"the attachments are over {total_max} bytes together, the most this service takes here", EXIT_USAGE)
    if len({a[0].lower() for a in attachments}) != len(attachments):
        raise ProviderError("two attachments have the same name", EXIT_USAGE)
    plan = {"key": key, "sender": sender, "to": to, "cc": cc, "bcc": bcc, "everyone": everyone, "subject": subject, "body": body, "message_id": mid,
            "in_reply_to": reply, "references": refs, "thread_id": thread, "reply_id": reply_id, "attachments": attachments}
    would = {
        "envelope": {"from": sender, "to": everyone},
        "headers": {"From": sender, "To": ", ".join(to), "Cc": ", ".join(cc) if cc else None, "Subject": subject, "Message-ID": mid,
                    "In-Reply-To": reply, "References": " ".join(refs) if refs else None},
        "body": body, "body_sha256": sha(body), "body_bytes": len(body.encode("utf-8")),
        "attachments": [{"name": n, "media_type": t, "bytes": len(d), "sha256": sha(d)} for n, t, d in attachments],
        "idempotency_key": key, "thread_id": thread, "reply_id": reply_id,
    }
    if with_wire:
        message_bytes(plan, mail, None)      # built and read back now
        would["wire"] = expected_view(plan)
    return {**plan, "would": would}


def finish_plan(plan: dict, mail, requests: list, service: str) -> dict:
    """The plan with its requests in the preview and the hash of the whole preview: what the dry run prints and the runtime stores."""
    would = {**plan["would"], "service": service, "requests": requests}
    return {**plan, "would": would, "would_sha256": mail.digest(would)}


def expected_view(plan: dict) -> dict:
    """What the built message must say when it is read back (providers/_email.py inspect_message): the headers, the text and the attachments."""
    headers = {"From": plan["sender"], "To": ", ".join(plan["to"]), "Subject": plan["subject"], "Message-ID": plan["message_id"]}
    if plan["cc"]:
        headers["Cc"] = ", ".join(plan["cc"])
    if plan["in_reply_to"]:
        headers["In-Reply-To"] = plan["in_reply_to"]
        headers["References"] = " ".join(plan["references"])
    return {"headers": headers, "text_sha256": sha(plan["body"].rstrip("\n")),
            "attachments": [[name, kind, sha(data)] for name, kind, data in plan["attachments"]]}


def message_bytes(plan: dict, mail, date) -> bytes:
    """The message as it goes on the wire: built from the checked plan, with the Date `date` (None: none, for the dry run). No Bcc header. The bytes are read
    back as a receiving library reads them, and they must say exactly what the plan says (the headers, the text, the attachments) and hold no other header,
    part or line end. ProviderError usage otherwise."""
    try:
        msg = mail.build_message(from_addr=plan["sender"], to=plan["to"], cc=plan["cc"], subject=plan["subject"], body=plan["body"],
                                 attachments=plan["attachments"], message_id_value=plan["message_id"], in_reply_to=plan["in_reply_to"], date=date,
                                 references=plan["references"] or None)
        data = msg.as_bytes()
        view = mail.inspect_message(data)
    except (mail.EmailError, ValueError, TypeError, UnicodeError) as e:
        raise ProviderError(f"the message cannot be built: {getattr(e, 'reason', e.__class__.__name__)}", EXIT_USAGE) from None
    wanted = expected_view(plan)
    if view != wanted:
        if {k: v for k, v in view["headers"].items() if k != "Subject"} == {k: v for k, v in wanted["headers"].items() if k != "Subject"} \
                and view["text_sha256"] == wanted["text_sha256"] and view["attachments"] == wanted["attachments"]:
            raise ProviderError("the subject could not be encoded exactly (read back, it differs from the one approved): write it with fewer special "
                                "characters or spaces in a row, or shorter; nothing is sent", EXIT_USAGE)
        raise ProviderError("the message built is not the message approved (read back, its headers, text or attachments differ): nothing is sent", EXIT_USAGE)
    return data


def result(plan: dict, replayed: bool, size: int = 0, **more) -> dict:
    return {"sent": True, "replayed": replayed, "message_id": plan["message_id"], "idempotency_key": plan["key"], "recipients": len(plan["everyone"]),
            "attachments": len(plan["attachments"]), "bytes": size, **more}


def same_address(a, b) -> bool:
    return isinstance(a, str) and isinstance(b, str) and a.strip().lower() == b.strip().lower()


# --- the flags -----------------------------------------------------------------------------------------------------------------------


def add_send_flags(verbs) -> None:
    send = verbs.add_parser("send", help="send one e-mail from the account's own address")
    send.add_argument("--from", dest="sender", required=True)
    send.add_argument("--to", nargs="+", required=True)
    send.add_argument("--cc", nargs="+", default=[])
    send.add_argument("--bcc", nargs="+", default=[])
    send.add_argument("--subject-file", required=True)
    send.add_argument("--body-file", required=True)
    send.add_argument("--attach", action="append", default=[])
    send.add_argument("--in-reply-to")
    send.add_argument("--references", nargs="+", default=[])
    send.add_argument("--thread-id")
    send.add_argument("--reply-id")
    send.add_argument("--message-id", required=True)
    send.add_argument("--idempotency-key", required=True)
    mode = send.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--confirmed", action="store_true")


def add_verb_flags(verbs) -> None:
    settle_parser = verbs.add_parser("resolve", help="settle a key left pending")
    settle_parser.add_argument("--idempotency-key", required=True)
    outcome = settle_parser.add_mutually_exclusive_group(required=True)
    outcome.add_argument("--sent", action="store_true")
    outcome.add_argument("--not-sent", action="store_true")
    mode = settle_parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--confirmed", action="store_true")
    find = verbs.add_parser("lookup", help="is this Message-ID among the sent messages of the account")
    find.add_argument("--message-id", required=True)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
