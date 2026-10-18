#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""What the providers that sign in to Microsoft Graph share: the OneDrive documents provider (providers/documents/onedrive.py), the Outlook
mail reader (providers/mailbox/outlook.py) and the Outlook calendar reader (providers/calendar/outlook.py), each with its authorization
helper. Each loads this file by path. A name with an underscore is never listed as an implementation by providers/resolve.py, so this file is
a module, not a provider. The code was moved here from onedrive.py and onedrive_auth.py (package M1); onedrive.py keeps every name it had and
its tests did not change.

What is shared is the identity code and the plumbing of a request, never a registration and never a record: **each provider is its own
Microsoft app registration, with its own client id, its own permission and its own record** (Microsoft documents that a refresh token is
bound to a user and a client and is not tied to a resource, so a client that held two permissions could use one token for both:
https://learn.microsoft.com/en-us/entra/identity-platform/refresh-tokens, read 2026-10-17 by the author of the plan). A `Profile` carries
what differs between providers (the one permission, the secret, the words of the messages), and every function here takes the profile.

  Profile                 what one provider is: its permission, secret, record, commands and the words of its messages
  ProviderError, EXIT_*   the one error type of the providers and their exit codes (0 ok, 1 failed, 2 usage, 3 not configured)
  http                    one request: no redirect followed, a body bounded, every library error reduced to its kind
  token_request           the token endpoint (the only POST), OAuth errors mapped to exit codes and to the words a person needs
  check_scope             a token whose scope is anything but the profile's one permission is refused (exit 3)
  refresh_access_token    a refresh that names its scope; usable_access_token / usable_refresh_token: printable ASCII only
  store_rotation          Microsoft replaces the refresh token on every use: written back into the one record it came from, if it still holds
                          the token this process used (contracts/secrets.md rule 1)
  GraphClient             GET requests with one access token to one base address; failure() words an error answer
  checked_next_link       a next-page address is followed only when it is the same scheme, host, port and path as the request
  CallbackServer, authorize, forget, check, auth_main   the authorization command (PKCE S256, state, one loopback callback)

Standard library only (the OS secret store is reached through the `keyring` package a provider imports, never here). Runs on Python 3.9.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import importlib.util
import json
import os
import secrets
import socket
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timezone
from http.client import HTTPException   # not `import http.client`: onedrive.py has a function called http
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re

SCOPE_PREFIX = "https://graph.microsoft.com/"
DEFAULT_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
AUTHORIZE_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
IGNORED_SCOPES = ("offline_access", "openid", "profile", "email")   # reported next to the one permission and grant no access to a resource
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
LOOPBACK_V4, LOOPBACK_V6 = "127.0.0.1", "::1"
HTTP_TIMEOUT_SECONDS = 60
TENANT = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{0,99}")   # common, organizations, consumers, a tenant id or a verified domain
REDIRECT_STATUSES = (301, 302, 303, 307, 308)
ADMIN_CODES = ("AADSTS65001", "AADSTS90094")   # "not consented" / "admin consent required"; AADSTS65004 is "declined" (to verify live)
REDIRECT_EXAMPLE = "http://localhost"
SESSION_TIMEOUT_SECONDS = 600
HANDLER_TIMEOUT_SECONDS = 5     # a connection that sends nothing is dropped, never waited on for ever
EXIT_OK, EXIT_SERVICE, EXIT_USAGE, EXIT_NOT_CONFIGURED = 0, 1, 2, 3


class ProviderError(Exception):
    def __init__(self, message: str, code: int = EXIT_SERVICE, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status


def one_line(text, limit: int = 300) -> str:
    return " ".join(str(text or "").split())[:limit]


def log(message: str) -> None:
    print(message, file=sys.stderr)


def emit(obj: dict) -> int:
    print(json.dumps(obj))
    return EXIT_OK


class Profile:
    """What one provider is, for the code of this file. Every field is a word or a name; none is a credential.

    label            how messages call the provider's service ("OneDrive", "Outlook mail")
    scope            the one delegated Graph permission, without its prefix ("Files.Read")
    secret           the registry name of the record (contracts/secrets.md), and keyring_username the OS secret store entry
    auth_command     the command a message tells the person to run, as written in the provider's help
    run_hint         how the provider is started ("uv run providers/documents/onedrive.py"), for a missing keyring package
    env_prefix       the test overrides are <env_prefix>_API_BASE, _TOKEN_URL and, when `download_hosts`, _DOWNLOAD_HOSTS
    user_agent       the User-Agent of every request
    not_found / forbidden_hint   the words of a 404 and of a 403
    client_id_var / tenant_var   the variables the authorization command reads (the id is never a flag)
    registration     one sentence of the consent text: what the app registration holds
    """

    def __init__(self, *, label, scope, secret, keyring_username, auth_command, run_hint, env_prefix, user_agent, not_found,
                 forbidden_hint, client_id_var, tenant_var, download_hosts=False, keyring_service="openhora"):
        self.label, self.scope, self.secret = label, scope, secret
        self.keyring_service, self.keyring_username = keyring_service, keyring_username
        self.auth_command, self.run_hint, self.env_prefix, self.user_agent = auth_command, run_hint, env_prefix, user_agent
        self.not_found, self.forbidden_hint = not_found, forbidden_hint
        self.client_id_var, self.tenant_var, self.download_hosts = client_id_var, tenant_var, download_hosts

    @property
    def refresh_scope(self) -> str:
        """What the authorization and every refresh name: the one permission and offline_access, nothing else."""
        return f"{SCOPE_PREFIX}{self.scope} offline_access"

    @property
    def env_base(self) -> str:
        return f"{self.env_prefix}_API_BASE"

    @property
    def env_token_url(self) -> str:
        return f"{self.env_prefix}_TOKEN_URL"

    @property
    def env_download_hosts(self) -> str:
        return f"{self.env_prefix}_DOWNLOAD_HOSTS"


# --- configuration -----------------------------------------------------------------------------------------------------------


def endpoints(profile: Profile, default_hosts: tuple = ()) -> tuple:
    """(API base, token URL or None for the tenant's own, download hosts, test mode). The overrides are for tests, must name loopback
    addresses only and are set all together; in test mode the secret store is never read or written."""
    api, token = os.environ.get(profile.env_base), os.environ.get(profile.env_token_url)
    hosts = os.environ.get(profile.env_download_hosts) if profile.download_hosts else None
    if not api and not token and not hosts:
        return DEFAULT_GRAPH_BASE, None, default_hosts, False
    names = [profile.env_base, profile.env_token_url] + ([profile.env_download_hosts] if profile.download_hosts else [])
    if not (api and token and (hosts or not profile.download_hosts)):
        listed = ", ".join(names[:-1]) + f" and {names[-1]}"
        raise ProviderError(f"{listed} are for tests only and are set together", EXIT_USAGE)
    for name, value in ((profile.env_base, api), (profile.env_token_url, token)):
        parsed = urllib.parse.urlparse(value)
        if parsed.scheme not in ("http", "https") or parsed.hostname not in LOOPBACK_HOSTS:
            raise ProviderError(f"{name} is for tests only and must be a loopback URL such as http://127.0.0.1:8080", EXIT_USAGE)
    if not profile.download_hosts:
        return api.rstrip("/"), token, (), True
    listed_hosts = tuple(h.strip().lower() for h in hosts.split(",") if h.strip())
    if not listed_hosts or any(h not in LOOPBACK_HOSTS for h in listed_hosts):
        raise ProviderError(f"{profile.env_download_hosts} is for tests only and must list loopback names such as 127.0.0.1", EXIT_USAGE)
    return api.rstrip("/"), token, listed_hosts, True


def secret_resolver(script: str):
    """The workbench's secret resolver, by path: next to the provider's script first (a copy run from a job folder), then
    providers/secrets/resolver.py beside the script's folder, then beside this file."""
    here = Path(script).resolve()
    candidates = (here.parent / "resolver.py", here.parents[1] / "secrets" / "resolver.py", Path(__file__).resolve().parent / "secrets" / "resolver.py")
    path = next((c for c in candidates if c.is_file()), None)
    if path is None:
        raise ProviderError("providers/secrets/resolver.py is not next to this script nor in the workbench", EXIT_NOT_CONFIGURED)
    spec = importlib.util.spec_from_file_location("workbench_secret_resolver", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def keyring_module(profile: Profile, test_mode: bool):
    """The OS secret store. Test mode never touches it: tests replace the provider's function with a fake store. Used to write: the rotated
    refresh token by the provider, the record of an authorization by its authorization command."""
    if test_mode:
        raise ProviderError(f"test mode (the {profile.env_prefix}_* overrides) never uses the OS secret store", EXIT_USAGE)
    try:
        import keyring
    except ImportError:
        raise ProviderError(f"the keyring package is missing; run with: {profile.run_hint}", EXIT_NOT_CONFIGURED) from None
    return keyring


def bad_text(value) -> bool:
    return not isinstance(value, str) or not value or any(ch.isspace() or not ch.isprintable() for ch in value)


def plain_ascii(value) -> bool:
    """True for a non-empty string of printable ASCII with no space (the characters \\x21 to \\x7e): the only kind of token or id this code
    sends, stores or prints. Anything else is refused without being shown."""
    return isinstance(value, str) and bool(value) and all("!" <= ch <= "~" for ch in value)


def parse_record(profile: Profile, text: str) -> dict:
    """The authorization record from its JSON text; ProviderError (not configured) when it is unreadable or lacks what a refresh needs.
    A record without a tenant is read as `common`."""
    try:
        record = json.loads(text)
    except ValueError:
        record = None
    if not isinstance(record, dict) or not plain_ascii(record.get("refresh_token")) or not plain_ascii(record.get("client_id")):
        raise ProviderError(f"the stored {profile.label} authorization is unreadable or incomplete; run: {profile.auth_command}", EXIT_NOT_CONFIGURED)
    tenant = record.get("tenant") or "common"
    if not isinstance(tenant, str) or not TENANT.fullmatch(tenant):
        raise ProviderError(f"the {profile.label} authorization holds a tenant that is not a tenant name; run: {profile.auth_command}", EXIT_NOT_CONFIGURED)
    return {**record, "tenant": tenant}


def load_record(profile: Profile, resolver, test_mode: bool) -> tuple:
    """(record, where it was found): "environment", "credentials directory" or "secret store". `resolver` is the provider's own
    function (so that a test can replace it)."""
    found = resolver().resolve(profile.secret, allow_store=not test_mode)
    if not found:
        raise ProviderError(f"no {profile.label} authorization: run {profile.auth_command}, or export {profile.secret} (the JSON record)", EXIT_NOT_CONFIGURED)
    return parse_record(profile, found[0]), found[1]


# --- HTTP --------------------------------------------------------------------------------------------------------------------


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: a 3xx comes back as an answer, and each caller decides what it means (a refusal for every request that
    carries a credential, the Location of /content to be checked for the download)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def http(method: str, url: str, headers: dict, body: bytes | None = None, limit: int = 1024 * 1024, *, what: str) -> tuple:
    """One request; (status, headers, at most limit + 1 bytes of the body) for any HTTP answer, ProviderError otherwise. `what` names the
    request in an error (never the URL: a download address is a credential)."""
    try:
        request = urllib.request.Request(url, data=body, method=method, headers=headers)
        with OPENER.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return response.status, response.headers, response.read(limit + 1)
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.headers, exc.read(65536)
        finally:
            exc.close()
    except urllib.error.URLError as exc:
        raise ProviderError(f"cannot reach {what}: {one_line(exc.reason, 120)}") from None
    except TimeoutError:
        raise ProviderError(f"{what} timed out after {HTTP_TIMEOUT_SECONDS} s") from None
    except OSError as exc:
        raise ProviderError(f"the connection to {what} failed: {type(exc).__name__}") from None
    except (HTTPException, ValueError) as exc:
        # The standard library puts the offending header or address into these messages, and one of them can be a credential: say the
        # kind only.
        raise ProviderError(f"the request to {what} could not be made or read ({type(exc).__name__})") from None


def token_request(profile: Profile, token_url: str, form: dict) -> dict:
    """POST to the token endpoint, mapping OAuth errors to exit codes."""
    status, _, body = http("POST", token_url, {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
                           urllib.parse.urlencode(form).encode(), what="the Microsoft token endpoint")
    try:
        data = json.loads(body or b"{}")
    except ValueError:
        data = {}
    if status == 200 and isinstance(data, dict) and data.get("access_token"):
        return data
    error = one_line(data.get("error"), 80) if isinstance(data, dict) else ""
    description = one_line(data.get("error_description"), 200) if isinstance(data, dict) else ""
    detail = f"{error}: {description}" if description else error or "no error code"
    problem = consent_problem(profile, error, description)
    if problem:
        raise ProviderError(f"{problem[0]} ({detail})", problem[1], status)
    if error == "invalid_grant":
        if form.get("grant_type") == "refresh_token":
            raise ProviderError(f"Microsoft refused the refresh token ({detail}): the authorization expired (90 days unused), was revoked, "
                                f"or the password changed. Run: {profile.auth_command}", EXIT_NOT_CONFIGURED, status)
        raise ProviderError(f"Microsoft refused the authorization code ({detail}); run it again", EXIT_SERVICE, status)
    if error in ("invalid_client", "unauthorized_client", "invalid_request") and "AADSTS" in description:
        raise ProviderError(f"Microsoft rejected the app registration ({detail}): check the Application (client) ID, that the redirect URI "
                            "http://localhost is on the \"Mobile and desktop applications\" platform, and that no client secret is needed",
                            EXIT_NOT_CONFIGURED, status)
    if status == 200:
        raise ProviderError("the token response has no access_token", EXIT_SERVICE, status)
    raise ProviderError(f"the Microsoft token endpoint returned {status} ({detail})", EXIT_SERVICE, status)


def consent_problem(profile: Profile, error: str, description: str):
    """(sentence, exit code) when an OAuth error is about the person's consent, in the words that tell them what to do; None otherwise.
    A declined sign-in is not a setup problem (exit 1); a consent the admin must give, or a step the command cannot take, is (exit 3)."""
    command = profile.auth_command
    if "AADSTS65004" in description:
        return f"the sign-in was declined, so nothing was stored: run `{command}` again and accept the permission", EXIT_SERVICE
    if error == "interaction_required":
        return ("Microsoft asks for a step this command cannot take (a multi-factor sign-in, or a rule of your organisation's conditional access): "
                f"sign in again with `{command}`; if it keeps asking, your Microsoft 365 admin must allow this app"), EXIT_NOT_CONFIGURED
    if error == "consent_required" or any(code in description for code in ADMIN_CODES):
        return (f"Microsoft needs a consent this account has not given: your Microsoft 365 admin must approve the app. "
                f"Ask them, then run `{command}`"), EXIT_NOT_CONFIGURED
    return None


def scopes_of(granted) -> set:
    """The scopes of a token response, the Graph prefix removed; the ones that grant no access to a resource ignored."""
    names = set()
    for word in str(granted or "").split():
        word = word[len(SCOPE_PREFIX):] if word.lower().startswith(SCOPE_PREFIX) else word
        if word.lower() not in IGNORED_SCOPES:
            names.add(word)
    return names


def check_scope(profile: Profile, granted) -> str:
    """Refuse a token whose reported scope is anything but the profile's one permission (plus the scopes that grant no access): a wider
    scope than this app asks for is a setup error to fix (a permission left on the registration), not a token to use, and a response that
    reports no scope cannot be shown to be the narrow one. Compared without case. Returns the permission."""
    names = scopes_of(granted)
    if {n.lower() for n in names} != {profile.scope.lower()}:
        extra = ", ".join(sorted(n for n in names if n.lower() != profile.scope.lower())) or "none"
        raise ProviderError(f"the token reports {', '.join(sorted(names)) or 'no scope'} where exactly {profile.scope} is wanted (extra: {extra}): "
                            "nothing was read. Remove the other permissions from the app registration (API permissions), revoke the app's "
                            f"access in your Microsoft account, and run: {profile.auth_command}", EXIT_NOT_CONFIGURED)
    return profile.scope


def usable_access_token(data: dict) -> str:
    """The access token of a token response, when it is something this provider will put in a header: printable ASCII, no space. A value
    with a line break could add a header, and the library would print it in an error; it is refused without being shown."""
    token = data.get("access_token")
    if not plain_ascii(token):
        raise ProviderError("the token response holds an access token this provider will not send (a space, a control character or a "
                            "non-ASCII character in it); nothing was read")
    return token


def refresh_access_token(profile: Profile, token_url: str, record: dict) -> tuple:
    """(a new access token held in memory for this process, the refresh token Microsoft issued with it or None); checks the scope. The
    request names its scope so that the access token is no wider than asked, and sends no client secret: the app is a public client. A
    refresh token that is not printable ASCII is not kept (a note says so, never its value)."""
    data = token_request(profile, token_url, {"client_id": record["client_id"], "grant_type": "refresh_token",
                                              "refresh_token": record["refresh_token"], "scope": profile.refresh_scope})
    check_scope(profile, data.get("scope"))
    access = usable_access_token(data)
    rotated = data.get("refresh_token")
    if rotated is not None and not plain_ascii(rotated):
        log("note: Microsoft issued a refresh token this provider will not keep (a space, a control character or a non-ASCII character in it)")
        rotated = None
    return access, rotated


def store_rotation(profile: Profile, record: dict, rotated, where: str, test_mode: bool, resolver, keyring) -> str:
    """Microsoft replaces the refresh token on every use (the old one stays valid until it expires). When the record was found in the OS
    secret store, write the new token into that one record; when the write fails, carry on with the old token and say so. Returns what
    happened: "stored", "not rotated", "not stored (<why>)". `resolver` and `keyring` are the provider's own functions."""
    if not rotated or rotated == record["refresh_token"]:
        return "not rotated"
    if test_mode or where != "secret store":
        return "not stored: the record comes from the environment or the credentials directory"
    try:
        # Write only into the record this process used: read it again through the resolver, and leave it alone when it is gone (forgotten)
        # or holds another refresh token (a newer authorization, or another process that rotated first).
        again = resolver().resolve(profile.secret, allow_store=True)
        try:
            current = json.loads(again[0]) if again and again[1] == "secret store" else None
        except ValueError:
            current = None
        if not isinstance(current, dict) or current.get("refresh_token") != record["refresh_token"]:
            log(f"note: the stored {profile.label} authorization changed (or was forgotten) while this ran; the new refresh token was not stored")
            return "not stored: the record changed meanwhile"
        keyring(test_mode).set_password(profile.keyring_service, profile.keyring_username, json.dumps({**current, "refresh_token": rotated}))
    except Exception as exc:   # a locked or missing store, headless: the old token still works until it expires
        log(f"warning: Microsoft issued a new refresh token and it could not be stored ({type(exc).__name__}); carrying on with the old one, "
            f"which works until it expires. If a later call is refused, run: {profile.auth_command}")
        return f"not stored ({type(exc).__name__})"
    return "stored"


def checked_next_link(link, request_url: str) -> str:
    """The address of the next page Graph named (`@odata.nextLink`), when it is the request's own: the same scheme, host, port and path (the
    page numbers are in the query), no user or password in it, and nothing outside \\x21-\\x7e. ProviderError otherwise, naming the host and
    never the rest of the address. A next link to another host, scheme, port or path is never followed: the request carries the access token."""
    if not isinstance(link, str) or not link or any(not "!" <= ch <= "~" for ch in link):
        raise ProviderError("Graph named a next-page address with characters an address does not hold; nothing more was read")
    try:
        wanted, got = urllib.parse.urlparse(request_url), urllib.parse.urlparse(link)
        same = (got.scheme == wanted.scheme and (got.hostname or "").lower() == (wanted.hostname or "").lower() and got.port == wanted.port
                and not got.username and not got.password
                and urllib.parse.unquote(got.path) == urllib.parse.unquote(wanted.path))
    except ValueError:
        raise ProviderError("Graph named a next-page address this provider cannot read; nothing more was read") from None
    if not same:
        try:
            host = one_line(urllib.parse.urlparse(link).hostname or "", 100) or "an address without a host"
        except ValueError:
            host = "an address this provider cannot read"
        raise ProviderError(f"refusing to follow a next-page address that leaves the request (it names {host}, or another scheme, port or path); "
                            "nothing more was read")
    return link


class GraphClient:
    """Microsoft Graph as these providers use it: GET requests with one access token, to one base address. Nothing here sends anything else."""

    def __init__(self, profile: Profile, base: str, access_token: str, test_mode: bool):
        self.profile, self.base, self.token, self.test_mode = profile, base, access_token, test_mode

    def url_for(self, path: str, params: dict | None) -> str:
        query = "&".join(f"{key}={urllib.parse.quote(value, safe=',')}" for key, value in (params or {}).items())   # the keys are ours ($select, $top)
        return self.base + path + ("?" + query if query else "")

    def get_url(self, url: str, limit: int = 1024 * 1024, extra: dict | None = None) -> tuple:
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json", "User-Agent": self.profile.user_agent, **(extra or {})}
        return http("GET", url, headers, limit=limit, what="Microsoft Graph")

    def get(self, path: str, params: dict | None, limit: int = 1024 * 1024, extra: dict | None = None) -> tuple:
        return self.get_url(self.url_for(path, params), limit, extra)

    def read_json(self, status: int, headers, body: bytes, what: str, limit: int) -> dict:
        if status != 200:
            raise self.failure(status, headers, body, what)
        if len(body) > limit:
            raise ProviderError(f"Graph answered more than {limit} bytes for one request ({what}); ask for less")
        try:
            data = json.loads(body)
        except ValueError:
            data = None
        if not isinstance(data, dict):
            raise ProviderError("Graph answered something this provider does not understand")
        return data

    def json(self, path: str, params: dict | None, what: str, limit: int = 1024 * 1024, extra: dict | None = None) -> dict:
        status, headers, body = self.get(path, params, limit, extra)
        return self.read_json(status, headers, body, what, limit)

    def json_url(self, url: str, what: str, limit: int = 1024 * 1024, extra: dict | None = None) -> dict:
        status, headers, body = self.get_url(url, limit, extra)
        return self.read_json(status, headers, body, what, limit)

    def failure(self, status: int, headers, body: bytes, what: str) -> ProviderError:
        profile = self.profile
        code, message = "", ""
        try:
            error = json.loads(body).get("error")
            if isinstance(error, dict):
                code, message = one_line(error.get("code"), 60), one_line(error.get("message"), 200)
        except (ValueError, AttributeError):
            pass
        detail = f": {message}{f' [{code}]' if code else ''}" if message or code else ""
        if status in REDIRECT_STATUSES:
            return ProviderError(f"refusing to follow a {status} redirect on {what}; the request carries a credential", EXIT_SERVICE, status)
        if status == 401:
            return ProviderError(f"Graph rejected the access token ({what}){detail}; run: {profile.auth_command}", EXIT_NOT_CONFIGURED, status)
        if status == 404:
            return ProviderError(f"{profile.not_found} ({what}){detail}", EXIT_SERVICE, status)
        if status in (429, 503):
            wait = str((headers.get("Retry-After") if headers is not None else "") or "").strip()
            after = f"; retry after {wait} seconds" if wait.isdigit() else "; try again later"
            return ProviderError(f"Graph is busy or limiting requests ({status} on {what}){after}{detail}", EXIT_SERVICE, status)
        if status == 403:
            return ProviderError(f"Graph refused the request ({what}){detail}; {profile.forbidden_hint}", EXIT_SERVICE, status)
        return ProviderError(f"Graph returned {status} ({what}){detail}", EXIT_SERVICE, status)


# --- the authorization command -----------------------------------------------------------------------------------------------


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def pkce_pair() -> tuple:
    """(code_verifier, code_challenge) for S256: 86 unreserved characters, then base64url(sha256), no padding."""
    verifier = secrets.token_urlsafe(64)
    return verifier, base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode()


def authorize_url(profile: Profile, client_id: str, tenant: str, redirect_uri: str, state: str, challenge: str) -> str:
    """The consent URL: the one permission plus offline_access (a refresh token), PKCE S256, the state, the code in the query (no id token)
    and the account chooser."""
    query = urllib.parse.urlencode({
        "client_id": client_id, "response_type": "code", "redirect_uri": redirect_uri, "response_mode": "query", "scope": profile.refresh_scope,
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256", "prompt": "select_account"}, quote_via=urllib.parse.quote)
    return AUTHORIZE_URL_TEMPLATE.format(tenant=tenant) + "?" + query


def state_matches(received: str, expected: str) -> bool:
    return hmac.compare_digest(received.encode("utf-8"), expected.encode("utf-8"))


class IPv6Server(ThreadingHTTPServer):
    address_family = socket.AF_INET6

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        super().server_bind()


PAGES = {
    "ok": "Authorization received. You can close this tab and return to the terminal.",
    "refused": "The authorization was not granted. Nothing was stored. You can close this tab.",
    "state": "State mismatch. Nothing was stored. You can close this tab.",
}


class CallbackServer:
    """One loopback listener on a random port (127.0.0.1, and ::1 on the same port when the machine has it, since a browser may resolve
    `localhost` to either). It serves the single redirect from Microsoft: only with the Host `localhost:<port>`, only a request shaped
    like a callback (a `state` and a `code` or an `error`), once; a request logged nowhere; nothing it receives is shown back.
    A provider's authorization helper subclasses it and sets `profile`."""

    profile: Profile | None = None

    def __init__(self, expected_state: str):
        self.expected_state = expected_state
        self.outcome: dict = {}
        self.done = threading.Event()
        self.lock = threading.Lock()
        self.served = False
        owner = self

        class Handler(BaseHTTPRequestHandler):
            timeout = HANDLER_TIMEOUT_SECONDS

            def log_message(self, *args):   # silence request logs: the request line carries the code
                return

            def _bare(self, status):
                self.send_response(status)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_GET(self):   # noqa: N802 (http.server naming)
                if (self.headers.get("Host") or "").strip().lower() != owner.host:
                    return self._bare(403)   # a page on the internet cannot reach this listener through a name of its own
                parsed = urllib.parse.urlparse(self.path)
                query = urllib.parse.parse_qs(parsed.query)
                if parsed.path != "/" or "state" not in query or not ("code" in query or "error" in query):
                    return self._bare(404)   # not a callback: it consumes nothing
                with owner.lock:
                    first, owner.served = not owner.served, True
                if not first:
                    return self._bare(404)   # the callback is served once
                page = owner.accept(query)
                body = f"<!doctype html><meta charset=utf-8><meta name=referrer content=no-referrer><title>openhora</title><p>{PAGES[page]}</p>".encode()
                self.send_response(200 if page == "ok" else 400)
                for key, value in (("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(body))), ("Cache-Control", "no-store"),
                                   ("Referrer-Policy", "no-referrer"), ("X-Content-Type-Options", "nosniff"),
                                   ("Content-Security-Policy", "default-src 'none'")):
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)
                self.wfile.flush()
                owner.done.set()

        try:
            first_server = ThreadingHTTPServer((LOOPBACK_V4, 0), Handler)
        except OSError as exc:
            raise ProviderError(f"cannot listen on {LOOPBACK_V4}: {exc.strerror}") from None
        self.servers = [first_server]
        port = first_server.server_address[1]
        try:
            self.servers.append(IPv6Server((LOOPBACK_V6, port), Handler))
        except OSError:
            log("note: this machine has no usable ::1; if your browser resolves localhost to ::1 the redirect will not arrive: try again or use "
                "another browser")
        for server in self.servers:
            server.daemon_threads = True
        self.port = port
        self.host = f"localhost:{port}"
        self.redirect_uri = f"http://localhost:{port}"
        self.threads = [threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True) for s in self.servers]
        for thread in self.threads:
            thread.start()

    def accept(self, query: dict) -> str:
        """Read the callback (called once); returns which page to show."""
        state = query.get("state", [""])[0]
        if not state_matches(state, self.expected_state):
            self.outcome = {"error": "the state parameter does not match; possible CSRF, nothing stored", "exit": EXIT_SERVICE}
            return "state"
        if "error" in query:
            error = one_line(query["error"][0], 80)
            description = one_line(query.get("error_description", [""])[0], 200)
            detail = f"{error}: {description}" if description else error
            problem = consent_problem(self.profile, error, description)
            if problem:
                self.outcome = {"error": f"{problem[0]} ({detail}); nothing stored", "exit": problem[1]}
            else:
                self.outcome = {"error": f"Microsoft returned {detail}; nothing stored", "exit": EXIT_SERVICE}
            return "refused"
        self.outcome = {"code": query["code"][0]}
        return "ok"

    def wait(self, timeout: float = SESSION_TIMEOUT_SECONDS) -> str:
        try:
            if not self.done.wait(timeout):
                raise ProviderError(f"no callback within {timeout:g} seconds")
        finally:
            self.close()
        if "error" in self.outcome:
            raise ProviderError(self.outcome["error"], self.outcome["exit"])
        return self.outcome["code"]

    def close(self) -> None:
        for server in self.servers:
            server.shutdown()
            server.server_close()
        self.servers = []


def client_inputs(profile: Profile) -> dict:
    """The client id (and, for an office's own registration, the tenant) of the one command: the environment, else a hidden prompt on a
    terminal for the id. Never a flag."""
    client = (os.environ.get(profile.client_id_var) or "").strip()
    if not client and sys.stdin.isatty():
        client = getpass.getpass(f"{profile.client_id_var} (the Application (client) ID of the app registration): ").strip()
    if not client:
        raise ProviderError(f"{profile.client_id_var} (the Application (client) ID) is not set: export it for this one command, or run it in a terminal "
                            "to type it at a hidden prompt", EXIT_NOT_CONFIGURED)
    if bad_text(client) or len(client) > 100 or not plain_ascii(client):
        raise ProviderError(f"{profile.client_id_var} holds whitespace, control or non-ASCII characters, or is too long", EXIT_USAGE)
    tenant = (os.environ.get(profile.tenant_var) or "common").strip()
    if not TENANT.fullmatch(tenant):
        raise ProviderError(f"{profile.tenant_var} is common, organizations, consumers, a tenant id or a verified domain", EXIT_USAGE)
    return {"client_id": client, "tenant": tenant}


def authorize(profile: Profile, provider, server_cls, open_browser: bool, account_kind=None) -> int:
    """The authorization command of a provider. `provider` is the provider's module (its endpoints, keyring_module, token_request,
    check_scope, usable_access_token and Graph are looked up when this runs, so that a test can replace them); `server_cls` the callback
    server; `account_kind(graph)` an optional function that names the kind of account from one read (a failure there is a note)."""
    base, token_url, hosts, test_mode = provider.endpoints()
    given = client_inputs(profile)
    store = provider.keyring_module(test_mode)   # fail before the browser step when the store is unavailable
    state = secrets.token_urlsafe(32)
    verifier, challenge = pkce_pair()
    server = server_cls(state)
    try:
        url = authorize_url(profile, given["client_id"], given["tenant"], server.redirect_uri, state, challenge)
        log("Open this URL in your browser (it holds no secret):")
        log(url)
        if open_browser:
            webbrowser.open(url)
        log(f"Waiting up to {SESSION_TIMEOUT_SECONDS // 60} minutes on {server.redirect_uri}; the listener stops after one callback ...")
    except BaseException:
        server.close()
        raise
    code = server.wait()
    data = provider.token_request(token_url or TOKEN_URL_TEMPLATE.format(tenant=given["tenant"]), {
        "client_id": given["client_id"], "grant_type": "authorization_code", "code": code, "redirect_uri": server.redirect_uri,
        "code_verifier": verifier, "scope": profile.refresh_scope})
    scope = provider.check_scope(data.get("scope"))   # a wider permission left on the registration: nothing is stored
    refresh = data.get("refresh_token")
    if not plain_ascii(refresh):
        raise ProviderError("Microsoft returned no refresh token that can be kept (is offline_access on the registration?); nothing stored")
    record = {"refresh_token": refresh, "client_id": given["client_id"], "tenant": given["tenant"], "scope": scope, "obtained_at": now_iso()}
    shown = {"authorized": True, "secret_store": {"service": profile.keyring_service, "username": profile.keyring_username}, "scope": scope}
    if account_kind is not None:
        kind = account_kind(provider.Graph(base, provider.usable_access_token(data), hosts, test_mode))
        record["account_kind"] = shown["account_kind"] = kind
    shown.update({"tenant": given["tenant"], "obtained_at": record["obtained_at"]})
    try:
        store.set_password(profile.keyring_service, profile.keyring_username, json.dumps(record))
    except Exception as exc:
        raise ProviderError(f"cannot write to the OS secret store: {type(exc).__name__}") from None
    print(json.dumps(shown, indent=2))
    return EXIT_OK


def forget(profile: Profile, provider) -> int:
    """Delete our record from the OS secret store: a local delete of our own entry, not Microsoft data and no revocation."""
    _, _, _, test_mode = provider.endpoints()
    store = provider.keyring_module(test_mode)
    try:
        store.delete_password(profile.keyring_service, profile.keyring_username)
        forgotten = True
    except Exception as exc:
        if type(exc).__name__ != "PasswordDeleteError":   # the library's word for "nothing was stored"
            raise ProviderError(f"cannot delete from the OS secret store: {type(exc).__name__}") from None
        forgotten = False
    print(json.dumps({"forgotten": forgotten, "secret_store": {"service": profile.keyring_service, "username": profile.keyring_username}}, indent=2))
    log("This removed the local record only. To revoke the app's access at Microsoft: your Microsoft account, Apps and services (a work "
        "account: My Apps).")
    return EXIT_OK


def check(profile: Profile, provider) -> int:
    """Whether an authorization is there, read the way the provider reads it. No network."""
    _, _, _, test_mode = provider.endpoints()
    found = provider.secret_resolver().resolve(profile.secret, allow_store=not test_mode)
    if not found:
        print(json.dumps({"found": False}, indent=2))
        log(f"not configured: no {profile.label} authorization in the environment, the credentials directory or the OS secret store; run: "
            f"{profile.auth_command}")
        return EXIT_NOT_CONFIGURED
    record = provider.parse_record(found[0])
    print(json.dumps({"found": True, "source": found[1], "has_refresh_token": True, "scope": record.get("scope"),
                      "account_kind": record.get("account_kind"), "tenant": record["tenant"], "obtained_at": record.get("obtained_at")}, indent=2))
    return EXIT_OK


def auth_main(argv, *, prog: str, doc: str, authorize_fn, forget_fn, check_fn) -> int:
    """The command line of an authorization helper: `authorize` or `forget`, or `--check`; the functions are the helper's own."""
    parser = argparse.ArgumentParser(prog=prog, description=doc.split("\n\n")[0], epilog=doc, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", nargs="?", choices=["authorize", "forget"], help="authorize once, or forget the stored record")
    parser.add_argument("--check", action="store_true", help="report whether an authorization is found (no network)")
    parser.add_argument("--no-browser", action="store_true", help="print the authorization URL without opening a browser")
    args = parser.parse_args(argv)
    try:
        if args.check:
            if args.command:
                raise ProviderError("--check takes no command", EXIT_USAGE)
            return check_fn()
        if args.command is None:
            raise ProviderError("give authorize or forget, or --check; see --help", EXIT_USAGE)
        if args.no_browser and args.command != "authorize":
            raise ProviderError("--no-browser is for authorize only", EXIT_USAGE)
        return authorize_fn(open_browser=not args.no_browser) if args.command == "authorize" else forget_fn()
    except ProviderError as exc:
        log(f"error: {exc}")
        return exc.code
    except Exception as exc:   # last resort: say the kind only, never the text (it can hold an address or a credential)
        log(f"error: unexpected failure ({type(exc).__name__}); nothing was stored or changed")
        return EXIT_SERVICE


def run_main(main_fn, argv=None) -> int:
    """`main_fn(argv)` with a last resort: an unexpected exception is an exit 1 that names its kind and never its text."""
    try:
        return main_fn(argv)
    except ProviderError as exc:
        log(f"error: {exc}")
        return exc.code
    except Exception as exc:
        log(f"error: unexpected failure ({type(exc).__name__})")
        return EXIT_SERVICE
