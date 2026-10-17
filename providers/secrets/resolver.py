#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["keyring==25.7.0"]
# ///
"""One way to find the workbench's secrets, the same on a laptop, in a cloud session and in CI.

Every script asks for a secret by name; the resolver looks in the same places, in the same order:
  1. environment variables: the name, then its aliases (a cloud environment's settings, CI secrets,
     or an export in the shell);
  2. the credentials directory, the one supported backend for a machine with no desktop session (see
     "The credentials directory" below);
  3. the OS secret store (keyring): service "openhora", the username listed below; a name not found
     there is looked up under the service the workbench used before it was renamed, "ai-workbench"
     (LEGACY_SERVICE), for one stage (removed with the next change of the lab models, T23);
  4. a password manager (1Password first), only for a name the person mapped to a reference in the mapping file (see "The
     password manager" below).
The first non-empty value wins. Values are never printed, logged or written, not even partially.
Adding a backend (a password manager) means adding one lookup function to the chain in resolve_state;
callers do not change.

A locked store is not a missing secret. When the OS secret store raises instead of answering (a locked
keychain or collection, no backend on a machine with no desktop session), the answer is "locked" and not
"missing": resolve_state says so (state "locked"), --check exits 4, --list prints "locked", and
store_locked_note() gives the sentence a caller shows. resolve and resolve_detail keep returning None, as
for a missing secret, so a caller that reads only None is unchanged; one that wants to tell the two apart
asks resolve_state. A store that answers with nothing is "missing".

The credentials directory. A folder with one file per secret, named exactly like the secret
(VCS_GITHUB_TOKEN), holding its value. It is looked for in OPENHORA_CREDENTIALS_DIR, then in
CREDENTIALS_DIRECTORY (what a systemd unit sets for LoadCredential= and LoadCredentialEncrypted=; a
container's mounted secrets work the same way), then in ~/.config/openhora/credentials when that folder
exists. It is read, never written, with checks that refuse an unsafe one (state "unsafe", and the reason; every message
that would say "missing" says "unsafe" instead, and --check exits 4): neither the folder nor a file may be a symbolic
link, a file is at most 64 KiB, each is owned by this user or by root, and neither is writable by group or others.
One this user owns must also be unreadable by anyone else (folder 0700, file 0600 or 0400). One root owns may be
readable by others (0755 and 0444): that is how an administrator or an orchestrator provisions it (systemd
credentials, Docker or Kubernetes secrets), and who may read it is then their decision, not a leak this user made.

The password manager. A fourth place, never a replacement: the order above is the contract and the person cannot change it, so a
stale entry in the OS secret store shadows the manager (--list and the doctor mark a name that is also mapped: "mapped in the
password manager, not asked: found earlier"). It is asked only for a name written in the mapping file,
$XDG_CONFIG_HOME/openhora/password-manager.json, else ~/.config/openhora/password-manager.json, which holds references and never
values: {"backend": "1password", "account": "<optional>", "timeout_seconds": 15, "references": {"VCS_GITHUB_TOKEN":
"op://Example Vault/github-read/credential"}}. Without the file nothing changes. The file is checked like the credentials directory
(not a link, a regular file, this user's, mode 0600; at most 64 KiB), and a file that fails, cannot be parsed, has an unknown key
or backend, or a reference that fails the syntax check is state "unsafe" and the manager is not called. Each lookup calls the
manager's tool once (providers/secrets/password_managers.py: no shell, no terminal, a deadline, a minimum environment, never inside
an eval container) and keeps no value. The person signs in: the desktop app's unlock, or a service account's token registered as
OP_SERVICE_ACCOUNT_TOKEN and found in the environment, the credentials directory or the OS secret store (never through the manager).
A manager that is locked, not signed in or not installed is "locked", never "missing"; only the tool's answer that the item or field
does not exist is "missing" (detail: check the reference in the mapping file).

The registry below holds the secrets the core reads: the providers' credentials. An adapter
registers the secrets its own runs need in the "secrets" list of adapters/<harness>/adapter.json.
The resolver never opens an adapter by itself: a caller outside the core hands it the file
(--registry <file>, or register_file(path)), and the list is merged into the registry for that call.

Usage:
  python3 providers/secrets/resolver.py [--registry <file>]... --list [--json]
  python3 providers/secrets/resolver.py [--registry <file>]... --check <NAME>

  --list      every registered secret: purpose, minimum permission, readers, whether it is found
              and where (environment or store, and which store service answered: "openhora" or
              "ai-workbench (legacy)", the name to move), and how to set it; never the value
  --check     exit 0 when <NAME> is found, 3 when not, 4 when the store is locked or unavailable or the
              credentials directory or the mapping file is unsafe or the password manager is locked or unavailable (the answer is not
              "missing"), 2 when <NAME> is not
              registered; the line printed carries "service" when the store answered
  --registry  a JSON file whose "secrets" list is merged into the registry first (repeatable);
              each entry has name, purpose, permission and readers, and optionally
              store_username, aliases, note and set_local
  --json      machine-readable output for --list
  --help      this text

Setting a secret:
  cloud session  the environment's settings, as an environment variable named like the secret
  CI             a repository secret, mapped to an environment variable of the same name in the
                 workflow (env: NAME: ${{ secrets.NAME }})
  local          uv run --with keyring==25.7.0 keyring set openhora <username>
                 (typed at a hidden prompt, never on the command line), or an export in the shell
  headless       a file in the credentials directory (chmod 600), see docs/architecture/platform/unattended.md
  password mgr   a reference in the mapping file (chmod 600), see "Use with 1Password" in docs/architecture/platform/unattended.md;
                 never the value, and nothing in the repository

Without the keyring package (plain python3), the store is reported as unavailable and only the
environment is read. Exit codes: 0 ok, 2 usage error, 3 not found, 4 the store is locked or unavailable, the password manager is locked or unavailable,
or the credentials directory or the mapping file is unsafe (the answer is not "missing").
"""
from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
from dataclasses import dataclass, field, replace

SERVICE = "openhora"
LEGACY_SERVICE = "ai-workbench"  # T23: what the store held before the rename; read as a fallback, never written
LEGACY_LABEL = f"{LEGACY_SERVICE} (legacy)"
EXIT_USAGE = 2
EXIT_NOT_FOUND = 3
EXIT_LOCKED = 4
CREDENTIALS_DIR_VARS = ("OPENHORA_CREDENTIALS_DIR", "CREDENTIALS_DIRECTORY")   # looked at in this order
CREDENTIALS_DEFAULT = (".config", "openhora", "credentials")                  # under the home folder, used only when it exists
CREDENTIAL_MAX_BYTES = 64 * 1024
MAPPING_FILE = ("openhora", "password-manager.json")                          # under $XDG_CONFIG_HOME, else under ~/.config
MAPPING_KEYS = ("backend", "account", "timeout_seconds", "references")
MANAGER_SOURCE = "password manager"
PROBE_USERNAME = "__store-probe__"                                            # a name nothing stores: asking for it reads no secret
ALSO_MAPPED = "mapped in the password manager, not asked: found earlier"
LOCKED_SENTENCE = ("the secret store is locked or unavailable: unlock it (a locked keychain or collection), or, on a machine with "
                   "no desktop session, put the secret in the credentials directory "
                   "(docs/architecture/platform/unattended.md). The secret may be stored; it cannot be read now")


@dataclass(frozen=True)
class Secret:
    name: str
    purpose: str
    permission: str
    readers: tuple[str, ...]
    store_username: str | None = None
    aliases: tuple[str, ...] = field(default_factory=tuple)
    note: str = ""
    set_local: str = ""  # how to store it locally when not with `keyring set`
    billing: str = ""  # how a credential of an adapter is billed: subscription, metered or free (BILLING_WORDS); "" for the core's own


REGISTRY: dict[str, Secret] = {s.name: s for s in (
    Secret("VCS_GITHUB_TOKEN",
           "read (and, with a separate token, dismiss) Dependabot alerts; read one file of a repository",
           "fine-grained token, only the repositories concerned: \"Dependabot alerts: Read-only\" "
           "(\"Read and write\" only in the separate token used to dismiss); \"Contents: Read-only\" to read a "
           "file of a private repository (read-file); commit-files uses no token",
           ("providers/vcs/github.py", ".github/workflows/dependabot-alerts.yml"),
           store_username="github", aliases=("GITHUB_TOKEN",),
           note="GITHUB_TOKEN is read last: a harness or CI may set its own, with other permissions; "
                "open-pr reads it only when VCS_GITHUB_PR_TOKEN is found nowhere"),
    Secret("VCS_GITHUB_PR_TOKEN",
           "open a pull request (open-pr); nothing else",
           "fine-grained token, only the repositories concerned: \"Pull requests: Read and write\" only",
           ("providers/vcs/github.py", "runtime/effects.py"),
           store_username="github-pr",
           note="open-pr reads it first and names it (never its value); when it is found nowhere, open-pr "
                "falls back to VCS_GITHUB_TOKEN"),
    Secret("LINKEDIN_ACCESS_TOKEN",
           "publish posts on LinkedIn",
           "OAuth scopes openid, profile and w_member_social (providers/publisher/auth.py)",
           ("providers/publisher/linkedin.py", "providers/publisher/auth.py"),
           store_username="publisher-linkedin",
           set_local="uv run providers/publisher/auth.py --provider linkedin (writes the record after the browser consent)",
           note="the store holds a JSON record written by providers/publisher/auth.py "
                "(access_token, expires_at); from the environment, LINKEDIN_TOKEN_EXPIRES_AT may give the expiry"),
    Secret("LINKEDIN_CLIENT_ID",
           "the LinkedIn app that authorizes the publisher, once",
           "an app with the \"Share on LinkedIn\" product",
           ("providers/publisher/auth.py",),
           store_username="linkedin-client-id"),
    Secret("LINKEDIN_CLIENT_SECRET",
           "the LinkedIn app's secret, used once by the authorization",
           "the app's primary client secret",
           ("providers/publisher/auth.py",),
           store_username="linkedin-client-secret"),
    Secret("GMAIL_REFRESH_TOKEN",
           "read the user's Gmail (search and read messages, never change them)",
           "OAuth scope https://www.googleapis.com/auth/gmail.readonly only (providers/mailbox/auth.py)",
           ("providers/mailbox/gmail.py", "providers/mailbox/auth.py"),
           store_username="mailbox-gmail",
           set_local="uv run providers/mailbox/auth.py --provider gmail (writes the record after the browser consent)",
           note="the store holds a JSON record written by providers/mailbox/auth.py (refresh_token, scope, "
                "obtained_at, account); from the environment, the bare refresh token"),
    Secret("GMAIL_CLIENT_ID",
           "the Google Cloud OAuth client (Desktop app) that authorizes and refreshes the Gmail access",
           "a Desktop app OAuth client in a project with the Gmail API and only the gmail.readonly scope",
           ("providers/mailbox/auth.py", "providers/mailbox/gmail.py"),
           store_username="gmail-client-id"),
    Secret("GMAIL_CLIENT_SECRET",
           "that Google OAuth client's secret, used by the authorization and every token refresh",
           "the Desktop app client's secret",
           ("providers/mailbox/auth.py", "providers/mailbox/gmail.py"),
           store_username="gmail-client-secret"),
    Secret("GOOGLE_CALENDAR_TOKEN",
           "read the events and the list of calendars of the person's Google Calendar, for the calendar sources they chose (and nothing else)",
           "OAuth scopes https://www.googleapis.com/auth/calendar.events.readonly and "
           "https://www.googleapis.com/auth/calendar.calendarlist.readonly only (providers/calendar/google_auth.py): they read every event of "
           "every calendar the account can see and the list of calendars, and change nothing; the narrowing to a calendar and a window is the "
           "runtime's, not the service's",
           ("providers/calendar/google.py", "providers/calendar/google_auth.py"),
           store_username="calendar-google",
           set_local="uv run providers/calendar/google_auth.py authorize (writes the record after the browser consent)",
           note="one JSON record (refresh_token, client_id, client_secret, scope, account, obtained_at) written by "
                "providers/calendar/google_auth.py; the Desktop app client travels with the refresh token so that this is the only entry, "
                "and it is a record of its own, apart from the Gmail one; from the environment, the same JSON text"),
    Secret("NOTION_TOKEN",
           "read and write the task board and the documents of a project on Notion",
           "an internal integration with read content, update content, insert content and read comments, "
           "given only the base and the parent page the project names",
           ("providers/issue-tracker/notion.py", "providers/documents/notion.py"),
           store_username="notion"),
    Secret("NOTION_SOURCES_TOKEN",
           "read the Notion pages the person chose as sources of a project (their text and version), and nothing else",
           "an internal integration with read content only (no update, no insert, no comments), given only the pages chosen as "
           "sources: a separate integration from the one behind NOTION_TOKEN, which can write",
           ("providers/documents/notion.py",),
           store_username="notion-sources"),
    Secret("GDRIVE_SOURCES_TOKEN",
           "read the Google Drive files the person picked as sources of a project (their content and version)",
           "OAuth scope https://www.googleapis.com/auth/drive.file only (providers/documents/gdrive_auth.py): it lets the app read and "
           "write every file the person picked in the Picker, so it is not read-only; the provider sends GET requests only",
           ("providers/documents/gdrive.py", "providers/documents/gdrive_auth.py"),
           store_username="gdrive-sources",
           set_local="uv run providers/documents/gdrive_auth.py authorize (writes the record after the browser consent)",
           note="one JSON record (refresh_token, client_id, client_secret, api_key, project_number, scope, obtained_at) written by "
                "providers/documents/gdrive_auth.py; the Desktop app client and the Picker's API key travel with the refresh token so "
                "that this is the only entry; from the environment, the same JSON text"),
    Secret("MESSENGER_TELEGRAM_BOT_TOKEN",
           "receive the person's messages and send the notices of the messaging bridge, as a Telegram bot",
           "a bot created for this person with the platform's bot service, used only by this bridge",
           ("providers/messenger/telegram.py",),
           store_username="messenger-telegram"),
    Secret("MESSENGER_DISCORD_BOT_TOKEN",
           "receive the person's messages and button taps and send the notices of the messaging bridge, as a Discord bot",
           "a bot of an application created for this person, used only by this bridge; no server permissions needed",
           ("providers/messenger/discord.py",),
           store_username="messenger-discord"),
    Secret("MESSENGER_WHATSAPP_CLOUD_TOKEN",
           "send the notices of the messaging bridge through the official WhatsApp Cloud API, and check at start that the token works",
           "a system user's permanent token with whatsapp_business_messaging, whatsapp_business_management and "
           "business_management, for the one app and phone number the bridge uses",
           ("providers/messenger/whatsapp-cloud.py",),
           store_username="messenger-whatsapp-cloud"),
    Secret("MESSENGER_WHATSAPP_CLOUD_APP_SECRET",
           "check the signature of every webhook call Meta makes to the bridge's local server",
           "the app's secret; used only to compute an HMAC, never sent anywhere",
           ("providers/messenger/whatsapp-cloud.py",),
           store_username="messenger-whatsapp-cloud-app-secret"),
    Secret("MESSENGER_WHATSAPP_CLOUD_VERIFY_TOKEN",
           "answer Meta's webhook handshake (the verify token typed in the app's webhook settings)",
           "a random string the person generates; it grants nothing but the handshake",
           ("providers/messenger/whatsapp-cloud.py",),
           store_username="messenger-whatsapp-cloud-verify-token"),
    Secret("MESSENGER_WHATSAPP_TWILIO_API_KEY_SID",
           "name the Restricted API key that sends the notices of the messaging bridge through Twilio's WhatsApp sender",
           "the SID (SK...) of a Restricted API key made for this bridge, with only the messaging permission (and the Content "
           "permission, if the console lists one) that Twilio's console offers; its name is copied from the console, not invented",
           ("providers/messenger/whatsapp-twilio.py",),
           store_username="messenger-whatsapp-twilio-api-key-sid"),
    Secret("MESSENGER_WHATSAPP_TWILIO_API_KEY_SECRET",
           "authenticate the sends of the messaging bridge through Twilio's Messages API, as the Restricted API key",
           "the secret of that Restricted API key, shown once when the key is created",
           ("providers/messenger/whatsapp-twilio.py",),
           store_username="messenger-whatsapp-twilio-api-key-secret"),
    Secret("MESSENGER_WHATSAPP_TWILIO_AUTH_TOKEN",
           "check X-Twilio-Signature on every webhook call Twilio makes to the bridge's local server",
           "the Twilio account's Auth Token; used only to compute an HMAC, never sent anywhere, never used to send",
           ("providers/messenger/whatsapp-twilio.py",),
           store_username="messenger-whatsapp-twilio-auth-token"),
    Secret("MAILER_SMTP_PASSWORD",
           "log in to the outbox mailbox of this machine to send the e-mails the person approved (SMTP), and to look for a sent message in its "
           "Sent folder (IMAP, read only)",
           "an app password (or the mailbox password where the host offers no app passwords) of a dedicated outbox account made for the "
           "runtime, never the person's own mailbox; the provider sends it only over TLS and never prints it",
           ("providers/mailer/smtp.py",),
           store_username="mailer-smtp"),
    Secret("MESSENGER_EMAIL_PASSWORD",
           "receive the person's messages (IMAP, read only) and send the cards of the messaging bridge (SMTP) through the dedicated mailbox of the "
           "e-mail channel",
           "an app password (or the mailbox password where the host offers no app passwords) of a mailbox made for the bridge, never the person's "
           "own; the provider sends it only over TLS and never prints it",
           ("providers/messenger/email-imap.py",),
           store_username="messenger-email"),
    Secret("OP_SERVICE_ACCOUNT_TOKEN",
           "let this resolver read the secrets mapped to 1Password on a machine with no desktop session (the manager's own sign-in)",
           "a 1Password service account with read access to only the vaults the mapping file names",
           ("providers/secrets/resolver.py",),
           store_username="password-manager-1password",
           note="found only in the environment, the credentials directory or the OS secret store, never through the manager, and it "
                "cannot be mapped; a provider the runtime starts does not get it from the environment (OP_* is stripped), so there only the "
                "credentials directory or the OS secret store works; on a laptop the desktop app's unlock is used and this is not needed"),
)}


class NotRegistered(KeyError):
    pass


ENTRY_REQUIRED = ("name", "purpose", "permission", "readers")
ENTRY_OPTIONAL = ("store_username", "aliases", "note", "set_local", "billing")
BILLING_WORDS = ("subscription", "metered", "free")
_NAME_OK = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"


def register(entries, origin: str = "a registry") -> list[str]:
    """Merge secrets registered outside the core (the "secrets" list of an adapter's manifest) into
    REGISTRY and return their names. An entry is a mapping with name, purpose, permission and
    readers, and optionally store_username, aliases, note and set_local. A name registered twice
    must agree on where it is looked up (store username and aliases); its readers are joined and
    the first purpose, permission and note stay. Anything else raises ValueError, before any entry
    is merged, so a malformed registry never leaves half of itself behind."""
    if not isinstance(entries, list):
        raise ValueError(f"{origin}: \"secrets\" must be a list")
    merged: dict[str, Secret] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"{origin}: every secret is an object")
        unknown = sorted(set(entry) - set(ENTRY_REQUIRED) - set(ENTRY_OPTIONAL))
        missing = [k for k in ENTRY_REQUIRED if not entry.get(k)]
        if unknown or missing:
            raise ValueError(f"{origin}: a secret has unknown keys {unknown} or lacks {missing}")
        name, readers, aliases = entry["name"], entry["readers"], entry.get("aliases") or []
        texts = [name, entry["purpose"], entry["permission"], *(entry.get(k) or "" for k in ENTRY_OPTIONAL if k != "aliases")]
        if not all(isinstance(t, str) for t in texts) or not all(
                isinstance(group, list) and all(isinstance(x, str) and x for x in group) for group in (readers, aliases)):
            raise ValueError(f"{origin}: {name!r} has a value of the wrong type")
        if not name or name[0].isdigit() or any(c not in _NAME_OK for c in name):
            raise ValueError(f"{origin}: {name!r} is not a variable name in capitals")
        if entry.get("billing") not in (None, *BILLING_WORDS):
            raise ValueError(f"{origin}: {name} has billing {entry.get('billing')!r}: one of {', '.join(BILLING_WORDS)}")
        new = Secret(name, entry["purpose"], entry["permission"], tuple(readers),
                     store_username=entry.get("store_username") or None, aliases=tuple(aliases),
                     note=entry.get("note") or "", set_local=entry.get("set_local") or "", billing=entry.get("billing") or "")
        old = merged.get(name) or REGISTRY.get(name)
        if old is not None:
            if (old.store_username, old.aliases) != (new.store_username, new.aliases):
                raise ValueError(f"{origin}: {name} is already registered with another store username or other aliases")
            if old.billing and new.billing and old.billing != new.billing:
                raise ValueError(f"{origin}: {name} is already registered with billing {old.billing}, not {new.billing}")
            new = Secret(old.name, old.purpose, old.permission,
                         old.readers + tuple(r for r in new.readers if r not in old.readers),
                         store_username=old.store_username, aliases=old.aliases, note=old.note, set_local=old.set_local,
                         billing=old.billing or new.billing)
        merged[name] = new
    REGISTRY.update(merged)
    return list(merged)


def register_file(path) -> list[str]:
    """Merge the "secrets" list of a JSON file (an adapter's manifest) into REGISTRY. A file with no
    such list registers nothing; a file that cannot be read or parsed raises ValueError."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise ValueError(f"{path}: cannot be read as JSON ({type(e).__name__})") from None
    if not isinstance(data, dict) or "secrets" not in data:
        return []
    return register(data["secrets"], origin=str(path))


def _from_env(secret: Secret, environ) -> tuple[str, str] | None:
    for name in (secret.name, *secret.aliases):
        value = (environ.get(name) or "").strip()
        if value:
            return value, f"environment ({name})"
    return None


def _keyring():
    try:
        import keyring  # imported lazily: only needed when the store is used
    except ImportError:
        return None
    return keyring


def store_available() -> bool:
    """True when the OS secret store can be asked at all, that is when the keyring library can be imported. False means a
    secret that is "not found" may only be one that was never looked for in the store (plain python3, no keyring library):
    callers say so instead of "missing". Read-only: it opens no store and reads no secret. It does not say whether the store
    is locked: see store_locked_note and resolve_state."""
    return _keyring() is not None


class StoreLocked(Exception):
    """The OS secret store raised instead of answering: locked (kind "locked") or unavailable (kind "unavailable": no backend,
    a daemon that is not running). Not "not found". The message holds no text of the underlying error."""

    def __init__(self, kind: str = "unavailable"):
        super().__init__(LOCKED_SENTENCE)
        self.kind = kind


class CredentialsUnsafe(Exception):
    """The credentials directory, or a file in it, is not safe to read; the message says which and how to fix it."""


_UNSAFE = {"detail": ""}    # the last credentials directory found unsafe in this process ("" when the last look found it fine or absent)
_FAILURE = {"kind": None, "sentence": ""}   # the last read of the store or the password manager: the kind of its failure ("locked", "unavailable" or, for the mapping file, "unsafe"), or None when it answered (found or not), and the sentence to show


def store_failure():
    """The kind ("locked" or "unavailable"; "unsafe" for the mapping file) of the failure of the last read of the OS secret store or of the
    password manager in this process, or None when the last read answered. Never a message of the backend."""
    return _FAILURE["kind"]


def unsafe_note() -> str:
    """The reason the last credentials directory this process looked at was refused (with the fix), or "". A caller that found a secret
    missing adds it first: a directory that is refused is not a secret that is absent."""
    return _UNSAFE["detail"]


def credentials_status(environ=None) -> dict:
    """The credentials directory as a whole, returning no value: {"state": "absent" | "ok" | "unsafe", "path", "detail"}. It checks
    the folder and the mode, owner and kind of each registered secret's file in it; the doctor and the runtime's messages ask it."""
    path = credentials_dir(environ)
    if path is None or not os.path.lexists(path):
        _UNSAFE["detail"] = ""
        return {"state": "absent", "path": path, "detail": "no credentials directory is set or present"}
    try:
        for secret in REGISTRY.values():
            _from_directory(secret, {"OPENHORA_CREDENTIALS_DIR": path})
    except CredentialsUnsafe as e:
        _UNSAFE["detail"] = str(e)
        return {"state": "unsafe", "path": path, "detail": str(e)}
    _UNSAFE["detail"] = ""   # the note follows the last look at the directory: one that reads fine clears it
    return {"state": "ok", "path": path, "detail": f"{path} is safe to read"}


def store_locked_note() -> str:
    """The sentence of the backend whose last read in this process failed (LOCKED_SENTENCE for the OS secret store, the manager's own
    sentence for the password manager, the reason for an unsafe mapping file), else "". A caller that found a secret missing adds it
    first, so that a locked store or manager is not reported as an absent secret."""
    return (_FAILURE["sentence"] or LOCKED_SENTENCE) if _FAILURE["kind"] else ""


def _ask(store, service: str, username: str) -> str:
    """The value the store holds, "" when it holds nothing there ("not found"). StoreLocked when the store raises instead of
    answering: that is not "not found"."""
    try:
        value = (store.get_password(service, username) or "").strip()
    except Exception as e:  # a locked or failing backend is told apart from an absent secret
        _FAILURE.update(kind="locked" if "locked" in type(e).__name__.lower() else "unavailable", sentence=LOCKED_SENTENCE)
        raise StoreLocked(_FAILURE["kind"]) from None
    _FAILURE.update(kind=None, sentence="")
    return value


def _from_store(secret: Secret, store) -> tuple[str, str, str] | None:
    """(value, "secret store", the service that answered): SERVICE first, then LEGACY_SERVICE. A service that raises does not stop
    the other from answering; StoreLocked when nothing was found and one of them raised (the secret may be in the one that could not
    be read)."""
    if not secret.store_username or store is None:
        return None
    failed = None
    for service, label in ((SERVICE, SERVICE), (LEGACY_SERVICE, LEGACY_LABEL)):
        try:
            value = _ask(store, service, secret.store_username)
        except StoreLocked as e:
            failed = failed or e
            continue
        if value:
            _FAILURE.update(kind=None, sentence="")
            return value, "secret store", label
    if failed is not None:
        _FAILURE.update(kind=failed.kind, sentence=LOCKED_SENTENCE)
        raise failed
    return None


def probe_store(store="default") -> dict:
    """Whether the OS secret store can be read at all, by asking it for a name nothing stores (it reads no secret):
    {"state": "ok" | "no-library" | "locked" | "unavailable", "detail"}. A store that is locked may ask the person to unlock it,
    as any read would."""
    store = _keyring() if store == "default" else store
    if store is None:
        return {"state": "no-library", "detail": "the keyring library is not available in this Python"}
    try:
        _ask(store, SERVICE, PROBE_USERNAME)
    except StoreLocked as e:
        return {"state": e.kind, "detail": LOCKED_SENTENCE}
    return {"state": "ok", "detail": "the store answered"}


def credentials_dir(environ=None) -> str | None:
    """The credentials directory: OPENHORA_CREDENTIALS_DIR, then CREDENTIALS_DIRECTORY, then ~/.config/openhora/credentials when it
    exists; None when none is set or there. It is not checked here: _from_directory refuses an unsafe one."""
    environ = os.environ if environ is None else environ
    for var in CREDENTIALS_DIR_VARS:
        value = (environ.get(var) or "").strip()
        if value:
            return value
    home = (environ.get("HOME") or "").strip()
    if home:
        path = os.path.join(home, *CREDENTIALS_DEFAULT)
        if os.path.isdir(path):
            return path
    return None


def _owned_private(info, what: str, wanted: str) -> None:
    """Refuse `what` (an open folder or file) unless this user or root owns it and group and others cannot write it; one this user owns
    must also be unreadable by group and others (`wanted` is the mode to give it). One root owns may be readable by others."""
    mode = stat.S_IMODE(info.st_mode)
    me = os.getuid() if hasattr(os, "getuid") else None
    if me is not None and info.st_uid not in (me, 0):
        raise CredentialsUnsafe(f"{what} is owned by neither this user nor root")
    if mode & 0o022:
        raise CredentialsUnsafe(f"{what} can be written by others (mode {mode:04o}): chmod {wanted}")
    if mode & 0o077 and (me is None or info.st_uid == me):
        raise CredentialsUnsafe(f"{what} can be read by others (mode {mode:04o}): chmod {wanted}")


def _from_directory(secret: Secret, environ) -> tuple[str, str] | None:
    """(value, "credentials directory") from the file named like the secret in the credentials directory, or None when there is no
    such directory or file. CredentialsUnsafe when the folder or the file is a link, not this user's, readable by others, not
    a regular file or too large: it is read with O_NOFOLLOW from the open descriptor of the folder."""
    path = credentials_dir(environ)
    if path is None:
        return None
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        if stat.S_ISLNK(os.lstat(path).st_mode):
            raise CredentialsUnsafe(f"the credentials directory {path} is a symbolic link: name the folder itself")
        dir_fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow)
    except FileNotFoundError:
        return None
    except CredentialsUnsafe:
        raise
    except OSError as e:
        raise CredentialsUnsafe(f"the credentials directory {path} cannot be opened: {e.strerror}") from None
    try:
        info = os.fstat(dir_fd)
        if not stat.S_ISDIR(info.st_mode):
            raise CredentialsUnsafe(f"{path} is not a folder")
        _owned_private(info, f"the credentials directory {path}", "700")
        try:
            file_fd = os.open(secret.name, os.O_RDONLY | nofollow | getattr(os, "O_NONBLOCK", 0), dir_fd=dir_fd)
        except FileNotFoundError:
            return None
        except OSError as e:
            raise CredentialsUnsafe(f"{secret.name} in the credentials directory cannot be read as a plain file: {e.strerror}") from None
        try:
            finfo = os.fstat(file_fd)
            if not stat.S_ISREG(finfo.st_mode):
                raise CredentialsUnsafe(f"{secret.name} in the credentials directory is not a regular file")
            _owned_private(finfo, f"{secret.name} in the credentials directory", "600")
            if finfo.st_size > CREDENTIAL_MAX_BYTES:
                raise CredentialsUnsafe(f"{secret.name} in the credentials directory is larger than {CREDENTIAL_MAX_BYTES} bytes")
            with os.fdopen(file_fd, "rb", closefd=False) as f:
                value = f.read(CREDENTIAL_MAX_BYTES + 1).decode("utf-8", errors="replace").strip()
        finally:
            os.close(file_fd)
    finally:
        os.close(dir_fd)
    return (value, "credentials directory") if value else None


class MappingUnsafe(Exception):
    """The password-manager mapping file is not safe to read or not valid; the message says why and how to fix it. No text of the file."""


@dataclass(frozen=True)
class Mapping:
    """The mapping file as read: the backend's word, the optional account, the deadline of a call and {NAME: reference}."""
    backend: str
    account: str
    timeout: int
    references: dict
    path: str


_MANAGERS = {"module": None}


def _managers():
    """providers/secrets/password_managers.py, loaded by path next to this file (the way secret_state loads this one). Raises
    ImportError when it cannot be: a resolver copied without its sibling then has no password manager, and says so."""
    if _MANAGERS["module"] is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "password_managers.py")
        if not os.path.isfile(path):
            raise ImportError("password_managers.py is not next to the resolver")
        spec = importlib.util.spec_from_file_location("workbench_password_managers", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        _MANAGERS["module"] = module
    return _MANAGERS["module"]


def mapping_path(environ=None) -> str | None:
    """$XDG_CONFIG_HOME/openhora/password-manager.json (an absolute XDG_CONFIG_HOME only, as the specification says), else
    $HOME/.config/openhora/password-manager.json; None when neither variable gives a folder."""
    environ = os.environ if environ is None else environ
    xdg = (environ.get("XDG_CONFIG_HOME") or "").strip()
    if xdg and os.path.isabs(xdg):
        return os.path.join(xdg, *MAPPING_FILE)
    home = (environ.get("HOME") or "").strip()
    return os.path.join(home, ".config", *MAPPING_FILE) if home else None


def _bad_mapping(path: str, why: str, fix: str = "") -> MappingUnsafe:
    return MappingUnsafe(f"the password-manager mapping {path} {why}" + (f": {fix}" if fix else ""))


def read_mapping(environ=None) -> Mapping | None:
    """The mapping file as a Mapping, or None when there is none (the password manager is then never asked). MappingUnsafe when the
    file is a link, not a regular file, not this user's (or root's), writable by others, readable by others when this user owns it,
    larger than CREDENTIAL_MAX_BYTES, not JSON, has a key or backend this module does not know, or a reference its backend refuses, or
    maps the backend's own token: a mapping someone else can write could point a name at another item. References are not secrets, but
    no value is read or printed here."""
    path = mapping_path(environ)
    if path is None or not os.path.lexists(path):
        return None
    try:
        if stat.S_ISLNK(os.lstat(path).st_mode):
            raise _bad_mapping(path, "is a symbolic link", "name the file itself")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except MappingUnsafe:
        raise
    except OSError as e:
        raise _bad_mapping(path, f"cannot be opened as a plain file ({e.strerror})") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise _bad_mapping(path, "is not a regular file")
        try:
            _owned_private(info, f"the password-manager mapping {path}", "600")
        except CredentialsUnsafe as e:
            raise MappingUnsafe(str(e)) from None
        if info.st_size > CREDENTIAL_MAX_BYTES:
            raise _bad_mapping(path, f"is larger than {CREDENTIAL_MAX_BYTES} bytes")
        with os.fdopen(fd, "rb", closefd=False) as f:
            raw = f.read(CREDENTIAL_MAX_BYTES + 1)
    finally:
        os.close(fd)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise _bad_mapping(path, "is not valid JSON", "fix the file") from None
    if not isinstance(data, dict):
        raise _bad_mapping(path, "must hold one JSON object")
    unknown = len(set(data) - set(MAPPING_KEYS))
    if unknown:   # counted, never listed: a key can be a value pasted in the wrong place
        raise _bad_mapping(path, f"has {unknown} key{'s' if unknown > 1 else ''} this resolver does not know", f"the keys are {', '.join(MAPPING_KEYS)}")
    try:
        managers = _managers()
    except ImportError:
        raise _bad_mapping(path, "cannot be used: the password-manager module is missing next to the resolver") from None
    word = data.get("backend")
    if not isinstance(word, str) or word not in managers.BACKENDS:
        raise _bad_mapping(path, "names a backend this resolver does not have", f"the backends are {', '.join(sorted(managers.BACKENDS))}")
    cls = managers.BACKENDS[word]
    account = data.get("account", "")
    if "account" in data and cls.account_problem(account):
        raise _bad_mapping(path, f"has an account that {cls.account_problem(account)}")
    low, high = managers.TIMEOUT_RANGE
    timeout = data.get("timeout_seconds", managers.DEFAULT_TIMEOUT)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not low <= timeout <= high:
        raise _bad_mapping(path, f"has a timeout_seconds that is not a whole number from {low} to {high}")
    references = data.get("references")
    if not isinstance(references, dict) or not references:
        raise _bad_mapping(path, 'needs a "references" object: {"NAME": "<reference>"}')
    for name, ref in references.items():
        if not name or name[0].isdigit() or any(c not in _NAME_OK for c in name):
            raise _bad_mapping(path, "maps a name that is not a secret name in capitals")
        if name == cls.token_name:
            raise _bad_mapping(path, f"maps {name}, the manager's own sign-in, which cannot be read through the manager",
                               f"remove it and provide {name} in the environment, the credentials directory or the OS secret store")
        if not cls.reference_ok(ref):
            raise _bad_mapping(path, f"has a reference for {name} that {cls.reference_problem(ref) or 'is not text'}", "fix the reference")
    return Mapping(word, account if isinstance(account, str) else "", timeout, dict(references), path)


@dataclass(frozen=True)
class Lookup:
    """The answer of resolve_state. state is "found" (value, source and, for the store, service are set), "missing" (nothing holds it),
    "locked" (the OS secret store raised: the secret may be stored, it cannot be read now; detail says what to do) or "unsafe" (the
    credentials directory, its file or the password-manager mapping file is not safe to read; detail says why). "locked" also covers a
    password manager that is locked, not signed in or not installed. `library` is False when the keyring library cannot be imported
    (a plain python3): a "missing" may then only be a store that was not asked. `backend` says which place answered or failed: None
    (the environment, the credentials directory, or nothing asked), "keyring" or "password-manager"."""
    state: str
    value: str = ""
    source: str | None = None
    service: str | None = None
    detail: str = ""
    library: bool = True
    backend: str | None = None


def _plain_lookup(secret: Secret, environ, store, ask_store: bool) -> str:
    """The value of a secret found in the environment, the credentials directory or (when asked) the OS secret store, or "". Never the
    password manager: this is how the manager's own sign-in token is found, so that the manager is never asked for the way to ask it.
    CredentialsUnsafe when the token's file is refused."""
    found = _from_env(secret, environ)
    if found:
        return found[0]
    in_dir = _from_directory(secret, environ)
    if in_dir:
        return in_dir[0]
    if ask_store and store is not None:
        try:
            hit = _from_store(secret, store)
        except StoreLocked:
            return ""
        return hit[0] if hit else ""
    return ""


def _from_manager(secret: Secret, environ, store, store_down: bool, failed: str = ""):
    """The password manager's answer for `secret`, as (Lookup, kind), or None when it is not to be asked: no mapping file, or the name is
    not in it. The Lookup is "found" (source "password manager (<backend>)", no reference), "missing" (the tool says the item or field
    does not exist), "locked" (kind "locked": not signed in, locked, the prompt dismissed, the deadline; kind "unavailable": the tool is
    not installed or answered something not recognised) or "unsafe" (the mapping file; kind "unsafe"). One call of the tool, no cache.
    `failed` is the sentence of an earlier failure of the manager in the same report: the tool is not asked again (each ask may prompt)."""
    try:
        mapping = read_mapping(environ)
    except MappingUnsafe as e:
        return Lookup("unsafe", detail=str(e), backend="password-manager"), "unsafe"
    if mapping is None or secret.name not in mapping.references:
        return None
    managers = _managers()
    backend = managers.BACKENDS[mapping.backend](account=mapping.account)
    if failed:
        return Lookup("locked", detail=failed, backend="password-manager"), "locked"
    if managers.in_container(environ):   # L39: a run never reaches a password manager; nothing is called
        return Lookup("locked", detail=backend.sentence("container"), backend="password-manager"), "unavailable"
    token = ""
    token_secret = REGISTRY.get(backend.token_name)
    if token_secret is not None:
        try:
            token = _plain_lookup(token_secret, environ, store, ask_store=not store_down)
        except CredentialsUnsafe as e:
            return Lookup("unsafe", detail=str(e), backend="password-manager"), "unsafe"
    env = managers.minimum_environment(environ, backend.token_name, token)
    result = backend.read(mapping.references[secret.name], env, mapping.timeout)
    if result.state == "found":
        return Lookup("found", result.value, f"{MANAGER_SOURCE} ({backend.name})", backend="password-manager"), None
    if result.state == "missing":
        return Lookup("missing", detail=f"check the reference of {secret.name} in the mapping file", backend="password-manager"), None
    return Lookup("locked", detail=backend.sentence(result.state), backend="password-manager"), result.state


def resolve_state(name: str, *, allow_store: bool = True, environ=None, store="default", manager_failed: str = "") -> Lookup:
    """The full answer for a registered secret, in order: the environment, the credentials directory, the OS secret store, then the
    password manager for a name the mapping file maps. Unlike resolve and resolve_detail, which read a locked store as None, this one says
    "locked". When the store is locked and the manager finds the secret it is found; when the store is locked and the manager does not,
    the store's sentence comes first; when the store answers nothing and the manager is locked, the manager's sentence is told.
    `manager_failed` (a sentence) stops the manager from being asked again after it failed in the same report. Never prints the value."""
    secret = REGISTRY.get(name)
    if secret is None:
        raise NotRegistered(name)
    environ = os.environ if environ is None else environ
    found = _from_env(secret, environ)
    if found:
        return Lookup("found", found[0], found[1])
    try:
        in_dir = _from_directory(secret, environ)
    except CredentialsUnsafe as e:
        _UNSAFE["detail"] = str(e)
        return Lookup("unsafe", detail=str(e))
    _UNSAFE["detail"] = ""
    if in_dir:
        return Lookup("found", in_dir[0], in_dir[1])
    if not allow_store:
        return Lookup("missing")
    store = _keyring() if store == "default" else store
    store_error = None
    try:
        hit = _from_store(secret, store)
    except StoreLocked as e:
        hit, store_error = None, e
    if hit:
        return Lookup("found", hit[0], hit[1], hit[2], backend="keyring")
    stored = dict(_FAILURE)   # what the store left: the manager's lookup does not erase it when the store's sentence stands
    managed = _from_manager(secret, environ, store, store_error is not None, manager_failed)
    if managed is not None:
        answer, kind = managed
        if answer.state == "found":
            _FAILURE.update(kind=None, sentence="")
            return answer
        if store_error is None:
            if kind:
                _FAILURE.update(kind=kind, sentence=answer.detail)
            return replace(answer, library=store is not None)
        _FAILURE.update(stored)
    if store_error is not None:
        return Lookup("locked", detail=str(store_error), library=True, backend="keyring")
    return Lookup("missing", library=store is not None)


def manager_applies(names, environ=None) -> bool:
    """Whether the password manager could hold one of `names` (secret names, or the runtime's own `WB_RUNTIME_KEY_<name>` forms), or
    whether its mapping file is refused (then it stands in the way of every lookup). False when there is no mapping file, or none of the
    names is in it: a caller that wants to say why a key cannot be read asks this first, so it never blames a manager that cannot hold
    the key. No tool is called."""
    try:
        mapping = read_mapping(environ)
    except MappingUnsafe:
        return True
    if mapping is None:
        return False
    wanted = {n for name in (names or ()) for n in (name, f"WB_RUNTIME_KEY_{name}")}
    return bool(wanted & set(mapping.references))


def probe_manager(environ=None) -> dict:
    """Whether the password manager can be used at all, with no secret read ('op whoami'): {"state": "na" | "ok" | "locked" |
    "unavailable" | "unsafe", "detail"}. "na": there is no mapping file, so the manager is never asked. "unsafe": the mapping file is
    refused. Asked as any read would be: a locked app may prompt the person. Never a text of the tool."""
    environ = os.environ if environ is None else environ
    try:
        mapping = read_mapping(environ)
    except MappingUnsafe as e:
        return {"state": "unsafe", "detail": str(e)}
    if mapping is None:
        return {"state": "na", "detail": "there is no password-manager mapping file, so the manager is not asked"}
    managers = _managers()
    backend = managers.BACKENDS[mapping.backend](account=mapping.account)
    if managers.in_container(environ):
        return {"state": "unavailable", "detail": backend.sentence("container")}
    token = ""
    token_secret = REGISTRY.get(backend.token_name)
    if token_secret is not None:
        try:
            token = _plain_lookup(token_secret, environ, _keyring(), ask_store=True)
        except CredentialsUnsafe as e:
            return {"state": "unsafe", "detail": str(e)}
    result = backend.probe(managers.minimum_environment(environ, backend.token_name, token), managers.PROBE_TIMEOUT)
    if result.state == "found":
        return {"state": "ok", "detail": f"the password manager ({backend.label}) answered"}
    return {"state": result.state, "detail": backend.sentence(result.state)}


def resolve_detail(name: str, *, allow_store: bool = True, environ=None, store="default") -> tuple[str, str, str | None] | None:
    """Return (value, source, service) for a registered secret, or None. The service is None for the environment and the credentials
    directory, and for the store "openhora" or "ai-workbench (legacy)". A locked store, an unsafe credentials directory and an absent
    secret are all None here: resolve_state tells them apart (and store_failure / store_locked_note say whether the last read of the
    store failed). Never prints the value."""
    got = resolve_state(name, allow_store=allow_store, environ=environ, store=store)
    return (got.value, got.source, got.service) if got.state == "found" else None


def resolve(name: str, *, allow_store: bool = True, environ=None, store="default") -> tuple[str, str] | None:
    """Return (value, source) for a registered secret, or None. Never prints the value."""
    found = resolve_detail(name, allow_store=allow_store, environ=environ, store=store)
    return None if found is None else (found[0], found[1])


def how_to_set(secret: Secret) -> str:
    local = secret.set_local or (f"uv run --with keyring==25.7.0 keyring set {SERVICE} {secret.store_username}"
                                 if secret.store_username else f"export {secret.name}=...")
    return f"cloud or CI: environment variable {secret.name}; local: {local}"


def report(environ=None, store="default") -> list[dict]:
    """One row for each registered secret: whether it is found and where, and "state" (found, missing, locked or unsafe). Once the
    store has raised, it is not asked again for the other secrets of the report (each ask may prompt the person to unlock it):
    those not found elsewhere are "locked". The password manager is treated the same way: once it has failed, the other names the
    mapping maps are "locked" with its sentence and the tool is not called again. A name found earlier that the mapping also maps
    is marked "also_mapped" (the manager is not asked for it)."""
    environ = os.environ if environ is None else environ
    store = _keyring() if store == "default" else store
    try:
        mapped = set((read_mapping(environ) or Mapping("", "", 0, {}, "")).references)
    except MappingUnsafe:
        mapped = set()
    rows, locked, manager_said = [], False, ""
    for secret in REGISTRY.values():
        got = resolve_state(secret.name, environ=environ, store=None if locked else store, manager_failed=manager_said)
        if got.state == "missing" and locked and secret.store_username:
            got = Lookup("locked", detail=LOCKED_SENTENCE, backend="keyring")
        locked = locked or (got.state == "locked" and got.backend != "password-manager")
        if got.state == "locked" and got.backend == "password-manager" and not manager_said:
            manager_said = got.detail
        rows.append({
            "name": secret.name,
            "found": got.state == "found",
            "state": got.state,
            "source": got.source if got.state == "found" else None,
            "service": got.service,
            "backend": got.backend,
            "also_mapped": got.state == "found" and got.backend != "password-manager" and secret.name in mapped,
            "store": "unavailable" if store is None else ("locked" if locked else "available"),
            "detail": got.detail,
            "purpose": secret.purpose,
            "permission": secret.permission,
            "readers": list(secret.readers),
            "set": how_to_set(secret),
            "note": secret.note,
        })
    return rows


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("--help", "-h"):
        print(__doc__)
        return 0 if argv else EXIT_USAGE
    while argv and argv[0] == "--registry":
        if len(argv) < 2:
            print("error: --registry needs a file; see --help", file=sys.stderr)
            return EXIT_USAGE
        try:
            register_file(argv[1])
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return EXIT_USAGE
        argv = argv[2:]
    if not argv:
        print("error: --registry goes with --list or --check; see --help", file=sys.stderr)
        return EXIT_USAGE
    if argv[0] == "--list" and len(argv) <= 2 and (len(argv) == 1 or argv[1] == "--json"):
        rows = report()
        if "--json" in argv:
            print(json.dumps(rows, indent=2))
        else:
            for r in rows:
                state = (f"found ({r['source']}" + (f", {r['service']}" if r["service"] else "") + ")") if r["found"] else (
                    r["state"] if r["state"] in ("locked", "unsafe") else "missing")
                print(f"{r['name']:<24} {state:<34} {r['purpose']}")
                if r["found"] and r["also_mapped"]:
                    print(f"{'':<24} {ALSO_MAPPED}")
                elif r["state"] == "locked":
                    print(f"{'':<24} {r['detail'] or LOCKED_SENTENCE}")
                elif r["state"] == "unsafe":
                    print(f"{'':<24} {r['detail']}")
                elif not r["found"]:
                    print(f"{'':<24} " + (f"{r['detail']}; " if r["detail"] else "") + f"set it: {r['set']}")
        return 0
    if argv[0] == "--check" and len(argv) == 2:
        try:
            found = resolve_state(argv[1])
        except NotRegistered:
            print(f"error: {argv[1]!r} is not a registered secret; see --list", file=sys.stderr)
            return EXIT_USAGE
        if found.state == "found":
            out = {"name": argv[1], "found": True, "source": found.source}
            if found.service:
                out["service"] = found.service
            if found.backend == "password-manager":
                out["backend"] = found.backend
            print(json.dumps(out))
            return 0
        if found.state in ("locked", "unsafe"):
            print(f"{argv[1]} cannot be read: {found.detail}", file=sys.stderr)
            return EXIT_LOCKED
        print(f"{argv[1]} not found: {how_to_set(REGISTRY[argv[1]])}" + (f" ({found.detail})" if found.detail else ""), file=sys.stderr)
        return EXIT_NOT_FOUND
    print("error: unknown arguments; see --help", file=sys.stderr)
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
