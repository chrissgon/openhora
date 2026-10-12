# Store providers

Implementations of the `store:runtime` class (`store` until 2026-10-02; the folder and `STORE_PROVIDER` keep that name): the durable state of the agent runtime (backlog R2). Interface: `providers/CONTRACT.md`. Selected with `STORE_PROVIDER=sqlite`. The first runtime (`scripts/runtime.py`) calls the store only through its CLI; the task runtime (`runtime/ops.py`) imports the functions of the implementation the class resolves to and calls them, one call per transaction (the paragraph below the table). The verbs are the class's interface; the task functions are the task runtime's own persistence, not a substitutable class, and no second backend is promised (decision D2 of the architecture fixes in `docs/decisions.md`).

The decision behind it is in `docs/decisions.md` ("2026-09-28: An agent runtime as a new, tool-free layer; storage behind an interface"): a Markdown file does not take several agents writing at once, so state that agents write goes to a store.

## SQLite (`sqlite.py`)

Standard library only (`sqlite3`); runs with `python3` or `uv run`. No credential: the database is a local file.

### Tables

| Table | What it holds | Written by |
|-------|---------------|------------|
| `schema_version` | one row per applied migration | `init` |
| `cursors` | where a trigger source left off, by name (for example the mailbox "since" time) | `cursor-set`, `cursor-clear` (the cursor is absent again) |
| `events` | triggers to handle (a notification e-mail, a calendar time), one per source and external id, with a status: `pending`, `claimed`, then `done`, `failed` or `to_inbox` | `event-add`, `event-next`, `event-done` |
| `runs` | one row per agent run (backlog R7): agent, triggering event, status, exit code, cost, tokens, duration, output folder, error | `run-start`, `run-end` |
| `inbox` | what waits for the user (backlog R5): kind, title, the payload as JSON and the approval hash the caller gave (`--payload-sha256`: the SHA-256 of what the person approves, in the sense of `contracts/environment.md`; it may be the hash of a file the payload only points to, and the store does not compare it with the payload), status `open`, then `approved`, `rejected` or `done`, and who decided when | `inbox-add`, `inbox-resolve` |
| `actions` | every outward action the runtime executed: kind, idempotency key (unique), target, payload hash, the provider's result | `action-add` |
| `tasks` | the task runtime (`runtime/`, schema version 2): a request (no parent, no skill) and the tasks of its plan, each with its skill, its text, the tasks it depends on and a state: `requested`, `planned`, `ready`, `running`, `waiting`, `blocked`, `done`, `failed` or `cancelled`; since schema version 4 also the task's item on the task board (`remote_id`, `remote_version`, `remote_written_sha256`, the hash of what the runtime last wrote to it) | the functions `request_add`, `task_claim_next`, `task_run_finish`, `pending_resolve`, `task_retry`, `task_fail_running`, `request_cancel`; since version 4 `task_remote_set`, `task_edit` (a person's edit, refused on a running, done or cancelled task), `request_from_board`, `acceptance_resolve`, `plan_approve`, `plan_reject` |
| `task_runs` | one row per run of a skill on a task: skill version and content hash, model, adapter, whether it had the web, how it failed or how it ended, attempts, cost, tokens, duration, the image's digest, the run folder, and (schema version 3) the number of passed values the lab replaced in what the run left, NULL when not reported, and (schema version 9) `billing`, how the credential the run used is billed (`subscription`, `metered`, `free`, or `unknown` when no manifest could bill the route; NULL for a run older than the column), which the daily caps of the runtime count by | `task_run_start`, `task_run_finish`, `task_fail_running` |
| `pending_decisions` | what a task waits for the person to decide, of a closed list of kinds (`plan`, `question`, `review`, `effect`, `acceptance`, `your_document`): title, body (a model's reply, kept as given), a payload, an optional payload hash, status `open`, `resolved` or `cancelled`, the resolution and the answer | `task_run_finish`, `pending_resolve`, `request_cancel`; since version 4 `route_run_finish` (the router's `plan` or `question`, on the request), `plan_open` (a plan of a flow the person named), `plan_approve`, `plan_reject`, `request_from_board`, `acceptance_resolve` |
| `document_records` | schema version 4: one row per document mirrored to a platform, by its path relative to the project: the provider, the page's id there, the hash of what the runtime last wrote and last read, the version the platform reported (opaque text, compared only for equality), a status `mirrored`, `read_only` or `rejected`, a note | `document_put` (only the fields given change) |
| `platform_comments` | schema version 4: comments read from a platform and saved before a page or an item is replaced, once per provider and comment id: the task or the document they belong to, author, text, a status `open`, `used` (by the pending decision whose answer they entered) or `dismissed` | `comments_save`, `comments_use` |
| `approvals` | schema version 5: what the person approved, of the three scopes of `contracts/environment.md`: `action` (one open `effect`, bound by the hash of its exact content: `pending-execution`, then `executed` once code executed it), `plan` (one hash of a batch: `pending-execution`) and `standing` (a policy with its bounds, the hash of its bounds file and an expiry: `active`, then `expired`). A record that only grows (limit L13): no row is deleted, only the status and `executed_at` change, and a status moves only forward (`pending-execution` to `executed` or `revoked`, `active` to `expired` or `revoked`); triggers refuse anything else at the database too. Answering, rejecting or cancelling an `effect` revokes its `pending-execution` approval in the same transaction | `approval_add` (approving twice returns the same row), `approval_get`, `approvals_list`, `approval_revoke`, `approvals_expire`, `effect_done` (after code executed the effect: the pending decision `approved`, the approval `executed`, the task `done`, all or nothing); `pending_resolve` takes `answered` or `rejected` for an `effect` |
| `conversation_messages` | schema version 6: the conversation with the planning agent, one row per message: the conversation's name, the role (`user` or `assistant`), the text as given, the task and the run it refers to | the function `message_add` (read by `messages_list`) |
| `task_waits` | schema version 8: the derived waits between requests (`contracts/runtime.md`, "Derived waits"): a planned task waits for another task (`input`: a path that task's skill writes), for a whole request (`after`, the person's override, kept in `tasks.after_request`); each with its reason, a status `open`, `cleared` or `dropped` (the person went ahead on that very wait: it is not derived again), and who ended it. A task with an open wait is given out to no one (`task_claim_next`, `task_claim`); a wait whose awaited row is `done` or `cancelled` ends in the transaction that moved it. A record that only grows (limit L13): a trigger refuses to delete a row | `waits_list`, `waits_sync`, `waits_go_ahead`, `request_after_set`; `request_add`, `plan_approve`, `tasks_add`, `acceptance_resolve` and `task_retry` take the waits their tasks begin with, and `request_add` and `request_from_board` the `after` of a new request |

The task runtime's tables (every table after `actions`) have no verb. Their contract is the functions named in the table, in the section "the task runtime" of `sqlite.py`: `runtime/ops.py` imports the implementation the class resolves to and calls them, and one call is one transaction, so a step that ends a run, opens a pending decision and moves its task is all or nothing. A task in `waiting` always has an open pending decision; one task of a database runs at a time. Since schema version 7 the database refuses to delete a row of `tasks`, `task_runs` or `pending_decisions` (and since 8 of `task_waits`; limit L13, triggers like those of `approvals`): a state, a status or a resolution moves, and the row stays. A request is never given out to run: the router's run on it (`route_run_start`) is a row of `task_runs` whose task is the request, the request stays `requested` until a person approves its plan, and an answer to the router's question leaves it `requested`. A `plan` is resolved only by `plan_approve` or `plan_reject`, an `acceptance` only by `acceptance_resolve`. `export` prints them with the others. Since schema version 6 the dispatcher and the planning agent also have `task_claim` (one named `ready` task, never while another runs), `tasks_add` (tasks added to a planned or a done request, which is then `planned`), `runs_since` (a period's runs with the agent of their task), `acceptance_open` (an `acceptance` of `subtasks` or `deliveries`, its payload's `what`; `acceptance_resolve` adds accepted sub-tasks in the same transaction), and `action_add` and `action_count`, which do the work of the verbs `action-add` and `action-count` through the same internal code. A task of a plan, of `tasks_add` and of an accepted sub-task carries its area agent (`agent`) when the item names one. `approval_standing_add` records a standing approval of one policy for one agent and, in the same transaction, revokes the active one of the same policy and agent. A delivery of an approved plan is routed again after its brief with `route_run_start(..., reroute=True)` on a `planned` or `done` request, and that run's `route_run_finish` opens an `acceptance` (never a plan or a question) whose state change waits for the person.

`action-count --kind reply --since <start of day>` is how a daily limit is enforced; `actions` and `export` are the audit. `runs`, `inbox-list` and `actions` stop at `--limit` and then print `"truncated": true`; `inbox-list --id <id>` reads one item whatever its status, so an item past the limit can still be reached.

### Guarantees

- **Several writers.** WAL mode (readers never wait for the writer), a 10-second busy timeout, and every write in one `BEGIN IMMEDIATE` transaction: several agents and overlapping scheduler firings can write at once, and each verb's change is all or nothing. A write still blocked after 10 seconds fails with exit 1 and changes nothing.
- **A change counter.** Every write transaction that changed at least one row raises the integer kept in the database file's header (`PRAGMA user_version`, read by `change_counter`) in the same transaction, so a reader learns with one read of the header that something was written, whoever wrote it. A transaction that changed nothing (a dispatcher tick with nothing ready) and one that is rolled back leave it alone; after 2,147,483,647 it starts again at 1. It is a signal and not a record: nothing is deleted or added, and a database written by an older script reads 0. `cursor_peek` reads a cursor with one plain `SELECT` and no transaction, for a reader that asks every second and must not wait for a writer.
- **One event per notification.** `event-add` is unique on source and external id; adding the same e-mail twice returns the first event with `"created": false`.
- **One claimant per event.** `event-next` claims inside one transaction and gives each event a fresh claim token; two overlapping ticks never receive the same event (tested with several processes). A claim older than `--reclaim-after-minutes` (default 60, at least 1) returns to pending on the next `event-next` for that source, for a run that crashed; an event already claimed 5 times whose claim expired again is not handed out a sixth time: it ends `failed` with a note, and `event-next` lists its id in `failed`. The old token is then refused by `event-done` (exit 1), so a late run cannot overwrite the new claimant's result. `event-done` with the same token and status twice is harmless (`"already": true`).
- **One open item per event and kind.** `inbox-add --event-id <id>` for an event that already has an open item of that kind returns that item with `"created": false` and adds nothing, so an event escalated twice makes one item.
- **Forward-only inbox.** `open` becomes `approved`, `rejected` or `done`; `approved` becomes `done`; nothing else. Who approved and who marked it done are kept separately.
- **One action per key.** `action-add` with a key already recorded returns the first action when kind, target and payload hash match, and fails with exit 1 when they differ.
- **External text is data.** Payloads may hold text written by other people (a comment in a notification e-mail). The store keeps the file's text exactly as given, only checks that it is UTF-8 JSON under the cap, and never interprets it. Every SQL statement is a constant with parameters.
- **Caps.** Payload and result files 64 KiB; notes, errors and cursor values 4 KiB; titles 1 KiB; external ids, targets and keys 512 bytes; names, kinds, sources, agents, triggers 128 bytes. Above a cap the verb exits 2 and stores nothing. Single-line fields refuse control characters.

### Where the database lives

Wherever `--db` or `STORE_SQLITE_PATH` points; the provider picks no default, so the runtime (or the user) decides per project. Put it outside every repository: it holds the agent's work data. `init` creates a missing folder 0700 and the file 0600, and resets the file (and its `-wal` and `-shm` files) to 0600 if it was loosened; `--check` warns when the file or its folder is readable by others.

### Usage

```sh
export STORE_SQLITE_PATH="$HOME/agent-state/agent.sqlite"
python3 providers/store/sqlite.py init
python3 providers/store/sqlite.py --check
python3 providers/store/sqlite.py event-add --source mailbox --external-id '<message id>' --payload-file event.json
python3 providers/store/sqlite.py event-next --source mailbox --limit 5
python3 providers/store/sqlite.py event-done --id 12 --token <claim token> --status done
python3 providers/store/sqlite.py run-start --agent example-agent --event-id 12 --trigger mailbox
python3 providers/store/sqlite.py run-end --run-id 7 --status ok --exit-code 0 --cost-usd 0.04 \
    --tokens 12000 --duration-ms 65000 --out-dir /path/to/run
python3 providers/store/sqlite.py action-count --kind reply --since 2026-09-29T00:00:00-03:00
python3 providers/store/sqlite.py export --format json --since 2026-09-28T00:00:00Z
```

`run-end` takes `null` for a number the run did not report (`timing.json` of an adapter has nulls when unknown). Every verb prints JSON; `--help` lists the verbs and their flags. Exit codes: 0 success, 1 store error (locked past the timeout, no such id, a lost claim, a conflicting key, a schema newer than the script), 2 usage error (including a value over its cap), 3 not configured (no database path, no database, or a schema that needs `init`).

### Schema changes

`init` applies the migrations the file does not have yet, in one transaction, and records each in `schema_version`; running it again changes nothing. Every other verb refuses a database whose version differs from the script's (exit 3 when older: run `init`; exit 1 when newer). A new migration is a new numbered entry in `MIGRATIONS` in `sqlite.py`, never an edit of an applied one.

### Backup

The database is one file plus its WAL. Copy it while no agent writes, or use SQLite's online backup, which is safe while others write:

```sh
sqlite3 "$STORE_SQLITE_PATH" ".backup '$HOME/agent-state/backup-$(date +%F).sqlite'"
```

Copying only the `.sqlite` file while a `-wal` file exists can miss the latest writes. `export --format json` is a readable dump, not a restorable backup.

### Tests

`uv run --with pytest==9.1.1 pytest providers/store/tests`: offline, one temporary database per test; the concurrency tests start several processes that claim events and add the same notification at once.
