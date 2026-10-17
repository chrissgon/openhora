#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["keyring==25.7.0"]
# ///
"""One-time OAuth 2.0 authorization for the Google Calendar provider (google.py): authorize, check, forget.

  authorize   asks for exactly two scopes, calendar.events.readonly and calendar.calendarlist.readonly, with PKCE (S256), a random state
              checked on the callback, access_type=offline and prompt=consent, on a one-shot listener on 127.0.0.1; stores the
              authorization as one record in the OS secret store. Run it once.
  check       whether an authorization is found, through the secret resolver (the environment, then the OS secret store); no network,
              nothing printed of it but the facts below.
  forget      removes the stored record from the OS secret store. It does not call Google: also remove the app's access in your Google
              Account (its third-party access page) so that the refresh token stops working there too.

Sources (accessed 2026-10-17, except the web server flow page, accessed 2026-09-29 for providers/mailbox/auth.py):
- Choose Google Calendar API scopes: https://developers.google.com/workspace/calendar/api/auth
- OAuth 2.0 for iOS and desktop apps: loopback redirect http://127.0.0.1:port on a random free port; PKCE with a code_verifier of 43 to 128
  unreserved characters and code_challenge "the Base64URL (with no padding) encoded SHA256 hash of the code verifier" (S256); authorization
  endpoint https://accounts.google.com/o/oauth2/v2/auth; token endpoint https://oauth2.googleapis.com/token; "Incremental authorization is
  not supported for installed apps", so the token carries exactly the scopes of this one consent (a calendar token cannot read mail even
  when the client is the one used for Gmail): https://developers.google.com/identity/protocols/oauth2/native-app
- access_type=offline and prompt=consent, from the web server flow's parameter list:
  https://developers.google.com/identity/protocols/oauth2/web-server
- Refresh token expiration (7 days for a Testing project with an external user type; revocation; six months unused; 100 tokens per client
  and account; invalid_grant): https://developers.google.com/identity/protocols/oauth2

Google Cloud setup (once), at https://console.cloud.google.com, in the project of your Gmail client (a Desktop app client may be reused:
the record is separate and the token carries only the calendar scopes) or in a project of its own:
  1. APIs and services, Library: enable the "Google Calendar API".
  2. Google Auth Platform, Data Access, "Add or remove scopes": add
         {events}
         {calendarlist}
     and nothing else. Together they let the app read events and the list of calendars, never change a calendar.
  3. Audience, "Publish app" (status "In production"). In "Testing" Google expires the authorization seven days after consent and the
     refresh token stops working every week (invalid_grant). A personal-use app keeps working in production; the consent screen of an
     unverified app asks you to click through it, for your own account.
  4. Clients: a client of application type "Desktop app" (no redirect URL is registered: this script listens on
     http://{host}:<a random free port>).
  5. Run: uv run <workbench>/providers/calendar/google_auth.py authorize
     It asks for the client id and the client secret at a hidden prompt (or reads GOOGLE_CALENDAR_CLIENT_ID and
     GOOGLE_CALENDAR_CLIENT_SECRET from the environment of this one command). Neither goes on the command line or in a file. Sign in with
     the Google account whose calendars to read and approve BOTH boxes of the consent screen: with one unticked nothing is stored.
  6. Verify: uv run <workbench>/providers/calendar/google.py --check, then google.py calendars.
The authorization (the refresh token and the client) is stored as one record in the OS secret store (service "openhora", username
"{username}"; the secret {secret}), never on disk.

exit codes: 0 success, 1 failed or timed out, 2 usage, 3 not configured (no authorization or no client credentials, a consent that did not
grant exactly the two scopes).
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


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


google = _load("workbench_calendar_google", "google.py")
ProviderError = google.ProviderError
EXIT_OK, EXIT_SERVICE, EXIT_USAGE, EXIT_NOT_CONFIGURED = google.EXIT_OK, google.EXIT_SERVICE, google.EXIT_USAGE, google.EXIT_NOT_CONFIGURED

KEYRING_SERVICE = google.KEYRING_SERVICE
KEYRING_USERNAME = google.KEYRING_USERNAME
GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
SCOPES = google.SCOPES
CALLBACK_HOST = "127.0.0.1"
CALLBACK_TIMEOUT_SECONDS = 600     # ten minutes for the person to sign in and approve; then the listener stops
# One connection is served at a time. A connection that sends nothing (a browser opens spare ones) is dropped after this long, so that it
# cannot hold the listener while the real callback waits.
CALLBACK_HANDLER_TIMEOUT_SECONDS = 5
INPUTS = (("GOOGLE_CALENDAR_CLIENT_ID", "the Desktop app OAuth client id"), ("GOOGLE_CALENDAR_CLIENT_SECRET", "that client's secret"))
__doc__ = __doc__.format(events=SCOPES[0], calendarlist=SCOPES[1], host=CALLBACK_HOST, username=KEYRING_USERNAME, secret=google.SECRET)


def log(message: str) -> None:
    print(message, file=sys.stderr)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def keyring_module(test_mode: bool):
    """The OS secret store. Test mode never touches it: tests replace this function with a fake store."""
    if test_mode:
        raise ProviderError("test mode (the INTEGRATION_CALENDAR_GOOGLE_* overrides) never uses the OS secret store", EXIT_USAGE)
    try:
        import keyring
    except ImportError:
        raise ProviderError("the keyring package is missing; run with: uv run <workbench>/providers/calendar/google_auth.py",
                            EXIT_NOT_CONFIGURED) from None
    return keyring


def pkce_pair() -> tuple[str, str]:
    """(code_verifier, code_challenge) for S256: 86 unreserved characters, then base64url(sha256), no padding."""
    verifier = secrets.token_urlsafe(64)
    return verifier, base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode()


def authorize_url(client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    """The consent URL: exactly the two calendar scopes, PKCE S256, the state, offline access (a refresh token) and a consent screen.
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
    return values


def exchange_code(token_url: str, code: str, verifier: str, client_id: str, client_secret: str, redirect_uri: str) -> dict:
    token = google.token_request(token_url, {"client_id": client_id, "client_secret": client_secret, "code": code,
                                             "code_verifier": verifier, "grant_type": "authorization_code", "redirect_uri": redirect_uri})
    if not token.get("refresh_token"):
        raise ProviderError("Google returned no refresh token; revoke the app's access in your Google Account and run this again")
    granted = set(str(token.get("scope") or "").split())
    if granted != set(SCOPES):
        extra = ", ".join(sorted(granted - set(SCOPES))) or "none"
        missing = ", ".join(sorted(set(SCOPES) - granted)) or "none"
        raise ProviderError(f"the consent granted {', '.join(sorted(granted)) or 'no scope'} where exactly the two calendar scopes are "
                            f"wanted (extra: {extra}; missing: {missing}); nothing stored. Run it again and keep both boxes ticked",
                            EXIT_NOT_CONFIGURED)
    return token


def primary_account(base: str, access_token: str) -> str | None:
    """The id of the primary calendar (an e-mail address), read from the calendar list: it proves the token and the API work before anything
    is stored, and names the account in the record and in the output."""
    items, _ = google.calendar_items(google.Calendar(base, access_token), "nextPageToken,items(id,primary)",
                                     stop=lambda item: isinstance(item, dict) and item.get("primary") is True)
    for item in items:
        if isinstance(item, dict) and item.get("primary") is True and isinstance(item.get("id"), str):
            return google.one_line(item["id"], 254) or None
    return None


def authorize(open_browser: bool) -> int:
    base, token_url, test_mode = google.endpoints()
    given = client_inputs()
    store = keyring_module(test_mode)   # fail before the browser step when the store is unavailable
    state = secrets.token_urlsafe(32)
    verifier, challenge = pkce_pair()
    client_id, client_secret = given["GOOGLE_CALENDAR_CLIENT_ID"], given["GOOGLE_CALENDAR_CLIENT_SECRET"]
    google._SECRET_VALUES.append(client_secret)
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
    account = primary_account(base, token["access_token"])
    record = {"refresh_token": token["refresh_token"], "client_id": client_id, "client_secret": client_secret,
              "scope": token.get("scope"), "account": account, "obtained_at": now_iso()}
    try:
        store.set_password(KEYRING_SERVICE, KEYRING_USERNAME, json.dumps(record))
    except Exception as exc:
        raise ProviderError(f"cannot write to the OS secret store: {type(exc).__name__}") from None
    print(json.dumps({"provider": "calendar-google", "stored": True, "secret_store": {"service": KEYRING_SERVICE, "username": KEYRING_USERNAME},
                      "account": account, "scope": record["scope"], "obtained_at": record["obtained_at"]}, indent=2))
    return EXIT_OK


def check() -> int:
    """Whether an authorization is there, read the way google.py reads it. No network."""
    _, _, test_mode = google.endpoints()
    found = google.secret_resolver().resolve(google.SECRET, allow_store=not test_mode)
    if not found:
        print(json.dumps({"provider": "calendar-google", "found": False}, indent=2))
        log(f"not configured: no Google Calendar authorization in the environment or the OS secret store; run: {google.AUTH_COMMAND}")
        return EXIT_NOT_CONFIGURED
    record = google.parse_record(found[0])
    print(json.dumps({"provider": "calendar-google", "found": True, "source": found[1], "has_refresh_token": True,
                      "account": record.get("account"), "scope": record.get("scope"), "obtained_at": record.get("obtained_at")}, indent=2))
    return EXIT_OK


def forget() -> int:
    """Remove the stored record. No network: Google is not told, so the app's access also has to be removed in the Google Account."""
    _, _, test_mode = google.endpoints()
    store = keyring_module(test_mode)
    try:
        store.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
        removed = True
    except Exception as exc:
        if type(exc).__name__ != "PasswordDeleteError":     # keyring's answer for "nothing stored there"
            raise ProviderError(f"cannot remove the record from the OS secret store: {type(exc).__name__}") from None
        removed = False
    print(json.dumps({"provider": "calendar-google", "forgotten": removed,
                      "secret_store": {"service": KEYRING_SERVICE, "username": KEYRING_USERNAME}}, indent=2))
    log("Google was not told: remove the app's access in your Google Account (its third-party access page) so the refresh token stops "
        "working there too." if removed else "nothing was stored in the OS secret store; a value in the environment is not touched.")
    return EXIT_OK


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="google_auth.py", description=__doc__.split("\n\n")[0], epilog=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["authorize", "check", "forget"], help="authorize once, check what is stored, or forget it")
    parser.add_argument("--no-browser", action="store_true", help="with authorize: print the consent URL without opening a browser")
    args = parser.parse_args(argv)
    try:
        if args.no_browser and args.command != "authorize":
            raise ProviderError("--no-browser is for authorize only", EXIT_USAGE)
        if args.command == "check":
            return check()
        if args.command == "forget":
            return forget()
        return authorize(open_browser=not args.no_browser)
    except ProviderError as exc:
        log(f"error: {google.scrub(str(exc))}")
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
