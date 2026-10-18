#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["keyring==25.7.0"]
# ///
"""Calendar provider for Google Calendar: an implementation of the class integration:calendar. It lists the person's calendars and reads
the events of one calendar in a window, read only. The runtime turns what it prints into a dated snapshot a task can be given
(SPEC-SECRETARY-INTEGRATIONS, sections 1 to 3); nothing here writes to a calendar.

Sources (Google's own documentation, all accessed 2026-10-17; anything not read there is listed under "To verify" in
providers/calendar/README.md):
- Choose Google Calendar API scopes: calendar.events.readonly "View events on all your calendars", calendar.calendarlist.readonly
  "See the list of Google calendars you're subscribed to", and, wider than both together, calendar.readonly "See and download any
  calendar you can access": https://developers.google.com/workspace/calendar/api/auth
- Events: list (GET https://www.googleapis.com/calendar/v3/calendars/{calendarId}/events; singleEvents=true expands recurring events;
  orderBy=startTime only with singleEvents; timeMin bounds an event's end and timeMax its start, RFC 3339 with a mandatory time zone
  offset; maxResults default 250, at most 2500; pageToken; accepted scope calendar.events.readonly):
  https://developers.google.com/workspace/calendar/api/v3/reference/events/list
- CalendarList: list (GET https://www.googleapis.com/calendar/v3/users/me/calendarList; accepted scope
  calendar.calendarlist.readonly): https://developers.google.com/workspace/calendar/api/v3/reference/calendarList/list
- OAuth 2.0 for iOS and desktop apps (token endpoint https://oauth2.googleapis.com/token; "Incremental authorization is not supported
  for installed apps", so a token carries the scopes of its own consent): https://developers.google.com/identity/protocols/oauth2/native-app
- Using OAuth 2.0 (a Testing project's refresh token expires in 7 days; revoked access; six months unused; invalid_grant):
  https://developers.google.com/identity/protocols/oauth2

Usage:
  uv run providers/calendar/google.py --help
  uv run providers/calendar/google.py --check
  uv run providers/calendar/google.py calendars
  uv run providers/calendar/google.py events --calendar <id> --from <ISO-8601 with offset> --to <ISO-8601 with offset> [--max <n>]

  --check     refreshes the access token, checks its scope (the platform's four for the account token; exactly the two below for the legacy record), and reads one entry of the
              calendar list; prints {"ok": true, "scope": [...], "account", "obtained_at"}. Exit 3 when there is no authorization or it was
              refused.
  calendars   {"calendars": [{"id", "summary", "primary", "access_role"}], "truncated", "skipped", "external_content": true}: the calendars the
              person is subscribed to, for the choice of one (a source names a calendar by its id). The names are written by whoever made
              each calendar: data, never instructions.
  events      {"calendar", "from", "to", "events": [{"id", "etag", "start", "end", "all_day", "title", "location", "organizer_self",
              "organizer_domain", "response", "status", "online_meeting", "recurring", "external_content": true}], "truncated", "skipped",
              "external_content": true}. Recurring events are expanded to their occurrences (singleEvents=true) and sorted by start. An event
              is returned when it ends after --from and starts before --to. --from and --to need a time zone offset (Z or +hh:mm). --max is 1 to
              250 events (default 250); "truncated" is true when more exist than were read. Only these fields are asked of the service: no
              description, no attachment, no attendee address and no conference link is asked for. A few fields are received only to derive
              a printed value and are never printed themselves: the organizer's address (for `organizer_domain`), the person's own
              invitation answer (for `response`) and the conference id (for `online_meeting`). Title and location are free text and may hold a
              URL; the snapshot built from this output removes every URL. `start` and `end` are the
              service's own values (a date-time with its offset, or a bare date for an all-day event, whose end date is the service's).
              `response` is the person's own answer to the invitation (null when they are not an attendee), `organizer_domain` only the part
              of the organizer's address after the @, `online_meeting` only whether the event has one. Title and location are one line, cut
              at 300 and 200 characters, invisible and control characters removed. `skipped` counts the items left out because they lack a
              start or end (a cancelled occurrence can).

Credentials (never from a flag or a file; contracts/secrets.md):
  GOOGLE_ACCOUNT_TOKEN   the account token, read first: one JSON record of the person's Google account (refresh token, the Desktop app client,
                         the scope, the address), made by providers/accounts/google_auth.py. It carries the platform's four scopes
                         (calendar.events among them: the reads of this provider are covered, and nothing else is sent: GET only); a token that
                         lacks one of the four or carries another is refused (exit 3).
  Legacy, for one cycle, used only when no account record exists (a warning on stderr says so, once per process):
  GOOGLE_CALENDAR_TOKEN  one JSON record, read through providers/secrets/resolver.py (the environment, then the OS secret store, username
                         calendar-google): {"refresh_token", "client_id", "client_secret", "scope", "account", "obtained_at"}, written by
                         providers/calendar/google_auth.py after the person's consent. The client travels with the token, so this is the only
                         entry. Printed nowhere.
Test overrides (tests only, loopback URLs only, both set together; the secret store is then never read):
  INTEGRATION_CALENDAR_GOOGLE_API_BASE    replaces https://www.googleapis.com
  INTEGRATION_CALENDAR_GOOGLE_TOKEN_URL   replaces https://oauth2.googleapis.com/token

Only GET is sent to the Calendar API (the token endpoint is the one POST). No redirect is followed. A verb never retries: a 429 or 503 is
reported with its Retry-After. Every request has a 60-second timeout. Prints one JSON object on stdout; diagnostics on stderr. Exit codes:
0 ok, 1 failed (the service answered an error or could not be reached), 2 usage (a bad flag or id, a verb the provider does not have),
3 not configured (no authorization, one that expired or was revoked, a rejected client, a token whose scope is not the set its record needs).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from http.client import HTTPException    # by name: this module's own http() function shadows the module
from pathlib import Path

DEFAULT_API_BASE = "https://www.googleapis.com"
DEFAULT_TOKEN_URL = "https://oauth2.googleapis.com/token"
EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events.readonly"
LIST_SCOPE = "https://www.googleapis.com/auth/calendar.calendarlist.readonly"
SCOPES = (EVENTS_SCOPE, LIST_SCOPE)   # exactly these two: google_auth.py asks for them and this file requires them
SECRET = "GOOGLE_CALENDAR_TOKEN"
KEYRING_SERVICE = "openhora"
KEYRING_USERNAME = "calendar-google"
AUTH_COMMAND = "uv run <workbench>/providers/calendar/google_auth.py authorize"
ENV_BASE = "INTEGRATION_CALENDAR_GOOGLE_API_BASE"
ENV_TOKEN_URL = "INTEGRATION_CALENDAR_GOOGLE_TOKEN_URL"
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
HTTP_TIMEOUT_SECONDS = 60
ANSWER_LIMIT_BYTES = 4 * 1024 * 1024    # one page of the API; a larger answer is refused
DEFAULT_MAX, MAX_EVENTS = 250, 250      # --max, and its bound (the events: list default page size)
MAX_PAGES = 25                          # a page holds at least one event, but a service may answer short pages: a bound on the loop
MAX_CALENDAR_PAGES = 10                 # pages of the calendar list read (the service's own page size is used)
TITLE_LIMIT, LOCATION_LIMIT, NAME_LIMIT = 300, 200, 200
# A calendar id goes into a URL path, so its shape is checked before use (holiday calendars carry a #), and it is always percent-encoded.
CALENDAR_ID_RE = re.compile(r"[A-Za-z0-9._%+#@-]{1,254}")
DOMAIN_RE = re.compile(r"[a-z0-9.-]{1,253}")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
# A token goes into a header: printable ASCII without space, nothing that could split a header or fail to encode.
TOKEN_RE = re.compile(r"[\x21-\x7e]{1,4096}")
RESPONSES = ("needsAction", "declined", "tentative", "accepted")
STATUSES = ("confirmed", "tentative", "cancelled")
# The only fields asked of the service. The description, the attendees' addresses, the attachments and the conference links are not in it;
# organizer(email), attendees(self,responseStatus) and conferenceData(conferenceId) are received only to derive organizer_domain, response and
# online_meeting, and are never printed.
EVENT_FIELDS = ("nextPageToken,items(id,etag,status,summary,location,start,end,organizer(email,self),attendees(self,responseStatus),"
                "conferenceData(conferenceId),recurringEventId)")
CALENDAR_FIELDS = "nextPageToken,items(id,summary,primary,accessRole)"
EXIT_OK, EXIT_SERVICE, EXIT_USAGE, EXIT_NOT_CONFIGURED = 0, 1, 2, 3
RECORD_TEXTS = ("refresh_token", "client_id", "client_secret")

_SECRET_VALUES: list[str] = []   # every credential this process held: scrubbed from any text before it is printed


class ProviderError(Exception):
    def __init__(self, message: str, code: int = EXIT_SERVICE, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status


def _email_text_module():
    """providers/_email_text.py, by path: next to this folder's parent first (the workbench), then next to this file (a copy)."""
    here = Path(__file__).resolve()
    path = next((c for c in (here.parents[1] / "_email_text.py", here.parent / "_email_text.py") if c.is_file()), None)
    if path is None:
        raise SystemExit("error: providers/_email_text.py is not next to this script's folder")
    spec = importlib.util.spec_from_file_location("providers_email_text", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


INVISIBLE_RE = _email_text_module().INVISIBLE_RE


def _google_module():
    """providers/_google.py, by path: next to this folder's parent first (the workbench), then next to this file (a copy)."""
    here = Path(__file__).resolve()
    path = next((c for c in (here.parents[1] / "_google.py", here.parent / "_google.py") if c.is_file()), None)
    if path is None:
        raise SystemExit("error: providers/_google.py is not next to this script's folder")
    spec = importlib.util.spec_from_file_location("providers_google_account", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# The account token (one record, the platform's scope set) is read first; the old record is the legacy fallback for one cycle.
_google = _google_module()


def scrub(text: str) -> str:
    for value in _SECRET_VALUES:
        text = text.replace(value, "<hidden>")
    return _google.scrub(text)


def one_line(text, limit: int = 300) -> str:
    """Third-party text on one line: invisible and control characters removed, the space folded, cut at `limit`, no credential in it."""
    text = CONTROL_RE.sub(" ", INVISIBLE_RE.sub("", str(text if text is not None else "")))
    return scrub(" ".join(text.split()))[:limit]


def log(message: str) -> None:
    print(message, file=sys.stderr)


def emit(obj: dict) -> int:
    print(json.dumps(obj, indent=2, ensure_ascii=False))
    return EXIT_OK


# --- configuration -----------------------------------------------------------------------------------------------------------


def endpoints() -> tuple[str, str, bool]:
    """(API base, token URL, test mode). The overrides are for tests and must be loopback URLs, both set together."""
    api, token = os.environ.get(ENV_BASE), os.environ.get(ENV_TOKEN_URL)
    if not api and not token:
        return DEFAULT_API_BASE, DEFAULT_TOKEN_URL, False
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
    candidates = (here.parent / "resolver.py", here.parents[1] / "secrets" / "resolver.py")
    path = next((c for c in candidates if c.is_file()), None)
    if path is None:
        raise ProviderError("providers/secrets/resolver.py is not next to this script nor in the workbench", EXIT_NOT_CONFIGURED)
    spec = importlib.util.spec_from_file_location("workbench_secret_resolver", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_record(text: str) -> dict:
    """The authorization record from its JSON text; ProviderError (not configured) when it is unreadable or lacks what a refresh needs."""
    try:
        record = json.loads(text)
    except ValueError:
        record = None
    if not isinstance(record, dict) or not all(isinstance(record.get(k), str) and record[k] for k in RECORD_TEXTS):
        raise ProviderError(f"the stored Google Calendar authorization is unreadable or incomplete; run: {AUTH_COMMAND}", EXIT_NOT_CONFIGURED)
    for key in RECORD_TEXTS:
        if any(ch.isspace() or not ch.isprintable() for ch in record[key]):
            raise ProviderError(f"the Google Calendar authorization holds a {key} with whitespace or control characters; run: {AUTH_COMMAND}",
                                EXIT_NOT_CONFIGURED)
    _SECRET_VALUES.extend(record[k] for k in RECORD_TEXTS)
    return record


def legacy_record(test_mode: bool):
    """(the legacy record, where it was found), or None when GOOGLE_CALENDAR_TOKEN is found nowhere."""
    found = secret_resolver().resolve(SECRET, allow_store=not test_mode)
    return (parse_record(found[0]), found[1]) if found else None


def load_record(test_mode: bool) -> dict:
    """The record to sign in with: the account record (GOOGLE_ACCOUNT_TOKEN) first, else the legacy one for one cycle. The dict carries
    `kind` ("account" or "legacy"), which decides the scope rule of the refresh, and `source`, where it was found."""
    loaded = _google.load_account_record(secret_resolver(), test_mode, legacy=(KEYRING_USERNAME, lambda: legacy_record(test_mode), AUTH_COMMAND),
                                         error=ProviderError)
    _SECRET_VALUES.extend(loaded.record[k] for k in RECORD_TEXTS)
    return {**loaded.record, "kind": "legacy" if loaded.legacy else "account", "source": loaded.source}


# --- HTTP --------------------------------------------------------------------------------------------------------------------


class RefuseRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: every request carries a credential to an address that was checked."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        fp.close()
        path = urllib.parse.urlparse(req.full_url).path
        raise ProviderError(f"refusing to follow a {code} redirect on {req.get_method()} {path}; the request carries a credential",
                            EXIT_SERVICE, code)


OPENER = urllib.request.build_opener(RefuseRedirect)


def http(method: str, url: str, headers: dict, body: bytes | None = None, limit: int = ANSWER_LIMIT_BYTES) -> tuple[int, bytes, str]:
    """One request; (status, at most limit + 1 bytes of the body, the Retry-After header or "") for any HTTP answer, ProviderError otherwise.
    Only GET is ever sent to the API (the token endpoint is the one POST), and nothing else can be asked of this function."""
    if method not in ("GET", "POST") or (method == "POST") != (body is not None):
        raise ProviderError(f"this provider sends GET requests only (and one POST to the token endpoint), not {method}", EXIT_USAGE)
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    path = urllib.parse.urlparse(url).path
    try:
        with OPENER.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return response.status, response.read(limit + 1), ""
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.read(65536), one_line(exc.headers.get("Retry-After"), 40)
        finally:
            exc.close()
    except urllib.error.URLError as exc:
        raise ProviderError(f"cannot reach Google on {method} {path}: {one_line(exc.reason, 120)}") from None
    except TimeoutError:
        raise ProviderError(f"Google timed out on {method} {path} after {HTTP_TIMEOUT_SECONDS} s") from None
    except OSError as exc:
        raise ProviderError(f"the connection to Google failed on {method} {path}: {type(exc).__name__}") from None
    except (ValueError, HTTPException) as exc:
        # A header the library refuses (a line break, a character it cannot encode) or an answer that is not HTTP. The message of such an
        # exception can hold the header, which holds the token, so only the kind is named.
        raise ProviderError(f"the request {method} {path} could not be made or read ({type(exc).__name__})") from None


def token_text(value, what: str) -> str:
    """A token from the service, accepted only as printable ASCII without space: it is put in a header and in the OS secret store."""
    if not isinstance(value, str) or not TOKEN_RE.fullmatch(value):
        raise ProviderError(f"the token response holds {what} of an unexpected shape; nothing was used or stored")
    return value


def token_request(token_url: str, form: dict) -> dict:
    """POST to the token endpoint, mapping OAuth errors to exit codes. Shared with google_auth.py."""
    status, body, _ = http("POST", token_url, {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
                           urllib.parse.urlencode(form).encode())
    try:
        data = json.loads(body or b"{}")
    except ValueError:
        data = {}
    if status == 200 and isinstance(data, dict) and data.get("access_token"):
        _SECRET_VALUES.append(token_text(data["access_token"], "an access_token"))
        if data.get("refresh_token"):
            _SECRET_VALUES.append(token_text(data["refresh_token"], "a refresh_token"))
        return data
    error = one_line(data.get("error"), 80) if isinstance(data, dict) else ""
    description = one_line(data.get("error_description"), 160) if isinstance(data, dict) else ""
    detail = f"{error}: {description}" if description else error or "no error code"
    if error == "invalid_grant":
        if form.get("grant_type") == "refresh_token":
            raise ProviderError(f"Google refused the refresh token ({detail}): the authorization expired or was revoked (a project left in "
                                "\"Testing\" expires it after seven days; access removed in the Google Account does too). "
                                f"Run: {AUTH_COMMAND}", EXIT_NOT_CONFIGURED, status)
        raise ProviderError(f"Google refused the authorization code ({detail}); run it again", EXIT_SERVICE, status)
    if error in ("invalid_client", "unauthorized_client"):
        raise ProviderError(f"Google rejected the OAuth client ({detail}): check the client id and secret of a Desktop app client",
                            EXIT_NOT_CONFIGURED, status)
    if status == 200:
        raise ProviderError("the token response has no access_token", EXIT_SERVICE, status)
    raise ProviderError(f"the Google token endpoint returned {status} ({detail})", EXIT_SERVICE, status)


def check_scope(granted) -> None:
    """Refuse a token whose reported scope is anything but exactly the two scopes of this provider. A wider scope than the one asked for is a
    setup error to fix, not a token to use; a response that reports no scope cannot be shown to be the narrow one; a token missing one of
    the two cannot do what the provider does."""
    scopes = set(str(granted or "").split())
    if scopes != set(SCOPES):
        extra = ", ".join(sorted(scopes - set(SCOPES))) or "none"
        missing = ", ".join(sorted(set(SCOPES) - scopes)) or "none"
        raise ProviderError(f"the token reports {', '.join(sorted(scopes)) or 'no scope'} where exactly {EVENTS_SCOPE} and {LIST_SCOPE} are "
                            f"wanted (extra: {extra}; missing: {missing}): nothing was read. Revoke the app's access in the Google Account "
                            f"and run: {AUTH_COMMAND}", EXIT_NOT_CONFIGURED)


def refresh_access_token(token_url: str, record: dict) -> str:
    """A new access token (held in memory, used for this process) from the refresh token; checks the scope: the platform's set for the
    account record, exactly the two legacy scopes for the legacy one."""
    if record.get("kind") == "account":
        data = _google.refresh_access_token(token_url, record, ProviderError)
        _SECRET_VALUES.append(data["access_token"])
        return data["access_token"]
    data = token_request(token_url, {"client_id": record["client_id"], "client_secret": record["client_secret"],
                                     "grant_type": "refresh_token", "refresh_token": record["refresh_token"]})
    check_scope(data.get("scope"))
    return data["access_token"]


class Calendar:
    """The Calendar API as this provider uses it: GET requests with one access token."""

    def __init__(self, base: str, access_token: str, command: str = AUTH_COMMAND):
        self.base, self.token, self.command = base, access_token, command

    def get(self, path: str, params: dict) -> dict:
        url = self.base + path + "?" + urllib.parse.urlencode(params)
        status, body, retry = http("GET", url, {"Authorization": f"Bearer {self.token}", "Accept": "application/json",
                                                "User-Agent": "openhora-calendar-google"})
        if status == 200 and len(body) <= ANSWER_LIMIT_BYTES:
            try:
                data = json.loads(body)
            except ValueError:
                data = None
            if isinstance(data, dict):
                return data
            raise ProviderError(f"Google answered {path.rsplit('/', 1)[-1]} with something this provider does not understand")
        if status == 200:
            raise ProviderError(f"the answer to GET {path.rsplit('/', 1)[-1]} is over {ANSWER_LIMIT_BYTES} bytes; ask for fewer events")
        raise self.failure(status, body, retry, path)

    def failure(self, status: int, body: bytes, retry: str, path: str) -> ProviderError:
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
        what = f"GET {urllib.parse.urlparse(path).path.rsplit('/', 1)[-1]}"
        if status == 401:
            return ProviderError(f"Google rejected the access token ({what}){detail}; run: {self.command}", EXIT_NOT_CONFIGURED, status)
        if status == 404:
            return ProviderError(f"Google does not know this calendar for the authorized account ({what}){detail}: list the ids with the "
                                 "calendars verb", EXIT_SERVICE, status)
        if status in (429, 503) or (status == 403 and "ateLimit" in reasons):
            after = f" Retry-After: {retry}." if retry else ""
            return ProviderError(f"Google asked to slow down ({status} on {what}){detail}.{after} Nothing was retried; run it again later",
                                 EXIT_SERVICE, status)
        if status == 403:
            return ProviderError(f"Google refused the request ({what}){detail}; check that the Google Calendar API is enabled in the Google "
                                 "Cloud project and that the token carries the two calendar scopes", EXIT_SERVICE, status)
        return ProviderError(f"Google returned {status} ({what}){detail}", EXIT_SERVICE, status)


def open_calendar() -> Calendar:
    base, token_url, test_mode = endpoints()
    record = load_record(test_mode)
    return Calendar(base, refresh_access_token(token_url, record), _google.AUTH_COMMAND if record["kind"] == "account" else AUTH_COMMAND)


# --- the verbs ---------------------------------------------------------------------------------------------------------------


def calendar_id(value) -> str:
    if not isinstance(value, str) or not CALENDAR_ID_RE.fullmatch(value) or set(value) <= {"."}:
        raise ProviderError("--calendar is a Google calendar id as the calendars verb prints it (letters, digits and . _ % + # @ -, "
                            "at most 254 characters)", EXIT_USAGE)
    return value


def instant(flag: str, value) -> datetime:
    """An ISO-8601 time with a mandatory offset, as the service wants it; a time without one is refused, never read as local time."""
    raw = (value or "").strip()
    if not raw:
        raise ProviderError(f"events needs {flag} <ISO-8601 time with an offset such as 2026-10-17T00:00:00-03:00>", EXIT_USAGE)
    if raw.endswith(("Z", "z")):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        raise ProviderError(f"{flag} is not an ISO-8601 time: {one_line(value, 60)}", EXIT_USAGE) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProviderError(f"{flag} needs a time zone offset (Z or +hh:mm): the service refuses a time without one, and this provider "
                            "does not guess the local zone", EXIT_USAGE)
    if parsed.utcoffset().total_seconds() % 60:
        raise ProviderError(f"{flag} has an offset with seconds; use a whole number of minutes (+hh:mm)", EXIT_USAGE)
    return parsed.replace(microsecond=0)


def moment(value) -> tuple[str, bool] | None:
    """(the service's own start or end, whether it is an all-day date) or None when the item lacks a usable one."""
    if not isinstance(value, dict):
        return None
    if isinstance(value.get("dateTime"), str):
        text = value["dateTime"].strip()
        try:
            datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text)
        except ValueError:
            return None
        return one_line(text, 40), False
    if isinstance(value.get("date"), str):
        try:
            date.fromisoformat(value["date"])
        except ValueError:
            return None
        return value["date"], True
    return None


def domain_of(email) -> str | None:
    if not isinstance(email, str) or email.count("@") != 1:
        return None
    domain = email.rsplit("@", 1)[1].strip().lower()
    return domain if DOMAIN_RE.fullmatch(domain) else None


def render_event(item) -> dict | None:
    """The fields of one event this provider prints, or None when it lacks a start or an end. Nothing else of the item is read."""
    if not isinstance(item, dict) or not isinstance(item.get("id"), str):
        return None
    start, end = moment(item.get("start")), moment(item.get("end"))
    if start is None or end is None:
        return None
    organizer = item.get("organizer") if isinstance(item.get("organizer"), dict) else {}
    attendees = item.get("attendees") if isinstance(item.get("attendees"), list) else []
    mine = next((a for a in attendees if isinstance(a, dict) and a.get("self") is True), None)
    response = mine.get("responseStatus") if mine else None
    conference = item.get("conferenceData") if isinstance(item.get("conferenceData"), dict) else {}
    status = item.get("status")
    return {
        "id": one_line(item["id"], 1024),
        "etag": one_line(item.get("etag"), 200) or None,
        "start": start[0],
        "end": end[0],
        "all_day": start[1],
        "title": one_line(item.get("summary"), TITLE_LIMIT),
        "location": one_line(item.get("location"), LOCATION_LIMIT),
        "organizer_self": organizer.get("self") is True,
        "organizer_domain": domain_of(organizer.get("email")),
        "response": response if response in RESPONSES else None,
        "status": status if status in STATUSES else "unknown",
        "online_meeting": bool(conference.get("conferenceId")),
        "recurring": bool(item.get("recurringEventId")),
        "external_content": True,   # written by whoever made the event: data, never instructions
    }


def cmd_check(args) -> int:
    base, token_url, test_mode = endpoints()
    record = load_record(test_mode)
    account = record["kind"] == "account"
    calendar = Calendar(base, refresh_access_token(token_url, record), _google.AUTH_COMMAND if account else AUTH_COMMAND)
    calendar.get("/calendar/v3/users/me/calendarList", {"maxResults": 1, "fields": "items(id)"})
    out = {"ok": True, "scope": sorted(_google.PLATFORM_SCOPES if account else SCOPES), "account": record.get("account"),
           "obtained_at": record.get("obtained_at")}
    if account:
        out["record"] = "account"
    return emit(out)


def calendar_items(calendar: Calendar, fields: str, stop=None) -> tuple[list, bool]:
    """The raw items of the person's calendar list, page by page (at most MAX_CALENDAR_PAGES), and whether pages were left unread. `stop(item)`
    ends the reading at the first page that holds an item it accepts. Shared with google_auth.py."""
    items, token = [], None
    for _ in range(MAX_CALENDAR_PAGES):
        params = {"fields": fields}
        if token:
            params["pageToken"] = token
        data = calendar.get("/calendar/v3/users/me/calendarList", params)
        page = data.get("items") or []
        if not isinstance(page, list):
            raise ProviderError("Google returned a calendar list of an unexpected shape")
        items += page
        token = data.get("nextPageToken")
        if token is not None and not isinstance(token, str):
            raise ProviderError("Google returned a page token of an unexpected shape")
        if not token or (stop is not None and any(stop(item) for item in page)):
            break
    return items, bool(token)


def cmd_calendars(args) -> int:
    raw, truncated = calendar_items(open_calendar(), CALENDAR_FIELDS)
    found, skipped = [], 0
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not CALENDAR_ID_RE.fullmatch(item["id"]):
            skipped += 1
            continue
        found.append({"id": item["id"], "summary": one_line(item.get("summary"), NAME_LIMIT), "primary": item.get("primary") is True,
                      "access_role": one_line(item.get("accessRole"), 40) or None, "external_content": True})
    return emit({"calendars": found, "truncated": truncated, "skipped": skipped, "external_content": True})


def cmd_events(args) -> int:
    ident = calendar_id(args.calendar)
    low, high = instant("--from", args.time_from), instant("--to", args.time_to)
    if not low < high:
        raise ProviderError("--from must be before --to", EXIT_USAGE)
    wanted = DEFAULT_MAX if args.max is None else args.max
    if not 1 <= wanted <= MAX_EVENTS:
        raise ProviderError(f"--max must be between 1 and {MAX_EVENTS}", EXIT_USAGE)
    calendar = open_calendar()
    path = f"/calendar/v3/calendars/{urllib.parse.quote(ident, safe='')}/events"
    events, read, skipped, token = [], 0, 0, None
    for _ in range(MAX_PAGES):
        params = {"singleEvents": "true", "orderBy": "startTime", "timeMin": low.isoformat(), "timeMax": high.isoformat(),
                  "maxResults": wanted - read, "fields": EVENT_FIELDS}
        if token:
            params["pageToken"] = token
        data = calendar.get(path, params)
        items = data.get("items") or []
        if not isinstance(items, list):
            raise ProviderError("Google returned an event list of an unexpected shape")
        for item in items[:wanted - read]:
            rendered = render_event(item)
            if rendered is None:
                skipped += 1
            else:
                events.append(rendered)
        read += min(len(items), wanted - read)
        token = data.get("nextPageToken")
        if token is not None and not isinstance(token, str):
            raise ProviderError("Google returned a page token of an unexpected shape")
        if not token or read >= wanted or not items:
            break
    return emit({"calendar": ident, "from": low.isoformat(), "to": high.isoformat(), "events": events, "truncated": bool(token),
                 "skipped": skipped, "external_content": True})


FLAG_NAMES = {"calendar": "--calendar", "time_from": "--from", "time_to": "--to", "max": "--max"}
VERB_FLAGS = {"events": {"calendar", "time_from", "time_to", "max"}, "calendars": set(), None: set()}


def check_flags(args) -> None:
    """A flag given to a verb that does not read it is a usage error, so a caller learns that it was ignored; --check takes no verb."""
    if args.check and args.verb:
        raise ProviderError(f"--check takes no verb: run --check alone, or {args.verb} without --check", EXIT_USAGE)
    extra = [flag for dest, flag in FLAG_NAMES.items() if getattr(args, dest) is not None and dest not in VERB_FLAGS[args.verb]]
    if extra:
        raise ProviderError(f"{', '.join(extra)}: not a flag of {args.verb or '--check'} (see --help)", EXIT_USAGE)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="google.py", description=__doc__.split("\n\n")[0], epilog=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("verb", nargs="?", choices=["calendars", "events"], help="the action to run")
    parser.add_argument("--check", action="store_true", help="refresh a token, check its scope and read one calendar entry; prints no secret")
    parser.add_argument("--calendar", help="with events: the calendar id, as the calendars verb prints it")
    parser.add_argument("--from", dest="time_from", help="with events: ISO-8601 time with an offset; events ending after it")
    parser.add_argument("--to", dest="time_to", help="with events: ISO-8601 time with an offset; events starting before it")
    parser.add_argument("--max", type=int, help=f"with events: 1 to {MAX_EVENTS} events (default {DEFAULT_MAX})")
    return parser


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        check_flags(args)
        if args.check:
            return cmd_check(args)
        if args.verb == "calendars":
            return cmd_calendars(args)
        if args.verb == "events":
            return cmd_events(args)
        raise ProviderError("give a verb (calendars, events) or --check; see --help", EXIT_USAGE)
    except ProviderError as exc:
        log(f"error: {scrub(str(exc))}")
        return exc.code
    except Exception as exc:     # last resort: no traceback, which can hold a header or a body; only the kind of the failure
        log(f"error: unexpected {type(exc).__name__}; nothing was changed")
        return EXIT_SERVICE


if __name__ == "__main__":
    sys.exit(main())
