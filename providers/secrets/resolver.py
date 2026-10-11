#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["keyring==25.7.0"]
# ///
"""One way to find the workbench's secrets, the same on a laptop, in a cloud session and in CI.

Every script asks for a secret by name; the resolver looks in the same places, in the same order:
  1. environment variables: the name, then its aliases (a cloud environment's settings, CI secrets,
     or an export in the shell);
  2. the OS secret store (keyring): service "openhora", the username listed below; a name not found
     there is looked up under the service the workbench used before it was renamed, "ai-workbench"
     (LEGACY_SERVICE), for one stage (removed with the next change of reference model, T23).
The first non-empty value wins. Values are never printed, logged or written, not even partially.
Adding a backend (a password manager) means adding one lookup function to BACKENDS; callers do
not change.

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
  --check     exit 0 when <NAME> is found, 3 when not, 2 when <NAME> is not registered; the line
              printed carries "service" when the store answered
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

Without the keyring package (plain python3), the store is reported as unavailable and only the
environment is read. Exit codes: 0 ok, 2 usage error, 3 not found.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field

SERVICE = "openhora"
LEGACY_SERVICE = "ai-workbench"  # T23: what the store held before the rename; read as a fallback, never written
LEGACY_LABEL = f"{LEGACY_SERVICE} (legacy)"
EXIT_USAGE = 2
EXIT_NOT_FOUND = 3


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
    Secret("MESSENGER_TELEGRAM_BOT_TOKEN",
           "receive the person's messages and send the notices of the messaging bridge, as a Telegram bot",
           "a bot created for this person with the platform's bot service, used only by this bridge",
           ("providers/messenger/telegram.py",),
           store_username="messenger-telegram"),
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


def _ask(store, service: str, username: str) -> str:
    try:
        return (store.get_password(service, username) or "").strip()
    except Exception:  # a locked or missing backend is "not found here", never a crash
        return ""


def _from_store(secret: Secret, store) -> tuple[str, str, str] | None:
    """(value, "secret store", the service that answered): SERVICE first, then LEGACY_SERVICE."""
    if not secret.store_username or store is None:
        return None
    value = _ask(store, SERVICE, secret.store_username)
    if value:
        return value, "secret store", SERVICE
    value = _ask(store, LEGACY_SERVICE, secret.store_username)
    return (value, "secret store", LEGACY_LABEL) if value else None


def resolve_detail(name: str, *, allow_store: bool = True, environ=None, store="default") -> tuple[str, str, str | None] | None:
    """Return (value, source, service) for a registered secret, or None. The service is None for the
    environment, and for the store "openhora" or "ai-workbench (legacy)". Never prints the value."""
    secret = REGISTRY.get(name)
    if secret is None:
        raise NotRegistered(name)
    environ = os.environ if environ is None else environ
    found = _from_env(secret, environ)
    if found:
        return found[0], found[1], None
    if not allow_store:
        return None
    return _from_store(secret, _keyring() if store == "default" else store)


def resolve(name: str, *, allow_store: bool = True, environ=None, store="default") -> tuple[str, str] | None:
    """Return (value, source) for a registered secret, or None. Never prints the value."""
    found = resolve_detail(name, allow_store=allow_store, environ=environ, store=store)
    return None if found is None else (found[0], found[1])


def how_to_set(secret: Secret) -> str:
    local = secret.set_local or (f"uv run --with keyring==25.7.0 keyring set {SERVICE} {secret.store_username}"
                                 if secret.store_username else f"export {secret.name}=...")
    return f"cloud or CI: environment variable {secret.name}; local: {local}"


def report(environ=None, store="default") -> list[dict]:
    environ = os.environ if environ is None else environ
    store = _keyring() if store == "default" else store
    rows = []
    for secret in REGISTRY.values():
        env_hit = _from_env(secret, environ)
        store_hit = None if env_hit else _from_store(secret, store)
        rows.append({
            "name": secret.name,
            "found": bool(env_hit or store_hit),
            "source": (env_hit or store_hit or (None, None))[1],
            "service": store_hit[2] if store_hit else None,
            "store": "unavailable" if store is None else "available",
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
                state = (f"found ({r['source']}" + (f", {r['service']}" if r["service"] else "") + ")") if r["found"] else "missing"
                print(f"{r['name']:<24} {state:<34} {r['purpose']}")
                if not r["found"]:
                    print(f"{'':<24} set it: {r['set']}")
        return 0
    if argv[0] == "--check" and len(argv) == 2:
        try:
            found = resolve_detail(argv[1])
        except NotRegistered:
            print(f"error: {argv[1]!r} is not a registered secret; see --list", file=sys.stderr)
            return EXIT_USAGE
        if found:
            out = {"name": argv[1], "found": True, "source": found[1]}
            if found[2]:
                out["service"] = found[2]
            print(json.dumps(out))
            return 0
        print(f"{argv[1]} not found: {how_to_set(REGISTRY[argv[1]])}", file=sys.stderr)
        return EXIT_NOT_FOUND
    print("error: unknown arguments; see --help", file=sys.stderr)
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
