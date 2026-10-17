#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["keyring==25.7.0"]
# ///
"""One-time OAuth 2.0 authorization for the OneDrive documents provider (onedrive.py).

Commands:
  authorize   the authorization code flow with PKCE (S256) and a state, as a public client (no client secret), in the system browser,
              with a loopback redirect. It asks for the delegated Microsoft Graph permission `Files.Read` and `offline_access` and
              nothing else, checks that the token carries nothing wider, and stores the authorization as one record in the OS secret
              store. Run it once.
  forget      deletes that record from the OS secret store (our own local record; it revokes nothing at Microsoft: do that in your
              Microsoft account, "Apps and services", or for a work account in My Apps).
  --check     whether an authorization is found, through the secret resolver (the environment, the credentials directory, then the OS
              secret store); no network, nothing printed of it but the facts below.
authorize prints one JSON object on stdout: {{"authorized": true, "secret_store": {{"service", "username"}}, "scope", "account_kind",
"tenant", "obtained_at"}}. It registers no file as a source: the runtime does (python3 runtime/cli.py source-onedrive).

`Files.Read` lets this app read EVERY file of your own OneDrive, not only the ones you choose, and it writes nothing. Microsoft has no
permission that is granted per chosen file. The provider (onedrive.py) sends GET requests only and the runtime reads only the files
registered as sources. The token is as private as your files.

Microsoft Entra setup (once), at https://entra.microsoft.com (the maintainer of the project does this, not each person):
  1. Identity, Applications, App registrations, New registration: a name, and the supported account types "Accounts in any
     organizational directory and personal Microsoft accounts". No redirect URI yet.
  2. Authentication, Add a platform, "Mobile and desktop applications", custom redirect URI {redirect}  (the port is ignored for
     localhost, so the random port this script listens on matches). No client secret, no certificate.
  3. API permissions: remove `User.Read`; add Microsoft Graph, Delegated permissions, `Files.Read` (and `offline_access`). Do not
     grant admin consent for a personal test. Any other permission left on the registration is refused by the check.
  4. Copy the Application (client) ID. Run: ONEDRIVE_CLIENT_ID=<the id> uv run providers/documents/onedrive_auth.py authorize
     (or run it in a terminal and type the id at the hidden prompt). The id never goes on the command line. An office with its own
     single-tenant registration also sets ONEDRIVE_TENANT=<its tenant id or domain> for that one command; the default is "common".
  5. Sign in with the account that owns the files and approve. A work or school tenant whose admin has blocked user consent answers
     with a consent error: your Microsoft 365 admin must approve the app, and the command stops (exit 3).
  6. Verify: uv run providers/documents/onedrive.py --check
The authorization (the refresh token, the client id, the tenant) is stored as one record in the OS secret store (service "openhora",
username "{username}"; the secret {secret}), never on disk. Microsoft replaces the refresh token on every use; onedrive.py writes the
new one into the same record.

The local address: the script listens on 127.0.0.1 (and on ::1 when it can) on one random port and sends redirect_uri
http://localhost:<port>. It accepts only a request whose Host is exactly localhost:<port>, serves the callback once, logs no request
line (the line carries the code) and stops after the callback or after {timeout} minutes.

exit codes: 0 success, 1 failed or timed out, 2 usage, 3 not configured (no authorization, no client id, a consent that needs the
admin, a rejected registration, a token with a wider scope than Files.Read).
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
import urllib.parse
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


onedrive = _load("workbench_documents_onedrive", "onedrive.py")
ProviderError = onedrive.ProviderError
EXIT_OK, EXIT_SERVICE, EXIT_USAGE, EXIT_NOT_CONFIGURED = onedrive.EXIT_OK, onedrive.EXIT_SERVICE, onedrive.EXIT_USAGE, onedrive.EXIT_NOT_CONFIGURED

AUTHORIZE_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
REDIRECT_EXAMPLE = "http://localhost"
LOOPBACK_V4, LOOPBACK_V6 = "127.0.0.1", "::1"
SESSION_TIMEOUT_SECONDS = 600
HANDLER_TIMEOUT_SECONDS = 5     # a connection that sends nothing is dropped, never waited on for ever
CLIENT_ID_VAR, TENANT_VAR = "ONEDRIVE_CLIENT_ID", "ONEDRIVE_TENANT"
__doc__ = __doc__.format(redirect=REDIRECT_EXAMPLE, username=onedrive.KEYRING_USERNAME, secret=onedrive.SECRET,
                         timeout=SESSION_TIMEOUT_SECONDS // 60)

log = onedrive.log


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def pkce_pair() -> tuple[str, str]:
    """(code_verifier, code_challenge) for S256: 86 unreserved characters, then base64url(sha256), no padding."""
    verifier = secrets.token_urlsafe(64)
    return verifier, base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode()


def authorize_url(client_id: str, tenant: str, redirect_uri: str, state: str, challenge: str) -> str:
    """The consent URL: the one permission Files.Read plus offline_access (a refresh token), PKCE S256, the state, the code in the query
    (no id token) and the account chooser."""
    query = urllib.parse.urlencode({
        "client_id": client_id, "response_type": "code", "redirect_uri": redirect_uri, "response_mode": "query", "scope": onedrive.REFRESH_SCOPE,
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
    like a callback (a `state` and a `code` or an `error`), once; a request logged nowhere; nothing it receives is shown back."""

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
            log(f"note: this machine has no usable ::1; if your browser resolves localhost to ::1 the redirect will not arrive: try again or use "
                f"another browser")
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
            error = onedrive.one_line(query["error"][0], 80)
            description = onedrive.one_line(query.get("error_description", [""])[0], 200)
            detail = f"{error}: {description}" if description else error
            if onedrive.consent_blocked(error, description):
                self.outcome = {"error": f"Microsoft needs a consent this account has not given ({detail}): your Microsoft 365 admin must approve "
                                         "the app; nothing stored", "exit": EXIT_NOT_CONFIGURED}
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


def client_inputs() -> dict:
    """The client id (and, for an office's own registration, the tenant) of the one command: the environment, else a hidden prompt on a
    terminal for the id. Never a flag."""
    client = (os.environ.get(CLIENT_ID_VAR) or "").strip()
    if not client and sys.stdin.isatty():
        client = getpass.getpass(f"{CLIENT_ID_VAR} (the Application (client) ID of the app registration): ").strip()
    if not client:
        raise ProviderError(f"{CLIENT_ID_VAR} (the Application (client) ID) is not set: export it for this one command, or run it in a terminal "
                            "to type it at a hidden prompt", EXIT_NOT_CONFIGURED)
    if onedrive.bad_text(client) or len(client) > 100:
        raise ProviderError(f"{CLIENT_ID_VAR} holds whitespace or control characters, or is too long", EXIT_USAGE)
    tenant = (os.environ.get(TENANT_VAR) or "common").strip()
    if not onedrive.TENANT.fullmatch(tenant):
        raise ProviderError(f"{TENANT_VAR} is common, organizations, consumers, a tenant id or a verified domain", EXIT_USAGE)
    return {"client_id": client, "tenant": tenant}


def account_kind(graph) -> str:
    """"personal" or "work" from the drive's own type, "unknown" when it cannot be told (a note on stderr; nothing fails for it)."""
    try:
        kind = graph.json("/me/drive", {"$select": "id,driveType"}, "drive get").get("driveType")
    except ProviderError as exc:
        log(f"note: the account kind could not be read ({exc}); stored as unknown")
        return "unknown"
    return {"personal": "personal", "business": "work"}.get(kind, "unknown")


def authorize(open_browser: bool) -> int:
    base, token_url, hosts, test_mode = onedrive.endpoints()
    given = client_inputs()
    store = onedrive.keyring_module(test_mode)   # fail before the browser step when the store is unavailable
    state = secrets.token_urlsafe(32)
    verifier, challenge = pkce_pair()
    server = CallbackServer(state)
    try:
        url = authorize_url(given["client_id"], given["tenant"], server.redirect_uri, state, challenge)
        log("Open this URL in your browser (it holds no secret):")
        log(url)
        if open_browser:
            webbrowser.open(url)
        log(f"Waiting up to {SESSION_TIMEOUT_SECONDS // 60} minutes on {server.redirect_uri}; the listener stops after one callback ...")
    except BaseException:
        server.close()
        raise
    code = server.wait()
    data = onedrive.token_request(token_url or onedrive.TOKEN_URL_TEMPLATE.format(tenant=given["tenant"]), {
        "client_id": given["client_id"], "grant_type": "authorization_code", "code": code, "redirect_uri": server.redirect_uri,
        "code_verifier": verifier, "scope": onedrive.REFRESH_SCOPE})
    scope = onedrive.check_scope(data.get("scope"))   # a wider permission left on the registration: nothing is stored
    refresh = data.get("refresh_token")
    if onedrive.bad_text(refresh):
        raise ProviderError("Microsoft returned no refresh token (is offline_access on the registration?); nothing stored")
    kind = account_kind(onedrive.Graph(base, data["access_token"], hosts, test_mode))
    record = {"refresh_token": refresh, "client_id": given["client_id"], "tenant": given["tenant"], "scope": scope, "account_kind": kind,
              "obtained_at": now_iso()}
    try:
        store.set_password(onedrive.KEYRING_SERVICE, onedrive.KEYRING_USERNAME, json.dumps(record))
    except Exception as exc:
        raise ProviderError(f"cannot write to the OS secret store: {type(exc).__name__}") from None
    print(json.dumps({"authorized": True, "secret_store": {"service": onedrive.KEYRING_SERVICE, "username": onedrive.KEYRING_USERNAME},
                      "scope": scope, "account_kind": kind, "tenant": given["tenant"], "obtained_at": record["obtained_at"]}, indent=2))
    return EXIT_OK


def forget() -> int:
    """Delete our record from the OS secret store: a local delete of our own entry, not Microsoft data and no revocation."""
    _, _, _, test_mode = onedrive.endpoints()
    store = onedrive.keyring_module(test_mode)
    try:
        store.delete_password(onedrive.KEYRING_SERVICE, onedrive.KEYRING_USERNAME)
        forgotten = True
    except Exception as exc:
        if type(exc).__name__ != "PasswordDeleteError":   # the library's word for "nothing was stored"
            raise ProviderError(f"cannot delete from the OS secret store: {type(exc).__name__}") from None
        forgotten = False
    print(json.dumps({"forgotten": forgotten, "secret_store": {"service": onedrive.KEYRING_SERVICE, "username": onedrive.KEYRING_USERNAME}}, indent=2))
    log("This removed the local record only. To revoke the app's access at Microsoft: your Microsoft account, Apps and services (a work "
        "account: My Apps).")
    return EXIT_OK


def check() -> int:
    """Whether an authorization is there, read the way onedrive.py reads it. No network."""
    _, _, _, test_mode = onedrive.endpoints()
    found = onedrive.secret_resolver().resolve(onedrive.SECRET, allow_store=not test_mode)
    if not found:
        print(json.dumps({"found": False}, indent=2))
        log(f"not configured: no OneDrive authorization in the environment, the credentials directory or the OS secret store; run: "
            f"{onedrive.AUTH_COMMAND}")
        return EXIT_NOT_CONFIGURED
    record = onedrive.parse_record(found[0])
    print(json.dumps({"found": True, "source": found[1], "has_refresh_token": True, "scope": record.get("scope"),
                      "account_kind": record.get("account_kind"), "tenant": record["tenant"], "obtained_at": record.get("obtained_at")}, indent=2))
    return EXIT_OK


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="onedrive_auth.py", description=__doc__.split("\n\n")[0], epilog=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", nargs="?", choices=["authorize", "forget"], help="authorize once, or forget the stored record")
    parser.add_argument("--check", action="store_true", help="report whether an authorization is found (no network)")
    parser.add_argument("--no-browser", action="store_true", help="print the authorization URL without opening a browser")
    args = parser.parse_args(argv)
    try:
        if args.check:
            if args.command:
                raise ProviderError("--check takes no command", EXIT_USAGE)
            return check()
        if args.command is None:
            raise ProviderError("give authorize or forget, or --check; see --help", EXIT_USAGE)
        if args.no_browser and args.command != "authorize":
            raise ProviderError("--no-browser is for authorize only", EXIT_USAGE)
        return authorize(open_browser=not args.no_browser) if args.command == "authorize" else forget()
    except ProviderError as exc:
        log(f"error: {exc}")
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
