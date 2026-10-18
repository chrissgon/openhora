#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["keyring==25.7.0"]
# ///
"""One-time OAuth 2.0 authorization of the person's own Microsoft account: the account token that every Microsoft provider of the platform
uses (decision of 2026-10-18; package ACCT-M).

Commands:
  authorize   the authorization code flow with PKCE (S256) and a state, as a public client (no client secret), in the system browser, with a
              loopback redirect. It asks for the platform's whole set of delegated Microsoft Graph permissions in one consent:
              Mail.ReadWrite, Mail.Send, Calendars.ReadWrite, Files.ReadWrite and User.Read, and offline_access (the refresh token). It
              checks that the token carries exactly that set (a missing or an extra permission stops it, exit 3, and nothing is stored),
              reads the account's address once (GET /me, with User.Read) and the account's kind, and stores the authorization as one record
              in the OS secret store. Run it once per account.
  check       whether an authorization is found, through the secret resolver (the environment, the credentials directory, then the OS
              secret store), and that it was made for the platform's set; no network, no token printed: only the facts below.
  forget      deletes that record from the OS secret store (our own local record; it revokes nothing at Microsoft: do that in your Microsoft
              account, "Apps and services", or for a work account in My Apps).
  --account <slot>  the record's slot (default main). Version 1 has the slot main only; another word is refused (exit 2). The record carries
              its slot so that a second account can be added later without moving this one.
  --no-browser      with authorize: print the consent URL and open nothing.
authorize prints one JSON object on stdout: {"authorized": true, "secret_store": {"service", "username"}, "slot", "account", "account_kind",
"scopes", "tenant", "obtained_at"}; check prints {"found", "source", "slot", "account", "account_kind", "tenant", "scopes", "has_refresh_token",
"obtained_at"}. Neither prints a token.

What the token can do. It is not narrow: with the whole set it reads, changes, sends and moves to the trash everything the account holds in
Outlook mail, Outlook calendar and OneDrive (Microsoft lists the permanentDelete actions of a message, an event and a drive item with these
permissions, so it could delete permanently too; what prevents that is code, never the scope), and it is as private as your mail. That is accepted (decision of 2026-10-18): the restriction is
the platform's, not the token's. The record is read only by a provider process that the runtime or you start, with this one secret in its
environment; it never enters a run, a prompt, a log or the store; every write is a hashed effect you approve; each provider script sends only
the verbs its job needs, and none holds a permanent-delete call. Revoking the app in your Microsoft account stops every provider at once.

Microsoft Entra setup (once, for the platform's one registration), at https://entra.microsoft.com (the maintainer of the project does this,
not each person):
  1. A personal Microsoft account (outlook.com, hotmail.com) first needs a directory (tenant) of its own: Microsoft no longer lets an app be
     registered outside a directory, and an app made under a personal account cannot be moved into one. Create a free Azure account (it
     creates a Default Directory; it asks for a phone number and a non-prepaid credit or debit card, with a temporary authorization of about
     US$1): https://azure.microsoft.com/pricing/purchase-options/azure-account
     or join the Microsoft 365 Developer Program: https://developer.microsoft.com/microsoft-365/dev-program
     Then switch to that directory (Settings icon, then "Directories + subscriptions") before registering. Sources, accessed 2026-10-18:
     https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app
  2. Entra ID, App registrations, New registration: a name, and the supported account types "Any Entra ID Tenant + Personal Microsoft
     accounts". The default tenant "common" serves both. No redirect URI yet.
  3. Authentication, Add a platform, "Mobile and desktop applications", custom redirect URI http://localhost  (the port is ignored for
     localhost, so the random port this script listens on matches). No client secret, no certificate.
  4. API permissions, Add a permission, Microsoft Graph, Delegated permissions: Mail.ReadWrite, Mail.Send, Calendars.ReadWrite,
     Files.ReadWrite, User.Read and offline_access, and nothing else. None needs an admin's consent on a personal account (the permissions
     reference: https://learn.microsoft.com/en-us/graph/permissions-reference, accessed 2026-10-18); do not grant admin consent for a
     personal test. Any other permission left on the registration is refused by the check.
  5. Copy the Application (client) ID. Run: MICROSOFT_CLIENT_ID=<the id> uv run <workbench>/providers/accounts/microsoft_auth.py authorize
     (or run it in a terminal and type the id at the hidden prompt). The id never goes on the command line. An office with its own
     single-tenant registration also sets MICROSOFT_TENANT=<its tenant id or domain> for that one command; the default is "common".
  6. Sign in with the account and approve the consent screen with every box ticked. A work or school tenant whose admin has blocked user
     consent answers with a consent error: your Microsoft 365 admin must approve the app, and the command stops (exit 3).
  7. Verify: uv run <workbench>/providers/accounts/microsoft_auth.py check, then a reader's --check (it says "record": "account").
The authorization (the refresh token, the client id, the tenant, the account's address) is stored as one record in the OS secret store
(service "openhora", username "microsoft-account"; the secret MICROSOFT_ACCOUNT_TOKEN), never on disk. Microsoft replaces the refresh token
on every use; the readers write the new one into the same record.

The old records (one single-permission registration per reader) keep working for one cycle, as a fallback, with a note each time. To remove
them once `check` passes: uv run --with keyring==25.7.0 keyring del openhora <username>, for onedrive-sources, outlook-mail and
outlook-calendar; and, in Entra, delete the three old registrations.

The local address: the script listens on 127.0.0.1 (and on ::1 when it can) on one random port and sends redirect_uri
http://localhost:<port>. It accepts only a request whose Host is exactly localhost:<port>, serves the callback once, logs no request line
(the line carries the code) and stops after the callback or after 10 minutes.

Test overrides (tests only, loopback URLs only, both set together; the secret store is then never read or written):
  ACCOUNT_MICROSOFT_API_BASE    replaces https://graph.microsoft.com/v1.0
  ACCOUNT_MICROSOFT_TOKEN_URL   replaces https://login.microsoftonline.com/<tenant>/oauth2/v2.0/token

Exit codes: 0 success, 1 failed or timed out (including an account address that could not be read: nothing is stored), 2 usage (a bad flag, a
slot other than main), 3 not configured (no authorization, no client id, a consent that needs the admin, a rejected registration, a token
that lacks one permission of the set or carries another).
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
import webbrowser   # noqa: F401  (a test replaces webbrowser.open through this module's name)
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _msgraph_module():
    """providers/_msgraph.py, by path: next to this folder's parent first (the workbench), then next to this file (a copy)."""
    path = next((c for c in (HERE.parent / "_msgraph.py", HERE / "_msgraph.py") if c.is_file()), None)
    if path is None:
        raise SystemExit("error: providers/_msgraph.py is not next to this script's folder")
    spec = importlib.util.spec_from_file_location("providers_msgraph", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


msgraph = _msgraph_module()
ProviderError, log = msgraph.ProviderError, msgraph.log
EXIT_OK, EXIT_SERVICE, EXIT_USAGE, EXIT_NOT_CONFIGURED = msgraph.EXIT_OK, msgraph.EXIT_SERVICE, msgraph.EXIT_USAGE, msgraph.EXIT_NOT_CONFIGURED
PLATFORM_SCOPES, SLOT, ACCOUNT_SLOT = msgraph.PLATFORM_SCOPES, msgraph.SLOT, msgraph.ACCOUNT_SLOT
SECRET, KEYRING_USERNAME = msgraph.ACCOUNT_SECRET, msgraph.ACCOUNT_KEYRING_USERNAME
ENV_PREFIX = "ACCOUNT_MICROSOFT"
PROFILE = msgraph.account_profile(
    run_hint="uv run <workbench>/providers/accounts/microsoft_auth.py", env_prefix=ENV_PREFIX, user_agent="openhora-accounts-microsoft",
    not_found="Microsoft does not know the item", forbidden_hint="check that the account token carries the platform's whole set")
ENV_BASE, ENV_TOKEN_URL = PROFILE.env_base, PROFILE.env_token_url
TOKEN_URL_TEMPLATE = msgraph.TOKEN_URL_TEMPLATE
pkce_pair, state_matches, now_iso = msgraph.pkce_pair, msgraph.state_matches, msgraph.now_iso


# --- what msgraph.authorize_account / check_account / forget look up on this module -----------------------------------------------


def endpoints() -> tuple:
    """(API base, token URL or None for the tenant's own, no download hosts, test mode). The overrides are for tests, must name loopback
    addresses only and are set together; in test mode the secret store is never read or written."""
    return msgraph.endpoints(PROFILE)


def secret_resolver():
    return msgraph.secret_resolver(__file__)


def keyring_module(test_mode: bool):
    return msgraph.keyring_module(PROFILE, test_mode)


def parse_record(text: str) -> dict:
    return msgraph.parse_account_record(PROFILE, text)


def token_request(token_url: str, form: dict) -> dict:
    return msgraph.token_request(PROFILE, token_url, form)


def usable_access_token(data: dict) -> str:
    return msgraph.usable_access_token(data)


class Graph(msgraph.GraphClient):
    """Microsoft Graph as this command uses it: two GET requests (the address and the kind of the account) with the access token of the
    authorization, held in memory and never stored."""

    def __init__(self, base: str, access_token: str, hosts: tuple, test_mode: bool):
        super().__init__(PROFILE, base, access_token, test_mode)


class CallbackServer(msgraph.CallbackServer):
    """The loopback listener of providers/_msgraph.py, for this command's words (see there for what it accepts and refuses)."""

    profile = PROFILE


def authorize_url(client_id: str, tenant: str, redirect_uri: str, state: str, challenge: str) -> str:
    """The consent URL: the whole platform set plus offline_access (a refresh token), PKCE S256, the state, the code in the query (no id
    token) and the account chooser."""
    return msgraph.authorize_url(PROFILE, client_id, tenant, redirect_uri, state, challenge)


class _Self:
    """This module as the shared commands look it up (endpoints, keyring_module, token_request, Graph ...): by name at the moment they run,
    so that a test can replace any of them, and whether or not the module is registered in sys.modules."""

    def __getattr__(self, name):
        try:
            return globals()[name]
        except KeyError:
            raise AttributeError(name) from None


SELF = _Self()


# --- the commands --------------------------------------------------------------------------------------------------------------------


def client_inputs() -> dict:
    """The client id (and, for an office's own registration, the tenant) of the one command: the environment, else a hidden prompt on a
    terminal for the id. Never a flag."""
    return msgraph.client_inputs(PROFILE)


def checked_slot(value) -> str:
    if not isinstance(value, str) or not SLOT.fullmatch(value):
        raise ProviderError("--account is a slot word: letters a-z and digits, 1 to 12 of them", EXIT_USAGE)
    if value != ACCOUNT_SLOT:
        raise ProviderError(f"only the slot {ACCOUNT_SLOT} exists in this version: a second account is not built yet", EXIT_USAGE)
    return value


def authorize(open_browser: bool, slot: str = ACCOUNT_SLOT) -> int:
    return msgraph.authorize_account(PROFILE, SELF, CallbackServer, open_browser, slot)


def check() -> int:
    """Whether an account authorization is there and holds the platform's set, read the way the readers read it. No network."""
    return msgraph.check_account(PROFILE, SELF)


def forget() -> int:
    """Delete our record from the OS secret store: a local delete of our own entry, not Microsoft data and no revocation."""
    return msgraph.forget(PROFILE, SELF)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="microsoft_auth.py", description=__doc__.split("\n\n")[0], epilog=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["authorize", "check", "forget"], help="authorize once, check what is stored, or forget the stored record")
    parser.add_argument("--account", default=ACCOUNT_SLOT, help="the record's slot (default main; the only one in this version)")
    parser.add_argument("--no-browser", action="store_true", help="print the consent URL without opening a browser (with authorize)")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:   # argparse: --help exits 0, a usage error 2
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE
    try:
        slot = checked_slot(args.account)
        if args.no_browser and args.command != "authorize":
            raise ProviderError("--no-browser is for authorize only", EXIT_USAGE)
        if args.command == "authorize":
            return authorize(not args.no_browser, slot)
        return check() if args.command == "check" else forget()
    except ProviderError as exc:
        log(f"error: {exc}")
        return exc.code
    except Exception as exc:   # last resort: say the kind only, never the text (it can hold an address or a credential)
        log(f"error: unexpected failure ({type(exc).__name__}); nothing was stored or changed")
        return EXIT_SERVICE


if __name__ == "__main__":
    sys.exit(main())
