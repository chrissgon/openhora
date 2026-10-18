# Calendar providers

Implementations of the class `integration:calendar`: read the events of the person's own calendar, read only. The task runtime turns what a provider prints into a dated snapshot a task can be given (the sources of a project; `docs/architecture/platform/sources.md`); nothing here writes to a calendar. The interface is the row of `integration:calendar` in `providers/CONTRACT.md`. The class is found by its folder (`providers/calendar/`) and chosen with `INTEGRATION_CALENDAR_PROVIDER`, or by the runtime, which names the implementation explicitly (the origin of a calendar source starts with it).

| File | What it is |
|------|------------|
| `outlook.py` | The events of an Outlook calendar (Microsoft 365 and outlook.com) through Microsoft Graph. Delegated permission `Calendars.ReadBasic`. Python 3.10 or newer, with `keyring`: run with `uv run` |
| `outlook_auth.py` | A helper, not an implementation: the one-time authorization (and `forget`) of `outlook.py` (see "Outlook" below) |

Titles, places and calendar names are written by whoever made each calendar or event: every item says so with `external_content: true`, and the runtime hands them to a task as data, never as an instruction.

## Outlook (`outlook.py`)

Verbs: `--check`, `calendars`, `events --calendar <default|id> --from <ISO-8601 with offset> --to <ISO-8601 with offset> [--max <n>]`. Every other verb is exit 2. GET only: the token endpoint is the one POST, and a test fails on any other method.

**One permission, and what it can do.** The authorization asks for the delegated Microsoft Graph permission `Calendars.ReadBasic` and `offline_access` (the refresh token), and nothing else; the refresh request names the same scope so that the access token is no wider than asked. `Calendars.ReadBasic` reads events "except for properties such as body, attachments, and extensions", needs no admin consent and exists for personal accounts, and is the least privileged permission for `calendarView`. So no event description, attachment or extension can reach this provider, and none is asked for or printed. It does **read the events of every calendar the account can see**, and changes none; the narrowing to one calendar and a window is the runtime's, not the service's. The provider refuses a token whose reported scope is anything but `Calendars.ReadBasic` (the `offline_access`, `openid`, `profile` and `email` it may report next to it are ignored): a registration that still carries `User.Read`, `Calendars.Read`, `Calendars.ReadWrite`, `Mail.Read` or `Files.Read` is a setup error (exit 3, naming the extra scope), and so is a response that reports no scope.

**One app registration per purpose.** Microsoft documents that "refresh tokens are bound to a combination of user and client, but aren't tied to a resource" and that a client can use a refresh token for any resource it has permission for [M5]. A registration that held `Mail.Read` and `Calendars.ReadBasic` together would let the calendar's refresh token read mail. So the calendar provider has a registration of its own with `Calendars.ReadBasic` alone, its own client id and its own record (`OUTLOOK_CALENDAR_TOKEN`, entry `outlook-calendar`); the mailbox provider (`Mail.Read`) and the OneDrive provider (`Files.Read`) each have theirs. The code they share (`providers/_msgraph.py`) shares no registration and no token. A test makes the point: the calendar provider refuses the client id of the mail registration.

### Setup (once; the maintainer of the project does it, not each person)

The full steps are in `uv run <workbench>/providers/calendar/outlook_auth.py --help`. In short, at https://entra.microsoft.com:

1. Identity, Applications, App registrations, New registration: a name, the supported account types "Accounts in any organizational directory and personal Microsoft accounts". No redirect URI yet.
2. Authentication, Add a platform, "Mobile and desktop applications", custom redirect URI `http://localhost`. No client secret, no certificate.
3. API permissions: remove `User.Read`; add Microsoft Graph, Delegated permissions, `Calendars.ReadBasic` (and `offline_access`). Do not grant admin consent for a personal test.
4. Run `OUTLOOK_CALENDAR_CLIENT_ID=<the Application (client) ID> uv run <workbench>/providers/calendar/outlook_auth.py authorize` (or type the id at the hidden prompt: it never goes on the command line; an office with its own single-tenant registration also sets `OUTLOOK_CALENDAR_TENANT`, default `common`), sign in with the account whose calendar to read and approve.
5. Verify: `uv run <workbench>/providers/calendar/outlook.py --check` prints `{"ok": true, "scope": "Calendars.ReadBasic", "tenant", "obtained_at", "rotation"}`; then `... outlook.py calendars` lists the calendars (the id of one is what a calendar source names).

The authorization flow, the loopback listener, the record and its rotation are the ones of the mailbox provider (`providers/mailbox/README.md`, "Outlook"), with the record `{refresh_token, client_id, tenant, scope, obtained_at}` in the OS secret store entry `outlook-calendar` (service `openhora`), and `invalid_grant` is exit 3 with `outlook_auth.py authorize`. `forget` deletes only this provider's entry.

### Usage

```sh
uv run <workbench>/providers/calendar/outlook.py --check
uv run <workbench>/providers/calendar/outlook.py calendars
uv run <workbench>/providers/calendar/outlook.py events --calendar default --from 2026-10-17T00:00:00-03:00 --to 2026-10-24T00:00:00-03:00
```

- `calendars` prints `{"calendars": [{"id", "summary", "primary", "access_role"}], "truncated", "skipped", "external_content": true}`. `access_role` is `writer` or `reader` from Graph's `canEdit`, `null` when it is absent.
- `events` prints `{"calendar", "from", "to", "events": [...], "truncated", "skipped", "external_content": true}`, each event `{"id", "etag", "start", "end", "all_day", "title", "location", "organizer_self", "organizer_domain", "response", "status", "online_meeting", "recurring", "external_content": true}`, the shape the Google provider prints. `--calendar default` reads `GET /me/calendarView`; an id from `calendars` reads `GET /me/calendars/{id}/calendarView` (the id is checked against `[A-Za-z0-9=_-]{1,256}` and percent-encoded).
- `--from` and `--to` need a time zone offset (`Z` or `+hh:mm`, else exit 2: the provider never guesses a zone), `--to` is after `--from`, and the window is at most 62 days. They are sent as UTC `startDateTime` and `endDateTime`; Graph returns the events that overlap the window, recurring events expanded to their occurrences (`type` `occurrence` or `exception` is `recurring: true`), ordered by `start/dateTime`. `--max` is 1 to 250 (default 250); the pages (50 events each) are read by the whole `@odata.nextLink`, never by editing `$skip`, and `truncated` is `true` when more exist.
- **Times are UTC.** The provider sends no `Prefer: outlook.timezone` header, so Graph returns UTC, and the runtime converts to the person's zone with `zoneinfo`. A timed event prints `start` and `end` as `YYYY-MM-DDTHH:MM:SSZ`; an all-day event prints a bare date (`all_day: true`; its `end` is the service's, the day after the last). An event Graph gives in a time zone other than UTC is **not guessed at**: it is counted in `skipped` (with those that lack an id, a start or an end).
- `etag` is the event's `changeKey`. `response` is the person's own answer: `accepted`, `tentative` (Graph's `tentativelyAccepted`), `declined`, `needsAction` (`notResponded`); `null` for the organizer, for `none` and for anything else. `status` is `cancelled` when `isCancelled`, else `confirmed`. `organizer_domain` is only the part of the organizer's address after the `@`; `online_meeting` is only whether the event has one, never its address. Title and location are one line, cut at 300 and 200 characters, with control and invisible characters removed.
- **Only these fields are asked of the service** (`$select`): `id, changeKey, subject, start, end, isAllDay, location, organizer, isOrganizer, responseStatus, isCancelled, isOnlineMeeting, type, seriesMasterId`. No body, attachment, attendee list or meeting link is asked for, and the organizer's address is received only to derive `organizer_domain` and is never printed. The stand-in service answers 403 to a `$select` that names a property `Calendars.ReadBasic` excludes, and the tests would fail.

### Errors

| Exit | When |
|------|------|
| 0 | success |
| 1 | Graph answered an error (403, 404, 429 or 503 with its `Retry-After`, a refused redirect, a next-page address that leaves the request), could not be reached, or answered a shape this provider does not understand; an access token it will not send; an unexpected failure (only its kind is printed) |
| 2 | usage: a bad flag, a flag the verb does not read, a calendar id that could leave the path, a time without an offset, a window that is backwards or longer than 62 days, `--max` out of bounds, a test override that is not loopback or not set together |
| 3 | not configured: no authorization, an unreadable record, a rejected app registration, a tenant that needs its admin's approval, a token whose scope is not exactly `Calendars.ReadBasic`, or `invalid_grant` |

A verb never retries. No redirect is followed with a credential, and a next-page address is followed only when its scheme, host, port and path are the first request's own.

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
4. **The time zone of the events returned** without a `Prefer: outlook.timezone` header: the provider expects `UTC` for every event and counts any other in `skipped`. For an all-day event, whether `start.dateTime` carries the event's own date at midnight (the provider prints the date part of what arrives).
5. **The next link.** That the `@odata.nextLink` of `calendarView` has the same path as the request (the provider refuses any other path).
6. **`response` for an organizer, for an event the person did not answer and for a cancelled occurrence**, to check the mapping above against real events.
7. **The scope string** the token endpoint returns, the rotation of the refresh token on every use, that `localhost` reaches the `127.0.0.1` listener, and the error codes of a work tenant that blocks user consent: as in the mailbox README.

### Tests

`uv run --with pytest==9.1.1 pytest -q providers/calendar/tests`, against `fake_graph_cal.py` (the stand-in for the calendar side of Graph and the token endpoint, on 127.0.0.1, built on `providers/mailbox/tests/fake_microsoft.py`: it refuses a `calendarView` without its two bounds, never returns a body, attachment or attendee list, and answers 403 to a `$select` that names one). The shared code is also tested through the mailbox suite (`providers/mailbox/tests/test_msgraph_shared.py`) and the OneDrive suites.
