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

The Microsoft account token is made by `providers/accounts/microsoft_auth.py` (package ACCT-M); its section is written with it.

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
