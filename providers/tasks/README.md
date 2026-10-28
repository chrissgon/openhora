# Tasks providers

Implementations of the `integration:tasks` class (package CB-4, SPEC-CATALOG-BATCH): the person's task lists and the open tasks of one list, read only. Interface: `providers/CONTRACT.md` (the `integration:tasks` row). The class is for the runtime (the answer to "what is on my task list", package CB-5), not for a skill: it is in `providers/resolve.py` `ROLES` as an integration (folder `providers/tasks/`, variable `INTEGRATION_TASKS_PROVIDER` alone) and in neither `LISTED` nor `contracts/environment.md`. The writers of the same two services are `providers/writer/google-tasks.py` and `microsoft-todo.py` (`providers/writer/README.md`).

| | `google.py` | `microsoft.py` |
|---|---|---|
| Service | Google Tasks (`https://tasks.googleapis.com`) | Microsoft To Do through Graph (`https://graph.microsoft.com/v1.0`) |
| Token | `GOOGLE_ACCOUNT_TOKEN`, the five scopes (`tasks` among them) | `MICROSOFT_ACCOUNT_TOKEN`, the six permissions (`Tasks.ReadWrite` among them) |
| `lists` | `GET /tasks/v1/users/@me/lists` (one page of at most 100); `default` is `null` for every list: the reference marks none | `GET /me/todo/lists`; `default` is true for the list Graph marks `defaultList` |
| `open --list <default\|id> [--max n]` | `GET /tasks/v1/lists/{list}/tasks` with `showCompleted=false`, `showHidden=false`, `showDeleted=false`, `maxResults=<n>` and a `fields` list that names no due date, note or parent; `default` is the literal `@default` | `GET /me/todo/lists/{id}/tasks`, no OData parameter, pages followed by a next-page address only when it is the request's own (at most 10 pages), tasks whose status is `completed` left out; `default` is found first with `GET /me/todo/lists` |
| A task | `{id, title, updated, etag}` (`etag` and `updated` are the service's own) | `{id, title, updated (lastModifiedDateTime), etag (@odata.etag)}` |

Both send GET only (and the token POST), on two paths each, refuse any other method or path before a connection opens (limit L58), print no title on stderr, print a title on one line (control and invisible characters removed, at most 200 characters) and say `external_content: true`. **No due date** is asked of either service or printed: the maintainer decided on 2026-10-27 that v1 has none (OPEN-CB-11).

**The scope rule.** The two providers refuse a token made before the Tasks scope was added (Google's four scopes, Microsoft's five permissions) with exit 3 and the authorize command named, and a token with a stranger beside the set; every other provider of the account keeps working with the previous set until the person authorizes again (`contracts/secrets.md`, "The transition"). No `--check` was run against a real account: every test is against a stand-in service on 127.0.0.1.

## Sources (accessed 2026-10-27)

Google: [service endpoint and methods](https://developers.google.com/workspace/tasks/reference/rest), [tasklists.list](https://developers.google.com/workspace/tasks/reference/rest/v1/tasklists/list), [tasks.list](https://developers.google.com/workspace/tasks/reference/rest/v1/tasks/list), [the Task resource](https://developers.google.com/workspace/tasks/reference/rest/v1/tasks), [scopes](https://developers.google.com/workspace/tasks/auth). Microsoft: [List lists](https://learn.microsoft.com/en-us/graph/api/todo-list-lists?view=graph-rest-1.0), [todoTaskList](https://learn.microsoft.com/en-us/graph/api/resources/todotasklist?view=graph-rest-1.0), [List tasks](https://learn.microsoft.com/en-us/graph/api/todotasklist-list-tasks?view=graph-rest-1.0), [todoTask](https://learn.microsoft.com/en-us/graph/api/resources/todotask?view=graph-rest-1.0).

## To verify on first use (not stated by the vendors' pages, or not checked against the live service)

- **Google's default list.** No page of the Tasks reference mentions `@default`; Google's own Ads Scripts example uses it as the id of the list in the calls that list, insert and update tasks ([google-tasks example](https://developers.google.com/google-ads/scripts/docs/examples/google-tasks)). `--list default` sends it. The reference marks no list as the default one, so `lists` cannot say which list is.
- **Microsoft's query parameters.** The pages for listing lists and tasks say the endpoints support "some of the OData query parameters" and name none, so none is sent. A list with many completed tasks may need several pages to reach its open ones (at most 10 are read; `truncated` says when more were left). Whether `$filter=status ne 'completed'`, `$top` or `$select` work there is for the first live use.
- **Google's page size.** `maxResults` is at most 100 (the page says so); a list with more open tasks than `--max` is `truncated`.
- **Titles.** Google allows a title of 1,024 characters and the Graph page states no limit; both providers cut at 200 characters.
