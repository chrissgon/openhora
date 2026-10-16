# Layer 3: providers

Part of [the platform map](README.md). Every layer page has the same eight sections, in this order.

## Purpose

A provider is a self-contained script that satisfies one requirement class (`integration:vcs`, `scheduler:job`, `publisher:<platform>`, and for the runtime alone `messenger:<platform>`) when the harness has no connector for it. A skill, the task runtime and the first runtime never name a provider: they name a class, and one function, `providers/resolve.py`, turns the class into the script that serves it. A provider executes and does not decide: the confirmation gate lives in the skill or in the runtime's code, and the provider refuses a side-effect verb that carries neither `--dry-run` nor `--confirmed`.

The contract is [providers/CONTRACT.md](../../../providers/CONTRACT.md); the classes are [contracts/environment.md](../../../contracts/environment.md); the secrets are [contracts/secrets.md](../../../contracts/secrets.md); each folder's `README.md` says what its implementations do and what was measured on the live service. This page maps them and does not repeat them. The messenger providers (`providers/messenger/`) are one feature's providers: the bridge they serve, the channel policy and the platforms are on [messaging.md](messaging.md); this page keeps what they have in common with every other provider and what makes them different.

## Artifacts it owns

Where: **repo** is this repository, **data** is the provider's data folder on the machine (`~/Library/Application Support/ai-workbench/` on macOS, `$XDG_DATA_HOME/ai-workbench/` or `~/.local/share/ai-workbench/` elsewhere), **store** is the OS secret store (service `openhora`; the service `ai-workbench` is read as a fallback for one stage, T23), **state** is the per-user state folder of the messaging bridge (`$OPENHORA_STATE_DIR`, else `$XDG_STATE_HOME/openhora`, else `~/.local/state/openhora`; mode 0700, outside every repository and every data folder). The data folder, the cache folder and the scheduler's labels keep the name `ai-workbench`: they hold state that a rename would orphan.

| Path | Where | Format | Written by | Read by | Lifecycle | Versioned | Generated |
|---|---|---|---|---|---|---|---|
| `providers/CONTRACT.md` | repo | the interface every provider implements, the verbs and the keys each verb prints, per class | maintainers | provider authors, callers | changed by pull request; a verb is added with the skill that needs it | yes | no |
| `providers/resolve.py` | repo | Python 3.9, standard library only; `LISTED`, `ROLES`, `FIXED`, `ALIASES`, `PARAMETER_ROLES`, `PLATFORM_DEFAULTS` | maintainers | skills (by command), `runtime/board.py`, `runtime/documents.py`, `runtime/effects.py`, `runtime/ops.py` (`_provider_path`), `runtime/ops_core.py` (the store), `runtime/ops_reads.py` (the connections read), `runtime/project_config.py` (`resolver()`), `runtime/handlers/published_posts.py`, `scripts/runtime.py`, `scripts/doctor.py` | a class is added here and in the environment contract in one change | yes | no |
| `providers/<folder>/<impl>.py` | repo | one script per implementation, PEP 723 header with exact pins; `auth.py` beside it is a helper, never an implementation | maintainers | the resolver (by name), its callers (by the printed path) | changed by pull request, with offline tests | yes | no |
| `providers/<folder>/tests/` | repo | pytest, offline: a stand-in service on 127.0.0.1, fake tokens | maintainers | CI, the commit hook | grows with each verb | yes | no |
| `providers/<folder>/README.md` | repo | setup, usage, calls made, live measurements | maintainers | people | updated with each verb and each measurement | yes | no |
| `providers/secrets/resolver.py` (`REGISTRY`) | repo | the one lookup of a secret by name: environment, aliases, the credentials directory, the OS store, then a password manager for a name its mapping file lists (`providers/secrets/password_managers.py`, the vendor's tool, S16) | maintainers | every provider, `runtime/ops_core.py` (its own key, registered by `runtime/secrets.json`), `runtime/ops_reads.py` (the secrets of `connections`), `runtime/lab.py` (`credential_usernames`), `evals/execution.py`, `scripts/doctor.py` | a secret is added here and in the secrets contract in one change | yes | no |
| `publisher-<platform>.json`, `vcs-github.json`, `issue-tracker-notion.json`, `documents-notion.json` | data | idempotency ledgers, mode 0600, under a file lock | the provider that owns each | that provider; `posts` reads the publisher's | grows; a pending key waits for `resolve` | no | yes |
| `scheduler/<id>/` (macOS) or the systemd user units (Linux) | data | one job folder: `job.json`, the snapshot copies (0400), `run.lock`, logs, `runs.jsonl`; `.history/` keeps the last 100 | the scheduler provider | its runner copy | moved to `.history/` when the id is scheduled again | no | yes |
| `<dir>/<id>.md`, `<dir>/.keys.json` (local board); `<dir>/<path>`, `<path>.comments.md` (local documents) | a folder the project configuration names, outside the project | Markdown items and documents, a key file | `issue-tracker/local.py`, `documents/local.py`; a person edits the Markdown | the same providers | as the board and the documents move | no | partly |
| The store's database (`--db` or `STORE_SQLITE_PATH`) | wherever the caller says; the task runtime puts it in its data folder | SQLite, WAL, 0600 in a 0700 folder; the schema version is the highest row of the table `schema_version` (`SCHEMA_VERSION`), and the header's `PRAGMA user_version` is the change counter | `providers/store/sqlite.py` only | its verbs; the task runtime through its functions; a reader of the counter (`change_counter`) | migrations only grow (`MIGRATIONS`); the counter wraps to 1 after its largest value | no | no |
| Secret records | store | one entry per store username of `REGISTRY` (an OAuth record is a JSON object written by `auth.py`) | `keyring set` by a person, or an `auth.py` after the browser consent | the resolver | replaced on a new authorization | no | no |
| `~/.cache/ai-workbench/vcs-github-work/` | the machine's cache | a shallow clone, 0700 | `vcs/github.py commit-files` | itself | removed after each call | no | yes |
| `providers/messenger/<impl>.py` (`telegram.py`, `discord.py`, `whatsapp.py`, `whatsapp-cloud.py`, `whatsapp-twilio.py`), `whatsapp_meta.py`, `discord.py.lock`, `whatsapp/` (the Go program), `README.md`, `tests/` | repo | one script per implementation of `messenger:<platform>` (each declares `PLATFORMS`), the code the two official WhatsApp providers share (its underscore keeps the resolver from listing it), the hash-locked lockfile of Discord's dependency, the Go source built on the person's machine (`go.mod`, `go.sum`), the platforms' setup and live measurements, offline tests with a fake HTTP client and server on port 0 | maintainers | the resolver (by class), the messaging bridge (through it) | changed by pull request; the repository carries source only, never a built binary | yes | the lockfile is |
| `providers/mailer/smtp.py` (`sender:email`), `README.md`, `tests/` (with `fake_mail.py`, a fake SMTP and a fake IMAP server) and `providers/_email.py` (shared: addresses, header values, the Message-ID, the rules of the connection, the MIME message) | repo | the outbox: one e-mail from the machine's one outbox account, over SMTP with TLS before any password, to exactly the recipients it is given, once; `lookup` reads the Sent folder over IMAP, read only. Python 3.9, standard library only | maintainers | the task runtime (`runtime/effect_send.py`, `runtime/ops_step_seams.py`) | changed by pull request, with offline tests | yes | no |
| `<state>/whatsapp/` (`bin/whatsapp-bridge`, `build.json`, `session.db` and its `-wal`, `-shm`, `-journal`) | state | mode 0700; the built program, the hashes of the binary and its sources (mode 0600), the keys of a linked device (mode 0600) | `whatsapp.py build`, `pair` and `listen` | `whatsapp.py`, the Go program | `build` writes it again; a logged-out device is mended by deleting `session.db` and running `pair`; excluded from backups | no | yes |
| `<state>/whatsapp-cloud/` and `<state>/whatsapp-twilio/` (`settings.json`, `seen.json`, `window.json`, `identities.json`, and for Twilio `sent.json`) | state | mode 0700, files 0600; the settings hold no secret; the others hold message ids, per-chat window times, phone numbers and sent SIDs | the provider's `setup` (settings) and `listen` (the rest), through `whatsapp_meta.Store` | the same | message ids 8 days, window rows and identities 30 days, sent SIDs 2 days; pruned at open and once a day; excluded from backups | no | yes |
| `<state>/mailer-smtp/` (`settings.json`, `ledger.json`, `ledger.lock`) | state | mode 0700, files 0600; the outbox account (address, hosts, ports, the Sent folder: no secret) and the ledger of idempotency keys (`pending` before the first connection, `done` after the server's 250 to DATA), under a file lock | `smtp.py setup` and `send` | `smtp.py` | a done key is kept; a pending key waits for the Sent folder or for `resolve` | no | yes |
| `<state>/messaging-<platform>.lock` (read by a WhatsApp provider's `whoami`) | state | the bridge's lock; a provider never takes it | the bridge | `whoami`, to refuse while a bridge holds it | held as long as the bridge runs | no | yes |

**The classes and their implementations, as built.** A row with no implementation is a reserved shape: a skill that requires it degrades as its body says.

<!-- generated: provider-classes -->
| Class | Folder | Implementation | Verbs |
|---|---|---|---|
| `publisher:<platform>` | `publisher/` | `linkedin.py` (PLATFORMS: linkedin) | `--check`, `publish`, `comment`, `resolve`, `posts` |
| `sender:email` | `mailer/` | `smtp.py` | `--check`, `send`, `resolve`, `lookup`, `setup` |
| `reader:email` | `mailbox/` | `gmail.py` | `--check`, `search`, `get`, `read-eml` |
| `messenger:<platform>` | `messenger/` | `discord.py` (PLATFORMS: discord) | `--check`, `capabilities`, `listen`, `receive`, `send`, `ack` |
| `messenger:<platform>` | `messenger/` | `telegram.py` (PLATFORMS: telegram) | `--check`, `capabilities`, `receive`, `send`, `ack` |
| `messenger:<platform>` | `messenger/` | `whatsapp.py` (PLATFORMS: whatsapp) | `capabilities`, `build`, `status`, `listen`, `receive`, `send`, `ack`, `pair`, `whoami` |
| `messenger:<platform>` | `messenger/` | `whatsapp-cloud.py` (PLATFORMS: whatsapp-cloud) | `capabilities`, `listen`, `receive`, `send`, `ack`, `setup`, `whoami` |
| `messenger:<platform>` | `messenger/` | `whatsapp-twilio.py` (PLATFORMS: whatsapp-twilio) | `capabilities`, `listen`, `receive`, `send`, `ack`, `setup`, `whoami` |
| `converter:document` | `converter/` | `container.py` | `--check`, `build`, `convert` |
| `exporter:document` | `exporter/` | `container.py` | `--check`, `build`, `render` |
| `generator:image` | `generator/` | none ships | - |
| `generator:video` | `generator/` | none ships | - |
| `search:web` | `search/` | none ships | - |
| `integration:vcs` | `vcs/` | `github.py` | `--check`, `alerts`, `dismiss-alert`, `read-file`, `commit-files`, `open-pr`, `resolve` |
| `integration:issue-tracker` | `issue-tracker/` | `local.py` | `--check`, `list`, `get`, `comments`, `upsert`, `resolve` |
| `integration:issue-tracker` | `issue-tracker/` | `notion.py` | `--check`, `list`, `get`, `comments`, `upsert`, `resolve` |
| `integration:documents` | `documents/` | `gdrive.py` | `--check`, `stat`, `read`, `pick`, `comments`, `write`, `notice`, `resolve` |
| `integration:documents` | `documents/` | `local.py` | `--check`, `stat`, `read`, `comments`, `write`, `notice`, `resolve` |
| `integration:documents` | `documents/` | `notion.py` | `--check`, `stat`, `read`, `comments`, `write`, `notice`, `resolve`, `page-create`, `table-read`, `table-create`, `rows-append`, `rows-state` |
| `scheduler:job` | `scheduler/` | `launchd.py` | `--check`, `schedule`, `list`, `cancel`, `resolve`, `run` |
| `scheduler:job` | `scheduler/` | `systemd.py` | `--check`, `schedule`, `list`, `cancel`, `resolve`, `run` |
| `store:runtime` | `store/` | `sqlite.py` | `--check`, `init`, `cursor-get`, `cursor-set`, `cursor-clear`, `event-add`, `event-next`, `event-done`, `run-start`, `run-end`, `runs`, `inbox-add`, `inbox-list`, `inbox-resolve`, `action-add`, `actions`, `action-count`, `export` |
<!-- /generated -->

Generated: the classes are the rows of the "Verbs per class" table of `providers/CONTRACT.md`, the folder is `providers/resolve.py`'s, and the verbs are read from each file's text (its `VERBS`, the choices of its `verb` argument, a `--check` flag), never by running it. Not generated: `sqlite.py`, `launchd.py`, `systemd.py` and both `local.py` are standard library only and run on Python 3.9, the two `notion.py` and `gdrive.py` run with `uv run`; `auth.py`, `gdrive_auth.py`, `gdrive_picker.py` and `notion_blocks.py` are helpers; the store's task tables have no verb and are reached through its functions; `run` of the scheduler is internal; `integration:design-tool` is a class of the environment contract with no row in the verbs table.

**The secrets registry, per provider** (`REGISTRY` of `providers/secrets/resolver.py`, equal cell by cell to the table of [contracts/secrets.md](../../../contracts/secrets.md)): `vcs/github.py` reads an everyday token (alerts, `read-file`) and a separate pull-request token (`open-pr` only); `publisher/linkedin.py` and its `auth.py` read the platform's access token, client id and client secret; `mailbox/gmail.py` and its `auth.py` read a refresh token, client id and client secret; `issue-tracker/notion.py` and `documents/notion.py` share one integration token; `documents/notion.py` reads a second, read-only one for the pages chosen as sources, and `documents/gdrive.py` with its `gdrive_auth.py` read one record (`GDRIVE_SOURCES_TOKEN`: the refresh token, the Desktop client and the Picker's API key, scope `drive.file`); the messengers read one bot token each (`telegram.py`, `discord.py`), the system user's token, the app secret and the verify token (`whatsapp-cloud.py`) and a restricted key's SID and secret and the Auth Token (`whatsapp-twilio.py`); `whatsapp.py` reads none, its secret is its session file. The messenger rows are the generated `messenger-secrets` block of [messaging.md](messaging.md). `commit-files` reads no token: it uses the person's own git and SSH key. The store, the scheduler and both `local.py` read no secret. `OP_SERVICE_ACCOUNT_TOKEN` is the resolver's own: the sign-in of the password manager (1Password), found only in the environment, the credentials directory or the OS store. The keys of the model providers are registered by the adapters, never here (layer 5); the task runtime registers its own optional key for each model in `runtime/secrets.json` (`WB_RUNTIME_KEY_<VARIABLE>`, one for each credential variable a model of the gate file uses), which `runtime/ops_core.py` hands to the resolver.

## Abstractions

**Class.** `<role>:<target>`: a fixed target (`integration:vcs`, `scheduler:job`) or a parameter (`publisher:<platform>` and `messenger:<platform>`, the two classes whose part after the colon is handed to the implementation as `--platform`). Four classes were bare names until 2026-10-02 and keep their folders and variables (`mailbox`, `mailer`, `scheduler`, `store`); the resolver still reads the old names as aliases.

**Implementation.** A file `providers/<folder>/<name>.py` that is not a helper (`auth`). An implementation of a class with a parameter declares the platforms it serves in one top-level line, `PLATFORMS = (...)`, which the resolver reads as text without importing the file; a file that declares nothing serves nothing.

**The resolver and its precedence.** First match wins:

```mermaid
flowchart TD
    A["resolve(class, implementation=None)"] --> B{"a caller names an implementation?<br/>(the runtime: runtime.json's provider)"}
    B -->|yes, and it is a candidate| R["that implementation"]
    B -->|no| C{"variable of the class set?<br/>&lt;ROLE&gt;_&lt;TARGET&gt;_PROVIDER, then &lt;ROLE&gt;_PROVIDER"}
    C -->|yes, and it is a candidate| R
    C -->|no, or it does not serve the platform| D{"platform default?<br/>scheduler:job: launchd on macOS, systemd on Linux"}
    D -->|yes, and it is shipped| R
    D -->|no| E{"exactly one candidate left?"}
    E -->|yes| R
    E -->|no| X["exit 3: nothing resolves; the message names the variable to set"]
```

A candidate is an implementation shipped in the class's folder and, for `publisher:<p>` and `messenger:<p>`, one that serves `<p>`. A name is never used as a path. The workbench root is `WORKBENCH_ROOT`, else the checkout the resolver is in.

**The messenger class and its two modes.** `messenger:<platform>` (folder `providers/messenger/`, variables `MESSENGER_<PLATFORM>_PROVIDER` then `MESSENGER_PROVIDER`) is a class the task runtime uses and a skill may not require, so it is on purpose not in the class table of `contracts/environment.md`; its only caller is the messaging bridge (`runtime/messaging_provider.py`). A messenger moves messages between a messaging app and the bridge and decides nothing. It works in one of two modes, declared by the optional capability `listen`: **per-call verbs** (Telegram: `capabilities`, `receive`, `send`, `ack`, one JSON object per process, started with `resolve.call`) or **a listen session** (Discord and the three WhatsApp providers: one long-lived process, started with `resolve.start`, speaking JSON lines on its standard input and output, with the answer kinds `deferred` and the error-event kind `paused` that no other class has). Its capabilities, read from the providers' text, are:

<!-- generated: messenger-capabilities -->
`yes` and `no` are booleans; a key a provider leaves out is `no` (`listen` is optional); `configured` is a value the provider computes from its saved settings, not a constant.

| Platform | Provider | `max_text` | `buttons` | `max_buttons` | `max_button_label` | `lists` | `max_list_rows` | `url_buttons` | `reply_context` | `documents` | `listen` |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `discord` | `discord.py` | 1900 | yes | 5 | 80 | no | 0 | yes | yes | yes | yes |
| `telegram` | `telegram.py` | 4096 | yes | 6 | 40 | no | 0 | yes | yes | yes | no |
| `whatsapp` | `whatsapp.py` | 4096 | no | 0 | 0 | no | 0 | no | yes | yes | yes |
| `whatsapp-cloud` | `whatsapp-cloud.py` | 4096 | yes | 3 | 20 | no | 0 | no | yes | yes | yes |
| `whatsapp-twilio` | `whatsapp-twilio.py` | 1600 | configured | 3 if configured, else 0 | 20 if configured, else 0 | no | 0 | no | yes | no | yes |
<!-- /generated -->

The protocol, the neutral message, the state machine of the session, the kinds and the platforms are on [messaging.md](messaging.md), "Abstractions". What is particular to the class: a messenger's `send` has neither `--confirmed` nor an idempotency key, because the bridge is its only caller, sends only to a chat of the project's accepted `messaging.senders` list and keeps the ledger; a provider refuses a message beyond its capabilities (exit 2); a provider of the listen mode must exit within 5 s of the end of its standard input; and `providers/messenger/whatsapp_meta.py` is a module two providers load by path, never an implementation.

**Verb.** One subcommand that prints one JSON object on stdout; diagnostics go to stderr. The "Prints" column of the contract names the keys a caller may depend on, and a second implementation is written against that column, never against the first one's output. Exit codes have one reading for `--check` and every verb: 0 ready or done, 1 a service or provider error, 2 usage, 3 not configured (the person has something to do).

**Dry run and `--confirmed`.** Every verb with a side effect takes one of the two. A dry run prints the exact payload, reads no credential and makes no call; the one exception is `commit-files --dry-run`, which clones the branch over SSH to show the diff and writes nothing. `resolve` writes a ledger, so it takes them too.

**Idempotency key and ledger.** A verb that publishes, sends or creates a record takes a required key. The key is written `pending` in the ledger, under a file lock, before the request, and `done` with the service's identifier after it. An unknown outcome (a timeout, a 5xx, a 408, a 429, a crash) keeps it pending and blocks every new attempt until `resolve` records what the person found; a definite refusal (a 4xx other than 408 and 429, or a failure before the request) releases it. The same key with other content is refused. A ledger is state, not cache: it lives in the data folder, and a ledger found at its old cache place is copied, never moved.

**The approval by payload hash.** The approval is the gate's, not the provider's: the gate shows what a dry run printed and the approval binds a hash of it ([contracts/environment.md](../../../contracts/environment.md), "Side effects and consent"). Two providers carry part of it in code: the scheduler's dry run prints an `approved` digest of every file the deferred command reads, the program and the runner, and `schedule --confirmed` must pass it back (a mismatch at run time refuses and records `refused`); `commit-files` compares the blob of every committed path with the sha256 of the file it was given and pushes nothing when one differs. The store records an approval hash and compares it with nothing: the caller hashes the file again before it acts.

**The credential by name.** A provider asks the resolver for a registered name and never reads its own variable or the store directly; the lookup is the environment variable, its aliases, the credentials directory (a file named like the secret, for a machine with no desktop session), then the store, and a store that is locked is told apart from a secret that is not stored ([unattended.md](unattended.md)); the provider prints where it found it, never the value. An `auth.py` writes the store once, after the browser consent. A request that carries a credential never follows a redirect.

**A provider's interpreter declaration.** A provider's header is what decides how it is started: a header with `dependencies = []` runs on the caller's interpreter (the set that must run on the system Python 3.9 is listed in `scripts/tests/test_runtime_python39.py`); any other header is started with `uv run <script>`, never with the caller's interpreter. `resolve.interpreter_for` reads the header to decide, once, for every caller of the task runtime; `scripts/doctor.py` runs every `--check` through `uv run`.

**The stand-in service.** Tests never reach a real service. An override of the service's address (`*_API_BASE`) or binary (`SCHEDULER_SYSTEMCTL`, `VCS_GIT_REMOTE`) is honoured only with a loopback URL or an explicit test flag, and then the secret store is never read. `providers/documents/tests/fake_notion.py` is the stand-in both page-based classes share: it serves exactly the calls of the providers' `CALLS` tables, refuses what the reference says the service refuses, and decides what the reference leaves open from the live measurements (a comment does not move the version; a code language off the list is refused).

**Document types and the fidelity test.** A skill's runtime manifest marks each document it writes `editable` or `read_only`. A type is `editable` only when it survives the trip to the platform's blocks and back: `providers/documents/tests/test_document_types.py` runs the skill's own checker on its fixture before and after `notion_blocks.round_trip` (or, with no checker, checks that no word is lost). A type that fails is set to `read_only`; the converter is not changed to make it pass. A `read_only` page carries one notice, its first block, which `read` returns apart and never as content.

**The task board's fields and states mapping.** The board owns only what a person edits: title, text, state, comments; everything else is written to a `shown` property and never read back. A platform board's configuration maps `fields` (`title`, `state`, `shown` to the base's property names) and `states` (each of the nine task states to an option); an option the map does not know reads as `null`, a row with no option is `requested`, and two states on one option is a usage error.

## Dependencies

**What it reads.**

| What | How | Why |
|---|---|---|
| The environment | the class's variable; the provider's own configuration variables; `WORKBENCH_ROOT` | which implementation, which ledger, which root |
| The secret store | `providers/secrets/resolver.py` only | credentials, by name |
| A JSON configuration file (`--config-file`) | the board's and the documents' object of the project's `runtime.json`, written by the runtime to a 0600 temporary file | where the board and the documents are |
| A platform's data file | a path given by flag (`media.max_count`, the notification header prefix) | design rule 2: a provider holds no platform's rules beyond what its own service requires |
| The machine's tools | `git` and `ssh` (`commit-files`), `launchctl` or `systemctl` (the scheduler), `uv`, and `go` (`whatsapp.py build`, with a cleaned environment) | each with a timeout and an argument list |

A provider never reads a skill, the store (except the store provider itself), anything under `runtime/` or an adapter: the layer map allows a file of `providers/` to reach `providers/` alone (the row `providers/**` of `ALLOWED` in `scripts/tests/test_layer_map.py`, `test_every_edge_of_the_code_is_allowed_or_tolerated`). The one cross-class load is `issue-tracker/notion.py` loading `documents/notion_blocks.py` by path, which a test asserts is the only one.

**Who calls it.**

- **Skills' scripts and steps**, by class: `python3 <workbench root>/providers/resolve.py --class <class>` prints the path, and the skill runs it. The skill holds the gate; the provider holds `--confirmed`.
- **The task runtime**, by class through `resolve.call(cls, verb, args, implementation=<the configuration's name>, config=...)`, the one function that resolves, picks the interpreter, starts the verb, maps the exit code and parses the one JSON object (`ProviderCallError`, which carries the last 300 characters of the provider's standard error as `stderr_tail`; the keywords `platform` (the operating system), `env` and `run` let a test choose them; "Calling a provider from code" of `providers/CONTRACT.md`): the board (`runtime/board.py`, class `integration:issue-tracker`), the documents (`runtime/documents.py`, `integration:documents`), the published-posts handler (`runtime/handlers/published_posts.py`, `publisher:<platform>`, the read-only `posts`) and the messaging bridge (`runtime/messaging_provider.py`, `messenger:<platform>`: `call` for the per-call verbs, and `start` for the long-lived `listen`, which returns the running `Popen` with its own session) call it. The effects (`integration:vcs`: `commit-files` then `open-pr`) do not use `call`: `runtime/ops.py` resolves the provider's path (`_provider_path`), and `effects.provider_call` is the only caller of `resolve.invoke`; `runtime/effect_pull_request.py` and `runtime/ops.py` call `provider_call`. The store (`store:runtime`) is resolved with `resolve.resolve` and its module imported by `runtime/ops.py`, since its task functions are the runtime's own persistence; `runtime/ops.py` also resolves each class to show the connections. `runtime/project_config.py` (`resolver()`) loads `providers/resolve.py` as a module for the board, the documents and the effects.
- **The first runtime** (`scripts/runtime.py`, `scripts/runtime_vote.py`, `scripts/vote_job.py`), which the scheduler starts on the system interpreter: the store's verbs, the mailbox, the publisher. It keeps its own loader of `providers/resolve.py` (`load_resolution`) and starts providers with `uv run` itself, until WP-7.5 retires it.
- **`scripts/doctor.py`**, which runs each class's `--check` through `uv run` and reports `connector`, `provider`, `missing` or `unknown`.

**The rules.**

- The core (this folder included) names no AI tool and never reads an adapter: `scripts/validate.py`, check `harness-name`; `providers/secrets/tests/test_resolver.py::test_the_core_registry_names_no_adapter`.
- Nothing outside `providers/` builds a provider's path: the resolver is the one door (`scripts/tests/test_provider_resolve.py::test_a_name_is_never_a_path`; `scripts/tests/test_doctor.py::test_a_class_is_checked_through_the_resolution_function`).
- Every class of the environment contract is in `LISTED`, and a contract row that ships nothing says so: `test_every_class_of_the_environment_contract_is_listed`, `test_a_verbs_row_says_when_no_implementation_ships` (both in `scripts/tests/test_provider_resolve.py`).
- The live measurements of a platform are recorded in its provider's README, each row as observed, with the command, the answer and the date; where a row is not measured, the stand-in decides by the reference and says so.

## Business rules

Each invariant with its guard. A test is in the provider's own `tests/` folder unless its path is given.

**The outbox (`sender:email`).**

- Nothing is sent without `--confirmed`; the dry run reads no credential, opens no connection and writes nothing (`providers/mailer/tests/test_smtp.py`).
- The recipients are exactly the flags: the envelope is To + Cc + Bcc, the headers have To and Cc only, every header is built from checked parts, a display name, a comment, a line break, an encoded word (`=?`), a second `@`, a non-ASCII domain not given as `xn--`, a repeated address or more than 20 recipients is exit 2; the built message is read back and must say exactly what was approved (`inspect_message`; `test_a_library_that_decodes_more_than_was_approved_is_caught_by_reading_the_built_message_back`) (`test_an_address_with_a_display_name_comment_break_or_second_at_is_refused_and_nothing_is_sent`, `test_no_address_outside_the_flags_reaches_the_envelope_even_when_the_text_names_one`, `providers/mailer/tests/test_email_helpers.py`).
- All or nothing: one refused `RCPT` is `RSET`, nothing sent and the key released (`test_one_refused_recipient_sends_nothing_names_the_address_and_releases_the_key`). Exit 1 guarantees nothing was sent; exit 4 means the outcome is not known and the key stays pending; the next send with that key looks in the Sent folder (a read-only IMAP `EXAMINE` and `UID SEARCH`: no `SELECT`, `STORE`, `COPY` or `EXPUNGE` is ever sent) and is blocked until `resolve` when the message is not there (`test_a_dropped_answer_after_data_keeps_the_key_pending_and_the_next_send_looks_in_the_sent_folder_first`, `test_lookup_is_read_only_and_says_whether_the_message_id_is_in_the_sent_folder`).
- No password before TLS: SMTP 465, or 587 with a required STARTTLS (a server that does not offer it, or a certificate that is not trusted, gets no `AUTH`); IMAP 993. Plain is for a test on a loopback host with `OPENHORA_MAIL_TEST_PLAIN=1`, and the variable refuses any other host (`test_a_server_that_does_not_offer_starttls_gets_no_password`, `test_a_certificate_that_is_not_trusted_gets_no_password`, `test_plain_is_for_a_test_on_loopback_only`).
- One outbox account per machine; the password is `MAILER_SMTP_PASSWORD`, read by the secret resolver and never printed (`test_another_from_address_is_not_configured_and_connects_to_nothing`, `test_the_password_is_never_printed_not_even_by_the_check_or_an_error`).

**Testing and the hook.**

- Every provider class has offline tests, and the commit hook refuses a commit that leaves an existing class without them: `.githooks/pre-commit` (rule 3); `scripts/tests/test_checks_wiring.py::test_the_hook_maps_each_folder_to_the_tests_that_cover_it`, `test_every_test_folder_of_this_repository_is_in_the_list_ci_runs`.
- Contract tests run on every implementation of the two runtime classes: `test_issue_tracker_contract.py` and `test_documents_contract.py`, each with `test_every_implementation_has_a_harness`. The scheduler's two implementations are held together by `test_scheduler_parity.py` (`test_a_shared_function_is_the_same_text_in_both_providers`, `test_the_contract_row_and_the_readme_name_every_verb_flag_and_key`). The other classes have one implementation and its own tests; no contract test exists for them.
- No network in tests: every provider suite's `conftest.py` applies the guard of `providers/loopback_only.py` to each test, so a connection, a datagram or a name lookup to an address that is not loopback raises `NetworkRefused`, and a provider a test starts as a subprocess with the test's environment is guarded through a `sitecustomize` the fixture puts first on `PYTHONPATH`: `providers/store/tests/test_loopback_only.py` (`test_every_provider_suite_carries_the_same_guard`, `test_a_test_reaches_loopback_and_nothing_else`, `test_a_provider_started_with_the_tests_environment_is_guarded_too`). A subprocess given an environment of its own is not covered; there the provider's own loopback rule holds, tested per provider (`test_a_base_address_that_is_not_loopback_is_refused` for both page-based providers; `test_rejects_non_loopback_api_base` for `vcs/github.py`).

**Selection.**

- The environment wins most specific first, a caller's explicit name wins over it, and both must be candidates: `test_environment_wins_most_specific_first`, `test_an_explicit_implementation_wins_over_the_environment`, `test_a_name_is_never_a_path`.
- A second publisher for another platform breaks nothing for the first, and a file that declares no platform serves none: `test_a_second_publisher_does_not_break_the_first`, `test_the_declaration_is_read_as_text_and_a_file_that_declares_nothing_serves_nothing`.
- A provider that needs dependencies is started through `uv run`, never with the caller's interpreter: `runtime/tests/test_system_python_starts.py::test_what_does_not_run_on_the_system_python_is_started_through_uv`; `scripts/tests/test_doctor.py::test_without_uv_a_provider_is_missing_and_never_run_with_the_callers_interpreter`.
- Every script the scheduler starts runs on Python 3.9: `scripts/tests/test_runtime_python39.py` (`ON_SYSTEM_PYTHON`) and the CI job `python39`.

**Secrets.**

- The secrets table of the contract equals the registry cell by cell: `providers/secrets/tests/test_resolver.py::test_the_contract_table_equals_the_registry_cell_by_cell`.
- No value is ever printed: `test_report_never_carries_a_value`, `test_cli_check_and_list_print_no_value` (resolver); `test_check_says_not_configured_with_exit_3_and_prints_no_secret` (both contract suites).
- A request with a credential never follows a redirect: `test_redirect_is_not_followed_with_the_token` (`vcs`, `publisher`), `test_redirect_is_refused` (`mailbox`), `test_the_token_is_never_printed_and_a_redirect_is_refused` (both page-based providers).
- The pull-request token is separate: only `open-pr` reads it, it is read first and named, and the everyday token is the fallback only when it is found nowhere: `test_only_open_pr_reads_the_pull_request_token`, `test_open_pr_reads_its_own_token_first_and_names_it_never_its_value`, `test_open_pr_falls_back_to_the_everyday_token_only_when_its_own_is_not_found`; `test_the_pull_request_token_has_a_row_of_its_own_and_the_everyday_token_lost_that_permission` (resolver).
- `git` run by `commit-files` gets neither the caller's `GIT_*` variables nor any registered secret: `test_git_gets_neither_the_callers_git_variables_nor_the_secrets`.

**Side effects.**

- A side-effect verb without `--confirmed` or `--dry-run` is refused, and a dry run changes nothing: `test_a_write_without_confirmation_is_refused_and_a_dry_run_changes_nothing` (both contract suites), `test_dismiss_refuses_without_confirmed`, `test_open_pr_needs_confirmed`, `test_open_pr_dry_run_prints_the_request_and_reads_no_token`.
- A skill that writes to a remote must declare it: `scripts/security_scan.py`, rule `undeclared-side-effect` (`scripts/tests/test_security_scan.py::test_remote_write_needs_declared_side_effects`, `test_remote_write_in_a_step_of_skill_md`).
- One record per idempotency key, and an unknown outcome blocks the key until `resolve`: `test_the_same_idempotency_key_creates_one_item`, `test_the_same_idempotency_key_creates_one_document`, `test_a_creation_with_an_unknown_outcome_blocks_its_key_until_resolve` (both page-based providers), `test_an_unknown_push_outcome_stays_pending_until_resolved`, `test_resolve_settles_a_pending_pull_request_either_way`, `test_open_pr_refuses_a_key_used_for_another_title_body_or_branch`.
- A 429 or a 5xx is exit 1 and is never retried by the provider: `test_too_many_requests_exits_1_with_the_status_and_is_not_retried` (documents); `test_the_board_never_retries_a_429_or_a_5xx` (`test_issue_tracker_notion.py`).

**The versioned output shapes.** The keys of the "Prints" column are what a caller depends on: the contract suites assert them for the board and the documents (`test_an_item_that_was_created_is_read_back_with_its_title_text_and_state`, `test_stat_reports_the_version_read_reports`), `test_publisher_posts_verb.py` for `posts` (`test_posts_lists_only_published_posts_since_the_given_time`, `test_a_published_post_whose_time_cannot_be_read_is_undated`), and `test_open_pr_creates_one_pull_request_and_prints_its_number_and_url`. The service's own API version is pinned in each provider (a version header per call). A second implementation of `integration:vcs` or `publisher:<platform>` would have no contract suite to run against: none exists.

**Documents and the board on a platform.**

- A write replaces the whole document and never merges: `test_a_write_replaces_the_whole_document`.
- The replacement appends the new blocks first and deletes the old ones after, so a failure never leaves a page empty: `test_a_write_appends_the_new_blocks_before_it_deletes_the_old_ones` (`test_documents_notion.py`); the calls are bounded by `test_a_long_document_is_written_in_calls_no_larger_than_the_limit`.
- A page that changed since the runtime last wrote it is never written over: the provider writes whatever it is given; the guard is the runtime's read before every write (`runtime/tests/test_documents_mirror.py`, `test_a_document_both_sides_changed_is_overwritten_on_neither_side_until_the_person_takes_one`). Two edits within one minute give one version (measured, N1), so that read is the only guard for that minute.
- A fence language the platform does not know goes up as plain text and comes back unchanged: `test_a_fence_word_the_service_does_not_know_goes_up_as_plain_text_and_a_known_one_is_unchanged` (converter), `test_a_fenced_block_whose_language_the_service_does_not_know_goes_up_as_plain_text_and_comes_back_unchanged` (provider).
- An editable type keeps passing its skill's checker after the trip: `test_an_editable_document_still_passes_its_skills_checker_after_the_trip`, `test_every_editable_document_type_has_a_fixture`.
- The notice is the page's first block once, and never part of what is read: `test_a_notice_is_the_pages_first_block_once_and_never_part_of_what_is_read`, `test_notice_adds_the_notice_to_a_page_that_has_none_and_nothing_to_one_that_has_it`.
- The board's `base` is the data source's id, not the database's: a wrong id is not configured (exit 3), as measured (N10); a test with a well-formed id the integration cannot see covers the parent page (`test_a_parent_the_integration_was_not_given_is_not_configured`); no test gives a database id in place of a data source id.
- A row in the trash is got as `archived`, with no body and no comments: `test_a_row_in_the_trash_is_got_as_archived_with_no_body`.
- A comment on a block is read with its page or item, and `comments` is one listing of the page's own comments whatever the version: `test_a_comment_on_one_block_is_read_with_the_document`, `test_comments_is_one_listing_of_the_pages_own_comments_and_a_comment_does_not_move_the_version`, and the board's pair. The runtime calls `comments` for every mirrored item and page at every pull: `runtime/tests/test_board_mirror.py::test_a_comment_added_on_an_unchanged_item_is_saved_by_the_next_pull`, `runtime/tests/test_documents_mirror.py::test_a_comment_added_on_an_unchanged_page_is_saved_by_the_next_pull`.
- A write of the state alone keeps the title and the text a person edited, and a write of values already on a row sends no change: `test_a_write_of_the_state_alone_keeps_the_title_and_the_text_a_person_edited`, `test_a_write_of_values_already_on_the_row_sends_no_change`.

**`commit-files`.**

- Every path matches an `--allow` glob, part by part; `*` never crosses `/` and no wildcard matches a leading dot: `test_paths_outside_allow_are_refused_before_cloning`, `test_a_wildcard_does_not_admit_a_dotfile`. The runtime passes each path of the change set as its own `--allow` (`runtime/effects.py`).
- One signed commit with exactly the files given; an unsigned commit is never pushed; a hook or an attribute that changes a file stops the push: `test_confirmed_pushes_one_signed_commit_with_exactly_the_files`, `test_an_unsigned_commit_is_never_pushed`, `test_a_hook_that_changes_a_file_stops_the_push`, `test_an_attribute_that_changes_a_file_stops_the_push`.
- Never written through a symlink; a deletion is never of a folder nor through a link: `test_a_symlink_in_the_repository_is_never_written_through`, `test_a_delete_through_a_symlink_or_of_a_folder_is_refused_and_nothing_is_pushed`.
- A moved branch is retried once from a fresh clone; only a definite refusal releases the key: `test_a_moved_branch_is_retried_once_from_a_fresh_clone`, `test_a_push_the_remote_refused_releases_the_key`, `test_a_push_whose_remote_did_not_report_keeps_the_key_pending`.
- A tag is refused as a branch; `--from-branch` starts a missing branch from the base and is ignored when the branch exists: `test_a_tag_is_refused_as_branch`, `test_from_branch_creates_the_branch_from_the_base_when_the_remote_lacks_it`, `test_from_branch_is_not_used_when_the_branch_already_exists`.

**The messenger providers** (tests in `providers/messenger/tests/`; the numbered rules of the feature are on [messaging.md](messaging.md), "Business rules").

- A dependency that holds a credential on a long-lived connection is hash-locked and started with `uv run --locked`; a missing or stale lock is flagged: `test_discord_lock.py`, `test_the_lock_exists_names_the_header_versions_and_hashes_every_package`, `test_a_missing_lock_is_flagged`, `test_a_lock_for_another_version_than_the_header_is_flagged`; `providers/resolve.py:322-334`.
- A webhook call is processed only with a valid signature, compared on bytes in constant time, and nothing is processed otherwise: `test_whatsapp_cloud_webhook.py`, `test_a_missing_malformed_or_wrong_signature_is_401_and_nothing_is_processed`, `test_the_signature_is_checked_on_the_raw_bytes_a_reserialised_body_fails`; `test_whatsapp_twilio_webhook.py`, `test_a_missing_or_wrong_signature_is_a_403_and_nothing_is_processed`, `test_the_provider_reproduces_twilios_published_test_vector`.
- The webhook server binds `127.0.0.1` only, cuts a request at a total deadline, bounds concurrent handlers (the next gets 503) and the size of a body, and logs no request: `test_the_server_binds_127_0_0_1_and_nothing_else`, `test_a_request_that_stalls_is_cut_at_the_total_deadline_not_only_the_read_timeout`, `test_concurrent_handlers_are_bounded_and_the_next_request_gets_503`, `test_a_post_needs_a_content_length_and_a_body_over_three_mebibytes_is_refused_before_it_is_read`.
- A duplicate message id is dropped, also after a restart; the state files are mode 0600 and their caps and retention hold: `test_a_duplicate_wamid_is_dropped_also_after_a_restart`, `test_a_duplicate_message_sid_is_dropped_also_after_a_restart`, `test_seen_ids_are_kept_eight_days_and_identities_thirty_and_pruned_at_the_start`, `test_the_state_files_are_mode_0600_and_the_caps_drop_the_oldest`.
- An error carries the class of the exception, the status and the service's own description, never a body or a token; a missing `keyring` library is told as such and not as a missing secret: `test_messenger_store_missing.py`, `test_telegram_says_the_store_is_missing_first`, `test_discord_says_the_store_is_missing_first`, `test_whatsapp_cloud_says_the_store_is_missing_first`, `test_whatsapp_twilio_says_the_store_is_missing_first`.
- Every test of the suite reaches no network but loopback, the null keyring backend and a fresh state folder: `providers/messenger/tests/conftest.py`, `test_every_test_here_is_isolated_from_the_real_secret_store_and_state_folder`.

**The store.** One call is one transaction; the task tables have no verb; a `waiting` task has one open pending decision; `approvals` only grows, and a task, a task run and a pending decision are never deleted (the delete triggers of the latest migration, which `init` also puts on a database at an earlier version): `providers/store/tests/test_sqlite_tasks.py` (`test_a_task_a_run_and_a_pending_decision_are_never_deleted`), `test_sqlite_platform.py`, `test_sqlite_approvals.py` (`test_limit_13_an_approval_is_never_deleted_and_its_status_only_moves_forward`), `test_sqlite_stage6.py`, and `test_sqlite.py`. The change counter (every write transaction that changed a row raises `PRAGMA user_version`; one that changed nothing or rolled back does not; it wraps to 1) and `cursor_peek` (a cursor read with no write lock) are in `test_sqlite_changes.py` (`test_a_write_that_changes_a_row_raises_the_counter_by_one`, `test_a_transaction_that_changes_nothing_leaves_the_counter_alone`, `test_cursor_peek_reads_a_cursor_without_a_write_lock_and_raises_nothing`). The runtime's page lists the invariants that rest on them.

## Entry points

Every provider takes `--help` and `--check`. Side-effect verbs take `--dry-run` or `--confirmed`. Run a provider whose header has dependencies with `uv run providers/<folder>/<impl>.py`.

**The resolver and the doctor.**

| Command | What it does |
|---|---|
| `python3 providers/resolve.py --class <class> [--json] [--root <dir>]` | the path of the implementation chosen now (exit 3 when nothing resolves) |
| `python3 providers/resolve.py --list [--json] [--root <dir>]` | every class, its folder, its variables, its implementations and the one that resolves |
| `python3 providers/secrets/resolver.py [--registry <file>]... --list [--json]` / `--check <NAME>` | which secrets are found and where, never a value; `--registry` goes before the verb and merges an adapter's list |
| `python3 scripts/doctor.py [--harness <name>] [--json] [--strict]` | every class the skills require: `connector`, `provider`, `missing` or `unknown`; every registered secret |

**Per class.**

| Class | Verb | Side effect | Credential |
|---|---|---|---|
| `store:runtime` | `init`, `cursor-get`, `cursor-set`, `cursor-clear`, `event-add`, `event-next`, `event-done`, `run-start`, `run-end`, `runs`, `inbox-add`, `inbox-list`, `inbox-resolve`, `action-add`, `actions`, `action-count`, `export` | local only; none takes `--confirmed` | none |
| `scheduler:job` | `schedule --id (--at \| --every) --command-file (--dry-run \| --confirmed --approved <digest>)` | registers a job | none |
| | `list`; `cancel --id`; `resolve --id (--done \| --failed)`; `run --id` (internal) | `cancel`, `resolve` | none |
| `integration:vcs` | `alerts`; `read-file` | none | everyday token (anonymous for a public file) |
| | `dismiss-alert --idempotency-key` | dismisses an alert | a separate write token |
| | `commit-files --repo --branch --message-file --file ... --allow ... --idempotency-key` | one signed commit, pushed | none: the person's git and SSH key |
| | `open-pr --repo --head --base --title-file --body-file --idempotency-key` | opens one pull request | the pull-request token |
| | `resolve --idempotency-key (...) --confirmed` | the ledger | none |
| `integration:issue-tracker` | `--check`, `list`, `get --id`, `comments --id` | none | the integration token (`notion.py`) |
| | `upsert [--id] --item-file --idempotency-key`, `resolve` | creates or updates an item | the same |
| `integration:documents` | `--check`, `stat --id`, `read --id`, `comments --id` | none | the integration token (`notion.py`) |
| | `write [--id] --path --markdown-file --idempotency-key [--notice]`, `notice --id --text`, `resolve` | replaces a whole document; adds the notice | the same |
| `publisher:<platform>` | `publish --platform --text-file --idempotency-key [--media] [--first-comment-file]`; `comment ...`; `resolve ...` | publishes a post or a comment | the platform's token |
| | `posts --platform --since <time with offset>` | none: reads the ledger only | none |
| `reader:email` | `search --query`, `get --id`, `read-eml --file` | none (read only by scope) | the refresh token and client |
| `messenger:<platform>` | `capabilities`; `receive --offset --timeout`, `send --chat --message-file`, `ack --action-ref` (Telegram only; the other four exit 2); `listen` (JSON lines, the other four); `setup`, `whoami` (`whatsapp-cloud.py`, `whatsapp-twilio.py`), `pair`, `whoami`, `build`, `status` (`whatsapp.py`) | `send` writes to a chat of the project's accepted list; it takes neither `--confirmed` nor a key, since the bridge is its only caller | the platform's bot token, or the secrets of the table in [messaging.md](messaging.md), or a session file |

**One-time authorizations**: `uv run providers/publisher/auth.py --provider <impl>`, `uv run providers/mailbox/auth.py --provider <impl>`; a token without OAuth is stored with `uv run --with keyring==25.7.0 keyring set openhora <store username>` at a hidden prompt.

**Tests**: `uv run --with pytest==9.1.1 pytest -q providers/<folder>/tests`; the resolver's in `scripts/tests/test_provider_resolve.py`.

## Known limits and improvements

| Limit or improvement | Where it is recorded |
|---|---|
| The live measurements of the page-based providers were made through the API, not by hand: an edit, a comment, a resolved comment, archiving and an unshared page by hand are still to measure (N1, N3, N4, N5, N8, N10); a 429 was not provoked (N6) | [providers/documents/README.md](../../../providers/documents/README.md) and [providers/issue-tracker/README.md](../../../providers/issue-tracker/README.md), "Measured on the live service" |
| One social platform, of one shape (text with optional media); a platform of another shape edits three skills | `providers/publisher/`; [AGENTS.md](../../../AGENTS.md), design rule 3 |
| One task-board platform and one documents platform besides `local` | the two folders' READMEs |
| `integration:documents` has no row in the environment contract and is not in `LISTED`; it resolves by its folder until the router's routing table first changes | [providers/CONTRACT.md](../../../providers/CONTRACT.md), its row; `test_the_class_resolves_by_its_folder_and_is_not_in_the_listed_classes` |
| Fidelity is per document type and per provider: a fenced block in a language the platform does not know failed to be written before the plain-text fallback | stage 3 findings (removed on 2026-10-14; `git show d3e60770:docs/architecture/stage-3-findings-2026-10-06.md`), finding 14; N11 of the documents README |
| A sync lists comments for every mirrored item and page at every pull, and a `read` lists the comments block by block (a 296-block page took about two minutes) | stage 3 findings (removed on 2026-10-14; `git show d3e60770:docs/architecture/stage-3-findings-2026-10-06.md`), finding 7; N4 |
| Rows changed since a time can be asked for in one call (N9); `list` does not use it yet, which is a decision | [providers/issue-tracker/README.md](../../../providers/issue-tracker/README.md), N9 |
| A board's own status property is not written; a base whose status has fewer options than the nine states holds only the mapped ones | [backlog](../../backlog.md), R13 |
| Three glob readings: `commit-files --allow` (`*` never crosses `/`, no leading dot), a policy's `files` (`*` does not cross `/`), a `protected_paths` entry (`*` crosses `/`) | [vcs README](../../../providers/vcs/README.md); [runtime.md](runtime.md), "Known limits and improvements" |
| No contract suite for a class with one implementation (`integration:vcs`, `publisher:<platform>`, `reader:email`): a second implementation has nothing to run against | "Business rules" above |
| The systemd scheduler was written on a machine without systemd and is tested against a fake `systemctl` | [providers/scheduler/README.md](../../../providers/scheduler/README.md), "Not verified yet" |
| The platform's comment endpoint for a member is an undocumented path; its behaviour may change | [providers/publisher/README.md](../../../providers/publisher/README.md), "To verify on first use" |
| No test runs one contract over every messenger implementation: each provider has its own suite, and only the two WhatsApp renderers share a corpus; none of the five has been run against its live platform for every verb (the unofficial WhatsApp client and the Meta Cloud API not at all) | [messaging.md](messaging.md), "Known limits and improvements"; `providers/messenger/README.md` |
| `sender:email` has one implementation, over SMTP with a password; the Gmail API (OAuth, `gmail.send` on a token of its own) is a later second one, and a host that forbids password logins (Microsoft 365 by default) needs it | [providers/mailer/README.md](../../../providers/mailer/README.md) |
| `generator:*`, `search:web` and `integration:design-tool` have no implementation | [providers/CONTRACT.md](../../../providers/CONTRACT.md), "Verbs per class" |
| The store's task functions are the task runtime's own persistence, not a substitutable class; no second backend is promised and no suite checks one (decision D2); the first runtime still calls the verbs through the command line | [providers/store/README.md](../../../providers/store/README.md), first paragraph; [providers/CONTRACT.md](../../../providers/CONTRACT.md), "Functions of the store" |
| A provider a test starts with an environment of its own is not under the loopback guard; there only the provider's own refusal of a base address that is not loopback holds | `providers/loopback_only.py`, its docstring |

## Changes

- 2026-10-06: first version, written from the code at the central branch's head of that day.
- 2026-10-06: the volatile tables are generated from the code by `scripts/architecture_tables.py` (the classes, implementations and verbs).
- 2026-10-06: the provider suites reach no network but loopback (`providers/loopback_only.py`), the board's 429 and 5xx and the append-before-delete order have tests, and the latest migration puts delete triggers on tasks, task runs and pending decisions (#214).
- 2026-10-07: `resolve.call` (and `invoke`, `interpreter_for`, `ProviderCallError`): the call of a provider's verb exists once in the task runtime, and the board, the documents, the effects and the published-posts handler use it (WP-R.7); the first runtime keeps its own loader.
- 2026-10-07: the store's task functions are declared runtime-owned persistence, not a substitutable class (decision D2).
- 2026-10-07: a fixture for the design-system document type joins the fidelity test (`providers/documents/tests/fixtures/types/design-system.json`, #232).
- 2026-10-08: the store keeps a change counter in the database header and reads a cursor without a write lock (`change_counter`, `cursor_peek`, #255).
- 2026-10-09: the page is brought to the code of the central branch: the callers of the resolver and of the secrets resolver are listed as they are, the layer map guards the provider boundary, the three statements that no guard was found now name the loopback guard and the two tests, the store's test files, delete triggers and change counter are described, the resolver's flags are corrected, and the row that the stand-in still moved the version on a comment is deleted.
- 2026-10-09: the workbench is called openhora: the secret store's service and the command that stores a token name `openhora`, the old service is read as a fallback (the resolver's `--list` says `ai-workbench (legacy)`); the provider's data folder, its cache folder and the scheduler's labels keep the old name, and renaming them waits for a decision.
- 2026-10-14: the page follows the messenger class (MSG-14): `messenger:<platform>` is the second class with a parameter, its five implementations, the Go program, the lockfile and the state-folder files of the providers are artifacts, the two modes and the capabilities (generated) are abstractions, the messenger rules have their tests, the class has its row among the verbs, and two limits are added.
- 2026-10-14: the messenger verbs moved from the table "From a class to a folder" into "Verbs per class" of `providers/CONTRACT.md`, in the form of the other classes (MSG-15): the generated `provider-classes` block shows the five `messenger:<platform>` rows, with the verbs the generator now also reads from `add_parser(...)` calls, and the known limit that the block had no messenger row is removed.
- 2026-10-15: the class `converter:document` (P4), a role like the messenger and not a listed class: one implementation, `providers/converter/container.py`, adopted tools in a container with no network ([sources.md](sources.md)); `read --as-source` of the Notion documents provider with the read-only secret `NOTION_SOURCES_TOKEN`; `provider_environment` moved to `providers/resolve.py` (the runtime builds a provider's environment through the resolver) and `providers/_container.py` `run(stdout_cap=)`.
- 2026-10-15: `documents/gdrive.py` (P7), the third implementation of `integration:documents` and the first that is sources only (`SOURCES_ONLY = True`; its write verbs exit 2): the files a person picked in Google Drive, scope `drive.file`, the secret `GDRIVE_SOURCES_TOKEN`; its helpers `gdrive_auth.py` and `gdrive_picker.py` (the one-shot loopback page that runs Google's Picker) are not implementations ([sources.md](sources.md), `providers/documents/README.md`).
- 2026-10-16: the outbox (EMAIL-SEND): `sender:email` has its first implementation, `providers/mailer/smtp.py`, with the shared `providers/_email.py`, the secret `MAILER_SMTP_PASSWORD`, the state folder `<state>/mailer-smtp/` and a fake SMTP and IMAP server for its tests; exit code 4 for an outcome that is not known.
