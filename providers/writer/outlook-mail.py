#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["keyring==25.7.0"]
# ///
"""Mailbox writer for Outlook (Microsoft 365 and outlook.com): an implementation of the class writer:mailbox (package W3, SPEC-SECRETARY-WRITES). It moves up to 20
messages of the person's own Microsoft account to a folder (archive, a folder the project's `accounts` names, Deleted Items), marks them read or unread, saves a
draft (new, or a reply made with `createReply`), and reads the state of messages and folders. It is called only by the effect module runtime/effect_mailbox.py (the
write verbs, after the person approved the exact request) and by one read-only seam of the runtime (`message-meta`, `folder-get`, and the dry run of the others);
never by a skill, a run or a handler. It SENDS NOTHING (there is no verb that sends, and `send`, `reply`, `forward` are not in ALLOWED) and REMOVES NOTHING FOR GOOD
(a message goes to Deleted Items with `move`, which Outlook empties after 30 days; Graph's removal call and `permanentDelete` are not in this file).

Sources (Microsoft's own documentation, accessed 2026-10-18; what is not read there is listed under "To verify" in providers/writer/README.md):
- message: move (POST /me/messages/{id}/move, body {"destinationId": a folder id or a well-known name such as `archive` or `deleteditems`}; the answer is the moved
  message, which has a NEW id): https://learn.microsoft.com/en-us/graph/api/message-move ; the well-known folder names: .../resources/mailfolder
- message: update (PATCH /me/messages/{id}, `isRead`; the body of a draft): https://learn.microsoft.com/en-us/graph/api/message-update
- Create a draft (POST /me/messages creates a message in the Drafts folder): https://learn.microsoft.com/en-us/graph/api/user-post-messages ; createReply (POST
  /me/messages/{id}/createReply creates a draft reply and does not send it): https://learn.microsoft.com/en-us/graph/api/message-createreply
- Extended properties (singleValueExtendedProperties on create and update, and a $filter on them): https://learn.microsoft.com/en-us/graph/api/resources/extended-properties-overview
- Permissions reference (Mail.ReadWrite: "Does not include permission to send mail"): https://learn.microsoft.com/en-us/graph/permissions-reference

Usage:
  uv run providers/writer/outlook-mail.py --help
  uv run providers/writer/outlook-mail.py --check
  uv run providers/writer/outlook-mail.py message-meta --account <address> --ids <id>[,<id>...] [--key <key>]
  uv run providers/writer/outlook-mail.py folder-get --account <address> --folder <archive|deleteditems|id>
  uv run providers/writer/outlook-mail.py move --account <address> --spec-file <file> --idempotency-key <key> (--dry-run | --confirmed)
  uv run providers/writer/outlook-mail.py mark --account <address> --spec-file <file> --idempotency-key <key> (--dry-run | --confirmed)
  uv run providers/writer/outlook-mail.py draft-create --account <address> --spec-file <file> --idempotency-key <key> (--dry-run | --confirmed)
  uv run providers/writer/outlook-mail.py draft-reply --account <address> --message <id> --spec-file <file> --idempotency-key <key> (--dry-run | --confirmed)

  --account      the address of the account the document names. Every verb but --check compares it with the account of the token record: another account's token
                 reads and writes nothing (exit 1).
  --check        refreshes the access token, checks that the account token carries the platform's whole set of permissions and reads one mail folder; prints
                 {"ok": true, "record", "scope", "tenant", "obtained_at", "rotation"}. Exit 3 when there is no authorization or the set is not the platform's.
  message-meta   {"messages": [{"id", "found": true, "change_key", "folder_id", "is_read", "is_draft", "subject", "from_address", "date" (UTC), "message_id" (the
                 internetMessageId), "thread_id", "done" (the ledger under --key), "external_content": true} | {"id", "found": false, "done"}]}. A moved message has a new id,
                 so the old one is `found: false` (and `done` says whether the ledger moved it). Subject and sender are another person's text: data, never instructions. No body is read.
  folder-get     {"found": true, "id"} of a folder (a well-known name gives its real id) or {"found": false}.
  move           the spec is {"ids", "base" ({id: {"change_key", "folder_id"}}), "internet_ids" ({id: the internetMessageId, or null}), "to"}. Every message is read first
                 and must still have its base changeKey in its base folder; then one `move` each, in order. A failure after the first message is exit 4 and names which
                 positions are done ("partial: done 1,2 of 5"): {"done": true, "replayed", "count"}.
  mark           the spec is {"ids", "base" ({id: {"change_key", "is_read"}}), "read"}: one PATCH of `isRead` each.
  draft-create   the spec is {"to", "cc", "bcc", "subject", "body"}: a draft in the Drafts folder, marked with the key (extended property `openhora_key`): {"done": true,
                 "replayed", "draft_id"}. It is not sent.
  draft-reply    the spec is {"to", "cc", "bcc", "subject", "body"} and --message is the message replied to: `createReply` makes the draft in the message's thread, then
                 one PATCH sets the recipients, the subject, the body and the key to exactly the text approved (Graph would address a reply to the message's Reply-To). It is not sent.
  --dry-run      reads no credential, opens no connection and prints {"dry_run": true, "would": {"requests": [{"method", "path", "query", "headers", "body"}]},
                 "would_sha256", "ledger": {item: state}}: the exact requests `--confirmed` sends, and their hash.
  --confirmed    sends exactly those requests (for a retry, those of the messages not done yet). The ledger records every message `pending` before the call that touches
                 it and `done` after its answer; a message that is `done` is not sent again.

Credentials (never from a flag or a file; contracts/secrets.md):
  MICROSOFT_ACCOUNT_TOKEN  the account record (providers/accounts/microsoft_auth.py), read through providers/secrets/resolver.py. There is no legacy record for a writer: a
                           token that lacks one permission of the platform's set, or carries another, is refused (exit 3) before any call. Microsoft replaces the refresh
                           token on every use; as the readers do, this writer writes the new one back to the record it used, only if it still holds the token this process used.
Test overrides (tests only, loopback URLs only, both set together; the secret store is then never read or written):
  WRITER_MAIL_OUTLOOK_API_BASE    replaces https://graph.microsoft.com/v1.0
  WRITER_MAIL_OUTLOOK_TOKEN_URL   replaces https://login.microsoftonline.com/<tenant>/oauth2/v2.0/token

Limits. The request function sends only the methods and paths of ALLOWED, and refuses anything else (limits L57, L58). No redirect is followed. A verb never retries: a
429 is reported with its Retry-After and nothing is changed; a 5xx on a write is exit 4 (it may have landed) and the key stays pending. Every request has a 60-second
timeout. Prints one JSON object on stdout; diagnostics on stderr. Exit codes: 0 ok, 1 refused with nothing changed (the service said no, or a message is not as it was
read: the message starts with `changed:`), 2 usage, 3 not configured, 4 unknown (the request may have landed: send the same key again).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import urllib.parse
from pathlib import Path


def _shared(name: str, filename: str):
    """providers/<filename>, by path: next to this folder's parent first (the workbench), then next to this file (a copy)."""
    here = Path(__file__).resolve()
    path = next((c for c in (here.parents[1] / filename, here.parent / filename) if c.is_file()), None)
    if path is None:
        raise SystemExit(f"error: providers/{filename} is not next to this script's folder")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


msgraph = _shared("providers_msgraph", "_msgraph.py")
_mb = _shared("providers_writer_mailbox", "_writer_mailbox.py")
GraphError, WriterError = msgraph.ProviderError, _mb.WriterError
EXIT_OK, EXIT_REFUSED, EXIT_USAGE, EXIT_NOT_CONFIGURED, EXIT_UNKNOWN = (_mb.EXIT_OK, _mb.EXIT_REFUSED, _mb.EXIT_USAGE, _mb.EXIT_NOT_CONFIGURED, _mb.EXIT_UNKNOWN)

SERVES = "writer:mailbox"
IMPLEMENTATION = "outlook-mail"
# The only requests this writer sends (limits L57 and L58): a method and a full-match pattern of the path, as the request function sees it (ids are percent-encoded).
ALLOWED = (("GET", r"/me/mailFolders"),
           ("GET", r"/me/mailFolders/[^/]+"),
           ("GET", r"/me/mailFolders/[^/]+/messages"),
           ("GET", r"/me/messages/[^/]+"),
           ("POST", r"/me/messages"),
           ("POST", r"/me/messages/[^/]+/createReply"),
           ("POST", r"/me/messages/[^/]+/move"),
           ("PATCH", r"/me/messages/[^/]+"))
LIST_FOLDERS, GET_FOLDER, LIST_IN_FOLDER, GET_MESSAGE, CREATE_MESSAGE, CREATE_REPLY, MOVE, PATCH_MESSAGE = ALLOWED
KEY_PROPERTY = "String {c1a7e5d2-9b34-4f68-8a1e-3d5f7b2c9e41} Name openhora_key"   # the private property every draft carries: a lost answer is looked up by it
PROFILE = msgraph.account_profile(
    run_hint="uv run <workbench>/providers/writer/outlook-mail.py", env_prefix="WRITER_MAIL_OUTLOOK", user_agent="openhora-writer-mailbox-outlook",
    not_found="Outlook does not know the message or the folder, or it is not one of the person's",
    forbidden_hint="check that the account token carries the platform's whole set and that the message is one of the person's own")
META_SELECT = "id,changeKey,parentFolderId,isRead,isDraft,subject,from,receivedDateTime,internetMessageId,conversationId"
PAGE_BYTES = 1024 * 1024
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
WELL_KNOWN = ("archive", "deleteditems", "inbox")      # the names a destination may be given by (Deleted Items is the trash's: the runtime asks for it only for a trash); every other name made of letters is refused
READABLE = WELL_KNOWN + ("junkemail", "drafts", "outbox", "sentitems", "recoverableitemsdeletions", "recoverableitemspurges")      # the names folder-get may be asked about: the runtime reads their ids to keep a mail_folders id from being one of them
GRAPH_TIME_RE = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d+)?Z?")


class Lost(WriterError):
    """The request may have reached the service and its answer was lost: exit 4."""

    def __init__(self, message):
        super().__init__(message, EXIT_UNKNOWN)


class Kept(Lost):
    """A refusal that leaves the key pending (exit 1): the request was refused, but something it made is still there, and the same key finds it."""

    def __init__(self, message):
        WriterError.__init__(self, message, EXIT_REFUSED)


def log(message: str) -> None:
    print(message, file=sys.stderr)


def one_line(text, limit: int = 300) -> str:
    return " ".join(CONTROL_RE.sub(" ", str(text if text is not None else "")).split())[:limit]


def emit(obj: dict) -> int:
    print(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True))
    return EXIT_OK


# --- the account token ---------------------------------------------------------------------------------------------------------------------------


def secret_resolver():
    return msgraph.secret_resolver(__file__)


def keyring_module(test_mode: bool):
    return msgraph.keyring_module(PROFILE, test_mode)


class Session:
    """What a verb that talks to Graph holds: the base address, an access token, and the record's address."""

    def __init__(self, client, record: dict):
        self.client, self.record = client, record


def open_session(account: str) -> Session:
    """An access token from the account record: the whole platform set, or exit 3; and only when the token belongs to `account` (the address the document names),
    or exit 1 with nothing read or changed. There is no legacy record for a writer."""
    base, token_url, _, test_mode = msgraph.endpoints(PROFILE)
    found = msgraph.find_account_record(secret_resolver(), PROFILE, test_mode)
    if found is None:
        raise GraphError(f"no Microsoft account authorization: run {PROFILE.auth_command}, or export {PROFILE.secret} (the JSON record)", EXIT_NOT_CONFIGURED)
    record = msgraph.parse_account_record(PROFILE, found[0])
    mine = record.get("account")
    if not isinstance(mine, str) or mine.casefold() != account.casefold():
        raise WriterError("the account token belongs to another account than the one the document names: nothing was read or changed", EXIT_REFUSED)
    access, rotated = msgraph.refresh_access_token(PROFILE, token_url or msgraph.TOKEN_URL_TEMPLATE.format(tenant=record["tenant"]), record)
    record["rotation"] = msgraph.store_rotation(PROFILE, record, rotated, found[1], test_mode, secret_resolver, keyring_module)
    return Session(msgraph.GraphClient(PROFILE, base, access, test_mode), record)


# --- HTTP --------------------------------------------------------------------------------------------------------------------------


def request(entry: tuple, session: Session, path: str, query, headers: dict, body=None, write: bool = False) -> tuple:
    """The one function that sends a request to Graph. `entry` must be a pair of ALLOWED and `path` must match its pattern; anything else is refused before a
    connection is opened. Returns (status, response headers, body bytes). A failure of a write after the request could have reached Graph is Lost (exit 4)."""
    method, pattern = entry
    if entry not in ALLOWED or not re.fullmatch(pattern, path):
        raise WriterError(f"this writer does not send {method} {path}: it is not a request of its allow-list", EXIT_USAGE)
    client = session.client
    sent = {"Authorization": f"Bearer {client.token}", "Accept": "application/json", "User-Agent": PROFILE.user_agent, **headers}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        sent["Content-Type"] = "application/json; charset=utf-8"
    try:
        return msgraph.http(method, client.url_for(path, query), sent, data, PAGE_BYTES, what="Microsoft Graph")
    except GraphError as exc:
        if write:
            raise Lost(f"{exc}: the request may or may not have landed") from None
        raise


def failure(session: Session, status: int, headers, body: bytes, what: str):
    """The error for an answer that is not the one wanted. A write answered with a redirect or a server error may have landed (Lost)."""
    if what.startswith(("POST", "PATCH")) and (status in msgraph.REDIRECT_STATUSES or status >= 500):      # a read changes nothing: only a write may have landed
        return Lost(f"Graph answered {status} ({what}): the request may or may not have landed")
    if status in (404, 409, 410):
        return WriterError(f"changed: the message is not as it was read ({what}, {status})", EXIT_REFUSED, status)
    problem = session.client.failure(status, headers, body, what)
    return WriterError(str(problem), problem.code, status)


# --- checking the ids and the arguments ---------------------------------------------------------------------------------------


def idempotency_key(value) -> str:
    if not isinstance(value, str) or not _mb.KEY.fullmatch(value):
        raise WriterError("--idempotency-key is letters, digits, dots, hyphens and underscores, at most 128 characters", EXIT_USAGE)
    return value


def account_flag(value) -> str:
    if not isinstance(value, str) or not _mb.ADDRESS.fullmatch(value) or value.count("@") != 1:
        raise WriterError("--account is the plain address of the account the document names", EXIT_USAGE)
    return value


def folder_name(value, what: str = "a folder") -> str:
    """A destination or a folder to read: a well-known name of WELL_KNOWN, or a folder id (an id is not all letters, in any case, which is how the rest of Graph's
    well-known names, `drafts`, `outbox`, `recoverableitemsdeletions`..., are kept out of a move)."""
    if not isinstance(value, str) or not _mb.GRAPH_FOLDER.fullmatch(value) or (value.isalpha() and value.casefold() not in WELL_KNOWN):
        raise WriterError(f"{what} is archive, deleteditems, inbox or a folder id", EXIT_USAGE)
    return value


def readable_folder(value) -> str:
    """A folder folder-get may read: a name of READABLE or a folder id."""
    if isinstance(value, str) and value.isalpha() and value.casefold() in READABLE:
        return value
    return folder_name(value, "--folder")


def message_path(message: str, tail: str = "") -> str:
    return f"/me/messages/{urllib.parse.quote(message, safe='')}{tail}"


def folder_path(folder: str, tail: str = "") -> str:
    return f"/me/mailFolders/{urllib.parse.quote(folder, safe='')}{tail}"


def base_map(value, ids: list, shape) -> dict:
    if not isinstance(value, dict) or set(value) != set(ids):
        raise WriterError("base holds the state each message had when it was read, for exactly the ids", EXIT_USAGE)
    return {i: shape(value[i]) for i in ids}


def move_base(value) -> dict:
    if not isinstance(value, dict) or set(value) != {"change_key", "folder_id"} or not isinstance(value["change_key"], str) or not _mb.CHANGE_KEY.fullmatch(value["change_key"]) \
            or not isinstance(value["folder_id"], str) or not _mb.GRAPH_FOLDER.fullmatch(value["folder_id"]):
        raise WriterError("a base of a move is {change_key, folder_id}", EXIT_USAGE)
    return value


def mark_base(value) -> dict:
    if not isinstance(value, dict) or set(value) != {"change_key", "is_read"} or not isinstance(value["change_key"], str) or not _mb.CHANGE_KEY.fullmatch(value["change_key"]) \
            or type(value["is_read"]) is not bool:
        raise WriterError("a base of a mark is {change_key, is_read}", EXIT_USAGE)
    return value


def spec_move(path) -> dict:
    spec = _mb.read_json_file(path)
    _mb.exact_keys(spec, ("ids", "base", "internet_ids", "to"), "a move")
    ids = _mb.id_list(spec["ids"], _mb.GRAPH_ID)
    internet = spec["internet_ids"]
    if not isinstance(internet, dict) or set(internet) != set(ids) or not all(v is None or (isinstance(v, str) and _mb.INTERNET_ID.fullmatch(v)) for v in internet.values()):
        raise WriterError("internet_ids holds the internetMessageId of each message (or null), for exactly the ids", EXIT_USAGE)
    return {"ids": ids, "base": base_map(spec["base"], ids, move_base), "internet_ids": internet, "to": folder_name(spec["to"], "to")}


def spec_mark(path) -> dict:
    spec = _mb.read_json_file(path)
    _mb.exact_keys(spec, ("ids", "base", "read"), "a mark")
    ids = _mb.id_list(spec["ids"], _mb.GRAPH_ID)
    if type(spec["read"]) is not bool:
        raise WriterError("read is true or false", EXIT_USAGE)
    return {"ids": ids, "base": base_map(spec["base"], ids, mark_base), "read": spec["read"]}


def spec_draft(path) -> dict:
    spec = _mb.read_json_file(path)
    _mb.exact_keys(spec, ("to", "cc", "bcc", "subject", "body"), "a draft")
    to, cc, bcc = (_mb.address_list(spec[k], k) for k in ("to", "cc", "bcc"))
    if not to or len(to) + len(cc) + len(bcc) > _mb.RECIPIENTS_MAX:
        raise WriterError(f"a draft has at least one recipient and at most {_mb.RECIPIENTS_MAX} in all", EXIT_USAGE)
    return {"to": to, "cc": cc, "bcc": bcc, "subject": _mb.one_line_text(spec["subject"], "the subject", _mb.SUBJECT_MAX, True), "body": _mb.body_text(spec["body"])}


# --- the requests, built without a connection -----------------------------------------------------------------------------------


def recipients(addresses: list) -> list:
    return [{"emailAddress": {"address": a}} for a in addresses]


def draft_body(spec: dict, key: str) -> dict:
    return {"subject": spec["subject"], "body": {"contentType": "text", "content": spec["body"]}, "toRecipients": recipients(spec["to"]),
            "ccRecipients": recipients(spec["cc"]), "bccRecipients": recipients(spec["bcc"]),
            "singleValueExtendedProperties": [{"id": KEY_PROPERTY, "value": key}]}


def req(entry: tuple, path: str, body=None, query=None) -> dict:
    return {"entry": entry, "method": entry[0], "path": path, "query": query or {}, "headers": {}, "body": body}


REPLY_PLACEHOLDER = "/me/messages/{the draft createReply makes}"


def build(verb: str, spec: dict, key: str, message=None) -> dict:
    """The requests a verb sends, as {"requests": [...], "items": {item: the sha256 of its part of the request}}: checked arguments in, no credential, no connection."""
    if verb == "move":
        requests = [req(MOVE, message_path(i, "/move"), {"destinationId": spec["to"]}) for i in spec["ids"]]
        items = {i: _mb.sha(_mb.canonical({"op": "move", "id": i, "to": spec["to"]})) for i in spec["ids"]}
    elif verb == "mark":
        requests = [req(PATCH_MESSAGE, message_path(i), {"isRead": spec["read"]}) for i in spec["ids"]]
        items = {i: _mb.sha(_mb.canonical({"op": "mark", "id": i, "read": spec["read"]})) for i in spec["ids"]}
    elif verb == "draft-create":
        requests = [req(CREATE_MESSAGE, "/me/messages", draft_body(spec, key))]
        items = {"draft": _mb.sha(_mb.canonical(requests[0]["body"]))}
    else:
        approved = draft_body(spec, key)
        requests = [req(CREATE_REPLY, message_path(message, "/createReply"), {"message": approved}), req(PATCH_MESSAGE, REPLY_PLACEHOLDER, approved)]
        items = {"draft": _mb.sha(_mb.canonical([r["body"] for r in requests]))}
    return {"requests": requests, "items": items}


def would_of(built: dict) -> dict:
    return {"requests": [{k: r[k] for k in ("method", "path", "query", "headers", "body")} for r in built["requests"]]}


# --- the message as Graph printed it --------------------------------------------------------------------------------------------


def json_body(body: bytes):
    try:
        found = json.loads(body)
    except ValueError:
        found = None
    return found if isinstance(found, dict) else None


def address_of(entry):
    address = ((entry or {}).get("emailAddress") or {}).get("address") if isinstance(entry, dict) else None
    return address if isinstance(address, str) and _mb.ADDRESS.fullmatch(address) else None


def read_message(item) -> dict:
    """The message as `message-meta` prints it. WriterError (exit 1) when it is not in a form this writer understands."""
    if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not _mb.GRAPH_ID.fullmatch(item["id"]):
        raise WriterError("Graph answered a message this writer does not understand")
    key, folder, internet, thread = item.get("changeKey"), item.get("parentFolderId"), item.get("internetMessageId"), item.get("conversationId")
    when = GRAPH_TIME_RE.fullmatch(item["receivedDateTime"]) if isinstance(item.get("receivedDateTime"), str) else None
    return {"id": item["id"], "found": True, "change_key": key if isinstance(key, str) and _mb.CHANGE_KEY.fullmatch(key) else None,
            "folder_id": folder if isinstance(folder, str) and _mb.GRAPH_FOLDER.fullmatch(folder) else None, "is_read": item.get("isRead") is True,
            "is_draft": item.get("isDraft") is True, "subject": one_line(item.get("subject"), _mb.SUBJECT_MAX), "from_address": address_of(item.get("from")),
            "date": f"{when.group(1)}Z" if when else None, "message_id": internet if isinstance(internet, str) and _mb.INTERNET_ID.fullmatch(internet) else None,
            "thread_id": thread if isinstance(thread, str) and _mb.GRAPH_ID.fullmatch(thread) else None, "external_content": True}


def fetch(session: Session, message: str):
    """The message as Graph holds it, or None when it is gone (404: a moved message has a new id, so its old one is gone)."""
    status, headers, body = request(GET_MESSAGE, session, message_path(message), {"$select": META_SELECT}, {})
    if status == 404:
        return None
    if status != 200:
        raise failure(session, status, headers, body, "GET message")
    item = json_body(body)
    if item is None:
        raise WriterError("Graph answered something this writer does not understand")
    return item


# --- the verbs -----------------------------------------------------------------------------------------------------------------


def cmd_check(args) -> int:
    base, token_url, _, test_mode = msgraph.endpoints(PROFILE)
    found = msgraph.find_account_record(secret_resolver(), PROFILE, test_mode)
    if found is None:
        raise GraphError(f"no Microsoft account authorization: run {PROFILE.auth_command}, or export {PROFILE.secret} (the JSON record)", EXIT_NOT_CONFIGURED)
    record = msgraph.parse_account_record(PROFILE, found[0])
    access, rotated = msgraph.refresh_access_token(PROFILE, token_url or msgraph.TOKEN_URL_TEMPLATE.format(tenant=record["tenant"]), record)
    record["rotation"] = msgraph.store_rotation(PROFILE, record, rotated, found[1], test_mode, secret_resolver, keyring_module)
    session = Session(msgraph.GraphClient(PROFILE, base, access, test_mode), record)
    status, headers, body = request(LIST_FOLDERS, session, "/me/mailFolders", {"$select": "id", "$top": "1"}, {})
    if status != 200:
        raise failure(session, status, headers, body, "GET mailFolders")
    return emit({"ok": True, "record": "account", "scope": " ".join(PROFILE.scopes), "tenant": record["tenant"], "obtained_at": record.get("obtained_at"),
                 "rotation": record["rotation"]})


def cmd_message_meta(args) -> int:
    account = account_flag(args.account)
    ids = _mb.id_list((args.ids or "").split(","), _mb.GRAPH_ID)
    key = idempotency_key(args.key) if args.key is not None else None
    session = open_session(account)
    ledger = _mb.peek(IMPLEMENTATION, key, ids) if key else {}
    out = []
    for i in ids:
        item = fetch(session, i)
        out.append({"id": i, "found": False, "done": ledger.get(i)} if item is None else {**read_message(item), "done": ledger.get(i)})
    return emit({"messages": out})


def cmd_folder_get(args) -> int:
    account = account_flag(args.account)
    folder = readable_folder(args.folder)
    session = open_session(account)
    status, headers, body = request(GET_FOLDER, session, folder_path(folder), {"$select": "id"}, {})
    if status == 404:
        return emit({"found": False})
    if status != 200:
        raise failure(session, status, headers, body, "GET mailFolder")
    item = json_body(body) or {}
    found = item.get("id")
    if not isinstance(found, str) or not _mb.GRAPH_FOLDER.fullmatch(found):
        raise WriterError("Graph answered a folder this writer does not understand")
    return emit({"found": True, "id": found})


def _record_done(key: str, items, **facts) -> None:
    """Record the items done. A ledger that cannot be written after the request landed does not turn it into a failure: the entries stay pending, and the next
    request with the key looks at the messages before it sends anything."""
    try:
        _mb.settle(IMPLEMENTATION, key, items, "done", **facts)
    except (WriterError, OSError) as exc:
        log(f"warning: the request landed, and the ledger could not record it ({one_line(exc, 200)}): the key {key} stays pending")


def _done_positions(key: str, ids: list) -> list:
    """The positions (1-based, in the spec's order) of every message the ledger holds done under the key, by this attempt or an earlier one."""
    states = _mb.peek(IMPLEMENTATION, key, ids)
    return [n for n, i in enumerate(ids, 1) if states[i] == "done"]


def _partial(done_positions, total: int, why: str) -> Lost:
    return Lost(f"partial: done {_mb.positions(done_positions) or 'none'} of {total}; the rest is unknown ({why})")


def landed_move(session: Session, spec: dict, message: str):
    """After an answer that was lost: whether the message moved to the destination. It did when its old id is gone and a message with its internetMessageId is in
    the destination. True, False (still where it was) or None (gone and not found there: the state cannot show it)."""
    item = fetch(session, message)
    if item is not None:
        return False if read_message(item)["folder_id"] == spec["base"][message]["folder_id"] else None
    internet = spec["internet_ids"][message]
    if internet is None:
        return None
    wanted = internet.replace("'", "''")
    status, headers, body = request(LIST_IN_FOLDER, session, folder_path(spec["to"], "/messages"),
                                    {"$filter": f"internetMessageId eq '{wanted}'", "$select": "id", "$top": "2"}, {})
    if status != 200:
        raise failure(session, status, headers, body, "GET messages")
    return True if (json_body(body) or {}).get("value") else None


def _check_states(verb: str, spec: dict, key: str, session: Session, states: dict) -> list:
    """Phase 1, before anything is written: every message that is not done is read, and must still be as it was read; one an earlier lost answer left pending may
    instead show the state the request would give (it landed: recorded done). Returns the ids still to write. WriterError `changed:` (nothing written by this
    attempt) names the positions that are not as they were read."""
    todo, moved, landed, unproved = [], [], [], []
    for position, i in enumerate(spec["ids"], 1):
        if states[i][0] == "done":
            continue
        item = fetch(session, i)
        now = read_message(item) if item is not None else None
        base = spec["base"][i]
        if verb == "move":
            same = now is not None and now["change_key"] == base["change_key"] and now["folder_id"] == base["folder_id"]
            reached = states[i][0] == "pending" and not same and landed_move(session, spec, i) is True
        else:
            same = now is not None and now["change_key"] == base["change_key"] and now["is_read"] == base["is_read"]
            reached = states[i][0] == "pending" and now is not None and now["is_read"] == spec["read"] and now["is_read"] != base["is_read"]
        if same:
            todo.append(i)
        elif reached:
            landed.append(i)
        elif states[i][0] == "pending" and states[i][1].get("attempted"):
            unproved.append(position)
        else:
            moved.append(position)
    if unproved:
        raise Lost(f"the messages at positions {_mb.positions(unproved)} were touched by an earlier attempt of this key and are neither as they were read nor shown moved by "
                   "the destination: look in the mailbox; the key stays pending")
    if moved:
        raise WriterError(f"changed: the messages at positions {_mb.positions(moved)} are not as they were read (moved, changed or gone): nothing was changed by "
                          "this attempt", EXIT_REFUSED)
    if landed:
        _record_done(key, landed)
    return todo


def write(verb: str, args) -> int:
    account, key = account_flag(args.account), idempotency_key(args.idempotency_key)
    spec = {"move": spec_move, "mark": spec_mark, "draft-create": spec_draft, "draft-reply": spec_draft}[verb](args.spec_file)
    message = None
    if verb == "draft-reply":
        message = args.message
        if not isinstance(message, str) or not _mb.GRAPH_ID.fullmatch(message):
            raise WriterError("--message is the id of the message replied to", EXIT_USAGE)
    built = build(verb, spec, key, message)
    would = would_of(built)
    digest = _mb.sha(_mb.canonical(would))
    items = built["items"]
    if args.dry_run:
        return emit({"dry_run": True, "would": would, "would_sha256": digest, "ledger": _mb.peek(IMPLEMENTATION, key, list(items))})
    session = open_session(account)
    states = _mb.claim(IMPLEMENTATION, key, items, verb)
    fresh = [i for i, (state, _) in states.items() if state == "new"]
    if all(state == "done" for state, _ in states.values()):
        return emit({"done": True, "replayed": True, "count": len(items), **_draft_facts(verb, states)})
    try:
        if verb in ("draft-create", "draft-reply"):
            return _write_draft(verb, spec, built, key, session, states)
        return _write_messages(verb, spec, built, key, session, states)
    except Lost:
        raise          # the entries stay pending: sending the key again looks at the messages first
    except BaseException:
        _mb.settle(IMPLEMENTATION, key, fresh, "released")      # nothing was sent by this attempt
        raise


def _draft_facts(verb: str, states: dict) -> dict:
    return {"draft_id": states["draft"][1].get("draft_id")} if verb in ("draft-create", "draft-reply") else {}


def landed_draft(session: Session, key: str):
    """After an answer that was lost: whether the draft of `key` is in the Drafts folder, found by the private property it carries. Its id, or None."""
    wanted = f"singleValueExtendedProperties/any(ep: ep/id eq '{KEY_PROPERTY}' and ep/value eq '{key}')"
    status, headers, body = request(LIST_IN_FOLDER, session, folder_path("drafts", "/messages"), {"$filter": wanted, "$select": "id", "$top": "2"}, {})
    if status != 200:
        raise failure(session, status, headers, body, "GET messages")
    found = (json_body(body) or {}).get("value") or []
    return found[0].get("id") if found and isinstance(found[0], dict) else None


def _patch_reply(session: Session, draft: str, built: dict):
    """The one PATCH that makes a reply draft the text approved. (status, headers, body)."""
    second = built["requests"][1]
    return request(second["entry"], session, message_path(draft), second["query"], second["headers"], second["body"], write=True)


def _move_orphan(session: Session, draft: str) -> bool:
    """Move a reply draft that never got the approved text to Deleted Items, so that no draft addressed as Graph would is left in Drafts. True when it moved."""
    try:
        status, _, _ = request(MOVE, session, message_path(draft, "/move"), {}, {}, {"destinationId": "deleteditems"}, write=True)
    except (WriterError, GraphError):
        return False
    return status in (200, 201)


def _write_reply(built, key, session, states) -> int:
    draft = states["draft"][1].get("draft_id") if states["draft"][0] == "pending" else None
    if draft is None and states["draft"][0] == "pending":      # an earlier attempt may have made it and lost the answer: look in Drafts by the key the createReply carried
        try:
            draft = landed_draft(session, key)
        except (WriterError, GraphError) as exc:
            raise Lost(f"an earlier attempt with this key did not say whether it landed, and the drafts cannot be looked up now ({exc}): the key stays pending; "
                       "send it again later") from None
    if draft is None:
        first = built["requests"][0]
        status, headers, body = request(first["entry"], session, first["path"], first["query"], first["headers"], first["body"], write=True)
        if status not in (200, 201):
            raise failure(session, status, headers, body, f"{first['method']} message")
        draft = (json_body(body) or {}).get("id")
        if not isinstance(draft, str) or not _mb.GRAPH_ID.fullmatch(draft):
            raise Lost("Graph answered a draft this writer does not understand: the request may or may not have landed")
    _mb.annotate(IMPLEMENTATION, key, ["draft"], draft_id=draft)      # noted before the PATCH: a retry sets the text of THIS draft
    try:
        status, headers, body = _patch_reply(session, draft, built)
        if status not in (200, 201):
            raise failure(session, status, headers, body, "PATCH message")
    except Lost as exc:
        raise Lost(f"the reply draft was made, and setting its text did not say whether it landed ({one_line(exc, 100)}): the key stays pending; send it again to set it") from None
    except (WriterError, GraphError) as exc:
        moved = _move_orphan(session, draft)
        if moved:
            _mb.settle(IMPLEMENTATION, key, ["draft"], "released")
        said = f"the reply draft was made but setting its text was refused ({one_line(exc, 100)}); "
        if moved:
            raise WriterError(said + "it was moved to Deleted Items, so no draft addressed as Graph would is left in Drafts: nothing is left to look for", EXIT_REFUSED) from None
        raise Kept(said + "it could not be moved: it is in Drafts addressed as Graph would, so remove it yourself; the key stays pending") from None
    _record_done(key, ["draft"], draft_id=draft)
    return emit({"done": True, "replayed": False, "draft_id": draft, "count": 1})


def _write_draft(verb, spec, built, key, session, states) -> int:
    if verb == "draft-reply":
        return _write_reply(built, key, session, states)
    if states["draft"][0] == "pending":      # an earlier attempt's answer was lost: look in the Drafts folder before anything is sent
        try:
            found = landed_draft(session, key)
        except (WriterError, GraphError) as exc:
            raise Lost(f"an earlier attempt with this key did not say whether it landed, and the drafts cannot be looked up now ({exc}): the key stays pending; "
                       "send it again later") from None
        if found is not None:
            _record_done(key, ["draft"], draft_id=found)
            return emit({"done": True, "replayed": True, "draft_id": found, "count": 1})
    first = built["requests"][0]
    status, headers, body = request(first["entry"], session, first["path"], first["query"], first["headers"], first["body"], write=True)
    if status not in (200, 201):
        raise failure(session, status, headers, body, f"{first['method']} message")
    draft = (json_body(body) or {}).get("id")
    if not isinstance(draft, str) or not _mb.GRAPH_ID.fullmatch(draft):
        raise Lost("Graph answered a draft this writer does not understand: the request may or may not have landed")
    _record_done(key, ["draft"], draft_id=draft)
    return emit({"done": True, "replayed": False, "draft_id": draft, "count": 1})


def _write_messages(verb, spec, built, key, session, states) -> int:
    todo = _check_states(verb, spec, key, session, states)
    ids = spec["ids"]
    if not todo:
        return emit({"done": True, "replayed": True, "count": len(ids)})
    done = []
    for i in todo:
        r = next(q for q in built["requests"] if q["path"] in (message_path(i, "/move"), message_path(i)))
        _mb.annotate(IMPLEMENTATION, key, [i], attempted=True)      # noted before the call: a message that was never attempted and moved is stale, not unknown
        try:
            status, headers, body = request(r["entry"], session, r["path"], r["query"], r["headers"], r["body"], write=True)
            if status not in (200, 201):
                raise failure(session, status, headers, body, f"{r['method']} message")
        except Lost as exc:
            raise _partial(_done_positions(key, ids), len(ids), one_line(exc, 80)) from None
        except (WriterError, GraphError) as exc:
            _mb.settle(IMPLEMENTATION, key, [i], "released")
            if _done_positions(key, ids):
                raise _partial(_done_positions(key, ids), len(ids), one_line(exc, 80)) from None
            raise
        moved = (json_body(body) or {}).get("id") if verb == "move" else None
        _record_done(key, [i], **({"new_id": moved} if isinstance(moved, str) else {}))
        done.append(i)
    return emit({"done": True, "replayed": False, "count": len(ids)})


VERBS = ("message-meta", "folder-get", "move", "mark", "draft-create", "draft-reply")
FLAG_NAMES = {"account": "--account", "ids": "--ids", "key": "--key", "folder": "--folder", "message": "--message", "spec_file": "--spec-file",
              "idempotency_key": "--idempotency-key"}
WRITE_FLAGS = {"account", "spec_file", "idempotency_key"}
VERB_FLAGS = {"message-meta": {"account", "ids", "key"}, "folder-get": {"account", "folder"}, "move": WRITE_FLAGS, "mark": WRITE_FLAGS, "draft-create": WRITE_FLAGS,
              "draft-reply": WRITE_FLAGS | {"message"}, None: set()}
OPTIONAL = {"key"}
READS = ("message-meta", "folder-get")


def check_flags(args) -> None:
    """A flag given to a verb that does not read it is a usage error, a required one that is missing too; --check takes no verb."""
    if args.check and args.verb:
        raise WriterError(f"--check takes no verb: run --check alone, or {args.verb} without --check", EXIT_USAGE)
    if args.check:
        return
    if not args.verb:
        raise WriterError(f"give a verb ({', '.join(VERBS)}) or --check; see --help", EXIT_USAGE)
    wanted = VERB_FLAGS[args.verb]
    extra = [flag for dest, flag in FLAG_NAMES.items() if getattr(args, dest) is not None and dest not in wanted]
    if extra:
        raise WriterError(f"{', '.join(extra)}: not a flag of {args.verb} (see --help)", EXIT_USAGE)
    missing = [FLAG_NAMES[dest] for dest in wanted - OPTIONAL if getattr(args, dest) is None]
    if missing:
        raise WriterError(f"{args.verb} needs {', '.join(sorted(missing))}", EXIT_USAGE)
    if args.verb not in READS and bool(args.dry_run) == bool(args.confirmed):
        raise WriterError(f"{args.verb} needs exactly one of --dry-run and --confirmed", EXIT_USAGE)
    if args.verb in READS and (args.dry_run or args.confirmed):
        raise WriterError(f"{args.verb} is a read: it takes neither --dry-run nor --confirmed", EXIT_USAGE)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="outlook-mail.py", description=__doc__.split("\n\n")[0], epilog=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("verb", nargs="?", choices=list(VERBS), help="the action to run")
    parser.add_argument("--check", action="store_true", help="refresh a token, check its scope and read one mail folder; prints no secret")
    parser.add_argument("--account", help="the address of the account the document names")
    parser.add_argument("--ids", help="message ids, comma-separated")
    parser.add_argument("--key", help="the idempotency key whose ledger entries message-meta reports")
    parser.add_argument("--folder", help="a well-known folder name (archive, deleteditems, inbox, junkemail, drafts, ...) or a folder id")
    parser.add_argument("--message", help="the id of the message a draft replies to")
    parser.add_argument("--spec-file", dest="spec_file", help="the file that holds the request as JSON")
    parser.add_argument("--idempotency-key", dest="idempotency_key", help="the key of this one request")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="print the exact requests and their hash; read no credential, open no connection")
    parser.add_argument("--confirmed", action="store_true", help="send exactly those requests")
    return parser


def run(argv=None) -> int:
    args = build_parser().parse_args(argv)
    check_flags(args)
    if args.check:
        return cmd_check(args)
    if args.verb == "message-meta":
        return cmd_message_meta(args)
    if args.verb == "folder-get":
        return cmd_folder_get(args)
    return write(args.verb, args)


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        return run(argv)
    except (WriterError, GraphError) as exc:
        log(f"error: {exc}")
        return exc.code
    except Exception as exc:     # last resort: no traceback, which can hold a header or a body; only the kind of the failure
        log(f"error: unexpected {type(exc).__name__}; nothing was changed")
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
