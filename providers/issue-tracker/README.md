# Task-board providers

Implementations of the `integration:issue-tracker` class: the task board of the task runtime (`runtime/`), where a person sees and edits the tasks of a project. Interface: the class's row in `providers/CONTRACT.md` ("Verbs per class"): `--check`, `list`, `get`, `upsert`, `resolve`, each with `--config-file <f>`, a JSON file holding the project configuration's `task_board` object (`docs/workbench/runtime.json`).

The board owns only what a person edits on a task: its title, its text, its state and its comments. Everything else stays in the runtime's store and is shown on the item (`shown`), never read back. A provider never reads the store or anything under `runtime/`.

| Implementation | Where the board is | Select with |
|----------------|--------------------|-------------|
| `local.py` | a folder of Markdown files on the machine, one per item | `"task_board": {"provider": "local", "dir": "<absolute folder>"}` |
| `notion.py` | a base (data source) of a Notion workspace, one row per item | `"task_board": {"provider": "notion", "base": "<data source id>", "expires": "YYYY-MM-DD", "fields": {}, "states": {}}` |

## Local (`local.py`)

Standard library only; runs on Python 3.9. No credential, no network. The board is the folder `dir`: `<dir>/<id>.md` per item, the id lowercase letters, digits and hyphens. An item the provider creates is `t<n>`; a file a person writes by hand in the folder is an item too, and one with no `State:` line is `requested`. The file:

```markdown
# <title>

State: <state>

<text, any Markdown>

## Comments

- <one comment per line>

## Runtime

- <key>: <value>
```

`version` is the sha256 of the file's bytes without its `## Comments` section, so it changes with any edit of the content and never with a comment alone; `comments` lists the comments whatever the version. A write goes through a temporary file and `os.replace`, keeps every part the item file does not name (a person's title, text and comments survive a write of the state), and writes `## Runtime` from `shown`. The key of a creation is kept in `<dir>/.keys.json`, so the same key never creates twice; `resolve` records what a person found for a key. `list` skips every file whose name starts with a dot.

## Notion (`notion.py`)

Python 3.10 or newer, with `keyring` (its header): run with `uv run`, never with the system interpreter. The token is `NOTION_TOKEN`, read only through `providers/secrets/resolver.py` (stored with `uv run --with keyring==25.7.0 keyring set openhora notion`): an internal integration with read content, update content, insert content and read comments, given only the base. Neither the base's identifier nor the token is ever written in this repository: they live in the project's `docs/workbench/runtime.json` and in the secret store.

- `base` is the identifier of the base's data source (in the app: the base's settings, "Manage data sources", "Copy data source ID"). API version 2026-03-11 queries rows and creates them on a data source, not on a database.
- `fields` maps `title`, `state` and `shown` to the names of the base's properties (defaults `Name`, `Status`, `Runtime`): a title, a status or select, and a text property. `--check` refuses (exit 3) a base that lacks one.
- `states` maps each of the nine task states to the option the base uses (default: the state's own word); two states on one option is a usage error. An option the map does not know is read as `null`; a row with no option is `requested`, as a local item with no `State:` line.
- The item's text is the body of the row's page, converted by `providers/documents/notion_blocks.py`, loaded by path: the only file this script loads from another class's folder (a test asserts it). `shown` is written to the shown property as `key: value` lines and never read back.
- `version` is the page's `last_edited_time`; `archived` is true when the page reports `in_trash`, `is_archived` or `archived` (the reference names all three across its pages). `list` takes rows from one paginated query; `get` adds the body at every depth and the open comments of the page and of each block of the body, each once (a comment on a block is listed under that block only, measured, N4); a row in the trash is got as `archived` with no text and no comments, since its body cannot be listed (measured, N8). The version is rounded to the minute and a comment does not move it (measured, N1 and N3), so the version covers the content and `comments` lists the row's own comments in one listing whatever the version; the runtime calls it for every item it knows at every pull, and the comments on the body's blocks come with `get` (WP-3.15).
- An `upsert` on an existing row reads it first and sends only the properties that differ, and replaces the body only when its text differs, so a write of a value already there changes nothing. A body is replaced by appending the new blocks first and deleting the old ones after, so a failure never leaves the row empty.
- At most one row per idempotency key: the key is pending in the ledger (`issue-tracker-notion.json` in the data folder, 0600; `INTEGRATION_ISSUE_TRACKER_NOTION_LEDGER` names another file) before the creation and done after it, scoped by the base. A 4xx other than 408 and 429 releases it; anything else keeps it pending until `resolve`. No verb retries: a 429 or a 5xx is exit 1 with the status (and `Retry-After`) on stderr.
- No redirect is followed. `INTEGRATION_ISSUE_TRACKER_NOTION_API_BASE` replaces the service's address for tests only, and only with a loopback URL (exit 2 otherwise); the secret store is then never read.

Choices made where the plan left one (the supervisor's rule: the smallest call table the verbs need): the board is read by one query of the data source, never per row; the type of the state property is read from the row (or, for a creation, from the data source), not configured; the body of a creation is appended after the row is created, so the creation itself carries properties only.

### Calls this provider makes

The one table of calls is `CALLS` at the top of `notion.py`; every row below is read from the public reference, none from memory.

| Method and path | Used for | Reference | Read on |
|---|---|---|---|
| `GET /v1/data_sources/{id}` | `--check`; the state property's type before a creation | https://developers.notion.com/reference/retrieve-a-data-source | 2026-10-06 |
| `POST /v1/data_sources/{id}/query` | `list` | https://developers.notion.com/reference/query-a-data-source | 2026-10-06 |
| `GET /v1/pages/{id}` | `get`; an `upsert` reads the row first and its version after | https://developers.notion.com/reference/retrieve-a-page | 2026-10-06 |
| `POST /v1/pages` | `upsert` without `--id`: a row, `parent` `{"type": "data_source_id", "data_source_id": <base>}` | https://developers.notion.com/reference/post-page | 2026-10-06 |
| `PATCH /v1/pages/{id}` | `upsert`: the properties that differ | https://developers.notion.com/reference/patch-page | 2026-10-06 |
| `GET /v1/blocks/{id}/children` | `get`, `upsert`: the body, at every depth (`has_children`) | https://developers.notion.com/reference/get-block-children | 2026-10-06 |
| `PATCH /v1/blocks/{id}/children` | `upsert`: the body, 100 children per call, a block's children under it in later calls | https://developers.notion.com/reference/patch-block-children | 2026-10-06 |
| `DELETE /v1/blocks/{id}` | `upsert`: the old body, after the new one is appended | https://developers.notion.com/reference/delete-a-block | 2026-10-06 |
| `GET /v1/comments?block_id={id}` | `get`: the open comments of the row's page, then of each block of its body (one call per block); `comments`: the row's own, one listing | https://developers.notion.com/reference/list-comments | 2026-10-06 |
| (every call) | Headers of every call: `Authorization: Bearer <token>`, `Notion-Version: 2026-03-11` | https://developers.notion.com/reference/versioning | 2026-10-06 |
| (every call) | Pagination: `page_size` 100 (the maximum), `start_cursor` from `next_cursor` while `has_more` | https://developers.notion.com/reference/intro | 2026-10-06 |
| (every call) | Limits: 100 children per append, two levels of nesting per request, 2,000 characters per text object, 1,000 block elements and 500 KB per request; 429 `rate_limited` with `Retry-After`; 180 requests a minute (600 on Business and Enterprise plans) | https://developers.notion.com/reference/request-limits | 2026-10-06 |
| (every call) | Errors: 401 a token the service rejects (exit 3), 403/404 an object missing or not shared with the integration, 409, 429, 5xx | https://developers.notion.com/reference/status-codes | 2026-10-06 |

## Measured on the live service

The ten measurements of the platform plan (stage 3, WP-3.10, step 4), made on a scratch page and a scratch base of the maintainer's workspace with the provider's own verbs and, where no verb exists, the smallest direct call, the token read from the secret store. The person's actions (an edit, a comment, archiving) were made through the API where the API allows it; each row says so, and what is still to be done by hand. Each row is written as observed: the command, what it printed with identifiers removed, the date; times are UTC. Where a row is not measured, the code follows the public reference and the stand-in service of the tests decides what the reference leaves open (`tests/fake_notion.py` of the documents class says what).

| # | What is not known | Observed | Date |
|---|---|---|---|
| N1 | Which field of a page says it changed, and how fine it is | By API, not by hand: a paragraph's text changed with `PATCH /v1/blocks/{id}`. The page's `last_edited_time` is rounded to the minute: `write` at 04:52:20Z printed `"version": "2026-10-06T04:52:00.000Z"`; two edits between 04:52:30Z and 04:52:33Z, each followed by `stat`, left `04:52:00.000Z`; an edit at 04:53:11Z moved it to `04:53:00.000Z` on the next `stat`. Two edits within one minute give one version, so the read before every write is the only guard for that minute. An edit by hand: not measured yet | 2026-10-06 |
| N2 | Whether the runtime's own write moves that field, and to what | `write --id <page>` at 04:54:04Z printed `"version": "2026-10-06T04:54:00.000Z"`; `stat` at 04:54:08Z and at 04:55:10Z both printed `04:54:00.000Z`. The runtime's own write moves the version to the minute of the write, and it stays there | 2026-10-06 |
| N3 | Whether a comment moves that field | By API, not by hand: `POST /v1/comments` on the page at 04:55:18Z; `stat` before, 2 s after and 22 s after all printed `04:54:00.000Z`. A comment on a paragraph at 05:02Z left `04:56:00.000Z` likewise. A comment does not move the version, so a comment alone causes no read; the contract's "`version` changes whenever ... the comments ... change" does not hold for this field (the stand-in no longer moves it either: its version covers the content only, since `f73f69e`, #171). A comment by hand: not measured yet | 2026-10-06 |
| N4 | Whether replacing a page's content deletes its open comments, and whether a comment on one block is listed with the page's | By API, not by hand: a comment on a paragraph (`parent.block_id`) was not listed by `GET /v1/comments?block_id=<page>` (only the page's own comment was), and was listed by `?block_id=<paragraph>`. After `write --id` replaced the body, the comment was not deleted: the page's listing then held it (`parent` still `block_id`, `original_content_deleted: true`), and the deleted block's listing returned it with an empty `rich_text`. Comments must be listed block by block: corrected, `read` and `get` now list the page and every block at every depth, each comment once (one call per block: a `read` of a 296-block page took 1 min 58 s, with no 429). A comment by hand: not measured yet | 2026-10-06 |
| N5 | Whether resolved comments are listed | Not measured by hand yet: a comment can only be resolved by hand, and no comment was resolved. Observed instead: a listed comment carries `created_by`, `created_time`, `discussion_id`, `display_name`, `has_pending_attachments`, `id`, `last_edited_time`, `object`, `original_content_deleted`, `parent`, `rich_text`; none of them says resolved | 2026-10-06 |
| N6 | The limits: child blocks per call, nesting depth per call, calls per second, and what too many requests answers | By direct call: an append of 101 children answered 400 `validation_error` "body.children.length should be ≤ `100`, instead was `101`"; an append whose list is nested three levels below the top answered 400 `validation_error` (the third level's `children` "should be not present"); two levels passed. `write` of a 296-block document (293 at the top, a list nested three deep) took 11 s and `read` returned exactly `notion_blocks.round_trip` of the source. No 429 was answered in this session (about 300 calls one after another ran at about 2.5 a second); a 429 was not provoked, so what it answers is the reference's, not observed | 2026-10-06 |
| N7 | Whether the live service returns the block shapes `notion_blocks.py` writes | `write` then `read` of each editable type's fixture (`biz-icp-positioning` icp.md, `biz-market-analysis` market.md, `brand-guidelines` guidelines.md, `brand-strategy` strategy.md): each `read` equals the offline `round_trip`, and each passes live (`check_refs.py`, `lint_icp.py`, `lint_market.py` and `check_guide.py` exit 0 with `ok: true`; `brand-strategy` loses no word). No type is set to `read_only` | 2026-10-06 |
| N8 | How an item deleted or archived by a person is reported | By API, not by hand: `PATCH /v1/pages/{id}` with `{"in_trash": true}`; the row then answers `in_trash: true`, `is_archived: false` and has no `archived` key. `list` leaves it out (`{"items": [], "truncated": false}`), so the runtime sees it as gone. `get` exited 1 with 404 on `GET /v1/blocks/{id}/children`: corrected, `get` of a row in the trash prints `archived: true`, no text and no comments (exit 0, live). Archiving by hand in the app: not measured yet | 2026-10-06 |
| N9 | Whether the rows of a base can be asked for "changed since" in one call | By direct call: `POST /v1/data_sources/{id}/query` with `{"filter": {"timestamp": "last_edited_time", "last_edited_time": {"on_or_after": "<time>"}}}` returned the row edited at 04:59 for 04:00Z and no row for 06:00Z. Rows changed since a time can be asked for in one call, to the minute. `list` is not changed: using it is a decision | 2026-10-06 |
| N10 | What the service answers when the integration was not given the page | Not measured by hand yet for a page that exists and was not shared. Observed instead: `--check` with a well-formed identifier the integration cannot see exited 3, "the parent page does not exist or the integration was not given it (Notion returned 404 on GET /v1/pages/{id}: object_not_found Could not find page with ID: <id>. Make sure the relevant pages and databases are shared with your integration "<name>".)"; the board the same on `GET /v1/data_sources/{id}`, also when `base` holds the base's database id instead of its data source id. The service's message names both causes | 2026-10-06 |

Also observed on 2026-10-06: an `upsert` of a state whose option the base's status property lacks exited 1 with "Notion returned 400 on PATCH /v1/pages/{id}: validation_error Invalid status option. Status option "planned" does not exist"; the service does not add a status option on a write. A base whose status property has fewer options than the nine states (the scratch base measured here has three) can hold only the mapped states until options are added in the app, or `fields.state` names another property.

## Tests

`uv run --with pytest==9.1.1 pytest providers/issue-tracker/tests`: offline. `test_issue_tracker_contract.py` runs the contract on every implementation the resolver lists; a new implementation adds its harness to `tests/board_harness.py` (how a person changes the board without the provider) and nothing else. The Notion harness plays the person on the stand-in service `providers/documents/tests/fake_notion.py` (127.0.0.1, a free port), shared with the documents class; `test_issue_tracker_notion.py` holds what is particular to `notion.py`.
