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

import getpass      # noqa: F401  (a test replaces getpass.getpass through this module's name)
import importlib.util
import sys
import webbrowser   # noqa: F401  (and webbrowser.open)
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


onedrive = _load("workbench_documents_onedrive", "onedrive.py")
msgraph = onedrive.msgraph
ProviderError = onedrive.ProviderError
EXIT_OK, EXIT_SERVICE, EXIT_USAGE, EXIT_NOT_CONFIGURED = onedrive.EXIT_OK, onedrive.EXIT_SERVICE, onedrive.EXIT_USAGE, onedrive.EXIT_NOT_CONFIGURED

REDIRECT_EXAMPLE = msgraph.REDIRECT_EXAMPLE
SESSION_TIMEOUT_SECONDS = msgraph.SESSION_TIMEOUT_SECONDS
CLIENT_ID_VAR, TENANT_VAR = onedrive.PROFILE.client_id_var, onedrive.PROFILE.tenant_var
__doc__ = __doc__.format(redirect=REDIRECT_EXAMPLE, username=onedrive.KEYRING_USERNAME, secret=onedrive.SECRET,
                         timeout=SESSION_TIMEOUT_SECONDS // 60)

log = onedrive.log
now_iso = msgraph.now_iso
pkce_pair = msgraph.pkce_pair
state_matches = msgraph.state_matches


def authorize_url(client_id: str, tenant: str, redirect_uri: str, state: str, challenge: str) -> str:
    """The consent URL: the one permission Files.Read plus offline_access (a refresh token), PKCE S256, the state, the code in the query
    (no id token) and the account chooser."""
    return msgraph.authorize_url(onedrive.PROFILE, client_id, tenant, redirect_uri, state, challenge)


class CallbackServer(msgraph.CallbackServer):
    """The loopback listener of providers/_msgraph.py, for this provider's words (see there for what it accepts and refuses)."""

    profile = onedrive.PROFILE


def client_inputs() -> dict:
    """The client id (and, for an office's own registration, the tenant) of the one command: the environment, else a hidden prompt on a
    terminal for the id. Never a flag."""
    return msgraph.client_inputs(onedrive.PROFILE)


def account_kind(graph) -> str:
    """"personal" or "work" from the drive's own type, "unknown" when it cannot be told (a note on stderr; nothing fails for it)."""
    try:
        kind = graph.json("/me/drive", {"$select": "id,driveType"}, "drive get").get("driveType")
    except ProviderError as exc:
        log(f"note: the account kind could not be read ({exc}); stored as unknown")
        return "unknown"
    return {"personal": "personal", "business": "work"}.get(kind, "unknown")


def authorize(open_browser: bool) -> int:
    return msgraph.authorize(onedrive.PROFILE, onedrive, CallbackServer, open_browser, account_kind)


def forget() -> int:
    """Delete our record from the OS secret store: a local delete of our own entry, not Microsoft data and no revocation."""
    return msgraph.forget(onedrive.PROFILE, onedrive)


def check() -> int:
    """Whether an authorization is there, read the way onedrive.py reads it. No network."""
    return msgraph.check(onedrive.PROFILE, onedrive)


def main(argv=None) -> int:
    return msgraph.auth_main(argv, prog="onedrive_auth.py", doc=__doc__, authorize_fn=lambda open_browser: authorize(open_browser),
                             forget_fn=lambda: forget(), check_fn=lambda: check())


if __name__ == "__main__":
    sys.exit(main())
