# Calendar providers

Implementations of the `integration:calendar` class: the calendars of the person and the events of one calendar in a window, read only. Interface: `providers/CONTRACT.md` (the `integration:calendar` row). Selected by `INTEGRATION_CALENDAR_PROVIDER`, or by being the only implementation. One implementation ships, `google.py`; a Microsoft one is a later package (`SPEC-SECRETARY-INTEGRATIONS`, M1).

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
