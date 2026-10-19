#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["keyring==25.7.0"]
# ///
"""One-time OAuth 2.0 authorization for the Outlook calendar provider (outlook.py).

LEGACY, for one cycle (backlog ACCT-LEGACY): the platform now uses one account token for the whole Microsoft account, authorized once with
`uv run <workbench>/providers/accounts/microsoft_auth.py authorize`. The provider reads that record first and this one only when the account
record is absent, with a note each time. This command behaves as it always did; it is removed in the cycle after the integration branch
reaches `main`.

Commands:
  authorize   the authorization code flow with PKCE (S256) and a state, as a public client (no client secret), in the system browser,
              with a loopback redirect. It asks for the delegated Microsoft Graph permission `Calendars.ReadBasic` and `offline_access`
              and nothing else, checks that the token carries nothing wider, and stores the authorization as one record in the OS secret
              store. Run it once.
  forget      deletes that record from the OS secret store (our own local record; it revokes nothing at Microsoft: do that in your
              Microsoft account, "Apps and services", or for a work account in My Apps).
  --check     whether an authorization is found, through the secret resolver (the environment, the credentials directory, then the OS
              secret store); no network, nothing printed of it but the facts below.
authorize prints one JSON object on stdout: {{"authorized": true, "secret_store": {{"service", "username"}}, "scope", "tenant",
"obtained_at"}}. It registers nothing as a source: the runtime does.

`Calendars.ReadBasic` lets this app read the events of EVERY calendar your account can see, without their body, attachments and
extensions, and it changes none. Microsoft has no permission that is granted per calendar. The provider (outlook.py) sends GET requests
only and the runtime reads only the calendar and window a source names. The token is as private as your calendar.

ONE APP REGISTRATION PER PURPOSE. This registration holds `Calendars.ReadBasic` and nothing else. Do not add `Mail.Read` (the mail
provider's registration) or `Files.Read` (the OneDrive provider's) to it: Microsoft binds a refresh token to a user and a client, not to a
resource, so a client that held two permissions could use one token to reach both. The mail, the calendar and the files each have their
own registration, their own client id and their own record.

Microsoft Entra setup (once), at https://entra.microsoft.com (the maintainer of the project does this, not each person):
  1. A personal Microsoft account (outlook.com, hotmail.com) first needs a directory (tenant) of its own: Microsoft no longer lets an app be
     registered outside a directory, and an app made under a personal account cannot be moved into one. Create a free Azure account (it
     creates a Default Directory; it asks for a phone number and a non-prepaid credit or debit card, with a temporary authorization of about
     US$1): https://azure.microsoft.com/pricing/purchase-options/azure-account
     or join the Microsoft 365 Developer Program: https://developer.microsoft.com/microsoft-365/dev-program
     Then switch to that directory (Settings icon, then "Directories + subscriptions") before registering. Sources, accessed 2026-10-18:
     https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app
     https://learn.microsoft.com/en-us/answers/questions/2127352/how-to-move-an-azure-application-created-under-a-p
  2. Entra ID, App registrations, New registration: a name (for example "openhora calendar"), and the supported account types "Any Entra ID Tenant + Personal
     Microsoft accounts" (formerly "Accounts in any organizational directory and personal Microsoft accounts"; "Personal accounts only"
     also serves a personal account). The default tenant "common" serves both. No redirect URI yet.
  3. Authentication, Add a platform, "Mobile and desktop applications", custom redirect URI {redirect}  (the port is ignored for
     localhost, so the random port this script listens on matches). No client secret, no certificate.
  4. API permissions: remove `User.Read`; add Microsoft Graph, Delegated permissions, `Calendars.ReadBasic` (and `offline_access`). Do not
     grant admin consent for a personal test. Any other permission left on the registration is refused by the check.
  5. Copy the Application (client) ID. Run:
     OUTLOOK_CALENDAR_CLIENT_ID=<the id> uv run <workbench>/providers/calendar/outlook_auth.py authorize
     (or run it in a terminal and type the id at the hidden prompt). The id never goes on the command line. An office with its own
     single-tenant registration also sets OUTLOOK_CALENDAR_TENANT=<its tenant id or domain> for that one command; the default is "common".
  6. Sign in with the account whose calendar to read and approve. A work or school tenant whose admin has blocked user consent answers
     with a consent error: your Microsoft 365 admin must approve the app, and the command stops (exit 3).
  7. Verify: uv run <workbench>/providers/calendar/outlook.py --check
The authorization (the refresh token, the client id, the tenant) is stored as one record in the OS secret store (service "openhora",
username "{username}"; the secret {secret}), never on disk. Microsoft replaces the refresh token on every use; outlook.py writes the new
one into the same record.

The local address: the script listens on 127.0.0.1 (and on ::1 when it can) on one random port and sends redirect_uri
http://localhost:<port>. It accepts only a request whose Host is exactly localhost:<port>, serves the callback once, logs no request
line (the line carries the code) and stops after the callback or after {timeout} minutes.

exit codes: 0 success, 1 failed or timed out, 2 usage, 3 not configured (no authorization, no client id, a consent that needs the
admin, a rejected registration, a token with a wider scope than Calendars.ReadBasic).
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


outlook = _load("workbench_calendar_outlook", "outlook.py")
msgraph = outlook.msgraph
ProviderError = outlook.ProviderError
EXIT_OK, EXIT_SERVICE, EXIT_USAGE, EXIT_NOT_CONFIGURED = outlook.EXIT_OK, outlook.EXIT_SERVICE, outlook.EXIT_USAGE, outlook.EXIT_NOT_CONFIGURED

SESSION_TIMEOUT_SECONDS = msgraph.SESSION_TIMEOUT_SECONDS
CLIENT_ID_VAR, TENANT_VAR = outlook.PROFILE.client_id_var, outlook.PROFILE.tenant_var
__doc__ = __doc__.format(redirect=msgraph.REDIRECT_EXAMPLE, username=outlook.KEYRING_USERNAME, secret=outlook.SECRET,
                         timeout=SESSION_TIMEOUT_SECONDS // 60)

log = outlook.log
pkce_pair = msgraph.pkce_pair


def authorize_url(client_id: str, tenant: str, redirect_uri: str, state: str, challenge: str) -> str:
    """The consent URL: the one permission Calendars.ReadBasic plus offline_access (a refresh token), PKCE S256, the state, the code in the
    query (no id token) and the account chooser."""
    return msgraph.authorize_url(outlook.PROFILE, client_id, tenant, redirect_uri, state, challenge)


class CallbackServer(msgraph.CallbackServer):
    """The loopback listener of providers/_msgraph.py, for this provider's words (see there for what it accepts and refuses)."""

    profile = outlook.PROFILE


def client_inputs() -> dict:
    """The client id (and, for an office's own registration, the tenant) of the one command: the environment, else a hidden prompt on a
    terminal for the id. Never a flag."""
    return msgraph.client_inputs(outlook.PROFILE)


def authorize(open_browser: bool) -> int:
    return msgraph.authorize(outlook.PROFILE, outlook, CallbackServer, open_browser)


def forget() -> int:
    """Delete our record from the OS secret store: a local delete of our own entry, not Microsoft data and no revocation."""
    return msgraph.forget(outlook.PROFILE, outlook)


def check() -> int:
    """Whether an authorization is there, read the way outlook.py reads it. No network."""
    return msgraph.check(outlook.PROFILE, outlook)


def main(argv=None) -> int:
    return msgraph.auth_main(argv, prog="outlook_auth.py", doc=__doc__, authorize_fn=lambda open_browser: authorize(open_browser),
                             forget_fn=lambda: forget(), check_fn=lambda: check())


if __name__ == "__main__":
    sys.exit(main())
