# Account tokens: one consent per account

This folder holds the authorization commands of the person's own accounts. It is not a class folder: `providers/resolve.py` never lists it, and a file whose name has an underscore is never an implementation. The readers and, in later packages, the writers of an account all sign in with the one token these commands make.

The decision (maintainer, 2026-10-18): the secretary manages everything the person has, so it asks each account for everything once, and **the restriction is inside the platform, not in a narrower token**. A token that read only would need another for every write, and a thousand registrations with different limits would be a thousand things to keep right. So there is one OAuth client per provider, one consent and one refresh token per account, with the platform's whole scope set. What stops misuse is code:

| Layer | What restricts |
|---|---|
| The account | One client, one consent, the platform's set; a token with fewer or more scopes is refused (exit 3) |
| The process | Only a provider process the runtime starts, with that one secret in its environment, reads the token; never a run, a prompt, a manifest, a card, a log or the store (limit L59) |
| The verb | Each provider script exposes only the verbs its job needs. The readers send GET only; a test fails on any other method (the readers' part of limit L58). No script holds a permanent-delete call |
| The content | Every write, in later packages, is an effect whose hash the person approves |
| The person and the channel | Policies and grants say who may ask and who may approve, and where |

The token itself can do everything its scopes allow, and that is accepted. **Revoking the app's access in the Google Account is the one switch that stops every reader and writer of that account at once** (every provider then exits 3, naming the authorize command).

## Google

```
uv run <workbench>/providers/accounts/google_auth.py authorize [--account main] [--no-browser]
uv run <workbench>/providers/accounts/google_auth.py check     [--account main]
uv run <workbench>/providers/accounts/google_auth.py forget    [--account main]
```

`authorize` asks for exactly four scopes, with PKCE (S256), a random state checked on the callback, `access_type=offline` and `prompt=consent`, on a one-shot listener on 127.0.0.1. The client id and secret come from `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in the environment of that one command, or at a hidden prompt; never a flag, never a file. A consent that does not grant exactly the four (one box unticked, or a wider scope such as `https://mail.google.com/`) stores nothing and exits 3 naming the command. The address of the account is read once from the Gmail profile and kept in the record. `check` reads the record the way the providers do and says whether its scope is the set; it calls nobody. `forget` removes the record; it does not tell Google and it never touches the old records.

| Scope | What Google says it grants | Class | What the platform uses it for |
|---|---|---|---|
| `https://www.googleapis.com/auth/gmail.modify` | "Read, compose, and send emails from your Gmail account"; it "does not allow immediate, permanent deletion of threads and messages, bypassing the trash" | Restricted | Reading messages (the Gmail reader today); in later packages drafts, sending, labels and the trash |
| `https://www.googleapis.com/auth/calendar.events` | "View and edit events on all your calendars" (it also lets a client delete an event) | not stated on Google's pages (to verify in the console) | Reading events (the Calendar reader today); in later packages creating, changing and removing an event |
| `https://www.googleapis.com/auth/calendar.calendarlist.readonly` | "See the list of Google calendars you're subscribed to" | not stated (to verify) | The reader's `calendars` verb (`calendar.events` does not cover the calendar list) |
| `https://www.googleapis.com/auth/drive` | "View and manage all your Drive files" (it also lets a client delete files permanently and empty the trash) | Restricted | Reading any file the person names (the Drive reader today); in later packages new files and new revisions |

**What the scopes allow and what prevents it.** Said plainly: `drive` can also delete Drive files permanently and empty the trash, and `calendar.events` can delete events: the scopes allow it, and what prevents it is code (limit L57 and the writers' allow-lists, no script holds such a call), not the scope. Only `gmail.modify` is limited by Google itself (it "does not allow immediate, permanent deletion"). The platform's promise "nothing is deleted permanently" (limit L57) is therefore kept by the verbs each script exposes and by static tests, never by the token.

The pair `calendar.events` and `calendar.calendarlist.readonly` is used in place of the full `https://www.googleapis.com/auth/calendar`, whose text is "See, edit, share, and permanently delete all the calendars you can access": nothing the platform does needs sharing or deleting whole calendars, which is the same reasoning that prefers `gmail.modify` to `https://mail.google.com/`. If the maintainer prefers the full scope it is one constant in `providers/_google.py` (and the set the stand-in service grants in the tests).

The words `openid`, `email` and `profile` (and the two `userinfo` forms Google returns for them) grant no access to mail, calendars or files and are ignored by the check. Any other scope beyond the four is refused.

### The record

One JSON record in the secret `GOOGLE_ACCOUNT_TOKEN` (OS secret store: service `openhora`, username `google-account`; or the same JSON text in the environment or the credentials directory, `docs/architecture/platform/unattended.md`):

```
{"slot": "main", "refresh_token": ..., "client_id": ..., "client_secret": ..., "scope": "<the four, space separated>", "account": "<address>", "obtained_at": "<UTC time>"}
```

The Desktop app client travels with the token, so this is the only entry (the pattern of the Drive and Calendar records before it): `GMAIL_CLIENT_ID` and `GMAIL_CLIENT_SECRET` are not needed by the account path. The `slot` is always `main` in this version. A second account later would take the rows `GOOGLE_ACCOUNT_<S>_TOKEN` and `google-account-<s>` (a registry row added by a person's change, never at run time) and a `--account <slot>` on every provider (the authorize command takes it already; the providers do not yet); nothing about the record would move (backlog ACCT-SLOT, not built).

### What each provider checks

Every authorization and every refresh is checked: the response's `scope` must be exactly the four (plus the ignored words). A refresh response that omits `scope` (Google may) is accepted only when the record's stored scope is the four; otherwise it is refused, because a response that names no scope cannot be shown to be the right one on its own. A token that lacks a scope exits 3 with "the account token lacks <scope>: run <authorize command> and keep every box ticked"; one that carries another exits 3 with "the account token carries <scope>, which the platform does not ask: revoke the app's access in your Google Account and run <authorize command>". Nothing is read with a token that fails the check, and no credential is in any message (every credential the process held is replaced by `<hidden>` before it is printed).

### Setup in Google Cloud (once)

1. In the project of your Gmail client, enable the Gmail API, the Google Calendar API and the Google Drive API.
2. Google Auth Platform, Data Access: the four scopes above. Keep the old scopes listed until the legacy records are gone.
3. Audience: **In production**. In "Testing", Google expires a refresh token after seven days. Do not submit the app for verification: an app for personal use with fewer than 100 users may be used unverified, and the consent screen asks you to click through "Google hasn't verified this app" (Advanced, go to the app). The 100 users are counted after the unverified-app screen is presented.
4. `uv run <workbench>/providers/accounts/google_auth.py authorize`, signed in with the account to connect, every box ticked; then `check`.

Other ways a refresh token stops working: access removed in the account's third-party access page, a password change (a token with Gmail scopes), six months without use, and more than 100 refresh tokens for one account and one client (the oldest stops; one record per account instead of three lowers the count).

### Later: the hosted product

A public app that asks for restricted scopes (`gmail.modify`, `drive`) needs Google's restricted-scope verification, and one that stores or transmits the data of restricted scopes on servers needs a security assessment, renewed at least every 12 months. Personal use, development, internal Workspace use and service accounts are exceptions. This is not a blocker now and is recorded as backlog HOSTED-VERIFY.

### The legacy records, for one cycle

Each Google reader reads the account record first and, when it is absent, its old record with its old exact scope rule: `GMAIL_REFRESH_TOKEN` with `GMAIL_CLIENT_ID` and `GMAIL_CLIENT_SECRET` (username `mailbox-gmail`, `gmail-client-id`, `gmail-client-secret`; scope `gmail.readonly`), `GOOGLE_CALENDAR_TOKEN` (`calendar-google`; the two read scopes), `GDRIVE_SOURCES_TOKEN` (`gdrive-sources`; `drive.file`). A reader that used a legacy record prints on stderr, once per process, "using the legacy record <username>; run <authorize command> to move to the account token". An account record that exists but is unreadable is an error, never a reason to fall back. The old `*_auth.py authorize` commands still work, unchanged. The Drive Picker (`gdrive_auth.py pick`) keeps the legacy record until then: it needs that record's Picker key and reads it explicitly. With only the account record, `pick` says the Picker is not needed, because under `drive` any file id the person names is readable: register it with `python3 runtime/cli.py source-drive --project <dir> --file-id <Drive file id> --source <id>`.

The fallback, the old authorize commands and, with the full `drive` scope, the Picker (`providers/documents/gdrive_picker.py`, `gdrive_auth.py pick`, `gdrive.py pick`, the `api_key` and `project_number` of the legacy record, and the rule "a folder is not a source" as the scope's doing) are removed in the cycle after the integration branch reaches `main` (backlog ACCT-LEGACY). The old records are never deleted by code. Once `check` passes and each reader has worked with the account record, remove the first four yourself, one command each. **Keep `gdrive-sources` until ACCT-LEGACY has removed the Picker**: the Picker needs it, and nothing else does once the account record works.

```
uv run --with keyring==25.7.0 keyring del openhora mailbox-gmail
uv run --with keyring==25.7.0 keyring del openhora gmail-client-id
uv run --with keyring==25.7.0 keyring del openhora gmail-client-secret
uv run --with keyring==25.7.0 keyring del openhora calendar-google
```

After ACCT-LEGACY: `uv run --with keyring==25.7.0 keyring del openhora gdrive-sources`.

### Tests

`uv run --with pytest==9.1.1 pytest -q providers/accounts/tests`, against `fake_google_account.py` (one stand-in for the token endpoint, the Gmail profile and messages, the Calendar list and events and the Drive file and export, on 127.0.0.1; it records every request and answers 405 to any method other than GET and the token POST). The suite runs on Python 3.9 too. The runtime's part of limit L59 is `runtime/tests/test_account_token_limit.py`.

## Microsoft

```
uv run <workbench>/providers/accounts/microsoft_auth.py authorize [--account main] [--no-browser]
uv run <workbench>/providers/accounts/microsoft_auth.py check     [--account main]
uv run <workbench>/providers/accounts/microsoft_auth.py forget    [--account main]
```

`--help` carries the Entra steps and the exit codes. The client id is read from `MICROSOFT_CLIENT_ID` in the environment of the command (or typed at a hidden prompt on a terminal), never from a flag; an office with its own single-tenant registration also sets `MICROSOFT_TENANT` (default `common`).

### One registration, six permissions

One app registration in the maintainer's Entra directory: supported account types "Any Entra ID Tenant + Personal Microsoft accounts", platform "Mobile and desktop applications" with the redirect `http://localhost` (the port is ignored for `localhost`), **a public client with no client secret**. Delegated permissions on Microsoft Graph, and nothing else:

| Permission | What Microsoft says it grants | Admin consent | What the platform uses it for |
|---|---|---|---|
| `Mail.ReadWrite` | "create, read, update, and delete email in user mailboxes. Does not include permission to send mail" | no; available for consent in personal Microsoft accounts | the mail reader today; drafts, replies, moves and read state later |
| `Mail.Send` | "send mail as users in the organization" | no | sending from the person's own address, later |
| `Calendars.ReadWrite` | "create, read, update, and delete events in user calendars" | no | the calendar reader today; events later |
| `Files.ReadWrite` | "read, create, update and delete the signed-in user's files"; on personal accounts it also reaches files shared with the user | no | the OneDrive reader today; new files and revisions later |
| `User.Read` | sign in and read the user's profile | no | `GET /me` once, at authorization, for the account's address |
| `offline_access` | grants no access to a resource; asks for a refresh token | no | the refresh token |

Sources (Microsoft's own pages, accessed 2026-10-18 by the research pass of the plan; the wording of `User.Read` is to verify): the permissions reference https://learn.microsoft.com/en-us/graph/permissions-reference ; refresh tokens https://learn.microsoft.com/en-us/entra/identity-platform/refresh-tokens . `Files.ReadWrite` is used and not `Files.ReadWrite.All`: on a personal account the first already reaches the person's own files and the files shared with them, and `.All` adds nothing this platform uses.

The code's constant is `PLATFORM_SCOPES` in `providers/_msgraph.py`. **A token whose granted set (the authorization's and every refresh's), without `openid`, `email`, `profile` and `offline_access`, is not exactly that set is refused** with exit 3: a missing permission ("the account token lacks <permission>: run the authorize command and keep every box ticked"), or an extra one ("the account token carries <permission>, which the platform does not ask: remove it from the registration, revoke the app's access, and run the authorize command"). An authorization that returns a wrong set stores nothing.

### Personal accounts and work accounts

None of the six needs an admin's consent on a personal account, and the consent screen lists them once. A work or school tenant may block user consent by its own policy; the command then stops with exit 3 and the sentence "your Microsoft 365 admin must approve the app". A personal account (outlook.com, hotmail.com) cannot register an app without a directory of its own; `microsoft_auth.py --help` says how to get a free one.

### The record

Secret `MICROSOFT_ACCOUNT_TOKEN` (registry in `providers/secrets/resolver.py`, table in `contracts/secrets.md`), store username `microsoft-account`, service `openhora`; one JSON record:

```
{"slot": "main", "refresh_token": "...", "client_id": "...", "tenant": "common",
 "scope": "Mail.ReadWrite Mail.Send Calendars.ReadWrite Files.ReadWrite User.Read",
 "account_kind": "personal", "account": "<the address>", "obtained_at": "<UTC>"}
```

The address is read once with `GET /me` (`mail`, else `userPrincipalName`); an authorization that cannot read it stores nothing (exit 1). `account_kind` comes from one more read, `GET /me/drive`; a failure there is a note and the kind is stored as `unknown`. The record carries a `slot` so that a second account can be added later without moving this one; only `main` exists, and `--account` with another word is refused (exit 2). A record without a `slot` is never the account's.

`check` reads the record back through the resolver (the environment, the credentials directory, then the OS secret store), checks it was made for the platform's set, and prints `{"found", "source", "slot", "account", "account_kind", "tenant", "scopes", "has_refresh_token", "obtained_at"}`: **no network call and no token**. `forget` deletes the local record of this account only (a local delete; it revokes nothing).

### Who reads it, and what they send

`providers/documents/onedrive.py`, `providers/mailbox/outlook.py` and `providers/calendar/outlook.py` read the account record first; their verbs are unchanged and they send **GET requests only** to Graph (the token endpoint is the one POST). Each prints `"record": "account"` in `--check`. The writers that come later send only the methods and paths of their own allow-list. A provider process is started by the runtime (or by the person's terminal) with the minimum environment plus this one secret (`providers/resolve.py` `provider_environment`), so the token is never in a run, a prompt, a manifest, a card or a log.

### The rotation, and the race

Microsoft replaces the refresh token on every use. Several provider processes now share one record, so two refreshes can overlap: both start from the token the record held, each is answered with a new one, and one of the two write-backs has to lose. The rule (`store_rotation` in `providers/_msgraph.py`):

1. A rotation is written only when the record was found in the OS secret store (a record from the environment or the credentials directory is never rewritten: it ages 90 days from the consent), and only into the record the process used, the account's or a legacy one.
2. Immediately before the write the record is read again through the resolver, and the new token is written only if the stored record **still holds the token this process used**. A record forgotten meanwhile, authorized again meanwhile, or rotated first by another process is left alone ("not stored: the record changed meanwhile").
3. The read, the comparison and the write are one step per process (a lock), so threads of one process that interleave write back once.
4. The loser keeps working with the token it has. Microsoft documents that a refresh token is bound to a user and a client, and replaced on use; that the old one stays valid until it expires is the stand-in's model and is **to verify live**. If Microsoft invalidated the old token at rotation, a loser's next refresh would be refused with exit 3 and the authorize command; nothing would be lost but that process's session.
5. Between two processes the OS secret store has no compare-and-swap: the window is the two calls (the read and the write), and the worst case is one still-valid token replacing another.

`providers/accounts/tests/test_account_microsoft_rotation.py` runs two (and four) refreshes interleaved against the stand-in token endpoint, with a slow write, and asserts one write-back and every call succeeding.

### The old records (one cycle)

Each reader's own single-permission record keeps working as a fallback, for one cycle, with its old exact check and one note on stderr per process: `onedrive-sources` (`ONEDRIVE_SOURCES_TOKEN`), `outlook-mail` (`OUTLOOK_MAIL_TOKEN`), `outlook-calendar` (`OUTLOOK_CALENDAR_TOKEN`). When both exist the account record is used and the legacy one is not read; an account record that the service refuses does **not** fall back to the legacy one. The fallback and the three old `*_auth.py authorize` commands are removed in the cycle after the integration branch reaches `main` (backlog ACCT-LEGACY). Code never deletes an old record. Once `check` passes and a reader's `--check` says `"record": "account"`, remove them yourself: `uv run --with keyring==25.7.0 keyring del openhora onedrive-sources` (and `outlook-mail`, `outlook-calendar`), and delete the three old registrations in Entra.

### To verify live (nothing here was run against Microsoft)

- The consent screen shows the six permissions once and a personal account can approve without an admin.
- The token response carries the granted set the way `check_platform_scope` reads it (with or without the Graph prefix), on a personal account and on a work account.
- Microsoft leaves the old refresh token valid after a rotation (the race above).
- `GET /me` names `mail` or `userPrincipalName` for a personal account; the wording of `User.Read`.

### Tests

`uv run --with pytest==9.1.1 pytest providers/accounts/tests` (offline: a stand-in token endpoint and Graph on `127.0.0.1`, fake tokens). `test_account_microsoft_auth.py` (the consent URL, the stored record, a missing or an extra permission, `check`, `forget`), `test_account_microsoft_readers.py` (each reader with the account record alone, the legacy record alone and both, GET only, no token in any output, the rotation per reader), `test_account_microsoft_rotation.py` (the race), `test_account_microsoft.py` (the set, the record, the choice between records, the static facts the limits rest on). The existing suites of the three readers run unchanged.

## Sources

All accessed 2026-10-18 (read in a research pass against the official pages; quotes are short).

- Gmail scopes and their classes: https://developers.google.com/workspace/gmail/api/auth/scopes
- Calendar scopes: https://developers.google.com/workspace/calendar/api/auth ; restoring deleted events (30 days in the trash): https://support.google.com/calendar/answer/37113
- Drive scopes and their classes: https://developers.google.com/workspace/drive/api/guides/api-specific-auth
- OAuth 2.0 for iOS and desktop apps (loopback redirect, PKCE, "Incremental authorization is not supported for installed apps"): https://developers.google.com/identity/protocols/oauth2/native-app
- Refresh token expiry (7 days in Testing, six months unused, 100 per account per client): https://developers.google.com/identity/protocols/oauth2
- Unverified apps and personal use (fewer than 100 users): https://support.google.com/cloud/answer/13464323 and https://support.google.com/cloud/answer/7454865
- Restricted-scope verification and the security assessment (the hosted product): https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification

**To verify (not checked against the live service, or not stated by the vendor):** the console classification of `calendar.events` and `calendar.calendarlist.readonly`; that `users.messages.list` and `get` are served under `gmail.modify` (expected: the reader uses them and `gmail.modify` includes the read scope).
