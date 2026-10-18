# Calendar providers

Implementations of the `integration:calendar` class: the calendars of the person and the events of one calendar in a window, read only. Interface: `providers/CONTRACT.md` (the `integration:calendar` row). Selected by `INTEGRATION_CALENDAR_PROVIDER` (two implementations ship, so nothing resolves without it or an explicit name): `google.py` (Google Calendar, package G1) and `outlook.py` (Outlook through Microsoft Graph, package M1). The runtime names the implementation of a calendar source explicitly. Each has its own authorization helper, secret and record, and `outlook_auth.py` is not an implementation.

A calendar enters the task runtime as a **snapshot**: the runtime calls this provider on the machine, records a dated, scanned, immutable version of what it printed, and a task is given that version, never a live read. That is the runtime's package (RT-1), not this folder's. This provider only reads and prints; nothing in it writes to a calendar.

## Google Calendar (`google.py`, `google_auth.py`)

Reads Google Calendar through the Calendar API with two scopes, both read only, and nothing else:

| Scope | Google's description | Used for |
|---|---|---|
| `https://www.googleapis.com/auth/calendar.events.readonly` | "View events on all your calendars" | the events of one calendar |
| `https://www.googleapis.com/auth/calendar.calendarlist.readonly` | "See the list of Google calendars you're subscribed to" | the list of calendars, to choose one |

Together they are narrower than `calendar.readonly` ("See and download any calendar you can access"), which also reads the properties of the calendars. Narrower still is `calendar.events.owned.readonly` ("events on Google calendars you own"), which drops the calendars shared with the person; it was not chosen because a shared family or team calendar is a normal thing to read. Source: [Choose Google Calendar API scopes](https://developers.google.com/workspace/calendar/api/auth), accessed 2026-10-17.

**What the token can do.** Both scopes read every event of every calendar the account can see, and the list of calendars. Neither changes anything. The narrowing to one calendar and one window is the provider's and the runtime's, not the service's: a leaked token reads the whole calendar. The provider refuses (exit 3, nothing read) a token whose reported scope is not exactly these two, so a wider token, a narrower one, or one that reports no scope is a setup error to fix, not a token to use.

**Separate from Gmail.** Google does not support incremental authorization for installed apps ([OAuth 2.0 for iOS and desktop apps](https://developers.google.com/identity/protocols/oauth2/native-app), accessed 2026-10-17), so a token carries the scopes of its own consent. This provider's record (`calendar-google`, the secret `GOOGLE_CALENDAR_TOKEN`) is separate from the Gmail one (`mailbox-gmail`) and asks only for the two calendar scopes: it cannot read mail even when the Desktop app client is the one used for Gmail. That the calendar token cannot be made to carry a Gmail scope is documented behaviour, not yet measured here (see "To verify on first use").

### Setup (once)

Commands are written from the workbench checkout, `<workbench>`.

1. Google Cloud console, in the project of your Gmail client (or a project of its own): enable the **Google Calendar API**.
2. Google Auth Platform, Data Access: add the two scopes above and nothing else.
3. Audience: "Publish app" (status "In production"). In "Testing", Google expires the refresh token after seven days of an external app ([Using OAuth 2.0](https://developers.google.com/identity/protocols/oauth2), accessed 2026-10-17), the provider would then answer `invalid_grant` (exit 3) every week, and a task would be refused a stale snapshot. A personal-use app keeps working in production; the consent screen of an unverified app asks you to click through it, for your own account. Other expiries: access removed in the Google Account, six months unused, 100 tokens for one client and account.
4. Clients: a client of type "Desktop app" (the Gmail one may be reused). No redirect URL is registered: the authorization listens on `http://127.0.0.1:<a random free port>`.
5. Authorize, on a machine with a browser:

   ```sh
   uv run <workbench>/providers/calendar/google_auth.py authorize
   ```

   It asks for the client id and the client secret at a hidden prompt, or reads `GOOGLE_CALENDAR_CLIENT_ID` and `GOOGLE_CALENDAR_CLIENT_SECRET` from the environment of that one command; neither goes on the command line or in a file. Sign in with the account whose calendars to read and approve **both** boxes of the consent screen: with one unticked nothing is stored. The command waits up to ten minutes for the browser, then stops. The record (refresh token, client, scope, account, date) is written to the OS secret store as one entry, service `openhora`, username `calendar-google`, never to disk.
6. Verify: `uv run <workbench>/providers/calendar/google.py --check`, then `uv run <workbench>/providers/calendar/google.py calendars`.

`google_auth.py check` says whether a record is found (the environment, then the OS secret store) without calling Google. `google_auth.py forget` removes the stored record; it does not tell Google, so also remove the app's access in your Google Account.

The authorization uses PKCE (S256), a random `state` compared in constant time, `access_type=offline` and `prompt=consent`. The listener serves one callback and no more, answers only the exact host `127.0.0.1:<port>`, ignores a visit that carries no `state`, `code` or `error`, and closes after the callback or after ten minutes. Before anything is stored it reads the calendar list once, which proves the token and the API work and names the account (the primary calendar's id).

### Usage

```sh
uv run <workbench>/providers/calendar/google.py --check
uv run <workbench>/providers/calendar/google.py calendars
uv run <workbench>/providers/calendar/google.py events --calendar primary-id@example.com \
    --from 2026-10-17T00:00:00-03:00 --to 2026-10-18T00:00:00-03:00 [--max 250]
```

- `calendars` prints `{"calendars": [{"id", "summary", "primary", "access_role", "external_content"}], "truncated", "skipped", "external_content": true}`. A source names a calendar by the `id` printed here. A calendar whose id this provider cannot use (a shape outside `[A-Za-z0-9._%+#@-]`, at most 254 characters) is counted in `skipped`.
- `events` prints `{"calendar", "from", "to", "events", "truncated", "skipped", "external_content": true}`, each event `{"id", "etag", "start", "end", "all_day", "title", "location", "organizer_self", "organizer_domain", "response", "status", "online_meeting", "recurring", "external_content": true}`.
  - Recurring events are expanded to their occurrences (`singleEvents=true`) and sorted by start (`orderBy=startTime`). An event is returned when it ends after `--from` and starts before `--to`.
  - `--from` and `--to` need an offset (`Z` or `+hh:mm`, a whole number of minutes; seconds in an offset are exit 2): the service refuses a time without one, and the provider does not guess the local zone (a time without an offset is exit 2). The runtime computes the window from the host's clock and zone and passes the offset.
  - `--max` is 1 to 250 (default 250). The provider reads pages until it has that many; `truncated` is `true` when more exist than were read. An item without a usable start or end (a cancelled occurrence can lack both) is counted in `skipped`, not printed.
  - `start` and `end` are the service's own values: a date-time with its offset, or a bare date for an all-day event (`all_day` is `true`). `etag` changes when the event does, which is what a snapshot's version is made of.
  - `title` and `location` are one line (invisible and control characters removed, the space folded), cut at 300 and 200 characters. `organizer_domain` is the part of the organizer's address after the `@`, never the address. `response` is the person's own answer (`accepted`, `declined`, `tentative`, `needsAction`), `null` when they are not an attendee. `online_meeting` says only whether the event has a conference. `status` is `confirmed`, `tentative`, `cancelled` or `unknown`.
  - **Not asked for:** the description, attachments, any attendee address and any conference link. The request carries a `fields` mask naming only what is needed. **Received only to derive a printed value, never printed themselves:** the organizer's address (`organizer_domain`), the person's own invitation answer (`response`) and the conference id (`online_meeting`). `title` and `location` are free text written by whoever made the event and may contain a URL; the snapshot the runtime builds from this output (RT-1) removes every URL.
- A calendar id is checked against a full-match pattern (and is refused when it is made only of dots) before it enters the URL, and is always percent-encoded (`en.usa#holiday@group.v.calendar.google.com` is sent as `en.usa%23holiday%40group.v.calendar.google.com`). Give an id as `calendars` prints it, not already percent-encoded.

### Endpoints

| Call | Endpoint | Scope | Source (accessed 2026-10-17) |
|---|---|---|---|
| list the calendars | `GET https://www.googleapis.com/calendar/v3/users/me/calendarList` | `calendar.calendarlist.readonly` | [CalendarList: list](https://developers.google.com/workspace/calendar/api/v3/reference/calendarList/list) |
| list the events | `GET https://www.googleapis.com/calendar/v3/calendars/{calendarId}/events` with `singleEvents=true`, `orderBy=startTime` (only with single events), `timeMin` and `timeMax` (RFC 3339 with a mandatory offset; `timeMin` bounds an event's end, `timeMax` its start), `maxResults` (default 250, at most 2500), `pageToken` | `calendar.events.readonly` | [Events: list](https://developers.google.com/workspace/calendar/api/v3/reference/events/list) |
| refresh a token | `POST https://oauth2.googleapis.com/token` | | [OAuth 2.0 for iOS and desktop apps](https://developers.google.com/identity/protocols/oauth2/native-app) |
| consent | `https://accounts.google.com/o/oauth2/v2/auth` | both | the same page |

### Security

- **External content is data.** Titles, places and calendar names are written by whoever made the event or the calendar, and anyone can send the person an invitation. The provider returns them as data, each item marked `"external_content": true`; whoever reads them quotes any instruction found inside to the user and never follows it. The snapshot the runtime builds from it (its package RT-1) is specified to say so in its first lines and to remove every URL.
- **Read only, GET only.** The scope cannot change a calendar, and the provider sends no other method to the API: the one POST is the token request, to a fixed address. A test fails on any other method.
- **Fixed hosts, no redirect.** The API and token hosts are fixed. The test overrides below are honoured only for loopback URLs, set together, and then the OS secret store is never read. A redirect is never followed with a credential. Every request has a 60-second timeout, and an answer over 4 MiB is refused.
- **No retry.** A 429 or 503 is reported with its `Retry-After` and exit 1; the verb never retries and never sleeps.
- **No token in output.** The access token, the refresh token and the client secret are never printed; any text that comes from the service is scrubbed of them before it is shown. They come only through `providers/secrets/resolver.py` (environment first, then the OS secret store).
- **A run never holds the token** (limit L6 of the runtime): this provider is called by the runtime on the host, with `provider_environment` and its one secret, never from a task.

### Errors

| Exit | When |
|---|---|
| 0 | success |
| 1 | a Google error (a 403 when the Calendar API is not enabled, a 404 for a calendar the account does not hold, a 429 or 503, a timeout, a refused redirect) |
| 2 | usage: a bad flag, a flag the verb does not read, a verb the provider does not have, a time without an offset, `--from` not before `--to`, a malformed calendar id, `--max` out of bounds |
| 3 | not configured: no authorization, a missing or rejected client, a token whose scope is not exactly the two, or `invalid_grant` (expired or revoked: a project in "Testing" expires it in seven days) |

### Environment variables

| Variable | Used by | Purpose |
|---|---|---|
| `GOOGLE_CALENDAR_TOKEN` | `google.py`, `google_auth.py` | The record (JSON) from the OS secret store, or the same JSON text from the environment or the credentials directory. |
| `GOOGLE_CALENDAR_CLIENT_ID`, `GOOGLE_CALENDAR_CLIENT_SECRET` | `google_auth.py authorize` | The Desktop app client, for that one command only (otherwise a hidden prompt). |
| `INTEGRATION_CALENDAR_PROVIDER` | `providers/resolve.py` | Selects the implementation when there is more than one. |
| `INTEGRATION_CALENDAR_GOOGLE_API_BASE`, `INTEGRATION_CALENDAR_GOOGLE_TOKEN_URL` | `google.py`, `google_auth.py` | Tests only: loopback URLs of a fake Google, set together. |

### Tests

`providers/calendar/tests/` runs against `fake_gcal.py`, a stand-in for the two API calls and the token endpoint on `127.0.0.1`: no network but loopback, no real account, every address a `.example` one, and the OS secret store is a stand-in object. `uv run --with pytest pytest providers/calendar/tests`.

### To verify on first use

Nothing here has touched the live service: the endpoints, scopes and parameters above are those the spec writer read on Google's pages on 2026-10-17, and the provider was tested against a stand-in. These are not checked against the live service, and the maintainer's first run should report them:

- **The `fields` mask on a real answer:** `nextPageToken,items(id,etag,status,summary,location,start,end,organizer(email,self),attendees(self,responseStatus),conferenceData(conferenceId),recurringEventId)` was written from the resource's field names, not from a page read; whether `attendees(self,responseStatus)` returns the person's own entry, whether `conferenceData(conferenceId)` is populated for an event with a meeting (`online_meeting` is derived from it alone; `hangoutLink` is not asked for), and whether `organizer(email,self)` is returned for an event on a shared calendar.
- **The end of an all-day event:** that `end.date` is the day after the last day (exclusive). The provider passes the service's value through and does not adjust it.
- **The calendar list's own page size and `maxResults`:** the provider does not send `maxResults` on `calendarList` and reads up to 10 pages; `--check` sends `maxResults=1`.
- **That a calendar token cannot carry a Gmail scope:** refresh the calendar record asking `gmail.readonly` (Google documents no incremental authorization for installed apps; not measured).
- **Google's classification of the scopes** (`gmail.readonly` restricted; the calendar scopes sensitive) and the unverified-app click-through for a production, personal-use app: only a third-party page was found (developer.nylas.com, accessed 2026-10-17), and Google's own page does not list scopes; check in the Cloud console.
- **The 403 text** when the Calendar API is not enabled in the project (`accessNotConfigured`), and whether a quota error reaches the provider as 403 `rateLimitExceeded` or as 429: both are reported with their `Retry-After`.
- **An event with no `start`** (a cancelled occurrence): counted in `skipped`.

Sources, accessed 2026-10-17: [Choose Google Calendar API scopes](https://developers.google.com/workspace/calendar/api/auth), [Events: list](https://developers.google.com/workspace/calendar/api/v3/reference/events/list), [CalendarList: list](https://developers.google.com/workspace/calendar/api/v3/reference/calendarList/list), [OAuth 2.0 for iOS and desktop apps](https://developers.google.com/identity/protocols/oauth2/native-app), [Using OAuth 2.0](https://developers.google.com/identity/protocols/oauth2).
The `access_type=offline` and `prompt=consent` parameters come from the [web server flow's parameter list](https://developers.google.com/identity/protocols/oauth2/web-server), accessed 2026-09-29 for `providers/mailbox/auth.py` and not read again. The pages above were read by the spec writer on 2026-10-17; the executor made no call to any Google host, so none was re-read.

## Outlook (`outlook.py`)

Verbs: `--check`, `calendars`, `events --calendar <default|id> --from <ISO-8601 with offset> --to <ISO-8601 with offset> [--max <n>]`. Every other verb is exit 2. GET only: the token endpoint is the one POST, and a test fails on any other method.

**One permission, and what it can do.** The authorization asks for the delegated Microsoft Graph permission `Calendars.ReadBasic` and `offline_access` (the refresh token), and nothing else; the refresh request names the same scope so that the access token is no wider than asked. `Calendars.ReadBasic` reads events "except for properties such as body, attachments, and extensions", needs no admin consent and exists for personal accounts, and is the least privileged permission for `calendarView`. So no event description, attachment or extension can reach this provider, and none is asked for or printed. It does **read the events of every calendar the account can see**, and changes none; the narrowing to one calendar and a window is the runtime's, not the service's. The provider refuses a token whose reported scope is anything but `Calendars.ReadBasic` (the `offline_access`, `openid`, `profile` and `email` it may report next to it are ignored): a registration that still carries `User.Read`, `Calendars.Read`, `Calendars.ReadWrite`, `Mail.Read` or `Files.Read` is a setup error (exit 3, naming the extra scope), and so is a response that reports no scope.

**One app registration per purpose.** Microsoft documents that "refresh tokens are bound to a combination of user and client, but aren't tied to a resource" and that a client can use a refresh token for any resource it has permission for [M5]. A registration that held `Mail.Read` and `Calendars.ReadBasic` together would let the calendar's refresh token read mail. So the calendar provider has a registration of its own with `Calendars.ReadBasic` alone, its own client id and its own record (`OUTLOOK_CALENDAR_TOKEN`, entry `outlook-calendar`); the mailbox provider (`Mail.Read`) and the OneDrive provider (`Files.Read`) each have theirs. The code they share (`providers/_msgraph.py`) shares no registration and no token. A test makes the point with the stand-in: the service refuses the client id of another registration, and the exact scope check refuses a token of another permission.

### Setup (once; the maintainer of the project does it, not each person)

The full steps are in `uv run <workbench>/providers/calendar/outlook_auth.py --help`. In short, at https://entra.microsoft.com:

1. A personal Microsoft account first needs a directory (tenant) of its own: create a free Azure account at [https://azure.microsoft.com/pricing/purchase-options/azure-account](https://azure.microsoft.com/pricing/purchase-options/azure-account) ("Try Azure for free"; it creates a Default Directory; the page says it needs a phone number and a credit or debit card, not prepaid, with a temporary authorization of about US$1) or join the [Microsoft 365 Developer Program](https://developer.microsoft.com/microsoft-365/dev-program), and switch to that directory before registering (Settings icon, then "Directories + subscriptions", in https://entra.microsoft.com; or in https://portal.azure.com, Microsoft Entra ID). Microsoft no longer lets an app be registered outside a directory, and an app made under a personal account cannot be moved into one. Sources, accessed 2026-10-18 (the Azure page also on the card): [Quickstart: register an application](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app), [How to move an Azure application created under a personal account](https://learn.microsoft.com/en-us/answers/questions/2127352/how-to-move-an-azure-application-created-under-a-p).
2. Entra ID, App registrations, New registration: a name, the supported account types "Any Entra ID Tenant + Personal Microsoft accounts" (formerly "Accounts in any organizational directory and personal Microsoft accounts"; "Personal accounts only" also serves a personal account; the default tenant `common` serves both). No redirect URI yet.
3. Authentication, Add a platform, "Mobile and desktop applications", custom redirect URI `http://localhost`. No client secret, no certificate.
4. API permissions: remove `User.Read`; add Microsoft Graph, Delegated permissions, `Calendars.ReadBasic` (and `offline_access`). Do not grant admin consent for a personal test.
5. Run `OUTLOOK_CALENDAR_CLIENT_ID=<the Application (client) ID> uv run <workbench>/providers/calendar/outlook_auth.py authorize` (or type the id at the hidden prompt: it never goes on the command line; an office with its own single-tenant registration also sets `OUTLOOK_CALENDAR_TENANT`, default `common`), sign in with the account whose calendar to read and approve.
6. Verify: `uv run <workbench>/providers/calendar/outlook.py --check` prints `{"ok": true, "scope": "Calendars.ReadBasic", "tenant", "obtained_at", "rotation"}`; then `... outlook.py calendars` lists the calendars (the id of one is what a calendar source names).

The authorization flow, the loopback listener, the record and its rotation are the ones of the mailbox provider (`providers/mailbox/README.md`, "Outlook"), with the record `{refresh_token, client_id, tenant, scope, obtained_at}` in the OS secret store entry `outlook-calendar` (service `openhora`), and `invalid_grant` is exit 3 with `outlook_auth.py authorize`. `forget` deletes only this provider's entry.

### Usage

```sh
uv run <workbench>/providers/calendar/outlook.py --check
uv run <workbench>/providers/calendar/outlook.py calendars
uv run <workbench>/providers/calendar/outlook.py events --calendar default --from 2026-10-17T00:00:00-03:00 --to 2026-10-24T00:00:00-03:00
```

- `calendars` prints `{"calendars": [{"id", "summary", "primary", "access_role"}], "truncated", "skipped", "external_content": true}`. `access_role` is `writer` or `reader` from Graph's `canEdit`, `null` when it is absent.
- `events` prints `{"calendar", "from", "to", "events": [...], "truncated", "skipped", "external_content": true}`, each event `{"id", "etag", "start", "end", "all_day", "title", "location", "organizer_self", "organizer_domain", "response", "status", "online_meeting", "recurring", "external_content": true}`, the shape the Google provider prints (`google.py`, above). `--calendar default` reads `GET /me/calendarView`; an id from `calendars` reads `GET /me/calendars/{id}/calendarView` (the id is checked against `[A-Za-z0-9=_-]{1,256}` and percent-encoded).
- `--from` and `--to` need a time zone offset (`Z` or `+hh:mm`, else exit 2: the provider never guesses a zone), `--to` is after `--from`, and the window is at most 62 days. They are sent as UTC `startDateTime` and `endDateTime`; Graph returns the events that overlap the window, recurring events expanded to their occurrences (`type` `occurrence` or `exception` is `recurring: true`), ordered by `start/dateTime`. `--max` is 1 to 250 (default 250); the pages (50 events each) are read by the whole `@odata.nextLink`, never by editing `$skip`, and `truncated` is `true` when more exist.
- **Times are UTC.** Every `calendarView` request, on every page, asks `Prefer: outlook.timezone="UTC"` (the other requests ask for no header), so Graph returns UTC, and the runtime converts to the person's zone with `zoneinfo`. A timed event prints `start` and `end` as `YYYY-MM-DDTHH:MM:SSZ`; an all-day event prints a bare date (`all_day: true`; its `end` is the service's, the day after the last). An event Graph gives in a time zone other than UTC is **not guessed at**: it is counted in `skipped`, an anomaly counter now that UTC is asked for (with those that lack an id, a start or an end).
- `etag` is the event's `changeKey`. `response` is the person's own answer: `accepted`, `tentative` (Graph's `tentativelyAccepted`), `declined`, `needsAction` (`notResponded`); `null` for the organizer, for `none` and for anything else. `status` is `cancelled` when `isCancelled`, else `confirmed`. `organizer_domain` is only the part of the organizer's address after the `@`; `online_meeting` is only whether the event has one, never its address. Title and location are one line, cut at 300 and 200 characters, with control and invisible characters removed.
- **Only these fields are asked of the service** (`$select`): `id, changeKey, subject, start, end, isAllDay, location, organizer, isOrganizer, responseStatus, isCancelled, isOnlineMeeting, type, seriesMasterId`. No body, attachment, attendee list or meeting link is asked for, and the organizer's address is received only to derive `organizer_domain` and is never printed. The stand-in service answers 403 to a `$select` that names a property `Calendars.ReadBasic` excludes, and the tests would fail.

### Errors

| Exit | When |
|------|------|
| 0 | success |
| 1 | Graph answered an error (403, 404, 429 or 503 with its `Retry-After`, a refused redirect), could not be reached, or answered a shape this provider does not understand; an access token it will not send; an unexpected failure (only its kind is printed) |
| 2 | usage: a bad flag, a flag the verb does not read, a calendar id that could leave the path, a time without an offset, a window that is backwards or longer than 62 days, `--max` out of bounds, a test override that is not loopback or not set together |
| 3 | not configured: no authorization, an unreadable record, a rejected app registration, a tenant that needs its admin's approval, a token whose scope is not exactly `Calendars.ReadBasic`, or `invalid_grant` |

A verb never retries. No redirect is followed with a credential, and a next-page address is followed only when it names the same scheme, host and port (443 written or not) as the request, no user or password, and a path inside the API (it starts, without case, with `/v1.0/`: Graph may spell the rest its own way); any other is not followed, the pages read so far are returned with `truncated: true` and a note on stderr.

### Environment variables

| Variable | Used by | Purpose |
|----------|---------|---------|
| `OUTLOOK_CALENDAR_TOKEN` | `outlook.py`, `outlook_auth.py` | The record, through the secret resolver (the environment, the credentials directory, then the OS secret store). |
| `OUTLOOK_CALENDAR_CLIENT_ID`, `OUTLOOK_CALENDAR_TENANT` | `outlook_auth.py` | Of the one `authorize` command only: the Application (client) ID of the calendar registration, and a tenant (default `common`). |
| `INTEGRATION_CALENDAR_PROVIDER` | `providers/resolve.py` | Selects the implementation of the class. |
| `INTEGRATION_CALENDAR_OUTLOOK_API_BASE`, `INTEGRATION_CALENDAR_OUTLOOK_TOKEN_URL` | both | Tests only: loopback URLs of a fake Graph and a fake token endpoint, set together; the secret store is then never read or written. |

### Calls this provider makes

| Call | Used for | Source (read 2026-10-17 by the author of the plan; not read again for this package) |
|---|---|---|
| `GET https://graph.microsoft.com/v1.0/me/calendarView?startDateTime=&endDateTime=&$select=&$orderby=&$top=` | `events --calendar default` | [List calendarView](https://learn.microsoft.com/en-us/graph/api/user-list-calendarview?view=graph-rest-1.0) |
| `GET .../me/calendars/{id}/calendarView?...` | `events --calendar <id>` | the same page |
| `GET .../me/calendars?$select=id,name,isDefaultCalendar,canEdit&$top=50` | `calendars` | to verify |
| `POST https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token` | the code exchange and every refresh (the only POST) | [Refresh tokens in the Microsoft identity platform](https://learn.microsoft.com/en-us/entra/identity-platform/refresh-tokens) [M5] |

Permission source: [Microsoft Graph permissions reference](https://learn.microsoft.com/en-us/graph/permissions-reference) (`Calendars.Read`, `Calendars.ReadBasic`, read 2026-10-17 by the author of the plan, not read again here).

### To verify on first use (the live step of the package; nothing here was run against Microsoft)

The tests use a stand-in service that serves what the plan's reading of the reference says, so each item below is a fact the stand-in encodes and the live service has not confirmed.

1. **`GET /me/calendars` under `Calendars.ReadBasic`**, with `$select=id,name,isDefaultCalendar,canEdit` (a 403 is exit 1 from `calendars`; `events --calendar default` does not need it).
2. **The shape of a calendar id** (the provider accepts `[A-Za-z0-9=_-]{1,256}`), and the path of `calendarView` for a calendar other than the default one.
3. **That `$select` of `organizer`, `isOrganizer`, `responseStatus`, `isOnlineMeeting`, `type` and `seriesMasterId`** is served under `Calendars.ReadBasic`, and that no `$select` is rejected for a name it needs.
4. **The time zone of the events returned** with `Prefer: outlook.timezone="UTC"` (that the header is honoured on a next page too): the provider expects `UTC` for every event and counts any other in `skipped`. For an all-day event, whether `start.dateTime` carries the event's own date at midnight (the provider prints the date part of what arrives).
5. **The next link.** How Graph spells the `@odata.nextLink` of `calendarView` (the provider accepts the request's scheme, host and port and any path under `/v1.0/`, read without case; a link it cannot follow ends the read as truncated, with a note). **The bound on a refresh token:** the provider keeps one only if it is printable ASCII of at most 4096 characters.
6. **`response` for an organizer, for an event the person did not answer and for a cancelled occurrence**, to check the mapping above against real events.
7. **The scope string** the token endpoint returns, the rotation of the refresh token on every use, that `localhost` reaches the `127.0.0.1` listener, and the error codes of a work tenant that blocks user consent: as in the mailbox README.

### Tests

`uv run --with pytest==9.1.1 pytest -q providers/calendar/tests`, against `fake_graph_cal.py` (the stand-in for the calendar side of Graph and the token endpoint, on 127.0.0.1, built on `providers/mailbox/tests/fake_microsoft.py`: it refuses a `calendarView` without its two bounds, never returns a body, attachment or attendee list, and answers 403 to a `$select` that names one). The shared code is also tested through the mailbox suite (`providers/mailbox/tests/test_msgraph_shared.py`) and the OneDrive suites.
