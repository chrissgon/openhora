# Mailbox providers

Implementations of the `reader:email` class (`mailbox` until 2026-10-02; the folder and `MAILBOX_PROVIDER` keep that name): search and read the user's own messages. Interface: `providers/CONTRACT.md`. Selected with `MAILBOX_PROVIDER=gmail`; `python3 scripts/doctor.py` then runs `gmail.py --check` for any skill that requires the class.

The first use is backlog PB5: finding new comments on the user's LinkedIn posts through the notification e-mails LinkedIn sends, because LinkedIn's API answers 403 when the member's comments are read.

## Gmail (`gmail.py`)

Reads Gmail through the Gmail API with the `https://www.googleapis.com/auth/gmail.readonly` scope and nothing else. Every verb only reads: nothing is sent, moved, labelled, marked as read or deleted, so no verb takes `--confirmed` or `--dry-run`.

### Setup (once)

The full steps are in `uv run providers/mailbox/auth.py --help`. In short:

1. In the Google Cloud console, create a project and enable the Gmail API.
2. Google Auth Platform: user type External; under Data Access add only `https://www.googleapis.com/auth/gmail.readonly`.
3. Audience: "Publish app", so the status is "In production". In "Testing", Google expires the authorization seven days after consent, and the provider would stop every week with `invalid_grant`. An app for personal use (fewer than 100 users) keeps working without Google's verification; the consent screen says the app is unverified and you click through it for your own account.
4. Clients: create an OAuth client of type "Desktop app". No redirect URL is registered: `auth.py` listens on `http://127.0.0.1:<a random free port>`.
5. Store the client id and secret (typed at a hidden prompt, never on the command line):

   ```sh
   uv run --with keyring==25.7.0 keyring set openhora gmail-client-id
   uv run --with keyring==25.7.0 keyring set openhora gmail-client-secret
   ```

6. Run `uv run providers/mailbox/auth.py --provider gmail`, sign in with the Gmail account to read and approve. The refresh token, the granted scope and the account address go to the OS secret store (service `openhora`, username `mailbox-gmail`) as one JSON record, never to disk. A record authorised before the rename is still read through the fallback to the old service, so authorising again is not required (`contracts/secrets.md`).
7. Verify: `uv run providers/mailbox/gmail.py --check` prints `{"ok": true, "account": ..., "token_source": ..., "scope": ...}`.

The authorization uses PKCE (S256), a random `state` compared in constant time on the callback, `access_type=offline` and `prompt=consent`. If the consent screen shows a box for Gmail, keep it ticked: without the scope nothing is stored.

### Usage

```sh
uv run providers/mailbox/gmail.py --check
uv run providers/mailbox/gmail.py search --query 'from:linkedin.com' --since 2026-09-28T00:00:00Z --limit 20
uv run providers/mailbox/gmail.py get --id <Gmail message id>
uv run providers/mailbox/gmail.py read-eml --file notification.eml [--header-prefix <prefix>]...
uv run providers/mailbox/gmail.py search --query 'in:inbox' --since 2026-10-10T00:00:00Z --limit 50 --own-words
```

- `search` takes a query in the syntax of the Gmail search box. `--since <ISO-8601>` is added as `after:<epoch seconds>` (Google reads a date in `q` as midnight Pacific time, so seconds are used) and checked again on each message; `--before <ISO-8601>` does the same with `before:<epoch seconds>`. `--limit` is 1 to 100, default 20: the provider reads the service's pages (`pageToken`) until it has that many, and the output's `truncated` is `true` when the mailbox holds more matches than were returned. Those are older: read on with `--before <the oldest received_at returned, plus one second>` (a message that comes back twice has the same `id`). Messages are fetched in parallel, `--jobs` at a time (1 to 10, default 4), and printed newest first.
- `get` returns one message by the id `search` printed.
- `read-eml` parses a saved RFC 822 file with no network and no credential. Use it to inspect a real notification before building on its layout, and to feed tests and eval fixtures.
- `--own-words` (on `search`, `get` and `read-eml`) makes `text` hold only what the sender wrote in that message. The text is cut before the first quoted line (`>`), signature delimiter (`-- `), attribution line (`On ... wrote:` and its Portuguese and Spanish forms, on one line or two), forward or original-message marker, or Outlook header block (`From:` followed by `Sent:`, `To:` or `Subject:`). The history of a reply was written by someone else earlier: a source that hands a message to a task should not hand that history along. It uses `strip_quoted` of `providers/_email_text.py`, the same function the e-mail channel (`providers/messenger/email-imap.py`) uses. Without the flag `text` is the whole body, as before; `links` are not changed by it. With the flag each message also has `own_words_cut`, the number of characters removed, so that a caller can see an over-cut (a message that is cut to nothing has `text` empty and `own_words_cut` equal to the length of the body).

  **Where the cut is too much or too little** (the function is the e-mail channel's and is not changed here; these are pinned by tests): an **inline reply** is cut at its first quoted line, so a reply written between or below the quoted lines (`> question` then the answer) loses the answers; a body line that **begins with `On`, `Em` or `El` and ends with `wrote:`, `escreveu:` or `escribió:`** cuts the text even when it introduces nothing quoted ("On the call you wrote:"); a line of **ten or more dashes, underscores or equals signs**, a **signature delimiter** (`--`), and a **`From:` line (or its Portuguese, Spanish or German form) followed within four lines by `Sent:`, `Date:`, `To:`, `Subject:` or their Portuguese and Spanish forms** cut the text too, even when they are part of what the sender wrote. In the other direction a quote introduced by a sentence that is not an attribution form ("Here is what Ana wrote:") is kept. Read `own_words_cut` and the text together before relying on a short `text`.

Every verb prints normalized messages:

```json
{"id": "...", "thread_id": "...", "source": "gmail", "received_at": "2026-09-28T14:05:07Z",
 "from": "...", "to": "...", "subject": "...", "text": "...", "truncated": false,
 "links": [{"href": "https://...?...", "text": "Reply"}],
 "headers": {"Message-ID": "...", "Date": "...", "From": "...", "To": "...", "Subject": "...", "List-Id": "..."},
 "attachments": [{"name": "invoice.pdf", "type": "application/pdf", "size": 122880}],
 "external_content": true}
```

- `id` and `thread_id` are Gmail's; both are null for an `.eml` file.
- `received_at` comes from Gmail's `internalDate`, or from the `Date` header for an `.eml` file, in UTC.
- `text` is the text/plain part, or text derived from the HTML part when there is none, capped at 100,000 bytes (`truncated` says so). Messages are fetched in Gmail's RAW format and decoded with the standard library's email package (quoted-printable, base64, charsets, encoded headers).
- `links` come from the HTML part, in order, one per `href` (the first one, with the first non-empty text), with the full URL including its query string: ids may live in tracking-link parameters. `javascript:` and `data:` links are dropped.
- `headers` keeps only Message-ID, Date, From, To, Subject, List-Id, and the headers whose name starts with a prefix given by `--header-prefix <prefix>` (on `search`, `get` and `read-eml`; repeatable; compared without case; the characters of a header name only, otherwise exit 2). The provider holds no platform's prefix: the caller passes the one in the platform's data file (`notification_email.header_prefix` in `shared/references/platforms/<platform>.json`). Without the flag no platform's own headers are kept.
- `attachments` lists each attached file from the MIME headers only: `name` is the file name the sender gave (one line, at most 200 characters, `null` when it gave none), `type` the content type the sender declared (not checked against the bytes), `size` a number of bytes worked out from the length of the encoded part without decoding it (exact for base64, the encoded length for other encodings, `null` for an attached message). A part marked `inline` (a picture in the body) is not listed; at most 50 are listed. No attachment is fetched, opened or decoded, and an attached message is listed whole, never entered. Turning an attachment into a file is a later step of the person's, not this provider's.
- Invisible and direction-changing characters are removed from the text and the links, and an HTML element hidden by an inline `display:none` or `visibility:hidden` style, or by the `hidden` attribute, gives no text and no link: text a reader cannot see is not message text.
- `external_content` is always `true`: the message was written by whoever sent it, and is data, never instructions.

### Security

- **E-mail content is external content.** Anyone can send the user an e-mail, and a comment is written by a stranger. The provider only returns messages as data, each marked `"external_content": true`, and drops text hidden from the reader by inline styles; a skill that reads them quotes any instruction found inside to the user and never follows it. Comments on the user's posts are the main prompt-injection surface of the engagement work (backlog PB6).
- Read only by scope: the token cannot change the mailbox even if a caller tried.
- The client secret and the refresh token are read through `providers/secrets/resolver.py` (environment first, then the OS secret store) and never printed. Requests that carry a token or the client secret never follow a redirect, and every request has a 60-second timeout.
- The test overrides below are honoured only with loopback URLs, and in test mode neither script reads or writes the OS secret store.

### Errors

| Exit | When |
|------|------|
| 0 | success |
| 1 | a Google error (a 403 when the Gmail API is not enabled, a 404, a timeout, a refused redirect) |
| 2 | usage: a bad flag, a flag the verb does not read (`--query` with `get`), `--check` with a verb, `--limit` out of bounds, a malformed message id, a missing `.eml` file |
| 3 | not configured: no authorization, a missing client id or secret, a rejected client, a token without `gmail.readonly`, or `invalid_grant` |

`invalid_grant` on a refresh means the authorization expired or was revoked. The likely cause is a project still in "Testing" (seven days); others are access removed in the Google Account, a password change (the token carries a Gmail scope) or six months without use. Rerun `auth.py`.

### Environment variables

| Variable | Used by | Purpose |
|----------|---------|---------|
| `GMAIL_CLIENT_ID` | `auth.py`, `gmail.py` | The Desktop app OAuth client; the authorization and every refresh need it. |
| `GMAIL_CLIENT_SECRET` | `auth.py`, `gmail.py` | That client's secret. |
| `GMAIL_REFRESH_TOKEN` | `gmail.py` | Optional; a bare refresh token from the environment instead of the stored record. |
| `MAILBOX_PROVIDER` | `scripts/doctor.py` | `gmail` selects this provider. |
| `GMAIL_API_BASE`, `GOOGLE_TOKEN_URL` | both | Tests only: loopback URLs of a fake Google, set together. |
| `GMAIL_HTTP_TIMEOUT` | `gmail.py` | Tests only, with the overrides: seconds before a request times out. |

### To verify on first use

- **The notification e-mail.** Save one real LinkedIn comment notification as `.eml` (Gmail: "Show original", "Download original") and run `read-eml` on it before anything else: whether it carries the comment text, the commenter, and the post and comment ids a reply needs (backlog PB5). The test fixture is synthetic and does not claim to match LinkedIn's format.
- **Search query.** Which sender address and words find the comment notifications, to fix the `--query` a skill uses.
- **RAW responses carry `internalDate`.** The Message resource lists it; if a RAW answer omits it, `received_at` falls back to the `Date` header.
- **Unverified-app consent.** That the consent screen of a production, unverified, personal-use app lets the owner click through for the `gmail.readonly` scope, and that the refresh token then outlives seven days.

Sources, accessed 2026-09-29: [OAuth 2.0 for iOS and desktop apps](https://developers.google.com/identity/protocols/oauth2/native-app), [Using OAuth 2.0](https://developers.google.com/identity/protocols/oauth2), [web server flow parameters](https://developers.google.com/identity/protocols/oauth2/web-server), [Manage App Audience](https://support.google.com/cloud/answer/15549945), [unverified apps](https://support.google.com/cloud/answer/13464323), [users.messages.list](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list), [users.messages.get](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/get), [Message resource](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages), [users.getProfile](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users/getProfile), [search and filter messages](https://developers.google.com/workspace/gmail/api/guides/filtering).

## Which implementation: `gmail` and `outlook`

Since package M1 this folder holds two implementations of `reader:email`, `gmail.py` and `outlook.py`. **`"mailbox": "auto"` no longer resolves.** The resolution function (`providers/resolve.py`, rule 3) falls to "the only implementation shipped" when nothing names one, so with two it exits 3 with "reader:email has several providers and none is selected: set MAILBOX_PROVIDER to one of ['gmail', 'outlook']". Nothing in the runtime changed to make this so; `tests/test_mailbox_resolution.py` pins both the exit 3 and the explicit name that keeps working.

- **The maintainer must set `"mailbox": "gmail"`** in the `runtime.json` of every project whose social handler (`runtime/handlers/social.py`) or tick (`scripts/runtime.py`) says `"mailbox": "auto"` **before the integration branch reaches `main`** (or export `MAILBOX_PROVIDER=gmail` for that tick). A value that names an implementation wins over the environment and was always valid, so the change can be made today, on the branch that still has one implementation.
- The mail sources of the task runtime never use `auto`: the origin of a source names its implementation (`gmail:...`, `outlook:...`), which the runtime passes to the resolver as the explicit implementation.
- Not done, with the reason: making `auto` skip `outlook.py` by a list in the resolver (a guess about which one the project meant, and a change to the resolver that every class shares); a `MAILBOX_PROVIDER` default in the environment (a silent default for the next project). A minimal fix that keeps `auto` working for existing projects without guessing would be a runtime change, so it is proposed in the pull request and not built.

## Outlook (`outlook.py`)

Reads the messages of an Outlook inbox (Microsoft 365 and outlook.com) through Microsoft Graph, read only: nothing is sent, moved, marked as read or deleted, so no verb takes `--confirmed` or `--dry-run`. It is the second implementation of the class and prints the same normalized messages as the Gmail provider.

**One permission, and what it can do.** The authorization asks for the delegated Microsoft Graph permission `Mail.Read` and `offline_access` (the refresh token), and nothing else; the refresh request names the same scope so that the access token is no wider than asked. `Mail.Read` is the permission to "read the signed-in user's mailbox": it needs no admin consent and exists for personal accounts. Microsoft has no permission granted per message or per folder, so **`Mail.Read` lets the token read every message of the person's mailbox, not only the inbox window a source names, and it changes none.** The narrowing to the inbox and a window is the runtime's. `Mail.ReadBasic`, the least privileged permission for listing messages, leaves out the body and the attachments, which is too little for a snapshot. The provider refuses a token whose reported scope is anything but `Mail.Read` (the `offline_access`, `openid`, `profile` and `email` it may report next to it grant no access to a message and are ignored): a registration that still carries `User.Read`, `Mail.ReadWrite`, `Mail.Send`, `Files.Read` or `Calendars.ReadBasic` is a setup error (exit 3, naming the extra scope), and so is a response that reports no scope.

**One app registration per purpose.** Microsoft documents that "refresh tokens are bound to a combination of user and client, but aren't tied to a resource" and that a client can use a refresh token to acquire access tokens for any resource it has permission for [M5]. A single registration that held `Files.Read` (OneDrive), `Mail.Read` and `Calendars.ReadBasic` would let the refresh token of any one of them read all three. So the mail provider has a registration of its own with `Mail.Read` alone, its own client id and its own record (`OUTLOOK_MAIL_TOKEN`, entry `outlook-mail`); the calendar provider and the OneDrive provider each have theirs. The shared code (`providers/_msgraph.py`) shares no registration and no token. The cost is one more registration to make for each purpose.

### Setup (once; the maintainer of the project does it, not each person)

The full steps are in `uv run <workbench>/providers/mailbox/outlook_auth.py --help`. In short, at https://entra.microsoft.com:

1. Identity, Applications, App registrations, New registration: a name, the supported account types "Accounts in any organizational directory and personal Microsoft accounts". No redirect URI yet.
2. Authentication, Add a platform, "Mobile and desktop applications", custom redirect URI `http://localhost` (the port is ignored for `localhost`, so the random port the script listens on matches). No client secret, no certificate.
3. API permissions: remove `User.Read`; add Microsoft Graph, Delegated permissions, `Mail.Read` (and `offline_access`). Do not grant admin consent for a personal test.
4. Copy the Application (client) ID. Run `OUTLOOK_MAIL_CLIENT_ID=<the id> uv run <workbench>/providers/mailbox/outlook_auth.py authorize` (or run it in a terminal and type the id at the hidden prompt: it never goes on the command line; an office with its own single-tenant registration also sets `OUTLOOK_MAIL_TENANT`, default `common`), sign in with the account whose mail to read and approve. A work or school tenant whose admin has blocked user consent answers with a consent error: "your Microsoft 365 admin must approve the app" (exit 3).
5. Verify: `uv run <workbench>/providers/mailbox/outlook.py --check` prints `{"ok": true, "scope": "Mail.Read", "tenant", "obtained_at", "rotation"}` and reads no mail.

The authorization is the code flow with PKCE (S256) and a state, as a public client, in the system browser with a loopback redirect: the script listens on `127.0.0.1` (and `::1` on the same port when it can), sends `redirect_uri=http://localhost:<port>`, accepts only a request whose `Host` is exactly `localhost:<port>` and that is shaped like a callback, compares the state in constant time, serves the callback once, logs no request line and stops after the callback or after 10 minutes. The record `{refresh_token, client_id, tenant, scope, obtained_at}` goes to the OS secret store (service `openhora`, username `outlook-mail`), or is exported as the same JSON text in `OUTLOOK_MAIL_TOKEN` or copied into the credentials directory. `outlook_auth.py forget` deletes the stored record (it revokes nothing at Microsoft). A token, a refresh token or a client id that is not printable ASCII is refused without being shown.

**Rotation.** Microsoft replaces the refresh token on every use. When the record was found in the OS secret store, `outlook.py` writes the new token back into that one record (the exception to "a provider never writes the store", `contracts/secrets.md` rule 1), after reading the record again through the resolver: it writes only when the stored refresh token is still the one it used (a record forgotten or authorized again meanwhile, or rotated first by another process, is left alone: `not stored: the record changed meanwhile`); when the write fails it carries on with the old token and says so on stderr. A record from the environment or the credentials directory is never rewritten, so it ages 90 days from the consent [M5]. `--check` prints `rotation` to say what happened. `invalid_grant` is exit 3 with the authorize command.

### Usage

```sh
uv run <workbench>/providers/mailbox/outlook.py --check
uv run <workbench>/providers/mailbox/outlook.py search --query "in:inbox" --since 2026-10-10T00:00:00Z --limit 20
uv run <workbench>/providers/mailbox/outlook.py search --query "in:inbox is:unread" --since 2026-10-10T00:00:00Z --own-words
uv run <workbench>/providers/mailbox/outlook.py get --id <Graph message id>
```

- `search` takes one of two **fixed boxes** in `--query`, `in:inbox` and `in:inbox is:unread` (the words the Gmail provider's source origins use for the same boxes); any other query is exit 2, because a free query is not supported in this version. The window: `--since` and `--before` (ISO-8601, a time without an offset is local time) become `receivedDateTime ge` and `lt` in the `$filter`, which is always sent with the received time first and `$orderby=receivedDateTime desc` (Graph requires a property in `$orderby` to be listed in `$filter` before any other; with no `--since` the filter starts at 1970). `--limit` is 1 to 100 (default 20); the pages (10 messages each, `$top`) are read by the whole `@odata.nextLink` Graph names, never by editing `$skip`, until the limit, and `truncated` is `true` when older matches were left out (read on with `--before`). `--jobs` is how many messages' attachment lists are read at the same time (1 to 4, default 4: Outlook limits concurrent requests on one mailbox, the figure of 4 is from memory of its documentation, to verify).
- A next-page address is followed only when it names the same scheme, host and port (443 written or not) as the request, no user or password, and a path inside the API (it starts, without case, with `/v1.0/`: Graph may spell the rest its own way); any other is not followed, the pages read so far are returned with `truncated: true` and a note on stderr. It also holds no backslash, no character outside `\x21`-`\x7e` and no `..`; the request carries the access token, so an address on another host is never followed.
- `get` returns one message by the id `search` printed (letters, digits and `- _ = +`, checked before it enters a path).
- `--own-words` cuts the quoted history (`strip_quoted` of `providers/_email_text.py`, the cut of the Gmail provider) and adds `own_words_cut` to each message, the number of characters removed, so that a caller sees an over-cut; it is exit 2 in a checkout whose `_email_text.py` does not have `strip_quoted`.
- `read-eml` is exit 2: it is a local parser, `gmail.py read-eml` does it.

Every verb prints normalized messages:

```json
{"id": "...", "thread_id": "...", "source": "outlook", "received_at": "2026-10-17T07:12:03Z", "change_key": "...",
 "from": "Ana Lima <ana@clinic.example>", "to": "...", "subject": "...", "text": "...", "truncated": false,
 "links": [{"href": "https://...", "text": "..."}],
 "headers": {"Message-ID": "...", "Date": "...", "From": "...", "To": "...", "Subject": "..."},
 "attachments": [{"name": "invoice.pdf", "type": "application/pdf", "size": 120000}],
 "external_content": true}
```

- `received_at` is Graph's `receivedDateTime`, in UTC. `change_key` is Graph's `changeKey`, which moves when the message changes (a snapshot's version is built from the ids and change keys it listed).
- **The body is turned into text here.** Graph can return a body as HTML or as text, and the provider never asks for a format (no `Prefer` header): an HTML body goes through `_email_text.html_to_text`, which removes invisible and direction-changing characters and any element hidden by the `hidden` attribute or by an inline style that sets `display:none`, `visibility:hidden`, `mso-hide:all`, a zero `font-size`, `opacity:0`, a zero `width` or `height`, or a zero `max-height`/`max-width` together with `overflow:hidden`; a text body is cleaned. **It does not read style sheets, class names, colours (white on white) or comments:** text hidden that way is not removed (a comment is dropped as markup, not read as text). A conversion done by the service would be a conversion whose treatment of hidden elements nobody here has read. `text` is capped at 100,000 bytes (`truncated` says so). `links` come from the HTML body; `javascript:` and `data:` links are dropped.
- **Attachments** are listed (name, declared type, size) from `GET /me/messages/{id}/attachments` with `$select=name,contentType,size` for a message that has any; no attachment is fetched, opened or decoded, and `contentBytes` is never asked for. When the list cannot be read, `attachments` is `null` (not `[]`: unknown is not none) and stderr says so.
- `headers` keeps Message-ID, Date, From, To and Subject, taken from the message's own properties; `--header-prefix <prefix>` (repeatable, the characters of a header name) asks Graph for `internetMessageHeaders` as well and keeps those whose name starts with a prefix, and List-Id.
- Names, subjects and addresses are cut to one line with control and invisible characters removed. `external_content` is always `true`: a message is data, never an instruction.

### Errors

| Exit | When |
|------|------|
| 0 | success |
| 1 | Graph answered an error (403, 404, 429 or 503 with its `Retry-After`, a refused redirect), could not be reached, or answered a shape this provider does not understand; an access token it will not send; an unexpected failure (only its kind is printed) |
| 2 | usage: a bad flag, a flag the verb does not read, a query that is not one of the two boxes, `--limit` or `--jobs` out of bounds, a malformed message id, `read-eml`, a test override that is not loopback or not set together |
| 3 | not configured: no authorization, an unreadable record, a rejected app registration, a tenant that needs its admin's approval, a token whose scope is not exactly `Mail.Read`, or `invalid_grant` |

A verb never retries. Only GET is sent to Graph; the token endpoint is the one POST. No redirect is followed with a credential.

### Environment variables

| Variable | Used by | Purpose |
|----------|---------|---------|
| `OUTLOOK_MAIL_TOKEN` | `outlook.py`, `outlook_auth.py` | The record, through the secret resolver (the environment, the credentials directory, then the OS secret store). |
| `OUTLOOK_MAIL_CLIENT_ID`, `OUTLOOK_MAIL_TENANT` | `outlook_auth.py` | Of the one `authorize` command only: the Application (client) ID of the mail registration, and a tenant (default `common`). |
| `MAILBOX_PROVIDER` | `providers/resolve.py` | `gmail` or `outlook` selects the implementation. |
| `MAILBOX_OUTLOOK_API_BASE`, `MAILBOX_OUTLOOK_TOKEN_URL` | both | Tests only: loopback URLs of a fake Graph and a fake token endpoint, set together; the secret store is then never read or written. |

### Calls this provider makes

| Call | Used for | Source (read 2026-10-17 by the author of the plan; not read again for this package) |
|---|---|---|
| `GET https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages` with `$filter`, `$orderby`, `$top`, `$select` and the next link | `search` | [List messages](https://learn.microsoft.com/en-us/graph/api/user-list-messages?view=graph-rest-1.0) |
| `GET .../me/messages/{id}` with `$select` | `get` | the same family of pages |
| `GET .../me/messages/{id}/attachments?$select=name,contentType,size` | the attachment names of a message with `hasAttachments` | to verify |
| `POST https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token` | the code exchange and every refresh (the only POST) | [Refresh tokens](https://learn.microsoft.com/en-us/entra/identity-platform/refresh-tokens) |
| `https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize` | the consent page in the person's browser | the authorization code flow reference |

Permission sources: [Microsoft Graph permissions reference](https://learn.microsoft.com/en-us/graph/permissions-reference) (`Mail.Read`, `Mail.ReadBasic`, read 2026-10-17 by the author of the plan, not read again here). [M5] is [Refresh tokens in the Microsoft identity platform](https://learn.microsoft.com/en-us/entra/identity-platform/refresh-tokens).

### To verify on first use (the live step of the package; nothing here was run against Microsoft)

The tests use a stand-in service that serves what the plan's reading of the reference says, so each item below is a fact the stand-in encodes and the live service has not confirmed.

1. **The body format received.** The page for listing messages offers a `Prefer: outlook.body-content-type="text"` header and also says the operation returns bodies in HTML only; the provider sends no `Prefer` and handles both. Record which `body.contentType` arrives for an HTML mail and for a plain-text one.
2. **`$select` on the attachment list.** That `GET /me/messages/{id}/attachments` accepts `$select=name,contentType,size` under `Mail.Read` (a failure there makes `attachments` `null`, nothing more; a service that ignored `$select` would answer with the attachments' bytes, past the 1 MiB read of that call, and the list would be `null` too: nothing is kept of them), whether the list needs `$top` (the provider sends none and keeps at most 50), and whether inline images should be left out (the provider lists them).
3. **The next link.** How Graph spells the `@odata.nextLink` of the inbox listing (the provider accepts the request's scheme, host and port and any path under `/v1.0/`, read without case; a link it cannot follow ends the read as truncated, with a note), and that a page of 10 messages with their bodies stays under 8 MiB.
4. **`internetMessageHeaders`** in a `$select` of a message list (only with `--header-prefix`).
5. **The scope string** the token endpoint returns (with or without the `https://graph.microsoft.com/` prefix, and which of `offline_access`, `openid`, `profile`, `email` it adds); `scopes_of` strips the prefix, compares without case and ignores those four.
6. **That `localhost` in the browser reaches the `127.0.0.1` listener**, and the error codes of a work tenant that blocks user consent (`AADSTS65001`, `AADSTS90094`, `AADSTS65004` are from memory of the identity platform).
7. **Whether the refresh token rotates on every use** for both account kinds, and how long an unrotated one lives (the plan says 90 days).
8. **The bound on a refresh token.** The provider keeps a refresh token or an id only if it is printable ASCII of at most 4096 characters (an access token, 16384; the bound of the Google providers' `TOKEN_RE`); report the length of a real refresh token. **A message id's characters** (the provider accepts letters, digits and `- _ = +`) and whether ids change when a message is moved (the immutable-id option is not used).
9. **A real message with a signature, a forward and a reply:** report whether `--own-words` cuts them, and whether the runtime's credential scan left a message out.

### Tests

`uv run --with pytest==9.1.1 pytest -q providers/mailbox/tests/test_mailbox_outlook.py providers/mailbox/tests/test_mailbox_outlook_auth.py providers/mailbox/tests/test_msgraph_shared.py providers/mailbox/tests/test_mailbox_resolution.py`, against `fake_graph_mail.py` and `fake_microsoft.py` (the stand-in for Graph and the token endpoint, on 127.0.0.1: it records the methods, refuses a `$filter` that does not list the `$orderby` property first, and can be made to send a malformed token, a wider scope, a redirect or a next link that leaves the request). The mailbox suite runs on Python 3.9 too (CI job `python39`): `outlook.py` and `_msgraph.py` use no newer syntax.
