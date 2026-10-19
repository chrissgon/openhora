#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["keyring==25.7.0"]
# ///
"""Mailer provider for Outlook (Microsoft 365 and outlook.com), class sender:email, package W2 of SPEC-SECRETARY-WRITES: send one e-mail from the person's own
Microsoft account through Microsoft Graph, to exactly the recipients it is given, once. The third implementation of the class, beside the SMTP outbox
(providers/mailer/smtp.py) and Gmail; the runtime names it explicitly, from the effect module runtime/effect_send.py, for a document whose `account` is microsoft,
and never lists it as the project's outbox.

Sources (Microsoft's own documentation, accessed 2026-10-18; what could not be read there is listed under "To verify" in providers/mailer/README.md):
- Create a draft (POST /me/messages; JSON with subject, body {contentType, content}, toRecipients, ccRecipients, bccRecipients, attachments) and send it
  (POST /me/messages/{id}/send; 202 Accepted, no body; the message goes to Sent Items): https://learn.microsoft.com/en-us/graph/api/user-post-messages and
  https://learn.microsoft.com/en-us/graph/api/message-send
- Reply in the conversation (POST /me/messages/{id}/createReply makes a draft in the thread; the draft is then updated with PATCH /me/messages/{id}):
  https://learn.microsoft.com/en-us/graph/api/message-createreply and https://learn.microsoft.com/en-us/graph/api/message-update
- Move a message to a folder (POST /me/messages/{id}/move; `deleteditems` is a well-known folder name; the only removal this mailer makes is moving an unsent
  draft there): https://learn.microsoft.com/en-us/graph/api/message-move
- The message resource (internetMessageId, subject, body, toRecipients, ccRecipients, bccRecipients, hasAttachments) and the well-known folder `sentitems`:
  https://learn.microsoft.com/en-us/graph/api/resources/message and https://learn.microsoft.com/en-us/graph/api/resources/mailfolder
- The request body limits (a JSON request body of up to 4 MB; larger attachments need an upload session, which this mailer does not use):
  https://learn.microsoft.com/en-us/graph/api/message-post-attachments
- Permissions (Mail.ReadWrite creates and updates, "Does not include permission to send mail"; Mail.Send sends): https://learn.microsoft.com/en-us/graph/permissions-reference

Usage:
  uv run providers/mailer/outlook.py --help
  uv run providers/mailer/outlook.py --check
  uv run providers/mailer/outlook.py send --from <addr> --to <addr>... [--cc <addr>...] [--bcc <addr>...] --subject-file <f> --body-file <f>
        [--attach <path>=<name>]... [--in-reply-to <id> --reply-id <the service's id of that message> [--references <id>...]] --message-id <oh.hex@domain>
        --idempotency-key <k> (--dry-run | --confirmed)
  uv run providers/mailer/outlook.py resolve --idempotency-key <k> (--sent | --not-sent) (--dry-run | --confirmed)
  uv run providers/mailer/outlook.py lookup --message-id <id>

  --check     refreshes the access token, checks that the account token carries the platform's whole set of permissions and reads the account's address; prints
              {"ok": true, "from", "obtained_at", "rotation"}. Exit 3 when there is no authorization or the set is not the platform's.
  send        the recipients are exactly the flags (at most 20 in all; a display name, a comment, a line break, an encoded word `=?`, a second @ or a repeated address
              is exit 2). The From address must be the address of the account token (the record's `account`, and Graph's own `/me`), else exit 3 and nothing is sent. A
              new message is a draft (POST /me/messages) that is then sent (POST /me/messages/{id}/send). A reply (--in-reply-to with --reply-id) is the draft
              Graph makes in the conversation (createReply), updated to be exactly the approved message (To only the sender, no Cc, no Bcc, the approved subject and
              text), read back, and then sent; a reply carries no attachment and no other recipient in this version. Whatever Graph made is read back and must be the
              approved message before anything is sent; if it is not, or if a step before the send fails, the draft is moved to Deleted Items (nothing is deleted for
              good) and the key is freed.
  --dry-run   reads no credential, opens no connection and prints {"dry_run": true, "would": {...}, "would_sha256", "ledger"}: the headers, the envelope, the text,
              each attachment's name, size and sha256, and the requests `--confirmed` sends, in order, with `{draft}` for the id Graph gives (`requests`; an attachment
              is shown by its hash). The hash covers all of it.
  --confirmed sends exactly that. The key is recorded `pending` in the ledger first (phase claimed, then drafted with the draft's id and the Message-ID Graph gave
              it, then sending just before the send) and `done` after the answer; a key that is `done` is not sent again (`replayed`); a key left `pending` in the phase
              `sending` is looked up in Sent Items by the Message-ID Graph gave the draft (exact match) before anything is sent: found, `replayed`; not found, exit 4
              until `resolve` records what the person found. A key left earlier than `sending` sent nothing and is taken again with a new draft.
  resolve     settles a key left pending (--sent: delivered; --not-sent: not, after which the e-mail may be sent again).
  lookup      is this Message-ID among the Sent Items of the account (read only): {"found", "count", "message_id"}.

Credentials (never from a flag or a file; contracts/secrets.md):
  MICROSOFT_ACCOUNT_TOKEN  the account record (providers/accounts/microsoft_auth.py), read through providers/secrets/resolver.py. There is no legacy record for a
                           mailer: a token that lacks one permission of the platform's set, or carries another, is refused (exit 3) before any call. Microsoft replaces
                           the refresh token on every use; as the readers do, this mailer writes the new one back to the record it used, only if it still holds the token
                           this process used (providers/_msgraph.py store_rotation).
Test overrides (tests only, loopback URLs only, both set together; the secret store is then never read or written):
  MAILER_OUTLOOK_API_BASE    replaces https://graph.microsoft.com/v1.0
  MAILER_OUTLOOK_TOKEN_URL   replaces https://login.microsoftonline.com/<tenant>/oauth2/v2.0/token

Limits. The request function sends only the methods and paths of ALLOWED and refuses anything else (limits L57, L58): the account (GET /me), the draft (POST, PATCH),
the send (POST), the move of an unsent draft to Deleted Items (POST) and the search of Sent Items (GET). There is no DELETE in it. No redirect is followed. A verb
never retries: a 429 is reported with its Retry-After and nothing is sent; a 5xx or a lost connection on the send is exit 4 (it may have landed) and the key stays
pending. Every request has a 60-second timeout. Attachments weigh 2.5 MiB together at most (the draft is one JSON request of at most 4 MB, the files base64 encoded
inside it). The state is <state>/mailer-outlook/ (0700, files 0600), where <state> is $OPENHORA_STATE_DIR, else $XDG_STATE_HOME/openhora, else
~/.local/state/openhora. Prints one JSON object on stdout; diagnostics on stderr. Exit codes: 0 ok; 1 the service or the ledger refuses and NOTHING was sent; 2 usage;
3 not configured; 4 the outcome is not known (the key stays pending).
"""
from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import re
import sys
import urllib.parse
from pathlib import Path

SERVES = "sender:email"
IMPLEMENTATION = "outlook"
ATTACH_TOTAL_MAX = 2560 * 1024
PAGE_BYTES = 1024 * 1024
# The only requests this mailer sends (limits L57 and L58): a method and a full-match pattern of the path, as the request function sees it (ids are percent-encoded).
ALLOWED = (("GET", r"/me"),
           ("POST", r"/me/messages"),
           ("POST", r"/me/messages/[^/]+/createReply"),
           ("PATCH", r"/me/messages/[^/]+"),
           ("POST", r"/me/messages/[^/]+/send"),
           ("POST", r"/me/messages/[^/]+/move"),
           ("GET", r"/me/mailFolders/sentitems/messages"))
ACCOUNT, CREATE, CREATE_REPLY, UPDATE, SEND, MOVE, SENT_ITEMS = ALLOWED
PREFER = {"Prefer": 'outlook.body-content-type="text"'}


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
_mail = _shared("providers_mailer_account", "_mailer_account.py")
GraphError, ProviderError, Lost = msgraph.ProviderError, _mail.ProviderError, _mail.Lost
EXIT_OK, EXIT_SERVICE, EXIT_USAGE, EXIT_NOT_CONFIGURED, EXIT_UNKNOWN = (_mail.EXIT_OK, _mail.EXIT_SERVICE, _mail.EXIT_USAGE, _mail.EXIT_NOT_CONFIGURED,
                                                                        _mail.EXIT_UNKNOWN)
PROFILE = msgraph.account_profile(
    run_hint="uv run <workbench>/providers/mailer/outlook.py", env_prefix="MAILER_OUTLOOK", user_agent="openhora-mailer-outlook",
    not_found="Outlook does not know the message, or it is not one of the person's",
    forbidden_hint="check that the account token carries the platform's whole set (Mail.ReadWrite and Mail.Send among them)")


def one_line(text, limit: int = 300) -> str:
    return _mail.one_line(text, limit)


def log(message: str) -> None:
    print(message, file=sys.stderr)


def secret_resolver():
    return msgraph.secret_resolver(__file__)


def keyring_module(test_mode: bool):
    return msgraph.keyring_module(PROFILE, test_mode)


class Session:
    """What a verb that talks to Graph holds: the base address, an access token, and the record."""

    def __init__(self, client, record: dict):
        self.client, self.record = client, record


def open_session() -> Session:
    """An access token from the account record: the whole platform set, or exit 3. There is no legacy record for a mailer."""
    base, token_url, _, test_mode = msgraph.endpoints(PROFILE)
    found = msgraph.find_account_record(secret_resolver(), PROFILE, test_mode)
    if found is None:
        raise ProviderError(f"no Microsoft account authorization: run {PROFILE.auth_command}, or export {PROFILE.secret} (the JSON record)", EXIT_NOT_CONFIGURED)
    record = msgraph.parse_account_record(PROFILE, found[0])
    _mail.hold(record["refresh_token"])
    access, rotated = msgraph.refresh_access_token(PROFILE, token_url or msgraph.TOKEN_URL_TEMPLATE.format(tenant=record["tenant"]), record)
    _mail.hold(access, rotated)
    record["rotation"] = msgraph.store_rotation(PROFILE, record, rotated, found[1], test_mode, secret_resolver, keyring_module)
    return Session(msgraph.GraphClient(PROFILE, base, access, test_mode), record)


# --- HTTP --------------------------------------------------------------------------------------------------------------------


def request(entry: tuple, session: Session, path: str, query: dict, headers: dict, body=None, sent_on_error: bool = False) -> tuple:
    """The one function that sends a request to Graph. `entry` must be a pair of ALLOWED and `path` must match its pattern; anything else is refused before a
    connection is opened. Returns (status, response headers, body bytes). A failure after the request could have reached Graph is Lost (exit 4) when
    `sent_on_error` (the send)."""
    method, pattern = entry
    if entry not in ALLOWED or not re.fullmatch(pattern, path):
        raise ProviderError(f"this mailer does not send {method} {path}: it is not a request of its allow-list", EXIT_USAGE)
    client = session.client
    sent = {"Authorization": f"Bearer {client.token}", "Accept": "application/json", "User-Agent": PROFILE.user_agent, **headers}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        sent["Content-Type"] = "application/json; charset=utf-8"
    try:
        return msgraph.http(method, client.url_for(path, query), sent, data, PAGE_BYTES, what="Microsoft Graph")
    except GraphError as exc:
        if sent_on_error:
            raise Lost(f"{exc}: the e-mail may or may not have been sent") from None
        raise


def failure(session: Session, status: int, headers, body: bytes, what: str):
    """The error for an answer that is not the one wanted. A send answered with a redirect or a server error may have landed (Lost)."""
    if what.startswith("POST send") and (status in msgraph.REDIRECT_STATUSES or status >= 500 or 200 <= status < 300):      # a 2xx the documentation does not give is not a refusal
        return Lost(f"Graph answered {status} ({what}): the e-mail may or may not have been sent", status)
    problem = session.client.failure(status, headers, body, what)
    return ProviderError(str(problem), problem.code, status)


def json_of(body: bytes) -> dict:
    try:
        data = json.loads(body or b"{}")
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise ProviderError("Graph answered something this mailer does not understand")
    return data


def quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")


# --- the account ---------------------------------------------------------------------------------------------------------------


def check_account(session: Session, sender: str) -> None:
    """The From address is the address of the account token: the record says it (written at the authorization) and Graph's own `/me` says it. Else exit 3, and
    nothing is sent."""
    record = session.record
    if not record.get("account"):
        raise ProviderError(f"the Microsoft account record names no address: run {PROFILE.auth_command}", EXIT_NOT_CONFIGURED)
    if not _mail.same_address(record["account"], sender):
        raise ProviderError("the From address is not the address of the Microsoft account token: nothing was sent (the account token sends from its own address "
                            "only)", EXIT_NOT_CONFIGURED)
    status, headers, body = request(ACCOUNT, session, "/me", {"$select": "mail,userPrincipalName"}, {})
    if status != 200:
        raise failure(session, status, headers, body, "GET me")
    me = json_of(body)
    if not any(_mail.same_address(me.get(key), sender) for key in ("mail", "userPrincipalName")):
        raise ProviderError("Microsoft says the account token belongs to another address than the From address: nothing was sent; run "
                            f"{PROFILE.auth_command}", EXIT_NOT_CONFIGURED)


# --- the plan: the requests, built without a connection -------------------------------------------------------------------------------


def recipients(addresses) -> list:
    return [{"emailAddress": {"address": a}} for a in addresses]


def draft_body(plan: dict, real: bool) -> dict:
    """The JSON of a new message. The files are base64 inside it when `real`; the preview shows each by its hash instead."""
    out = {"subject": plan["subject"], "body": {"contentType": "text", "content": plan["body"]}, "toRecipients": recipients(plan["to"]),
           "ccRecipients": recipients(plan["cc"]), "bccRecipients": recipients(plan["bcc"])}
    if plan["attachments"]:
        out["attachments"] = [{"@odata.type": "#microsoft.graph.fileAttachment", "name": name, "contentType": kind,
                               **({"contentBytes": base64.b64encode(data).decode("ascii")} if real else {"contentBytes_sha256": _mail.sha(data), "bytes": len(data)})}
                              for name, kind, data in plan["attachments"]]
    return out


def reply_patch(plan: dict) -> dict:
    """The update that makes the draft Graph made in the conversation exactly the approved message: To only the sender, no Cc, no Bcc, the approved subject and text."""
    return {"subject": plan["subject"], "body": {"contentType": "text", "content": plan["body"]}, "toRecipients": recipients(plan["to"]),
            "ccRecipients": [], "bccRecipients": []}


def requests_of(plan: dict) -> list:
    if plan["in_reply_to"]:
        return [{"method": "POST", "path": f"/me/messages/{quote(plan['reply_id'])}/createReply", "query": {}, "headers": {}, "body": {}},
                {"method": "PATCH", "path": "/me/messages/{draft}", "query": {}, "headers": PREFER, "body": reply_patch(plan)},
                {"method": "POST", "path": "/me/messages/{draft}/send", "query": {}, "headers": {}, "body": None},
                {"method": "POST", "path": "/me/messages/{draft}/move", "query": {}, "headers": {}, "body": {"destinationId": "deleteditems"},
                 "when": "only if the draft is not the approved message, or a step before the send failed: nothing is deleted for good"}]
    return [{"method": "POST", "path": "/me/messages", "query": {}, "headers": PREFER, "body": draft_body(plan, False)},
            {"method": "POST", "path": "/me/messages/{draft}/send", "query": {}, "headers": {}, "body": None},
            {"method": "POST", "path": "/me/messages/{draft}/move", "query": {}, "headers": {}, "body": {"destinationId": "deleteditems"},
             "when": "only if the draft is not the approved message, or a step before the send failed: nothing is deleted for good"}]


def plan_of(args, mail) -> dict:
    """The e-mail the flags describe, checked whole, with the requests it sends and the hash of the whole preview. Nothing is read from the network or a
    credential."""
    plan = _mail.plan_of(args, mail, total_max=ATTACH_TOTAL_MAX, with_wire=False, reply_id_required=True)
    if plan["in_reply_to"] and (len(plan["to"]) != 1 or plan["cc"] or plan["bcc"] or plan["attachments"]):
        raise ProviderError("a reply goes to one recipient, with no Cc, no Bcc and no attachment, in this version", EXIT_USAGE)
    if plan["thread_id"]:
        raise ProviderError("--thread-id is Gmail's: an Outlook reply joins its conversation through the message it answers (--reply-id)", EXIT_USAGE)
    return _mail.finish_plan(plan, mail, requests_of(plan), IMPLEMENTATION)


# --- the draft, read back -------------------------------------------------------------------------------------------------------------


def _addresses(items) -> list:
    out = []
    for item in items if isinstance(items, list) else []:
        address = ((item or {}).get("emailAddress") or {}).get("address") if isinstance(item, dict) else None
        out.append(str(address).lower() if isinstance(address, str) else "")
    return out


def _text(value) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").rstrip()


def draft_problem(draft: dict, plan: dict):
    """Why the draft Graph holds is not the approved message, or None: the recipients (To, Cc and Bcc, exactly), the subject, the text as plain text, and the
    presence of the attachments. The draft is read back as Graph answered it, before anything is sent."""
    if not isinstance(draft.get("id"), str) or not _mail.PROVIDER_ID.fullmatch(draft["id"]):
        return "Graph named no draft this mailer can use"
    for key, wanted in (("toRecipients", plan["to"]), ("ccRecipients", plan["cc"]), ("bccRecipients", plan["bcc"])):
        if _addresses(draft.get(key)) != [a.lower() for a in wanted]:
            return f"the draft's {key} are not the approved ones"
    if draft.get("subject") != plan["subject"]:
        return "the draft's subject is not the approved one"
    body = draft.get("body") if isinstance(draft.get("body"), dict) else {}
    if str(body.get("contentType", "")).lower() != "text" or _text(body.get("content")) != _text(plan["body"]):
        return "the draft's text is not the approved text, or Graph did not keep it as plain text"
    if bool(plan["attachments"]) != (draft.get("hasAttachments") is True) or (not plan["attachments"] and draft.get("hasAttachments") is not False):
        return "the draft does not hold exactly the approved attachments"
    return None


def discard_draft(session: Session, draft_id) -> None:
    """Move an unsent draft to Deleted Items (nothing is deleted for good). Best effort: a failure is said on stderr and changes nothing else."""
    if not isinstance(draft_id, str):
        return
    try:
        status, _, _ = request(MOVE, session, f"/me/messages/{quote(draft_id)}/move", {}, {}, {"destinationId": "deleteditems"})
        if status not in (200, 201):
            log("warning: the unsent draft could not be moved to Deleted Items; it stays in Drafts (nothing was sent)")
    except (ProviderError, GraphError):
        log("warning: the unsent draft could not be moved to Deleted Items; it stays in Drafts (nothing was sent)")


def make_draft(session: Session, plan: dict) -> dict:
    """The draft, made and read back. ProviderError exit 1 (nothing was sent) when Graph refuses, or when the draft is not the approved message (it is moved to
    Deleted Items first)."""
    if plan["in_reply_to"]:
        status, headers, body = request(CREATE_REPLY, session, f"/me/messages/{quote(plan['reply_id'])}/createReply", {}, {}, {})
        if status not in (200, 201):
            raise failure(session, status, headers, body, "POST createReply")
        made = json_of(body)
        if not isinstance(made.get("id"), str) or not _mail.PROVIDER_ID.fullmatch(made["id"]):
            raise ProviderError("Graph named no draft this mailer can use")
        try:
            status, headers, body = request(UPDATE, session, f"/me/messages/{quote(made['id'])}", {}, PREFER, reply_patch(plan))
        except BaseException:
            discard_draft(session, made["id"])
            raise
        if status != 200:
            discard_draft(session, made["id"])
            raise failure(session, status, headers, body, "PATCH message")
        draft = json_of(body)
        draft.setdefault("id", made["id"])
    else:
        status, headers, body = request(CREATE, session, "/me/messages", {}, PREFER, draft_body(plan, True))
        if status not in (200, 201):
            raise failure(session, status, headers, body, "POST message")
        draft = json_of(body)
    why = draft_problem(draft, plan)
    if why:
        discard_draft(session, draft.get("id"))
        raise ProviderError(f"{why}: the draft was not sent (it was moved to Deleted Items)")
    return draft


# --- looking a message up in Sent Items -------------------------------------------------------------------------------------------------


def sent_count(session: Session, internet_message_id: str) -> int:
    """How many messages of Sent Items carry exactly this internetMessageId: the filter finds candidates and each one's own id is compared. The identity is the
    message's Message-ID, never its size or its time."""
    escaped = internet_message_id.replace("'", "''")
    status, headers, body = request(SENT_ITEMS, session, "/me/mailFolders/sentitems/messages",
                                    {"$filter": f"internetMessageId eq '{escaped}'", "$select": "id,internetMessageId", "$top": "5"}, {})
    if status != 200:
        raise failure(session, status, headers, body, "GET sent items")
    return sum(1 for item in (json_of(body).get("value") or []) if isinstance(item, dict) and item.get("internetMessageId") == internet_message_id)


# --- the verbs -----------------------------------------------------------------------------------------------------------------


def cmd_check() -> int:
    session = open_session()
    status, headers, body = request(ACCOUNT, session, "/me", {"$select": "mail,userPrincipalName"}, {})
    if status != 200:
        raise failure(session, status, headers, body, "GET me")
    me = json_of(body)
    record = session.record
    if record.get("account") and not any(_mail.same_address(me.get(key), record["account"]) for key in ("mail", "userPrincipalName")):
        raise ProviderError(f"Microsoft says the account token belongs to another address than the one the record names: run {PROFILE.auth_command}",
                            EXIT_NOT_CONFIGURED)
    return _mail.emit({"ok": True, "from": record.get("account"), "scope": " ".join(PROFILE.scopes), "obtained_at": record.get("obtained_at"),
                       "rotation": record["rotation"]})


def cmd_send(args) -> int:
    mail = _mail.helpers()
    plan = plan_of(args, mail)
    if args.dry_run:
        return _mail.emit({"dry_run": True, "would": plan["would"], "would_sha256": plan["would_sha256"], "ledger": _mail.ledger_state(IMPLEMENTATION, plan["key"])})
    session = open_session()
    check_account(session, plan["sender"])
    state, entry = _mail.claim(IMPLEMENTATION, plan, "claimed")
    if state == "busy":
        raise ProviderError("another send of this key is in progress (it has made a draft or is making one and has moved in the last minutes): nothing was sent by "
                            "this attempt; try again later, and if it stays so, look in the sent mail and then run resolve", EXIT_SERVICE)
    if state == "done":
        return _mail.emit(_mail.result(plan, True, **({"service_message_id": entry["service_message_id"]} if entry.get("service_message_id") else {})))
    if state == "pending":
        assigned = entry.get("service_message_id")
        try:
            if not assigned:
                raise ProviderError("the earlier attempt recorded no Message-ID to look for")
            found = sent_count(session, assigned)
        except (ProviderError, GraphError) as exc:
            raise Lost(f"an earlier attempt with this key did not say whether the e-mail was sent, and Sent Items cannot be looked up now ({exc}): look in "
                       f"Sent Items, then run resolve --idempotency-key {plan['key']} --sent or --not-sent") from None
        if not found:
            raise Lost("an earlier attempt with this key did not say whether the e-mail was sent, and it is not in Sent Items (by the Message-ID Graph gave the "
                       "draft): nothing is sent again until you settle the key. Look in Sent Items first, because resolve --not-sent can lead to a second copy; "
                       f"resolve --idempotency-key {plan['key']} --sent records it as delivered")
        _mail.record_done(IMPLEMENTATION, plan["key"])
        return _mail.emit(_mail.result(plan, True, service_message_id=assigned))
    draft = None
    try:
        draft = make_draft(session, plan)
        given = draft.get("internetMessageId")
        assigned = given if isinstance(given, str) and mail.REFERENCE.fullmatch(given) else None      # a Message-ID in its plain form, or none: a lookup needs a value it can search for exactly
        _mail.mark(IMPLEMENTATION, plan["key"], phase="drafted", draft_id=draft["id"], **({"service_message_id": assigned} if assigned else {}))
        _mail.mark(IMPLEMENTATION, plan["key"], phase="sending")
    except BaseException:
        _mail.settle(IMPLEMENTATION, plan["key"], "released")      # nothing was sent: the key is free
        if draft is not None:
            discard_draft(session, draft.get("id"))
        raise
    try:
        status, headers, body = request(SEND, session, f"/me/messages/{quote(draft['id'])}/send", {}, {}, None, sent_on_error=True)
    except Lost:
        raise          # the key stays pending, in the phase sending: sending it again looks in Sent Items first
    except (ProviderError, GraphError):
        _mail.settle(IMPLEMENTATION, plan["key"], "released")
        discard_draft(session, draft["id"])
        raise
    except Exception as exc:      # anything else after the send was started: it may have been handed over, so the key stays pending
        raise Lost(f"the send ended with an unexpected {type(exc).__name__}: the e-mail may or may not have been sent") from None
    if status not in (200, 202, 204):
        problem = failure(session, status, headers, body, "POST send")
        if not isinstance(problem, Lost):
            _mail.settle(IMPLEMENTATION, plan["key"], "released")      # Graph said no: nothing was sent, the key is free
            discard_draft(session, draft["id"])
        raise problem
    _mail.record_done(IMPLEMENTATION, plan["key"])
    return _mail.emit(_mail.result(plan, False, len(plan["body"].encode("utf-8")),
                                   **({"service_message_id": assigned} if assigned and assigned != plan["message_id"] else {})))


def cmd_lookup(args) -> int:
    mail = _mail.helpers()
    if not mail.REFERENCE.fullmatch(args.message_id or ""):
        raise ProviderError("--message-id is one <local@domain> with no space", EXIT_USAGE)
    found = sent_count(open_session(), args.message_id)
    return _mail.emit({"found": found > 0, "count": found, "message_id": args.message_id})


HELP_EPILOG = """\
verbs:
  send     send one e-mail from the account's own address: --from <a> --to <a>... [--cc <a>...] [--bcc <a>...] --subject-file <f> --body-file <f>
           [--attach <path>=<name>]... [--in-reply-to <id> --reply-id <service id> [--references <id>...]] --message-id <oh.hex@domain>
           --idempotency-key <k> (--dry-run | --confirmed). The recipients are exactly the flags (at most 20 in all).
  resolve  settle a key left pending: --idempotency-key <k> (--sent | --not-sent) (--dry-run | --confirmed)
  lookup   is this Message-ID among the Sent Items of the account? --message-id <id> (read only)
  --check  refresh the token, check its permissions and the account's address; sends nothing

environment: MICROSOFT_ACCOUNT_TOKEN (or the OS secret store, store username microsoft-account), OPENHORA_STATE_DIR.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="outlook.py", description=__doc__.split("\n\n")[0], epilog=HELP_EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="verify the authorization and the account's address; send nothing")
    verbs = parser.add_subparsers(dest="verb")
    _mail.add_send_flags(verbs)
    _mail.add_verb_flags(verbs)
    return parser


def run(argv=None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return EXIT_OK if e.code in (0, None) else EXIT_USAGE
    if args.check:
        if args.verb:
            raise ProviderError("--check takes no verb", EXIT_USAGE)
        return cmd_check()
    if args.verb == "send":
        return cmd_send(args)
    if args.verb == "resolve":
        return _mail.cmd_resolve(args, IMPLEMENTATION)
    if args.verb == "lookup":
        return cmd_lookup(args)
    parser.print_usage(sys.stderr)
    return EXIT_USAGE


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        return run(argv)
    except (ProviderError, GraphError) as exc:
        log(f"error: {_mail.scrub(str(exc))}")
        return exc.code
    except Exception as exc:     # last resort: no traceback, which can hold a header or a body; only the kind of the failure
        log(f"error: unexpected {type(exc).__name__}; nothing was changed")
        return EXIT_SERVICE


if __name__ == "__main__":
    sys.exit(main())
