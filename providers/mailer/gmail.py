#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["keyring==25.7.0"]
# ///
"""Mailer provider for Gmail (class sender:email, package W2 of SPEC-SECRETARY-WRITES): send one e-mail from the person's own Google account, to exactly the
recipients it is given, once. The second implementation of the class, beside the SMTP outbox (providers/mailer/smtp.py); the runtime names it explicitly, from the
effect module runtime/effect_send.py, for a document whose `account` is google, and never lists it as the project's outbox.

Sources (Google's own documentation, accessed 2026-10-18; what could not be read there is listed under "To verify" in providers/mailer/README.md):
- users.messages.send (POST https://gmail.googleapis.com/gmail/v1/users/{userId}/messages/send; the body is a Message resource whose `raw` is the whole RFC 2822
  message, base64url encoded, and whose `threadId` puts a reply in a conversation; the scope gmail.modify is accepted):
  https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/send and https://developers.google.com/workspace/gmail/api/guides/sending
- Threads (a reply joins a thread when the `threadId` is given, the References and In-Reply-To headers follow RFC 2822, and the Subject matches):
  https://developers.google.com/workspace/gmail/api/guides/threads
- users.getProfile (GET /gmail/v1/users/{userId}/profile; emailAddress): https://developers.google.com/workspace/gmail/api/reference/rest/v1/users/getProfile
- users.messages.list and get (GET; `q` takes the Gmail search syntax, `rfc822msgid:` finds a message by its Message-ID, `in:sent` limits it to what the account sent):
  https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list and https://support.google.com/mail/answer/7190
- Scopes (gmail.modify: read, compose and send, and no permanent deletion): https://developers.google.com/workspace/gmail/api/auth/scopes

Usage:
  uv run providers/mailer/gmail.py --help
  uv run providers/mailer/gmail.py --check
  uv run providers/mailer/gmail.py send --from <addr> --to <addr>... [--cc <addr>...] [--bcc <addr>...] --subject-file <f> --body-file <f>
        [--attach <path>=<name>]... [--in-reply-to <id> [--references <id>...] [--thread-id <id>]] --message-id <oh.hex@domain> --idempotency-key <k> (--dry-run | --confirmed)
  uv run providers/mailer/gmail.py resolve --idempotency-key <k> (--sent | --not-sent) (--dry-run | --confirmed)
  uv run providers/mailer/gmail.py lookup --message-id <id>

  --check     refreshes the access token, checks that the account token carries the platform's whole set of scopes and reads the account's profile; prints
              {"ok": true, "from": <the account's address>, "obtained_at"}. Exit 3 when there is no authorization or the set is not the platform's.
  send        the recipients are exactly the flags (To and Cc, which the message's headers carry and the API reads, at most 20 in all; a display name, a comment, a
              line break, an encoded word `=?`, a second @ or a repeated address is exit 2; a Bcc is exit 2 in this version, see "To verify" in providers/mailer/README.md). The From address must be the address of the account token: the record's
              `account` and the service's own profile both say it, else exit 3 and nothing is sent. A reply carries --in-reply-to (the Message-ID of the message
              answered), the References chain (default: that message) and the --thread-id of its conversation.
  --dry-run   reads no credential, opens no connection and prints {"dry_run": true, "would": {...}, "would_sha256", "ledger"}: the headers, the envelope, the text,
              each attachment's name, size and sha256, the message as it reads back (`wire`) and the one request `--confirmed` sends (`requests`: the message `wire`
              describes, to which the send adds its Date header; the MIME boundaries are not content). The hash covers all of it.
  --confirmed sends exactly that. The key is recorded `pending` in the ledger first and `done` after the answer; a key that is `done` is not sent again
              (`replayed`), and a key left `pending` by an answer that was lost is looked up in the account's sent mail by its Message-ID (the message's own
              header, checked, and the label SENT) before anything is sent: found, `replayed`; not found, exit 4 until `resolve` records what the person found.
  resolve     settles a key left pending (--sent: delivered; --not-sent: not, after which the e-mail may be sent again).
  lookup      is this Message-ID among the sent messages of the account (read only): {"found", "count", "message_id"}.

Credentials (never from a flag or a file; contracts/secrets.md):
  GOOGLE_ACCOUNT_TOKEN   the account record (providers/accounts/google_auth.py), read through providers/secrets/resolver.py. There is no legacy record for a mailer:
                         a token that lacks one scope of the platform's set, or carries another, is refused (exit 3) before any call.
Test overrides (tests only, loopback URLs only, both set together; the secret store is then never read):
  MAILER_GMAIL_API_BASE    replaces https://gmail.googleapis.com
  MAILER_GMAIL_TOKEN_URL   replaces https://oauth2.googleapis.com/token

Limits. The request function sends only the methods and paths of ALLOWED and refuses anything else (limits L57, L58): the profile, the search and the metadata of
a message (GET), and the one send (POST). There is no delete, no trash, no modify and no draft in it. No redirect is followed. A verb never retries: a 429 is
reported with its Retry-After and nothing is sent; a 5xx or a lost connection on the send is exit 4 (it may have landed) and the key stays pending. Every request
has a 60-second timeout. Attachments weigh 3 MiB together at most (the message goes as one JSON request). The state is <state>/mailer-gmail/ (0700, files 0600),
where <state> is $OPENHORA_STATE_DIR, else $XDG_STATE_HOME/openhora, else ~/.local/state/openhora. Prints one JSON object on stdout; diagnostics on stderr. Exit
codes: 0 ok; 1 the service or the ledger refuses and NOTHING was sent; 2 usage; 3 not configured; 4 the outcome is not known (the key stays pending).
"""
from __future__ import annotations

import argparse
import base64
import datetime
import importlib.util
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.client import HTTPException    # by name: this module's own http() function shadows the module
from pathlib import Path

SERVES = "sender:email"
IMPLEMENTATION = "gmail"
ENV_BASE = "MAILER_GMAIL_API_BASE"
ENV_TOKEN_URL = "MAILER_GMAIL_TOKEN_URL"
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
HTTP_TIMEOUT_SECONDS = 60
ANSWER_LIMIT_BYTES = 1024 * 1024
ATTACH_TOTAL_MAX = 3 * 1024 * 1024
# The only requests this mailer sends (limits L57 and L58): a method and a full-match pattern of the path, as the request function sees it.
ALLOWED = (("GET", r"/gmail/v1/users/me/profile"),
           ("GET", r"/gmail/v1/users/me/messages"),
           ("GET", r"/gmail/v1/users/me/messages/[^/]+"),
           ("POST", r"/gmail/v1/users/me/messages/send"))
PROFILE, SEARCH, GET_MESSAGE, SEND = ALLOWED
SEND_PATH = "/gmail/v1/users/me/messages/send"
SEND_QUERY = {"fields": "id,threadId"}      # the query of the send, in the preview and on the wire alike


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


_google = _shared("providers_google_account", "_google.py")
_mail = _shared("providers_mailer_account", "_mailer_account.py")
ProviderError, Lost = _mail.ProviderError, _mail.Lost
EXIT_OK, EXIT_SERVICE, EXIT_USAGE, EXIT_NOT_CONFIGURED, EXIT_UNKNOWN = (_mail.EXIT_OK, _mail.EXIT_SERVICE, _mail.EXIT_USAGE, _mail.EXIT_NOT_CONFIGURED,
                                                                        _mail.EXIT_UNKNOWN)


def scrub(text) -> str:
    return _google.scrub(_mail.scrub(text))


def one_line(text, limit: int = 300) -> str:
    return scrub(_mail.one_line(text, limit))


def log(message: str) -> None:
    print(message, file=sys.stderr)


# --- configuration -----------------------------------------------------------------------------------------------------------


def endpoints() -> tuple:
    """(API base, token URL, test mode). The overrides are for tests and must be loopback URLs, both set together."""
    api, token = os.environ.get(ENV_BASE), os.environ.get(ENV_TOKEN_URL)
    if not api and not token:
        return _google.DEFAULT_GMAIL_BASE, _google.DEFAULT_TOKEN_URL, False
    if not (api and token):
        raise ProviderError(f"{ENV_BASE} and {ENV_TOKEN_URL} are for tests only and are set together", EXIT_USAGE)
    for name, value in ((ENV_BASE, api), (ENV_TOKEN_URL, token)):
        parsed = urllib.parse.urlparse(value)
        if parsed.scheme not in ("http", "https") or parsed.hostname not in LOOPBACK_HOSTS:
            raise ProviderError(f"{name} is for tests only and must be a loopback URL such as http://127.0.0.1:8080", EXIT_USAGE)
    return api.rstrip("/"), token, True


def secret_resolver():
    """The workbench's one secret resolver, by path: next to this file first (a copy run from a job folder), then providers/secrets/resolver.py."""
    here = Path(__file__).resolve()
    path = next((c for c in (here.parent / "resolver.py", here.parents[1] / "secrets" / "resolver.py") if c.is_file()), None)
    if path is None:
        raise ProviderError("providers/secrets/resolver.py is not next to this script nor in the workbench", EXIT_NOT_CONFIGURED)
    spec = importlib.util.spec_from_file_location("workbench_secret_resolver", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def open_session() -> tuple:
    """(API base, an access token, the account record) from the account record: the whole platform set, or exit 3. There is no legacy record for a mailer."""
    base, token_url, test_mode = endpoints()
    loaded = _google.load_account_record(secret_resolver(), test_mode, legacy=None, error=ProviderError)
    data = _google.refresh_access_token(token_url, loaded.record, ProviderError)
    _mail.hold(data["access_token"])
    return base, data["access_token"], loaded.record


# --- HTTP --------------------------------------------------------------------------------------------------------------------


class RefuseRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: every request carries a credential to an address that was checked. A write answered with a redirect reached the service."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        fp.close()
        lost = Lost if req.get_method() != "GET" else ProviderError
        raise lost(f"refusing to follow a {code} redirect on {req.get_method()} {urllib.parse.urlparse(req.full_url).path}; the request carries a credential")


OPENER = urllib.request.build_opener(RefuseRedirect)


def http(method: str, url: str, headers: dict, body, sent_on_error: bool) -> tuple:
    """One request; (status, at most ANSWER_LIMIT_BYTES + 1 bytes of the body, the Retry-After header or "") for any HTTP answer. A failure before the request
    could have reached the service is ProviderError (exit 1); one after it may have is Lost (exit 4) when `sent_on_error`."""
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    path = urllib.parse.urlparse(url).path
    unknown = Lost if sent_on_error else ProviderError
    try:
        with OPENER.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return response.status, response.read(ANSWER_LIMIT_BYTES + 1), ""
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.read(65536), one_line(exc.headers.get("Retry-After"), 40)
        finally:
            exc.close()
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ConnectionRefusedError) or "Name or service not known" in str(exc.reason):
            raise ProviderError(f"cannot reach Google on {method} {path}: nothing was sent") from None
        raise unknown(f"the connection to Google failed on {method} {path} ({one_line(exc.reason, 80)}): the request may or may not have landed") from None
    except TimeoutError:
        raise unknown(f"Google timed out on {method} {path} after {HTTP_TIMEOUT_SECONDS} s: the request may or may not have landed") from None
    except OSError as exc:
        raise unknown(f"the connection to Google failed on {method} {path} ({type(exc).__name__}): the request may or may not have landed") from None
    except (ValueError, HTTPException) as exc:
        raise unknown(f"the request {method} {path} could not be made or read ({type(exc).__name__})") from None


def request(entry: tuple, base: str, token: str, path: str, query: dict, body=None, sent_on_error: bool = False) -> tuple:
    """The one function that sends a request to the Gmail API. `entry` must be a pair of ALLOWED and `path` must match its pattern; anything else is refused
    before a connection is opened. Returns (status, body bytes, Retry-After)."""
    method, pattern = entry
    if entry not in ALLOWED or not re.fullmatch(pattern, path):
        raise ProviderError(f"this mailer does not send {method} {path}: it is not a request of its allow-list", EXIT_USAGE)
    url = base + path + ("?" + urllib.parse.urlencode(query) if query else "")
    sent = {"Authorization": f"Bearer {token}", "Accept": "application/json", "User-Agent": "openhora-mailer-gmail"}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        sent["Content-Type"] = "application/json; charset=utf-8"
    return http(method, url, sent, data, sent_on_error)


def failure(status: int, body: bytes, retry: str, what: str) -> ProviderError:
    reasons, message = "", ""
    try:
        error = json.loads(body).get("error")
        if isinstance(error, dict):
            message = one_line(error.get("message"), 200)
            listed = error.get("errors")
            reasons = ",".join(one_line(e.get("reason"), 40) for e in (listed if isinstance(listed, list) else []) if isinstance(e, dict))
    except (ValueError, AttributeError):
        pass
    detail = f": {message}{f' [{reasons}]' if reasons else ''}" if message or reasons else ""
    write = not what.startswith("GET")
    if status == 401:
        return ProviderError(f"Google rejected the access token ({what}){detail}; run: {_google.AUTH_COMMAND}", EXIT_NOT_CONFIGURED, status)
    after = f" Retry-After: {retry}." if retry else ""
    if write and (status >= 500 or status in (301, 302, 303, 307, 308) or 200 <= status < 300):      # an answer the documentation does not give for a send (a 2xx but 200) is not a refusal: the e-mail may have gone      # a write the service may have taken: like any server error, its outcome is not known
        return Lost(f"Google answered {status} ({what}){detail}: the e-mail may or may not have been sent", status)
    if status in (429, 503) or (status == 403 and "ateLimit" in reasons):
        return ProviderError(f"Google asked to slow down ({status} on {what}){detail}.{after} Nothing was sent or retried", EXIT_SERVICE, status)
    if status == 403:
        return ProviderError(f"Google refused the request ({what}){detail}; check that the Gmail API is enabled and that the account token is the person's own",
                             EXIT_SERVICE, status)
    return ProviderError(f"Google returned {status} ({what}){detail}", EXIT_SERVICE, status)


def json_of(body: bytes) -> dict:
    try:
        data = json.loads(body or b"{}")
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise ProviderError("Google answered something this mailer does not understand")
    return data


# --- the account ---------------------------------------------------------------------------------------------------------------


def profile_address(base: str, token: str):
    status, body, retry = request(PROFILE, base, token, "/gmail/v1/users/me/profile", {"fields": "emailAddress"})
    if status != 200:
        raise failure(status, body, retry, "GET profile")
    address = json_of(body).get("emailAddress")
    return address if isinstance(address, str) else None


def check_account(base: str, token: str, record: dict, sender: str) -> None:
    """The From address is the address of the account token: the record says it (written at the authorization) and the service's own profile says it. Else
    exit 3, and nothing is sent."""
    if not record.get("account"):
        raise ProviderError(f"the Google account record names no address (it was made before the address was kept): run {_google.AUTH_COMMAND}", EXIT_NOT_CONFIGURED)
    if not _mail.same_address(record["account"], sender):
        raise ProviderError("the From address is not the address of the Google account token: nothing was sent (the account token sends from its own address only)",
                            EXIT_NOT_CONFIGURED)
    if not _mail.same_address(profile_address(base, token), sender):
        raise ProviderError("Google says the account token belongs to another address than the From address: nothing was sent; run "
                            f"{_google.AUTH_COMMAND}", EXIT_NOT_CONFIGURED)


# --- the plan --------------------------------------------------------------------------------------------------------------------


def plan_of(args, mail) -> dict:
    """The e-mail the flags describe, checked whole, with the one request it sends and the hash of the whole preview. Nothing is read from the network or a
    credential."""
    if args.bcc:
        raise ProviderError("Bcc is refused in this version: the Gmail API reads the recipients from the headers of the message, and whether it removes a Bcc header "
                            "before delivery is not verified (a Bcc header it kept would show the hidden list to the others); send to To and Cc, or use the outbox", EXIT_USAGE)
    if args.reply_id:
        raise ProviderError("--reply-id is Outlook's: a Gmail reply joins its conversation through --thread-id", EXIT_USAGE)
    plan = _mail.plan_of(args, mail, total_max=ATTACH_TOTAL_MAX, with_wire=True)
    body = {"raw": "the message `wire` describes, built from the checked parts and read back", "date_header": "added at send"}
    if plan["thread_id"]:
        body["threadId"] = plan["thread_id"]
    return _mail.finish_plan(plan, mail, [{"method": "POST", "path": SEND_PATH, "query": SEND_QUERY, "body": body}], IMPLEMENTATION)


# --- looking a message up in the sent mail -------------------------------------------------------------------------------------------


def sent_count(base: str, token: str, message_id: str) -> int:
    """How many messages of the account's sent mail carry exactly this Message-ID. The search finds candidates; each one's own Message-ID header is read and
    compared, and it must carry the label SENT: the identity is the message's content, never its size or its time."""
    status, body, retry = request(SEARCH, base, token, "/gmail/v1/users/me/messages",
                                  {"q": f"rfc822msgid:{message_id.strip('<>')} in:sent", "maxResults": 5, "fields": "messages(id)"})
    if status != 200:
        raise failure(status, body, retry, "GET messages")
    found = 0
    for item in (json_of(body).get("messages") or []):
        ident = item.get("id") if isinstance(item, dict) else None
        if not isinstance(ident, str) or not _mail.PROVIDER_ID.fullmatch(ident):
            continue
        status, body, retry = request(GET_MESSAGE, base, token, f"/gmail/v1/users/me/messages/{urllib.parse.quote(ident, safe='')}",
                                      {"format": "metadata", "metadataHeaders": "Message-ID", "fields": "id,labelIds,payload(headers)"})
        if status != 200:
            raise failure(status, body, retry, "GET message")
        one = json_of(body)
        headers = (one.get("payload") or {}).get("headers") or []
        carries = any(isinstance(h, dict) and str(h.get("name", "")).lower() == "message-id" and str(h.get("value", "")).strip() == message_id for h in headers)
        if carries and "SENT" in (one.get("labelIds") or []):
            found += 1
    return found


# --- the verbs -----------------------------------------------------------------------------------------------------------------


def cmd_check() -> int:
    base, token, record = open_session()
    address = profile_address(base, token)
    if not address or not _mail.same_address(address, record.get("account") or address):
        raise ProviderError("Google says the account token belongs to another address than the one the record names: "
                            f"run {_google.AUTH_COMMAND}", EXIT_NOT_CONFIGURED)
    return _mail.emit({"ok": True, "from": address, "scope": sorted(_google.PLATFORM_SCOPES), "obtained_at": record.get("obtained_at")})


def cmd_send(args) -> int:
    mail = _mail.helpers()
    plan = plan_of(args, mail)
    if args.dry_run:
        return _mail.emit({"dry_run": True, "would": plan["would"], "would_sha256": plan["would_sha256"], "ledger": _mail.ledger_state(IMPLEMENTATION, plan["key"])})
    data = _mail.message_bytes(plan, mail, datetime.datetime.now(datetime.timezone.utc))      # read back: it says exactly what `wire` says (the Date is the one thing the send adds)
    base, token, record = open_session()
    check_account(base, token, record, plan["sender"])
    state, _ = _mail.claim(IMPLEMENTATION, plan, "sending")
    if state == "done":
        return _mail.emit(_mail.result(plan, True))
    if state == "pending":
        try:
            found = sent_count(base, token, plan["message_id"])
        except ProviderError as exc:
            raise Lost(f"an earlier attempt with this key did not say whether the e-mail was sent, and the sent mail cannot be looked up now ({exc}): look "
                       f"in the account's sent mail, then run resolve --idempotency-key {plan['key']} --sent or --not-sent") from None
        if not found:
            raise Lost("an earlier attempt with this key did not say whether the e-mail was sent, and it is not among the account's sent mail (by its "
                       "Message-ID): nothing is sent again until you settle the key. Gmail may have given the message another Message-ID than this one, and then "
                       "'not found' says nothing: look in the sent mail first, because resolve --not-sent can lead to a second copy; "
                       f"resolve --idempotency-key {plan['key']} --sent records it as delivered")
        _mail.record_done(IMPLEMENTATION, plan["key"])
        return _mail.emit(_mail.result(plan, True))
    body = {"raw": base64.urlsafe_b64encode(data).decode("ascii")}
    if plan["thread_id"]:
        body["threadId"] = plan["thread_id"]
    try:
        status, answer, retry = request(SEND, base, token, SEND_PATH, SEND_QUERY, body, sent_on_error=True)
    except Lost:
        raise          # the key stays pending: sending it again looks in the sent mail first
    except ProviderError:
        _mail.settle(IMPLEMENTATION, plan["key"], "released")      # nothing was sent
        raise
    except Exception as exc:      # anything else after the request was started: the e-mail may have been handed over, so the key stays pending
        raise Lost(f"the send ended with an unexpected {type(exc).__name__}: the e-mail may or may not have been sent") from None
    if status != 200:
        problem = failure(status, answer, retry, "POST send")
        if not isinstance(problem, Lost):
            _mail.settle(IMPLEMENTATION, plan["key"], "released")      # the service said no: nothing was sent, the key is free
        raise problem
    try:
        facts = json_of(answer)
    except ProviderError:
        facts = {}
    ident = facts.get("id") if isinstance(facts.get("id"), str) else None
    _mail.record_done(IMPLEMENTATION, plan["key"], service_id=ident)
    return _mail.emit(_mail.result(plan, False, len(data), **({"service_id": ident} if ident else {})))


def cmd_lookup(args) -> int:
    mail = _mail.helpers()
    if not mail.REFERENCE.fullmatch(args.message_id or ""):
        raise ProviderError("--message-id is one <local@domain> with no space", EXIT_USAGE)
    base, token, _ = open_session()
    found = sent_count(base, token, args.message_id)
    return _mail.emit({"found": found > 0, "count": found, "message_id": args.message_id})


HELP_EPILOG = """\
verbs:
  send     send one e-mail from the account's own address: --from <a> --to <a>... [--cc <a>...] [--bcc <a>...] --subject-file <f> --body-file <f>
           [--attach <path>=<name>]... [--in-reply-to <id> [--references <id>...] [--thread-id <id>]] --message-id <oh.hex@domain>
           --idempotency-key <k> (--dry-run | --confirmed). The recipients are exactly the flags (at most 20 in all); a Bcc is never a header.
  resolve  settle a key left pending: --idempotency-key <k> (--sent | --not-sent) (--dry-run | --confirmed)
  lookup   is this Message-ID among the account's sent messages? --message-id <id> (read only)
  --check  refresh the token, check its scopes and the account's address; sends nothing

environment: GOOGLE_ACCOUNT_TOKEN (or the OS secret store, store username google-account), OPENHORA_STATE_DIR.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gmail.py", description=__doc__.split("\n\n")[0], epilog=HELP_EPILOG,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="verify the authorization and the account's address; send nothing")
    verbs = parser.add_subparsers(dest="verb")
    _mail.add_send_flags(verbs)
    _mail.add_verb_flags(verbs)
    return parser


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
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
        if args.verb == "send":
            return cmd_send(args)
        if args.verb == "resolve":
            return _mail.cmd_resolve(args, IMPLEMENTATION)
        if args.verb == "lookup":
            return cmd_lookup(args)
        parser.print_usage(sys.stderr)
        return EXIT_USAGE
    except ProviderError as e:
        log(f"error: {scrub(str(e))}")
        return e.code
    except Exception as e:     # last resort: no traceback, which can hold a header or a body; only the kind of the failure
        log(f"error: unexpected {type(e).__name__}; nothing was changed")
        return EXIT_SERVICE


if __name__ == "__main__":
    sys.exit(main())
