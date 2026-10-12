#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["keyring==25.7.0"]
# ///
"""One-time OAuth 2.0 authorization for mailbox providers.

Gmail (--provider gmail), sources accessed 2026-09-29:
- OAuth 2.0 for iOS and desktop apps: loopback redirect http://127.0.0.1:port with "an HTTP listener
  on a random available port" ("localhost" works too "but this configuration may cause issues with
  client firewalls"); PKCE with a code_verifier of 43 to 128 unreserved characters and code_challenge
  "the Base64URL (with no padding) encoded SHA256 hash of the code verifier" (S256); authorization
  endpoint https://accounts.google.com/o/oauth2/v2/auth; token endpoint https://oauth2.googleapis.com/token
  with client_id, client_secret, code, code_verifier, grant_type, redirect_uri; "refresh tokens are
  always returned for installed applications"; error=access_denied when the user declines:
  https://developers.google.com/identity/protocols/oauth2/native-app
- access_type=offline ("return a refresh token and an access token the first time that your application
  exchanges an authorization code") and prompt=consent, from the web server flow's parameter list:
  https://developers.google.com/identity/protocols/oauth2/web-server
- Refresh token expiration (7 days for a Testing project with an external user type; revocation;
  six months unused; password change with Gmail scopes; 100 refresh tokens per account per client;
  invalid_grant): https://developers.google.com/identity/protocols/oauth2
- Publishing status: in Testing, "Authorizations by a test user will expire seven days from the time
  of consent": https://support.google.com/cloud/answer/15549945
- Unverified apps: "If the app is for your personal use (fewer than 100 users), you and your limited
  number of users can continue using the app without going through verification", clicking through
  the unverified app screen: https://support.google.com/cloud/answer/13464323
- users.getProfile returns emailAddress and accepts gmail.readonly:
  https://developers.google.com/workspace/gmail/api/reference/rest/v1/users/getProfile
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import importlib.util
import json
import secrets
import sys
import threading
import urllib.parse
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


def _load_gmail():
    path = Path(__file__).resolve().parent / "gmail.py"
    spec = importlib.util.spec_from_file_location("workbench_mailbox_gmail", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gmail = _load_gmail()
ProviderError = gmail.ProviderError
EXIT_OK, EXIT_SERVICE, EXIT_USAGE, EXIT_NOT_CONFIGURED = (gmail.EXIT_OK, gmail.EXIT_SERVICE, gmail.EXIT_USAGE,
                                                          gmail.EXIT_NOT_CONFIGURED)

KEYRING_SERVICE = gmail.KEYRING_SERVICE
GMAIL_KEYRING_USERNAME = gmail.KEYRING_USERNAME
GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GMAIL_SCOPE = gmail.GMAIL_SCOPE
CALLBACK_HOST = "127.0.0.1"
CALLBACK_TIMEOUT_SECONDS = 300
# One connection is served at a time. A connection that sends nothing (a browser opens spare ones) is
# dropped after this long, so that it cannot hold the listener while the real callback waits.
CALLBACK_HANDLER_TIMEOUT_SECONDS = 5

HELP_EPILOG = f"""\
Google Cloud setup (once), at https://console.cloud.google.com:
  1. Create a project (or pick one used only for this).
  2. APIs and services, Library: enable the "Gmail API".
  3. Google Auth Platform, Branding: the app name, and your e-mail as user
     support and developer contact. Audience: user type External.
  4. Data Access, "Add or remove scopes": add
         {GMAIL_SCOPE}
     and nothing else. It lets the app read, never change, your mail.
  5. Audience, "Publish app" (status "In production"). Why: in "Testing", Google
     expires the authorization seven days after consent, so the refresh token
     would stop working every week (invalid_grant). A personal-use app (fewer than
     100 users) keeps working in production without Google's verification; the
     consent screen then says the app is unverified and you click through it
     for your own account.
  6. Clients, create a client of application type "Desktop app". No redirect URL
     is registered: this script listens on the loopback address
     http://{CALLBACK_HOST}:<a random free port>, as Google's desktop-app guide says.
  7. Store the client id and secret, never in a file (typed at a hidden prompt):
         uv run --with keyring==25.7.0 keyring set {KEYRING_SERVICE} gmail-client-id
         uv run --with keyring==25.7.0 keyring set {KEYRING_SERVICE} gmail-client-secret
     or export GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET for the session. They are
     read through providers/secrets/resolver.py, environment first.
  8. Run:
         uv run providers/mailbox/auth.py --provider gmail
     Sign in with the Gmail account to read and approve. The refresh token, the
     granted scope and the account address are stored in the OS secret store
     (service "{KEYRING_SERVICE}", username "{GMAIL_KEYRING_USERNAME}"), never on disk.
  9. Verify: uv run providers/mailbox/gmail.py --check

secrets (environment variable, else the OS secret store; see contracts/secrets.md):
  GMAIL_CLIENT_ID       required for the authorization and every refresh.
  GMAIL_CLIENT_SECRET   required for the authorization and every refresh.

The authorization asks only for {GMAIL_SCOPE}, with PKCE (S256), a random
state checked on the callback, access_type=offline and prompt=consent. If the
consent screen shows a box for Gmail, keep it ticked: without it nothing is stored.
--check says whether an authorization is found, through the secret resolver (the
environment, then the OS secret store; no network); gmail.py --check proves the
token still works.

exit codes: 0 success, 1 provider or service error, 2 usage error, 3 not configured.

examples:
  uv run providers/mailbox/auth.py --provider gmail
  uv run providers/mailbox/auth.py --provider gmail --no-browser
  uv run providers/mailbox/auth.py --provider gmail --check
"""


def log(message: str) -> None:
    print(message, file=sys.stderr)


def now_iso() -> str:
    return gmail.iso_utc(datetime.now(timezone.utc))


def keyring_module(test_mode: bool):
    """The OS secret store. Test mode never touches it: tests replace this function with a fake store."""
    if test_mode:
        raise ProviderError("test mode (GMAIL_API_BASE and GOOGLE_TOKEN_URL set) never uses the OS secret store",
                            EXIT_USAGE)
    try:
        import keyring
    except ImportError:
        raise ProviderError("the keyring package is missing; run with: uv run providers/mailbox/auth.py",
                            EXIT_NOT_CONFIGURED)
    return keyring


def pkce_pair() -> tuple[str, str]:
    """(code_verifier, code_challenge) for S256: 86 unreserved characters, then base64url(sha256), no padding."""
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode()
    return verifier, challenge


def authorize_url(client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    return GOOGLE_AUTHORIZE_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GMAIL_SCOPE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    })


def state_matches(received: str, expected: str) -> bool:
    return hmac.compare_digest(received.encode("utf-8"), expected.encode("utf-8"))


class CallbackServer:
    """One loopback listener on a random free port; serves the single redirect from Google."""

    def __init__(self, expected_state: str):
        self.expected_state = expected_state
        self.outcome: dict = {}
        self.done = threading.Event()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            timeout = CALLBACK_HANDLER_TIMEOUT_SECONDS  # a silent connection is dropped, never waited on for ever

            def do_GET(self):  # noqa: N802 (http.server naming)
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path != "/" or owner.done.is_set():
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                query = urllib.parse.parse_qs(parsed.query)
                state = query.get("state", [""])[0]
                if not state_matches(state, owner.expected_state):
                    owner.outcome["error"] = "the state parameter does not match; possible CSRF, nothing stored"
                    status, text = 401, "State mismatch. Nothing was stored. You can close this tab."
                elif "error" in query:
                    owner.outcome["error"] = f"Google returned {gmail._short(query['error'][0], 80)}; nothing stored"
                    status, text = 400, "Authorization was not granted. You can close this tab."
                elif not query.get("code"):
                    owner.outcome["error"] = "the callback carried no code"
                    status, text = 400, "No authorization code received. You can close this tab."
                else:
                    owner.outcome["code"] = query["code"][0]
                    status, text = 200, "Authorization received. You can close this tab and return to the terminal."
                body = f"<!doctype html><title>openhora</title><p>{text}</p>".encode()
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                owner.done.set()

            def log_message(self, *args):  # silence request logs: the URL carries the code
                return

        try:
            self.server = HTTPServer((CALLBACK_HOST, 0), Handler)
        except OSError as exc:
            raise ProviderError(f"cannot listen on {CALLBACK_HOST}: {exc.strerror}")
        self.redirect_uri = f"http://{CALLBACK_HOST}:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        self.thread.start()

    def wait(self, timeout: float = CALLBACK_TIMEOUT_SECONDS) -> str:
        try:
            if not self.done.wait(timeout):
                raise ProviderError(f"no callback within {timeout:g} seconds")
        finally:
            self.close()
        if "error" in self.outcome:
            raise ProviderError(self.outcome["error"])
        return self.outcome["code"]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def exchange_code(token_url: str, code: str, verifier: str, client_id: str, client_secret: str,
                  redirect_uri: str) -> dict:
    token = gmail.token_request(token_url, {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "code_verifier": verifier,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    })
    if not token.get("refresh_token"):
        raise ProviderError("Google returned no refresh token; revoke the app's access in your Google Account and "
                            "rerun this command")
    granted = set((token.get("scope") or "").split())
    if GMAIL_SCOPE not in granted:
        raise ProviderError(f"the consent did not grant {GMAIL_SCOPE} (was the Gmail box left unticked?); nothing "
                            "stored; rerun and keep it ticked", EXIT_NOT_CONFIGURED)
    extra = sorted(granted - {GMAIL_SCOPE})
    if extra:
        log(f"warning: Google also granted {' '.join(extra)}; the provider only uses {GMAIL_SCOPE}")
    return token


def gmail_authorize(open_browser: bool) -> int:
    base, token_url, test_mode = gmail.endpoints()
    client_id, client_secret = gmail.client_credentials(gmail.secret_resolver(), test_mode)
    store = keyring_module(test_mode)  # fail before the browser step if the store is unavailable

    state = secrets.token_urlsafe(32)
    verifier, challenge = pkce_pair()
    server = CallbackServer(state)
    try:
        url = authorize_url(client_id, server.redirect_uri, state, challenge)
        log("Open this URL to authorize (it contains no secret):")
        log(url)
        if open_browser:
            webbrowser.open(url)
        log(f"Waiting for the callback on {server.redirect_uri} ...")
    except BaseException:
        server.close()
        raise
    code = server.wait()

    token = exchange_code(token_url, code, verifier, client_id, client_secret, server.redirect_uri)
    account = gmail.Gmail(base, token["access_token"]).profile().get("emailAddress")
    record = {
        "refresh_token": token["refresh_token"],
        "scope": token.get("scope"),
        "obtained_at": now_iso(),
        "account": account,
    }
    try:
        store.set_password(KEYRING_SERVICE, GMAIL_KEYRING_USERNAME, json.dumps(record))
    except Exception as exc:
        raise ProviderError(f"cannot write to the OS secret store: {type(exc).__name__}")
    print(json.dumps({
        "provider": "gmail",
        "stored": True,
        "secret_store": {"service": KEYRING_SERVICE, "username": GMAIL_KEYRING_USERNAME},
        "account": account,
        "scope": record["scope"],
        "obtained_at": record["obtained_at"],
    }, indent=2))
    return EXIT_OK


def gmail_check() -> int:
    """Whether an authorization is there, read the way gmail.py reads it: through the secret resolver (the
    environment, then the OS secret store; contracts/secrets.md). No network. Test mode never reads the store."""
    _, _, test_mode = gmail.endpoints()
    found = gmail.secret_resolver().resolve("GMAIL_REFRESH_TOKEN", allow_store=not test_mode)
    if not found:
        print(json.dumps({"provider": "gmail", "found": False, "stored": False}, indent=2))
        log("not configured: no Gmail authorization in the environment or the OS secret store; "
            "run auth.py --provider gmail")
        return EXIT_NOT_CONFIGURED
    value, source = found
    if source != "secret store":  # a bare refresh token from the environment: nothing else is known about it
        print(json.dumps({"provider": "gmail", "found": True, "source": source, "stored": False,
                          "has_refresh_token": True}, indent=2))
        return EXIT_OK
    try:
        record = json.loads(value)
        record.get("refresh_token")
    except (ValueError, AttributeError):
        raise ProviderError("the stored Gmail authorization is unreadable; rerun auth.py --provider gmail",
                            EXIT_NOT_CONFIGURED)
    print(json.dumps({
        "provider": "gmail",
        "found": True,
        "source": source,
        "stored": True,
        "has_refresh_token": bool(record.get("refresh_token")),
        "account": record.get("account"),
        "scope": record.get("scope"),
        "obtained_at": record.get("obtained_at"),
    }, indent=2))
    if not record.get("refresh_token"):
        log("not configured: the stored record has no refresh token; rerun auth.py --provider gmail")
        return EXIT_NOT_CONFIGURED
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="auth.py",
        description="Run the OAuth 2.0 authorization for a mailbox provider once and store the refresh token "
        "in the OS secret store.",
        epilog=HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--provider", required=True, choices=["gmail"], help="the provider to authorize")
    parser.add_argument("--check", action="store_true", help="report whether an authorization is found: the environment, then the OS secret "
                        "store (no network)")
    parser.add_argument("--no-browser", action="store_true", help="print the authorization URL without opening a browser")
    args = parser.parse_args(argv)
    try:
        if args.check:
            return gmail_check()
        return gmail_authorize(open_browser=not args.no_browser)
    except ProviderError as exc:
        log(f"error: {exc}")
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
