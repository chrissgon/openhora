#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["keyring==25.7.0"]
# ///
"""One-time OAuth 2.0 authorization for the Drive documents provider (gdrive.py), and the Picker that gives it files.

Two commands, one page each, both on a one-shot server on 127.0.0.1 (gdrive_picker.py):
  authorize   asks for the Drive scope `drive.file` (and no other), stores the authorization, then opens the Picker so that the
              person chooses the first files, in one visit. Run it once.
  pick        opens the Picker again with the stored authorization, to give the app more files. No new consent.
Both print one JSON object on stdout: {{"picked": [{{"id", "name", "mime_type"}}...], "cancelled": bool, ...}}. They register nothing:
the runtime does (python3 runtime/cli.py source-drive).
  --check     whether an authorization is found, through the secret resolver (the environment, then the OS secret store);
              no network, nothing printed of it but the facts below.

`drive.file` lets this app read and write every file the person picked in the Picker. It is not read-only. The provider
(gdrive.py) sends GET requests only; the scope itself does not stop a write, so the token is as private as the files it opens.
Only files can be picked (a picked folder gives the app nothing inside it, measured), several at once.

Google Cloud setup (once), at https://console.cloud.google.com, in a project used only for this:
  1. APIs and services, Library: enable the "Google Drive API" and the "Google Picker API".
  2. Google Auth Platform, Branding: the app name and your e-mail as support and developer contact. Audience: user type External.
  3. Data Access, "Add or remove scopes": add
         {scope}
     and nothing else. It is a non-sensitive scope: no Google verification of the app is needed for it.
  4. Audience, "Publish app" (status "In production"). In "Testing" Google expires the authorization seven days after consent
     and the refresh token stops working every week (invalid_grant).
  5. Clients, create a client of application type "Desktop app". No redirect URL is registered: this script listens on
     http://{host}:<a random free port>, as Google's desktop-app guide says.
  6. Credentials, create an API key (the Picker needs one). Restrict it to the "Google Picker API" and, if you can,
     to the HTTP referrer http://{host}:*/* .
  7. Run: uv run providers/documents/gdrive_auth.py authorize
     It asks for the client id, the client secret and the API key at a hidden prompt (or reads GDRIVE_CLIENT_ID,
     GDRIVE_CLIENT_SECRET and GDRIVE_PICKER_API_KEY from the environment of this one command). None goes on the command
     line or in a file. Sign in with the Google account that owns the files and approve; the consent screen of an
     unverified personal app asks you to click through it.
  8. Verify: uv run providers/documents/gdrive.py --check
The authorization (the refresh token, the client and the key) is stored as one record in the OS secret store (service
"openhora", username "{username}"; the secret {secret}), never on disk.

exit codes: 0 success (also when the Picker was cancelled), 1 failed or timed out, 2 usage, 3 not configured (no authorization
or no client credentials).
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import importlib.util
import json
import os
import secrets
import sys
import urllib.parse
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gdrive = _load("workbench_documents_gdrive", "gdrive.py")
picker = _load("workbench_documents_gdrive_picker", "gdrive_picker.py")
ProviderError = gdrive.ProviderError
EXIT_OK, EXIT_SERVICE, EXIT_USAGE, EXIT_NOT_CONFIGURED = gdrive.EXIT_OK, gdrive.EXIT_SERVICE, gdrive.EXIT_USAGE, gdrive.EXIT_NOT_CONFIGURED

KEYRING_SERVICE = "openhora"
GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
SCOPE = gdrive.SCOPE
SESSION_TIMEOUT_SECONDS = 600
INPUTS = (("GDRIVE_CLIENT_ID", "the Desktop app OAuth client id"), ("GDRIVE_CLIENT_SECRET", "that client's secret"),
          ("GDRIVE_PICKER_API_KEY", "the API key for the Google Picker API"))
__doc__ = __doc__.format(scope=SCOPE, host=picker.HOST, username=gdrive.KEYRING_USERNAME, secret=gdrive.SECRET)


def log(message: str) -> None:
    print(message, file=sys.stderr)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def pkce_pair() -> tuple[str, str]:
    """(code_verifier, code_challenge) for S256: 86 unreserved characters, then base64url(sha256), no padding."""
    verifier = secrets.token_urlsafe(64)
    return verifier, base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode()


def authorize_url(client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    """The consent URL: the one scope drive.file, PKCE S256, the state, offline access (a refresh token) and a consent screen."""
    return GOOGLE_AUTHORIZE_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code", "scope": SCOPE,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": state, "access_type": "offline", "prompt": "consent"})


def keyring_module(test_mode: bool):
    """The OS secret store. Test mode never touches it: tests replace this function with a fake store."""
    if test_mode:
        raise ProviderError("test mode (the INTEGRATION_DOCUMENTS_GDRIVE_* overrides) never uses the OS secret store", EXIT_USAGE)
    try:
        import keyring
    except ImportError:
        raise ProviderError("the keyring package is missing; run with: uv run providers/documents/gdrive_auth.py", EXIT_NOT_CONFIGURED) from None
    return keyring


def client_inputs() -> dict:
    """The client id, secret and Picker API key of the one command: the environment, else a hidden prompt on a terminal. Never a flag."""
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
    number = (os.environ.get("GDRIVE_PROJECT_NUMBER") or values["GDRIVE_CLIENT_ID"].split("-", 1)[0]).strip()
    if not number.isdigit():
        raise ProviderError("cannot read the Cloud project number from the client id; export GDRIVE_PROJECT_NUMBER for this command",
                            EXIT_USAGE)
    values["project_number"] = number
    return values


def run_session(server, open_browser: bool) -> None:
    """Serve one session, wait for its end, and stop the server; ProviderError when it failed or timed out."""
    server.serve()
    try:
        log("Open this URL in your browser (it holds no secret):")
        log(server.start_url)
        if open_browser:
            webbrowser.open(server.start_url)
        log(f"Waiting up to {SESSION_TIMEOUT_SECONDS // 60} minutes on {server.redirect_uri}; the page stops after one use ...")
        finished = server.wait(SESSION_TIMEOUT_SECONDS)
    finally:
        server.close()
    if not finished:
        raise ProviderError(f"nothing came back within {SESSION_TIMEOUT_SECONDS // 60} minutes")
    if server.error:
        raise ProviderError(server.error)


def result_of(server, extra=None) -> dict:
    return {**(extra or {}), "picked": server.picks, "cancelled": server.cancelled}


def authorize(open_browser: bool) -> int:
    _, token_url, test_mode = gdrive.endpoints()
    given = client_inputs()
    store = keyring_module(test_mode)   # fail before the browser step when the store is unavailable
    verifier, challenge = pkce_pair()
    stored = {}

    def exchange(code, redirect_uri):
        data = gdrive.token_request(token_url, {"client_id": given["GDRIVE_CLIENT_ID"], "client_secret": given["GDRIVE_CLIENT_SECRET"],
                                                "code": code, "code_verifier": verifier, "grant_type": "authorization_code",
                                                "redirect_uri": redirect_uri})
        if not data.get("refresh_token"):
            raise ProviderError("Google returned no refresh token; revoke the app's access in your Google Account and run this again")
        return data

    def on_token(data):
        record = {"refresh_token": data["refresh_token"], "client_id": given["GDRIVE_CLIENT_ID"],
                  "client_secret": given["GDRIVE_CLIENT_SECRET"], "api_key": given["GDRIVE_PICKER_API_KEY"],
                  "project_number": given["project_number"], "scope": data.get("scope"), "obtained_at": now_iso()}
        try:
            store.set_password(KEYRING_SERVICE, gdrive.KEYRING_USERNAME, json.dumps(record))
        except Exception as exc:
            raise ProviderError(f"cannot write to the OS secret store: {type(exc).__name__}") from None
        stored.update({"service": KEYRING_SERVICE, "username": gdrive.KEYRING_USERNAME, "obtained_at": record["obtained_at"],
                       "scope": record["scope"]})

    server = picker.OneShotServer(
        api_key=given["GDRIVE_PICKER_API_KEY"], project_number=given["project_number"], scope=SCOPE,
        authorize_url=lambda redirect_uri, state: authorize_url(given["GDRIVE_CLIENT_ID"], redirect_uri, state, challenge),
        exchange=exchange, on_token=on_token)
    try:
        run_session(server, open_browser)
    except ProviderError:
        if stored:   # the consent worked and is kept; only the Picker step failed
            log("the authorization is stored; run the pick command to choose files")
        raise
    print(json.dumps(result_of(server, {"authorized": True, "secret_store": {k: stored[k] for k in ("service", "username")},
                                        "scope": stored.get("scope"), "obtained_at": stored.get("obtained_at")}), indent=2))
    return EXIT_OK


def pick(open_browser: bool) -> int:
    _, token_url, test_mode = gdrive.endpoints()
    record = gdrive.load_record(test_mode)
    if not record.get("api_key") or not str(record.get("project_number") or "").isdigit():
        raise ProviderError(f"the stored authorization has no Picker API key; run: {gdrive.AUTH_COMMAND}", EXIT_NOT_CONFIGURED)
    token = gdrive.refresh_access_token(token_url, record)
    server = picker.OneShotServer(api_key=record["api_key"], project_number=str(record["project_number"]), scope=SCOPE, access_token=token)
    run_session(server, open_browser)
    print(json.dumps(result_of(server), indent=2))
    return EXIT_OK


def check() -> int:
    """Whether an authorization is there, read the way gdrive.py reads it. No network."""
    _, _, test_mode = gdrive.endpoints()
    found = gdrive.secret_resolver().resolve(gdrive.SECRET, allow_store=not test_mode)
    if not found:
        print(json.dumps({"found": False}, indent=2))
        log(f"not configured: no Drive authorization in the environment or the OS secret store; run: {gdrive.AUTH_COMMAND}")
        return EXIT_NOT_CONFIGURED
    record = gdrive.parse_record(found[0])
    print(json.dumps({"found": True, "source": found[1], "has_refresh_token": True, "has_api_key": bool(record.get("api_key")),
                      "scope": record.get("scope"), "obtained_at": record.get("obtained_at")}, indent=2))
    return EXIT_OK


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="gdrive_auth.py", description=__doc__.split("\n\n")[0], epilog=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", nargs="?", choices=["authorize", "pick"], help="authorize once, or pick more files later")
    parser.add_argument("--check", action="store_true", help="report whether an authorization is found (no network)")
    parser.add_argument("--no-browser", action="store_true", help="print the local URL without opening a browser")
    args = parser.parse_args(argv)
    try:
        if args.check:
            if args.command:
                raise ProviderError("--check takes no command", EXIT_USAGE)
            return check()
        if args.command is None:
            raise ProviderError("give authorize or pick, or --check; see --help", EXIT_USAGE)
        return (authorize if args.command == "authorize" else pick)(open_browser=not args.no_browser)
    except ProviderError as exc:
        log(f"error: {exc}")
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
