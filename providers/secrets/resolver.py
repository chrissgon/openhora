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
     (LEGACY_SERVICE), for one stage (removed with the next change of the lab models, T23).
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
exists. It is read, never written, with checks that refuse an unsafe one (state "unsafe", and the reason): the
folder and each file must be this user's and not readable by anyone else (folder 0700, file 0600 or 0400),
neither may be a symbolic link, and a file is at most 64 KiB.

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
              credentials directory is unsafe (the answer is not "missing"), 2 when <NAME> is not
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

Without the keyring package (plain python3), the store is reported as unavailable and only the
environment is read. Exit codes: 0 ok, 2 usage error, 3 not found, 4 the store is locked or unavailable.
"""
from __future__ import annotations

import json
import os
import stat
import sys
from dataclasses import dataclass, field

SERVICE = "openhora"
LEGACY_SERVICE = "ai-workbench"  # T23: what the store held before the rename; read as a fallback, never written
LEGACY_LABEL = f"{LEGACY_SERVICE} (legacy)"
EXIT_USAGE = 2
EXIT_NOT_FOUND = 3
EXIT_LOCKED = 4
CREDENTIALS_DIR_VARS = ("OPENHORA_CREDENTIALS_DIR", "CREDENTIALS_DIRECTORY")   # looked at in this order
CREDENTIALS_DEFAULT = (".config", "openhora", "credentials")                  # under the home folder, used only when it exists
CREDENTIAL_MAX_BYTES = 64 * 1024
PROBE_USERNAME = "__store-probe__"                                            # a name nothing stores: asking for it reads no secret
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


_FAILURE = {"kind": None}   # the last read of the store: the kind of its failure, or None when it answered (found or not)


def store_failure():
    """The kind ("locked" or "unavailable") of the failure of the last read of the OS secret store in this process, or None
    when the last read answered. Never a message of the backend."""
    return _FAILURE["kind"]


def store_locked_note() -> str:
    """LOCKED_SENTENCE when the last read of the OS secret store in this process failed, else "". A caller that found a secret
    missing adds it first, so that a locked store is not reported as an absent secret."""
    return LOCKED_SENTENCE if _FAILURE["kind"] else ""


def _ask(store, service: str, username: str) -> str:
    """The value the store holds, "" when it holds nothing there ("not found"). StoreLocked when the store raises instead of
    answering: that is not "not found"."""
    try:
        value = (store.get_password(service, username) or "").strip()
    except Exception as e:  # a locked or failing backend is told apart from an absent secret
        _FAILURE["kind"] = "locked" if "locked" in type(e).__name__.lower() else "unavailable"
        raise StoreLocked(_FAILURE["kind"]) from None
    _FAILURE["kind"] = None
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
            _FAILURE["kind"] = None
            return value, "secret store", label
    if failed is not None:
        _FAILURE["kind"] = failed.kind
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
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise CredentialsUnsafe(f"{what} is not owned by this user")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise CredentialsUnsafe(f"{what} can be read by others (mode {stat.S_IMODE(info.st_mode):04o}): chmod {wanted}")


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


@dataclass(frozen=True)
class Lookup:
    """The answer of resolve_state. state is "found" (value, source and, for the store, service are set), "missing" (nothing holds it),
    "locked" (the OS secret store raised: the secret may be stored, it cannot be read now; detail says what to do) or "unsafe" (the
    credentials directory, or its file, is not safe to read; detail says why). `library` is False when the keyring library cannot be
    imported (a plain python3): a "missing" may then only be a store that was not asked."""
    state: str
    value: str = ""
    source: str | None = None
    service: str | None = None
    detail: str = ""
    library: bool = True


def resolve_state(name: str, *, allow_store: bool = True, environ=None, store="default") -> Lookup:
    """The full answer for a registered secret, in order: the environment, the credentials directory, the OS secret store. Unlike
    resolve and resolve_detail, which read a locked store as None, this one says "locked". Never prints the value."""
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
        return Lookup("unsafe", detail=str(e))
    if in_dir:
        return Lookup("found", in_dir[0], in_dir[1])
    if not allow_store:
        return Lookup("missing")
    store = _keyring() if store == "default" else store
    try:
        hit = _from_store(secret, store)
    except StoreLocked as e:
        return Lookup("locked", detail=str(e), library=True)
    if hit:
        return Lookup("found", hit[0], hit[1], hit[2])
    return Lookup("missing", library=store is not None)


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
    those not found elsewhere are "locked"."""
    environ = os.environ if environ is None else environ
    store = _keyring() if store == "default" else store
    rows, locked = [], False
    for secret in REGISTRY.values():
        got = resolve_state(secret.name, environ=environ, store=None if locked else store)
        if got.state == "missing" and locked and secret.store_username:
            got = Lookup("locked", detail=LOCKED_SENTENCE)
        locked = locked or got.state == "locked"
        rows.append({
            "name": secret.name,
            "found": got.state == "found",
            "state": got.state,
            "source": got.source if got.state == "found" else None,
            "service": got.service,
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
                if r["state"] == "locked":
                    print(f"{'':<24} {LOCKED_SENTENCE}")
                elif r["state"] == "unsafe":
                    print(f"{'':<24} {r['detail']}")
                elif not r["found"]:
                    print(f"{'':<24} set it: {r['set']}")
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
            print(json.dumps(out))
            return 0
        if found.state in ("locked", "unsafe"):
            print(f"{argv[1]} cannot be read: {found.detail}", file=sys.stderr)
            return EXIT_LOCKED
        print(f"{argv[1]} not found: {how_to_set(REGISTRY[argv[1]])}", file=sys.stderr)
        return EXIT_NOT_FOUND
    print("error: unknown arguments; see --help", file=sys.stderr)
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
