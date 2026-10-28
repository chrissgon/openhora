#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""What the Google providers share for the person's account token (decision of 2026-10-18, SPEC-SECRETARY-WRITES section 2): the Gmail
reader (providers/mailbox/gmail.py), the Google Calendar reader (providers/calendar/google.py), the Drive reader
(providers/documents/gdrive.py) and the authorization command (providers/accounts/google_auth.py). Each loads this file by path. A name
with an underscore is never listed as an implementation by providers/resolve.py, so this file is a module, not a provider.

The model: one OAuth client, one consent and one refresh token per Google account, carrying the platform's whole scope set. The token can do
everything those scopes allow; what restricts it is the platform (policies, effect cards of the exact content, the verbs each provider
script exposes, no token in a run), never a narrower token. A token that lacks a scope of the set, or carries one more, is refused.

The transition (CB-4, OPEN-CB-7, 2026-10-27): the set gained the Google Tasks scope. A token made before it carries the four scopes of
PREVIOUS_SCOPES, and the maintainer's accounts keep working until the person authorizes again: every provider but the tasks ones accepts
EXACTLY the five or EXACTLY the four (nothing between, nothing beyond); the tasks providers (`tasks=True`) accept exactly the five, and a
four-scope token is refused by them with the authorize command named. The authorization always asks the five. A follow-up (CB-4b) removes
PREVIOUS_SCOPES once both accounts carry the five.

  PLATFORM_SCOPES         the five scopes the platform asks, once, for every Google provider (the authorization asks all five)
  PREVIOUS_SCOPES         the four scopes a token made before Google Tasks was added carries; accepted, exactly, by every provider but the tasks ones
  check_platform_scope    a token response (the authorization and every refresh) must carry exactly the five (or, for a provider that does not
                          read tasks, exactly the four); a refresh that omits `scope` is accepted only when the record's stored scope is one of them
  parse_account_record    the one JSON record (slot, refresh token, client, scope, account, date) of the secret GOOGLE_ACCOUNT_TOKEN
  load_account_record     the account record first, a provider's legacy record (its old exact rule) when the account record is absent, with
                          one warning on stderr per process when the legacy one was used
  token_request, refresh_access_token   the token endpoint (the only POST this module sends), OAuth errors mapped to exit codes
  get_json                one GET with a bearer token to a checked address (the profile, at authorization)
  hold, scrub             every credential this process held is replaced by <hidden> in any text a provider prints

Standard library only; runs on Python 3.9. This file sends GET and the token POST and no other method, and follows no redirect.
Sources (Google's own documentation, accessed 2026-10-18): scopes https://developers.google.com/workspace/gmail/api/auth/scopes,
https://developers.google.com/workspace/calendar/api/auth, https://developers.google.com/workspace/drive/api/guides/api-specific-auth;
refresh tokens https://developers.google.com/identity/protocols/oauth2; desktop apps
https://developers.google.com/identity/protocols/oauth2/native-app.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import namedtuple
from http.client import HTTPException   # by name: a provider that loads this file has a function called http

EXIT_OK, EXIT_SERVICE, EXIT_USAGE, EXIT_NOT_CONFIGURED = 0, 1, 2, 3
SECRET = "GOOGLE_ACCOUNT_TOKEN"
KEYRING_SERVICE = "openhora"
KEYRING_USERNAME = "google-account"
AUTH_COMMAND = "uv run <workbench>/providers/accounts/google_auth.py authorize"
DEFAULT_TOKEN_URL = "https://oauth2.googleapis.com/token"
DEFAULT_GMAIL_BASE = "https://gmail.googleapis.com"
HTTP_TIMEOUT_SECONDS = 60
SLOT_RE = re.compile(r"[a-z0-9]{1,12}")
MAIN_SLOT = "main"
# The scopes of the platform (SPEC-SECRETARY-WRITES 2.1), in the order the consent screen lists them.
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
CALENDAR_EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events"
CALENDAR_LIST_SCOPE = "https://www.googleapis.com/auth/calendar.calendarlist.readonly"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
TASKS_SCOPE = "https://www.googleapis.com/auth/tasks"      # CB-4: "Create, edit, organize, and delete all your tasks" (the tasks providers send no delete: their ALLOWED has none)
PREVIOUS_SCOPES = (GMAIL_SCOPE, CALENDAR_EVENTS_SCOPE, CALENDAR_LIST_SCOPE, DRIVE_SCOPE)
PLATFORM_SCOPES = PREVIOUS_SCOPES + (TASKS_SCOPE,)
# Words a token response may carry that grant no access to mail, calendar or files: identity only. Anything else beyond the set is refused.
IGNORED_SCOPES = ("openid", "email", "profile", "https://www.googleapis.com/auth/userinfo.email",
                  "https://www.googleapis.com/auth/userinfo.profile")
RECORD_TEXTS = ("refresh_token", "client_id", "client_secret")
# A token goes into a header: printable ASCII without space, nothing that could split a header or fail to encode.
TOKEN_RE = re.compile(r"[\x21-\x7e]{1,4096}")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
ADDRESS_RE = re.compile(r"[^@\s]{1,64}@[^@\s]{1,253}")

_SECRET_VALUES = []   # every credential this process held: replaced by <hidden> in any text before it is printed
_WARNED = set()       # the legacy usernames already warned about in this process

Loaded = namedtuple("Loaded", "record source legacy")   # legacy: the username of the legacy record that served, or None for the account record


class AccountError(Exception):
    """An error with an exit code and a one-line message. A provider passes its own ProviderError as `error=` so that its main catches it."""

    def __init__(self, message, code=EXIT_SERVICE, status=None):
        super().__init__(message)
        self.code = code
        self.status = status


# --- credentials never printed -----------------------------------------------------------------------------------------------


def hold(*values) -> None:
    """Remember credentials so that scrub() can remove them from any text a provider prints."""
    for value in values:
        if isinstance(value, str) and value and value not in _SECRET_VALUES:
            _SECRET_VALUES.append(value)


def scrub(text) -> str:
    """The text with every held credential replaced by <hidden>, in one pass (a replacement is never scanned again)."""
    text = str(text)
    if not _SECRET_VALUES:
        return text
    return re.sub("|".join(re.escape(v) for v in sorted(_SECRET_VALUES, key=len, reverse=True)), "<hidden>", text)


def one_line(text, limit=300) -> str:
    """Third-party text on one line: control characters removed, the space folded, cut at `limit`, no credential in it."""
    text = CONTROL_RE.sub(" ", str(text if text is not None else ""))
    return scrub(" ".join(text.split()))[:limit]


# --- the scope set -------------------------------------------------------------------------------------------------------------


def scope_words(text) -> set:
    """The scopes a token response or a record names, without the words that grant no access."""
    return set(str(text or "").split()) - set(IGNORED_SCOPES)


def scope_problems(words, wanted=PLATFORM_SCOPES) -> tuple:
    """(missing, extra), each sorted, of a set of scope words against a wanted set (the platform's five by default). `extra` is always
    measured against the five: the four of a token made before Google Tasks are never extra."""
    return sorted(set(wanted) - set(words)), sorted(set(words) - set(PLATFORM_SCOPES))


def check_platform_scope(granted, stored=None, error=AccountError, outcome="nothing was read", tasks=False) -> None:
    """Refuse a token whose scope is not exactly the platform's set. `granted` is the `scope` of a token response (the authorization or a
    refresh). A refresh response that omits it is accepted only when the record's `stored` scope is the set: Google may leave it out, and a
    response that names no scope cannot be shown to be the right one on its own. `outcome` ends the message ("nothing was read" for a
    reader, "nothing was stored" for the authorization). The set is the five, or, unless `tasks` (a provider that reads or writes
    tasks, and the authorization), exactly the four of PREVIOUS_SCOPES: a token made before Google Tasks was added (CB-4, OPEN-CB-7)."""
    words = scope_words(granted)
    if not words:
        words = scope_words(stored)
    if words == set(PLATFORM_SCOPES) or (not tasks and words == set(PREVIOUS_SCOPES)):
        return
    if tasks and words == set(PREVIOUS_SCOPES):
        raise error(f"the account token was made before Google Tasks was added to the platform's set and lacks {TASKS_SCOPE}: {outcome}. "
                    f"Run {AUTH_COMMAND} and keep every box ticked on the consent screen", EXIT_NOT_CONFIGURED)
    missing, extra = scope_problems(words, PLATFORM_SCOPES if tasks else PREVIOUS_SCOPES)
    if missing:
        more = f"; it also carries {', '.join(extra)}, which the platform does not ask" if extra else ""
        raise error(f"the account token lacks {', '.join(missing)}{more}: {outcome}. Run {AUTH_COMMAND} and keep every box ticked "
                    "on the consent screen", EXIT_NOT_CONFIGURED)
    if extra:
        raise error(f"the account token carries {', '.join(extra)}, which the platform does not ask: {outcome}. Revoke the app's "
                    f"access in your Google Account (its third-party access page) and run {AUTH_COMMAND}", EXIT_NOT_CONFIGURED)


# --- the record ----------------------------------------------------------------------------------------------------------------


def parse_account_record(text, error=AccountError) -> dict:
    """The account record from its JSON text: a dict with the refresh token, the client id and secret, the slot, and the scope, account and
    date when the record has them. `error` (exit 3) when it is unreadable or lacks what a refresh needs."""
    try:
        record = json.loads(text)
    except (ValueError, TypeError):
        record = None
    if not isinstance(record, dict) or not all(isinstance(record.get(k), str) and record[k] for k in RECORD_TEXTS):
        raise error(f"the stored Google account authorization ({SECRET}, store username {KEYRING_USERNAME}) is unreadable or incomplete; "
                    f"no older record takes its place; run: {AUTH_COMMAND}", EXIT_NOT_CONFIGURED)
    for key in RECORD_TEXTS:
        if any(ch.isspace() or not ch.isprintable() for ch in record[key]):
            raise error(f"the Google account authorization ({SECRET}, store username {KEYRING_USERNAME}) holds a {key} with whitespace or "
                        f"control characters; run: {AUTH_COMMAND}", EXIT_NOT_CONFIGURED)
    slot = record.get("slot", MAIN_SLOT)
    if slot != MAIN_SLOT:
        raise error(f"the Google account authorization ({SECRET}, store username {KEYRING_USERNAME}) names the slot {one_line(slot, 20)!r}; "
                    f"only the slot {MAIN_SLOT!r} exists in this version; run: {AUTH_COMMAND}", EXIT_NOT_CONFIGURED)
    hold(*(record[k] for k in RECORD_TEXTS))
    out = {k: record[k] for k in RECORD_TEXTS}
    out["slot"] = MAIN_SLOT
    out["scope"] = record["scope"] if isinstance(record.get("scope"), str) else ""
    out["account"] = one_line(record["account"], 254) or None if isinstance(record.get("account"), str) else None
    out["obtained_at"] = one_line(record["obtained_at"], 40) or None if isinstance(record.get("obtained_at"), str) else None
    return out


def check_slot(slot, error=AccountError) -> str:
    """The slot word of --account: `main` is the only one in this version (another needs a registry row of its own, backlog ACCT-SLOT)."""
    if not isinstance(slot, str) or not SLOT_RE.fullmatch(slot):
        raise error("--account is a slot word of 1 to 12 lowercase letters and digits", EXIT_USAGE)
    if slot != MAIN_SLOT:
        raise error(f"the slot {slot!r} has no registry row yet: only {MAIN_SLOT!r} exists in this version", EXIT_USAGE)
    return slot


def find_account_record(resolver, test_mode, slot=MAIN_SLOT, error=AccountError):
    """(the record's JSON text, where it was found) through the secret resolver, or None when the record is ABSENT. The slot main is
    GOOGLE_ACCOUNT_TOKEN. A record that is there and cannot be read now (the OS secret store is locked or unavailable, the credentials
    directory or its file is not safe: any state but "missing") is not absent: `error` (exit 3) with the lookup's own detail, and no
    legacy record takes its place."""
    check_slot(slot, error)
    found = resolver.resolve_state(SECRET, allow_store=not test_mode)
    if found.state == "found":
        return found.value, found.source
    if found.state != "missing":
        raise error(f"the Google account authorization ({SECRET}, store username {KEYRING_USERNAME}) cannot be read ({found.state}): "
                    f"{one_line(found.detail, 300) or 'no detail'}; no older record takes its place", EXIT_NOT_CONFIGURED)
    return None


def legacy_warning(username) -> None:
    """One line on stderr, once per process and username, when a provider used its old record."""
    if username in _WARNED:
        return
    _WARNED.add(username)
    print(f"warning: using the legacy record {username}; run {AUTH_COMMAND} to move to the account token", file=sys.stderr)


def load_account_record(resolver, test_mode, slot=MAIN_SLOT, legacy=None, error=AccountError) -> Loaded:
    """The record a Google provider signs in with: the account record when there is one (an unreadable one is an error, not a reason to fall
    back: the legacy record is used only when the account record is ABSENT, and which record served is decided by the secret it was found
    under), else the provider's legacy record, else `error` (exit 3).

    `legacy` is (username, loader, command) of that provider (`command`: the authorize command of its legacy record, named in the message
    when nothing is found): loader() returns (record, source) in the same shape as an account record (refresh_token,
    client_id, client_secret, and whatever else the provider keeps), None when its old record is absent, and raises `error` when it is present
    but unusable. The legacy path keeps the provider's old exact scope check: the caller knows which record served from `Loaded.legacy`."""
    found = find_account_record(resolver, test_mode, slot, error)
    if found:
        return Loaded(parse_account_record(found[0], error), found[1], None)
    legacy_command = ""
    if legacy is not None:
        username, loader, command = legacy
        legacy_command = f" (or, for the legacy record of this provider, run {command})"
        got = loader()
        if got is not None:
            record, source = got
            hold(*(record.get(k) for k in RECORD_TEXTS))
            legacy_warning(username)
            return Loaded(record, source, username)
    raise error(f"no Google account authorization: run {AUTH_COMMAND}{legacy_command}, or export {SECRET} (the JSON record)",
                EXIT_NOT_CONFIGURED)


# --- the token endpoint --------------------------------------------------------------------------------------------------------


class RefuseRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: every request carries a credential to an address that was checked."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        fp.close()
        path = urllib.parse.urlparse(req.full_url).path
        raise AccountError(f"refusing to follow a {code} redirect on {req.get_method()} {path}; the request carries a credential",
                           EXIT_SERVICE, code)


OPENER = urllib.request.build_opener(RefuseRedirect)


def _send(method, url, headers, body, error) -> tuple:
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    path = urllib.parse.urlparse(url).path
    try:
        with OPENER.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return response.status, response.read(4 * 1024 * 1024 + 1)
    except AccountError as exc:
        raise error(str(exc), exc.code, exc.status) from None
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.read(65536)
        finally:
            exc.close()
    except urllib.error.URLError as exc:
        raise error(f"cannot reach Google on {method} {path}: {one_line(exc.reason, 120)}") from None
    except TimeoutError:
        raise error(f"Google timed out on {method} {path} after {HTTP_TIMEOUT_SECONDS} s") from None
    except OSError as exc:
        raise error(f"the connection to Google failed on {method} {path}: {type(exc).__name__}") from None
    except (ValueError, HTTPException) as exc:
        # A header the library refuses or an answer that is not HTTP. The message of such an exception can hold the header, which holds the
        # token, so only the kind is named.
        raise error(f"the request {method} {path} could not be made or read ({type(exc).__name__})") from None


def token_text(value, what, error=AccountError) -> str:
    """A token from the service, accepted only as printable ASCII without space: it is put in a header and in the OS secret store."""
    if not isinstance(value, str) or not TOKEN_RE.fullmatch(value):
        raise error(f"the token response holds {what} of an unexpected shape; nothing was used or stored")
    return value


def token_request(token_url, form, error=AccountError) -> dict:
    """POST to the token endpoint (the one POST of this module), mapping OAuth errors to exit codes."""
    status, body = _send("POST", token_url, {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
                         urllib.parse.urlencode(form).encode(), error)
    try:
        data = json.loads(body or b"{}")
    except ValueError:
        data = {}
    if status == 200 and isinstance(data, dict) and data.get("access_token"):
        hold(token_text(data["access_token"], "an access_token", error))
        if data.get("refresh_token"):
            hold(token_text(data["refresh_token"], "a refresh_token", error))
        return data
    reason = one_line(data.get("error"), 80) if isinstance(data, dict) else ""
    description = one_line(data.get("error_description"), 160) if isinstance(data, dict) else ""
    detail = f"{reason}: {description}" if description else reason or "no error code"
    if reason == "invalid_grant":
        if form.get("grant_type") == "refresh_token":
            raise error(f"Google refused the refresh token ({detail}): the authorization expired or was revoked. A likely cause: the Google "
                        "Cloud project is still in \"Testing\", where Google expires it seven days after consent (publish the app \"In "
                        "production\"). Other causes: access removed in the Google Account's third-party access page, a password change "
                        f"(the token carries a Gmail scope), six months without use. Run: {AUTH_COMMAND}", EXIT_NOT_CONFIGURED, status)
        raise error(f"Google refused the authorization code ({detail}); run it again", EXIT_SERVICE, status)
    if reason in ("invalid_client", "unauthorized_client"):
        raise error(f"Google rejected the OAuth client ({detail}): check the client id and secret of a Desktop app client", EXIT_NOT_CONFIGURED,
                    status)
    if status == 200:
        raise error("the token response has no access_token", EXIT_SERVICE, status)
    raise error(f"the Google token endpoint returned {status} ({detail})", EXIT_SERVICE, status)


def refresh_access_token(token_url, record, error=AccountError, tasks=False) -> dict:
    """A new access token from the account record's refresh token; the whole token response, after the scope check (`tasks`: a provider that
    needs the Google Tasks scope, see check_platform_scope)."""
    data = token_request(token_url, {"client_id": record["client_id"], "client_secret": record["client_secret"],
                                     "grant_type": "refresh_token", "refresh_token": record["refresh_token"]}, error)
    check_platform_scope(data.get("scope"), record.get("scope"), error, tasks=tasks)
    return data


def get_json(url, access_token, error=AccountError) -> dict:
    """One GET with a bearer token; the JSON object it answers. Used once, to read the address of the account at authorization."""
    status, body = _send("GET", url, {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}, None, error)
    path = urllib.parse.urlparse(url).path
    try:
        data = json.loads(body or b"{}")
    except ValueError:
        data = None
    if status == 200 and isinstance(data, dict):
        return data
    if status == 401:
        raise error(f"Google rejected the access token (401 on GET {path}); run: {AUTH_COMMAND}", EXIT_NOT_CONFIGURED, status)
    raise error(f"Google returned {status} on GET {path}", EXIT_SERVICE, status)


def account_address(gmail_base, access_token, error=AccountError):
    """The address the token belongs to, read once from the Gmail profile (users.getProfile), or None when it is not an address."""
    data = get_json(gmail_base.rstrip("/") + "/gmail/v1/users/me/profile", access_token, error)
    address = data.get("emailAddress")
    return address if isinstance(address, str) and ADDRESS_RE.fullmatch(address) else None
