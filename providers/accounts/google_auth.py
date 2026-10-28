#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["keyring==25.7.0"]
# ///
"""One-time OAuth 2.0 authorization of the person's own Google account for the whole platform: authorize, check, forget.

  authorize   asks for exactly five scopes, once, for every Google provider of the platform (Gmail, Calendar, Drive, Tasks):
                {gmail}
                {events}
                {calendarlist}
                {drive}
                {tasks}
              with PKCE (S256), a random state checked on the callback, access_type=offline and prompt=consent, on a one-shot listener on
              127.0.0.1. A consent that does not grant exactly those five (one box unticked, or a wider scope such as
              https://mail.google.com/) stores nothing and exits 3 naming this command. The address the token belongs to is read once
              from the Gmail profile. The result is one record in the OS secret store (service "openhora", username "{username}"; the
              secret {secret}): the refresh token, the Desktop app client that travels with it, the scope, the address and the date.
  check       whether an authorization is found, through the secret resolver (the environment, then the credentials directory, then the OS
              secret store), and whether its scope is exactly the five; no network, nothing printed of the token. A record made before Google Tasks was added
              holds the four of PREVIOUS_SCOPES: Gmail, Calendar and Drive keep working with it, `check` prints "scope_is_previous_set": true
              and exits 3, and the Tasks providers say "authorize again" (run `authorize` once).
  forget      removes the stored record from the OS secret store. It does not call Google: also remove the app's access in your Google
              Account (its third-party access page), which is the one switch that stops every reader and writer of the account at once.
              The old records (mailbox-gmail, gmail-client-id, gmail-client-secret, calendar-google, gdrive-sources) are never touched by
              this command or by any code: remove each with `uv run --with keyring==25.7.0 keyring del openhora <username>` once
              `check` passes and each reader has worked with the account record.

--account <slot> names the account (default main). Only main exists in this version; another slot needs a registry row of its own
(backlog ACCT-SLOT).

One token reaches everything its scopes allow: reading, changing, sending and trashing mail, the events of every calendar, every file of
the Drive. That is accepted (decision of 2026-10-18). What restricts it is the platform: policies, an effect card of the exact content for
every write, the verbs each provider script exposes, and no token in a run. Revoking the app's access in the Google Account stops it all.

Sources (Google's own documentation, accessed 2026-10-18):
- OAuth 2.0 for iOS and desktop apps: loopback redirect http://127.0.0.1:port on a random free port; PKCE with a code_verifier of 43 to 128
  unreserved characters and code_challenge "the Base64URL (with no padding) encoded SHA256 hash of the code verifier" (S256); authorization
  endpoint https://accounts.google.com/o/oauth2/v2/auth; token endpoint https://oauth2.googleapis.com/token; "Incremental authorization is
  not supported for installed apps", so the token carries exactly the scopes of this one consent:
  https://developers.google.com/identity/protocols/oauth2/native-app
- access_type=offline and prompt=consent: https://developers.google.com/identity/protocols/oauth2/web-server
- Scopes: gmail.modify (restricted; "does not allow immediate, permanent deletion of threads and messages"):
  https://developers.google.com/workspace/gmail/api/auth/scopes ; calendar.events and calendar.calendarlist.readonly:
  https://developers.google.com/workspace/calendar/api/auth ; drive (restricted):
  https://developers.google.com/workspace/drive/api/guides/api-specific-auth
- Refresh token expiry (7 days for a project in Testing, six months unused, 100 per account per client) and unverified personal apps
  (under 100 users): https://developers.google.com/identity/protocols/oauth2 and https://support.google.com/cloud/answer/13464323

Google Cloud setup (once), at https://console.cloud.google.com, in the project of your Gmail client (the Desktop app client is reused):
  1. APIs and services, Library: enable the Gmail API, the Google Calendar API, the Google Drive API and the Google Tasks API.
  2. Google Auth Platform, Data Access, "Add or remove scopes": the five above (and enable the Google Tasks API in step 1). Keep the old scopes listed until the legacy records are gone.
  3. Audience: "In production" (in "Testing" Google expires the authorization every seven days). Do not submit the app for verification: a
     personal-use app under 100 users works unverified, and the consent screen asks you to click through "Google hasn't verified this app".
  4. Run: uv run <workbench>/providers/accounts/google_auth.py authorize
     It asks for the client id and the client secret at a hidden prompt (or reads GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET from the
     environment of this one command). Neither goes on the command line or in a file. Sign in with the Google account to connect and
     approve EVERY box of the consent screen: with one unticked nothing is stored.
  5. Verify: uv run <workbench>/providers/accounts/google_auth.py check

Test overrides (tests only, loopback URLs only, both set together; the OS secret store is then never used):
  GOOGLE_ACCOUNT_API_BASE    replaces {gmail_base}   (only the profile is read from it)
  GOOGLE_ACCOUNT_TOKEN_URL   replaces {token_url}

exit codes: 0 success, 1 failed or timed out, 2 usage, 3 not configured (no authorization or no client credentials, a consent that did
not grant exactly the five scopes, an incomplete record).
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
import sys
import threading
import urllib.parse
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


google = _load("workbench_google_account_shared", HERE.parent / "_google.py")
ProviderError = google.AccountError
EXIT_OK, EXIT_SERVICE, EXIT_USAGE, EXIT_NOT_CONFIGURED = google.EXIT_OK, google.EXIT_SERVICE, google.EXIT_USAGE, google.EXIT_NOT_CONFIGURED

KEYRING_SERVICE, KEYRING_USERNAME = google.KEYRING_SERVICE, google.KEYRING_USERNAME
GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
SCOPES = google.PLATFORM_SCOPES
CALLBACK_HOST = "127.0.0.1"
CALLBACK_TIMEOUT_SECONDS = 600     # ten minutes for the person to sign in and approve; then the listener stops
# One connection is served at a time. A connection that sends nothing (a browser opens spare ones) is dropped after this long, so that it
# cannot hold the listener while the real callback waits.
CALLBACK_HANDLER_TIMEOUT_SECONDS = 5
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
ENV_API_BASE, ENV_TOKEN_URL = "GOOGLE_ACCOUNT_API_BASE", "GOOGLE_ACCOUNT_TOKEN_URL"
INPUTS = (("GOOGLE_CLIENT_ID", "the Desktop app OAuth client id"), ("GOOGLE_CLIENT_SECRET", "that client's secret"))
PROVIDER = "google-account"
__doc__ = __doc__.format(gmail=SCOPES[0], events=SCOPES[1], calendarlist=SCOPES[2], drive=SCOPES[3], tasks=SCOPES[4], username=KEYRING_USERNAME,
                         secret=google.SECRET, gmail_base=google.DEFAULT_GMAIL_BASE, token_url=google.DEFAULT_TOKEN_URL)


def log(message: str) -> None:
    print(message, file=sys.stderr)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def endpoints() -> tuple:
    """(Gmail base, token URL, test mode). The overrides are for tests and must be loopback URLs, both set together."""
    api, token = os.environ.get(ENV_API_BASE), os.environ.get(ENV_TOKEN_URL)
    if not api and not token:
        return google.DEFAULT_GMAIL_BASE, google.DEFAULT_TOKEN_URL, False
    if not (api and token):
        raise ProviderError(f"{ENV_API_BASE} and {ENV_TOKEN_URL} are for tests only and are set together", EXIT_USAGE)
    for name, value in ((ENV_API_BASE, api), (ENV_TOKEN_URL, token)):
        parsed = urllib.parse.urlparse(value)
        if parsed.scheme not in ("http", "https") or parsed.hostname not in LOOPBACK_HOSTS:
            raise ProviderError(f"{name} is for tests only and must be a loopback URL such as http://127.0.0.1:8080", EXIT_USAGE)
    return api.rstrip("/"), token, True


def keyring_module(test_mode: bool):
    """The OS secret store. Test mode never touches it: tests replace this function with a fake store."""
    if test_mode:
        raise ProviderError(f"test mode (the {ENV_API_BASE} override) never uses the OS secret store", EXIT_USAGE)
    try:
        import keyring
    except ImportError:
        raise ProviderError("the keyring package is missing; run with: uv run <workbench>/providers/accounts/google_auth.py",
                            EXIT_NOT_CONFIGURED) from None
    return keyring


def secret_resolver():
    """The workbench's one secret resolver, by path: providers/secrets/resolver.py."""
    path = HERE.parent / "secrets" / "resolver.py"
    if not path.is_file():
        raise ProviderError("providers/secrets/resolver.py is not in the workbench", EXIT_NOT_CONFIGURED)
    return _load("workbench_secret_resolver", path)


def pkce_pair() -> tuple:
    """(code_verifier, code_challenge) for S256: 86 unreserved characters, then base64url(sha256), no padding."""
    verifier = secrets.token_urlsafe(64)
    return verifier, base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode()


def authorize_url(client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    """The consent URL: exactly the five platform scopes, PKCE S256, the state, offline access (a refresh token) and a consent screen.
    No include_granted_scopes: the token carries only what this consent grants."""
    return GOOGLE_AUTHORIZE_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code", "scope": " ".join(SCOPES),
        "code_challenge": challenge, "code_challenge_method": "S256", "state": state, "access_type": "offline", "prompt": "consent"})


def state_matches(received: str, expected: str) -> bool:
    return hmac.compare_digest(received.encode("utf-8"), expected.encode("utf-8"))


class CallbackServer:
    """One loopback listener on a random free port; serves the single redirect from Google. One callback only: after it, every request is a
    404. A request that carries no state, code or error (a favicon, a stray visit) is a 404 that does not end the wait."""

    def __init__(self, expected_state: str):
        self.expected_state = expected_state
        self.outcome: dict = {}
        self.done = threading.Event()
        self.port = 0
        owner = self

        class Handler(BaseHTTPRequestHandler):
            timeout = CALLBACK_HANDLER_TIMEOUT_SECONDS

            def _reply(self, status, text=None):
                body = f"<!doctype html><title>openhora</title><p>{text}</p>".encode() if text else b""
                self.send_response(status)
                if text:
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # noqa: N802 (http.server naming)
                parsed = urllib.parse.urlparse(self.path)
                query = urllib.parse.parse_qs(parsed.query)
                if owner.done.is_set() or parsed.path != "/" or not (query.get("state") or query.get("code") or query.get("error")):
                    return self._reply(404)
                if self.headers.get("Host", "") != f"{CALLBACK_HOST}:{owner.port}":
                    return self._reply(400, "Wrong host. Nothing was stored.")
                if not state_matches(query.get("state", [""])[0], owner.expected_state):
                    owner.outcome["error"] = "the state parameter does not match; possible CSRF, nothing stored"
                    status, text = 401, "State mismatch. Nothing was stored. You can close this tab."
                elif "error" in query:
                    owner.outcome["error"] = f"Google returned {google.one_line(query['error'][0], 80)}; nothing stored"
                    status, text = 400, "Authorization was not granted. You can close this tab."
                elif not query.get("code"):
                    owner.outcome["error"] = "the callback carried no code"
                    status, text = 400, "No authorization code received. You can close this tab."
                else:
                    owner.outcome["code"] = query["code"][0]
                    status, text = 200, "Authorization received. You can close this tab and return to the terminal."
                self._reply(status, text)
                owner.done.set()

            def log_message(self, *args):   # silence request logs: the URL carries the code
                return

        try:
            self.server = HTTPServer((CALLBACK_HOST, 0), Handler)
        except OSError as exc:
            raise ProviderError(f"cannot listen on {CALLBACK_HOST}: {exc.strerror}") from None
        self.port = self.server.server_address[1]
        self.redirect_uri = f"http://{CALLBACK_HOST}:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        self.thread.start()

    def wait(self, timeout: float = CALLBACK_TIMEOUT_SECONDS) -> str:
        try:
            if not self.done.wait(timeout):
                raise ProviderError(f"no callback within {timeout:g} seconds; nothing stored")
        finally:
            self.close()
        if "error" in self.outcome:
            raise ProviderError(self.outcome["error"])
        return self.outcome["code"]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def client_inputs() -> dict:
    """The client id and secret of the one command: the environment, else a hidden prompt on a terminal. Never a flag."""
    values = {}
    for name, what in INPUTS:
        value = (os.environ.get(name) or "").strip()
        if not value and sys.stdin.isatty():
            value = getpass.getpass(f"{name} ({what}): ").strip()
        if not value:
            raise ProviderError(f"{name} ({what}) is not set: export it for this one command, or run it in a terminal to type it at a "
                                "hidden prompt", EXIT_NOT_CONFIGURED)
        if any(ch.isspace() or not ch.isprintable() for ch in value):
            raise ProviderError(f"{name} holds whitespace or control characters", EXIT_USAGE)
        values[name] = value
    google.hold(*values.values())
    return values


def exchange_code(token_url: str, code: str, verifier: str, client_id: str, client_secret: str, redirect_uri: str) -> dict:
    """The authorization code for the tokens, and the check that the consent granted exactly the platform's set: before anything is stored."""
    token = google.token_request(token_url, {"client_id": client_id, "client_secret": client_secret, "code": code, "code_verifier": verifier,
                                             "grant_type": "authorization_code", "redirect_uri": redirect_uri}, ProviderError)
    if not token.get("refresh_token"):
        raise ProviderError("Google returned no refresh token; revoke the app's access in your Google Account and run this again")
    google.token_text(token["refresh_token"], "a refresh_token", ProviderError)      # before the scope check and long before anything is stored
    google.check_platform_scope(token.get("scope") or None, None, ProviderError, "nothing stored", tasks=True)     # exactly the five: a response with no scope cannot be shown to be the set
    return token


def authorize(slot: str, open_browser: bool) -> int:
    gmail_base, token_url, test_mode = endpoints()
    given = client_inputs()
    store = keyring_module(test_mode)   # fail before the browser step when the store is unavailable
    state = secrets.token_urlsafe(32)
    verifier, challenge = pkce_pair()
    client_id, client_secret = given["GOOGLE_CLIENT_ID"], given["GOOGLE_CLIENT_SECRET"]
    server = CallbackServer(state)
    try:
        url = authorize_url(client_id, server.redirect_uri, state, challenge)
        log("Open this URL to authorize (it contains no secret):")
        log(url)
        if open_browser:
            webbrowser.open(url)
        log(f"Waiting up to {CALLBACK_TIMEOUT_SECONDS // 60} minutes for the callback on {server.redirect_uri} ...")
    except BaseException:
        server.close()
        raise
    code = server.wait()
    token = exchange_code(token_url, code, verifier, client_id, client_secret, server.redirect_uri)
    account = google.account_address(gmail_base, token["access_token"], ProviderError)
    if not account:
        raise ProviderError("the Gmail profile gave no usable address for the account, so the record would not name it; nothing stored")
    record = {"slot": slot, "refresh_token": token["refresh_token"], "client_id": client_id, "client_secret": client_secret,
              "scope": token.get("scope"), "account": account, "obtained_at": now_iso()}
    try:
        store.set_password(KEYRING_SERVICE, KEYRING_USERNAME, json.dumps(record))
    except Exception as exc:
        raise ProviderError(f"cannot write to the OS secret store: {type(exc).__name__}") from None
    print(json.dumps({"provider": PROVIDER, "stored": True, "slot": slot, "secret_store": {"service": KEYRING_SERVICE, "username": KEYRING_USERNAME},
                      "account": account, "scope": sorted(google.scope_words(record["scope"])), "obtained_at": record["obtained_at"]}, indent=2))
    return EXIT_OK


def check(slot: str) -> int:
    """Whether an authorization is there, read the way the providers read it, and whether its scope is the set. No network."""
    _, _, test_mode = endpoints()
    found = google.find_account_record(secret_resolver(), test_mode, slot, ProviderError)
    if not found:
        print(json.dumps({"provider": PROVIDER, "found": False, "slot": slot}, indent=2))
        log(f"not configured: no Google account authorization in the environment, the credentials directory or the OS secret store; run: {google.AUTH_COMMAND}")
        return EXIT_NOT_CONFIGURED
    record = google.parse_account_record(found[0], ProviderError)
    words = google.scope_words(record["scope"])
    missing, extra = google.scope_problems(words)
    whole = not missing and not extra
    previous = words == set(google.PREVIOUS_SCOPES)      # made before Google Tasks was added: every provider but the tasks ones accepts it (CB-4)
    print(json.dumps({"provider": PROVIDER, "found": True, "source": found[1], "slot": record["slot"], "has_refresh_token": True,
                      "account": record["account"], "scope": sorted(words), "scope_is_platform_set": whole, "scope_is_previous_set": previous,
                      "missing": missing, "extra": extra, "obtained_at": record["obtained_at"]}, indent=2))
    if not whole:
        if previous:
            log(f"the stored scope is the four of before Google Tasks: Gmail, Calendar and Drive work, the Tasks providers need {google.TASKS_SCOPE}; "
                f"run: {google.AUTH_COMMAND}")
        else:
            log(f"the stored scope is not the platform's set (missing: {', '.join(missing) or 'none'}; extra: {', '.join(extra) or 'none'}); "
                f"run: {google.AUTH_COMMAND}")
        return EXIT_NOT_CONFIGURED
    return EXIT_OK


def forget(slot: str) -> int:
    """Remove the stored record. No network: Google is not told, so the app's access also has to be removed in the Google Account."""
    _, _, test_mode = endpoints()
    store = keyring_module(test_mode)
    try:
        store.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
        removed = True
    except Exception as exc:
        if type(exc).__name__ != "PasswordDeleteError":     # keyring's answer for "nothing stored there"
            raise ProviderError(f"cannot remove the record from the OS secret store: {type(exc).__name__}") from None
        removed = False
    print(json.dumps({"provider": PROVIDER, "forgotten": removed, "slot": slot,
                      "secret_store": {"service": KEYRING_SERVICE, "username": KEYRING_USERNAME}}, indent=2))
    log("Google was not told: remove the app's access in your Google Account (its third-party access page) so the refresh token stops "
        "working there too. The legacy records were not touched." if removed else
        "nothing was stored in the OS secret store; a value in the environment is not touched.")
    return EXIT_OK


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="google_auth.py", description=__doc__.split("\n\n")[0], epilog=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["authorize", "check", "forget"], help="authorize once, check what is stored, or forget it")
    parser.add_argument("--account", default=google.MAIN_SLOT, help="the account's slot (default main; only main exists in this version)")
    parser.add_argument("--no-browser", action="store_true", help="with authorize: print the consent URL without opening a browser")
    args = parser.parse_args(argv)
    try:
        slot = google.check_slot(args.account, ProviderError)
        if args.no_browser and args.command != "authorize":
            raise ProviderError("--no-browser is for authorize only", EXIT_USAGE)
        if args.command == "check":
            return check(slot)
        if args.command == "forget":
            return forget(slot)
        return authorize(slot, open_browser=not args.no_browser)
    except ProviderError as exc:
        log(f"error: {google.scrub(str(exc))}")
        return exc.code
    except Exception as exc:     # last resort: no traceback, which can hold a header or a body; only the kind of the failure
        log(f"error: unexpected {type(exc).__name__}; nothing was stored")
        return EXIT_SERVICE


if __name__ == "__main__":
    sys.exit(main())
