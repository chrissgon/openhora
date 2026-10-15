# The sources of a project

What a person gives a project to read, how it becomes clean text a task can use, and the guardrails that keep it from becoming a way in. It crosses three layers of the platform map and belongs to none alone: the runtime owns the registry and the folder (`runtime/sources.py`, `runtime/ops_sources.py`), a provider converts (`providers/converter/`), another reads a Notion page (`providers/documents/notion.py`), and the store keeps the rows. Package P4 of the delegation plan; decisions D9, D10, D11, D13, D16, D29 and D30 of `docs/architecture/delegation-platform-plan-2026-10-14.md`.

## Purpose

A project declares **sources**: an uploaded file (a PDF, a Word document, a spreadsheet, a presentation, a CSV, an HTML page, a text file) or a Notion page chosen by its address. Each import is an **immutable version** kept in the project's **sources folder** (`sources_dir`), as the original, the converted text and a manifest. A **catalog**, built by code from the converted text alone, tells the planning run what each source holds, so that the **plan** can name, for each task, the sources it needs; the person approves that plan by its hash, and a task **receives copies** of the newest version of each source at the moment it starts. The sources folder itself never enters a run.

The idea behind each piece, in one line each:

- the folder is the person's, it is dedicated and private, and the runtime treats it as hostile ground: it writes only inside it, through an open descriptor, and reads nothing from it that it did not first check against a hash;
- a file is never read on this machine: bytes go through the generic intake (the length bounded first, the type read from the bytes), a container with no network converts them with adopted open tools, and only the converted text is scanned, catalogued and handed to a run;
- the planner is given data, not instructions: the catalog is text other people wrote, and it is named in the external-content line of `core-orchestrator`;
- a task sees only the sources chosen for it, and the plan shows them before anyone approves it.

## Artifacts it owns

| Artifact | Where | Notes |
|---|---|---|
| The sources folder | `sources_dir` of `runtime.json` (mandatory, no default; accepted only in the terminal) | `.openhora-sources` (the marker; it names the project folder's device and inode, so a folder serves one project), `.incoming/` (the assembly area; it also takes a leftover numbered folder aside), `<source id>/<version>/original.<ext>`, `converted.md` or `converted.csv`, `manifest.json`. Files are mode 0400; a version is moved into place with one rename and never written again |
| The registry | table `sources` of the store (migration 11; migration 14 added the type `drive`) | id, type (`file`, `notion` or `drive`), origin (a file's name, or a Notion page's address; never a credential), the person's description. Never deleted; only the description changes |
| The versions | table `source_versions` | one row per version: label (`import`, `refresh`, `changed-by-person`), who made it (`runtime` or `person`), the sniffed kind, the hashes and sizes of the original and the converted text, the converter and its tools, `hidden_text` (1 found, 0 none found, null not examined: P8), warnings, the catalog entry, the origin's own version (a Notion page's `last_edited_time`), the date from the clock. Never changed, never deleted |
| What a task received | table `task_sources` | for each run: the source id, the version and the sha256 of the converted text copied; plus `tasks.sources`, the ids the approved plan chose |
| The copies in a run | `.workbench-local/sources/<source id>/converted.<ext>` in the run's copy | made when the task starts; staged like the file drop, so never brought back |

## Abstractions

| Name | What it is | Where |
|---|---|---|
| Source | an id (`[a-z0-9][a-z0-9-]{0,39}`), a type and an origin | `sources.register`, store `source_add` |
| Version | an immutable import; the next number of the source | `sources.import_version`, store `source_version_add` |
| Catalog entry | name, type, size, date, sheets and columns with a few sample values, first headings, warnings; the person's description is joined when it is read | `sources.catalog_entry`, `sources.list_catalog`, `sources.catalog_text` |
| Convert | a function `(input, subtype, out_dir) -> info`; in production the provider of `converter:document` | `sources.provider_convert` |
| Folder | the open sources folder: one descriptor, `O_NOFOLLOW` at every step | `sources.Folder` |
| Mention | `@<source id>` in a request: forces that source into every task of the plan | `sources.mentions`, `plan.combine(forced=)` |

## Dependencies

- `runtime/intake.py` (P0): the length bounded before a byte is read, the type read from the bytes with the sniffers `sources.py` adds (PDF, Office Open XML, text), the hash while it streams, one upload at a time.
- `providers/_container.py` (P0): the lifecycle and every limit of the container (no network, a read-only root, every capability dropped, memory-backed `/tmp` and `/scratch` with no exec, an image never pulled at run time); `run(stdout_cap=)` was added for the converter's stream.
- `runtime/workcopy.py`: `scan` for the credential scan of the converted text, `entering` for what a run sees.
- `providers/resolve.py`: the class `converter:document` (a role, not listed in `contracts/environment.md`: no skill may require it) and the call to the documents provider.
- `runtime/lab.py`: `local_evidence_base()`, the folder the sources folder must be disjoint from.
- The store: migration 11, and `plan_approve` / `request_add` carry `sources` on the tasks.

## Business rules

The numbered limits L21 to L27 of `contracts/runtime.md`, each with a test named after it (`runtime/tests/test_sources_limits.py`):

1. **L21** dedicated, private, marked for this project, mode 0700 (at acceptance and before every use).
2. **L22** disjoint from `data_dir`, `store_db`, the checkout and the local evidence folder, by device and inode.
3. **L23** the runtime writes only inside it and never follows a link out (the import staging folder in `data_dir` included); a pipe where a file is expected is refused before it is opened; the home folder, the root, a folder that contains the project and a folder at or under the project's `docs/` or `.workbench-local/` are refused.
4. **L24** what a container writes comes back only as regular files, with closed names, under a byte cap.
5. **L25** a file changed outside the runtime is found by its hash, checked again, labelled as the person's, and never used unattended.
6. **L26** the work copy excludes the folder, even inside a tracked tree, and nothing a run leaves is written into it (a returned path inside it is kept; a change set that touches it is refused).
7. **L27** the catalog is built only from converted output.

Beside them:

8. **A converted text is scanned for credentials after the conversion**, because text compressed inside a PDF is invisible to a scan of its bytes; a text that fails is not kept, and nothing is left in the folder or the store.
9. **A source has a size cap, with a warning.** An original is at most 25 MiB (the intake's route limit). The converted text is at most 1 MiB: a task reads all of it, 1 MiB is beyond what a model's context takes, and indexing or retrieval waits for a real case. From 256 KiB (about 65,000 tokens at four bytes a token) the import succeeds and says it is large, and the catalog entry carries the warning.
10. **The planner chooses, code checks.** The router's reply may carry a `Sources:` line (`runtime/router.py`); an id the project does not hold, or a skill that is not in the plan, makes no plan (the person is asked). An `@mention` is added by code to every task of the delivery. The ids are part of each task, so they are in the plan hash; a new version of a source changes none of them.
11. **A task receives the newest version at the moment it starts** (D29): copied from the folder after its files are hashed against the record; recorded as id, version and sha256, only for the copies the run received (a copy that fails the credential scan again stops the task with the reason). A version made by the person (`changed-by-person`) goes only to a task the person starts with `run-next`; the dispatcher's starts and `run-task` are unattended and refuse it (the page cannot start a task). A source refreshed after the plan and before the start reaches the task as the newer version; one refreshed after the start does not reach that run. A later run of the same task takes the newest version at its own start.
12. **A Notion page is read with its own read-only secret** (`NOTION_SOURCES_TOKEN`, store username `notion-sources`), by `read --as-source`; `NOTION_TOKEN`, which writes, is never used for sources. The page's id is extracted from the address (every URL shape the provider knows: a bare id, `Title-<id>`, a workspace path, a `p=` query, a `notion.site` host); anything else is refused.
13. **The channels.** The four writes (`source-add`, `source-import`, `source-refresh`, `source-describe`) are for the terminal and the page; the catalog read (`sources`) is also for the MCP mode and the messaging channel, and sits in the group `sources`, which a project's policy turns on (it is not in the default policy of messaging: the catalog shows samples of the person's data).

14. **A Google Drive file is a source by its id, with one scope and no folder** (P7). The person picks one or more FILES in Google's Picker (`source-drive`); each file id is registered as a source of type `drive` and imported like any other. The registry's type column admits `drive` since migration 14 (P7 stored a Drive source as a `file` row whose origin was `drive:<file id>`; the migration rewrote those rows to the type `drive` with the bare file id as the origin, and `sources.public_row` is the identity for them). The provider is `providers/documents/gdrive.py` (the documents class, read only, `SOURCES_ONLY`), with the scope `drive.file` and the secret `GDRIVE_SOURCES_TOKEN`. **`drive.file` is not read-only**: it lets the app read and write every file the person picked. The provider sends GET requests only and the runtime calls only its read verbs; the token is as private as those files. **A folder is not a source**: under `drive.file`, a picked folder gives the app nothing inside it (the spike of 2026-10-15: `files.get` on the folder answered, `files.list` of its children returned none while it held files), so the Picker lets the person open folders and not pick them. A Google Doc is read as Markdown (its text, no converter), a Sheet as a workbook, Slides as a PDF, any other file as it is; the bytes go through the same intake, converter, credential scan and rows as a file of the person's, and the manifest and the catalog name the file. **A refresh asks Drive for the file's version first** (`stat`: Drive's `version` and `modifiedTime`, recorded as the version's `origin_version`) and reads nothing when it matches; bytes already held make no version either. The files of a version are still checked against their hashes when Drive did not change (limit L25).
15. **The Picker never runs in the runtime's page.** Its script and frames come from Google's hosts, which the page's policy (`default-src 'self'`) and the interface's rule (nothing from another host) forbid. It runs on a one-shot server on 127.0.0.1 (`providers/documents/gdrive_picker.py`, started by `providers/documents/gdrive_auth.py`): a random port; every request must carry that exact `Host` (no DNS rebinding); the way in is the printed start URL `/start?k=<key>` (a random key, served once: without it nothing is revealed, neither the consent URL nor the nonce); the OAuth callback is served once, only when shaped like one, and its state compared in constant time; the page, the token and the picks need a nonce that /start gives only to the key's holder; a post must carry the server's own `Origin`; it stops after the picks, a cancel, a failure or ten minutes. The authorization asks for `drive.file` and nothing else (PKCE S256, a state, offline access); the refresh token, the client and the Picker's API key are one record in the OS secret store, and the access token is made in memory for each call. The provider's process has the minimum environment and that one secret; a run receives converted text only, and its environment is an allow-list that holds no Drive secret.

## Entry points

| Call | What it does |
|---|---|
| `source-add --source <id> --type file\|notion\|drive --origin <name, address or Drive file id>` | register a source |
| `source-import --source <id> (--file <path> \| --url <address>)` | import a version; an unregistered id is registered |
| `source-refresh --source <id> [--file <path>]` | a new version: a new file, the page again, or the file the person changed in the folder |
| `source-describe --source <id> --description <text>` | the person's description |
| `source-drive [--file-id <id> --source <id>]` | terminal only: open the Picker and make each picked FILE a source with its first version; or import one file already picked |
| `sources` | the catalog, with each source's status (`ok`, `changed`, `missing`, `empty`) |
| the page | `GET/POST /projects/{p}/sources`, `/sources/{id}/files` (the upload follows the existing file route), `/import`, `/refresh`, `/refresh/files`, `/description` |

## Known limits and improvements

- There is no screen for the sources yet; the page's routes exist and the plan card shows each task's sources (and highlights a web task that receives them). An ingest is a task since P5: the step kind `ingest` (`runtime/step_ingest.py`) wraps the same operations on the step engine, with the arguments a plan shows and its hash covers; the terminal's `source-import` stays the synchronous way.
- A Drive folder as a source is not built (`drive.file` does not reach a picked folder's files; it would need `drive.readonly`, a wider scope, and the maintainer's decision). Drive write-back is not built (the Drive provider is sources-only); the hidden-text flag of a converted HTML or PDF is built (P8: `outputs.md`, "Hidden text").
- The Markdown export of a Google Doc, Google's 10 MB export limit and the Picker's behaviour with the page's headers are not verified against the live service (`providers/documents/README.md`, "Google Drive").
- A PDF of scanned pages has no text layer; no OCR is made, and the manifest notes it.
- A table in a PDF comes out as the lines of its cells (`pdftotext`), not as a Markdown table; the MarkItDown measured recovers the table but drops the page marks and writes `(cid:n)` for a bullet, so `pdftotext` was kept (the comparison in `docs/decisions.md`).
- Text a Word document marks as hidden still comes out (pandoc keeps it); like the text hidden by CSS in HTML it waits for the hidden-text flag of P8.
- A formula cell with no stored value in a workbook comes out empty (the converter reads stored values, it calculates nothing).
- A source over the converted cap is refused, not indexed: indexing and retrieval wait for a real case.
- A folder synced between machines is written by one host at a time: every writer takes the folder's lease (`.openhora-lease`, limit L28), and a live lease of another host refuses the write and names that host; the sources lock stays a file under `data_dir`, never inside the folder. Old versions are pruned beyond `source_versions_kept` ([unattended.md](unattended.md)).
- The converter image is built from a pinned definition by a step the person starts (`providers/converter/container.py build --confirmed`); the base image is pinned by digest, the Debian packages by a dated snapshot of the Debian archive and the Python packages by a lock of exact versions and sha256 hashes (`providers/converter/requirements.lock`, installed with `--require-hashes`). The tools it holds are poppler's `pdftotext` and `pandoc` (the Debian versions of that snapshot), `openpyxl`, and `python-pptx` 1.0.2 for presentations; which tool converts which format was chosen by a measured comparison in which Microsoft's MarkItDown was measured and not adopted (`providers/converter/README.md`, `docs/decisions.md` 2026-10-15).

## Changes

- 2026-10-15: the registry's type column admits `drive` (migration 14, package P6b); the rows P7 stored as a `file` with a `drive:` origin were rewritten.
- 2026-10-15: the lease and the retention of old versions, with package P-OPS (limits L28 and L29; [unattended.md](unattended.md)).
- 2026-10-15: Google Drive files as sources (P7): `providers/documents/gdrive.py`, its authorization and the one-shot Picker page, `source-drive`, the refresh by version, `public_row`; files only, one scope.
- 2026-10-15: first version, with package P4 (the sources folder and limits L21 to L27, the registry and versions of migration 11, the catalog, `converter:document`, Notion pages by address, the planner's choice in `core-orchestrator` 3.0.0, the plan card, the copies a task receives).
- 2026-10-15: package P4b: presentations (pptx) are a source, converted by python-pptx (a hidden slide is not read); MarkItDown was measured and not adopted; the other formats keep their tools (`docs/decisions.md`).
- 2026-10-15: the step kind `ingest` (P5): an import or a refresh as a step task of a plan, run by `run-step`; its failures are closed codes, and it writes nothing in the project or in the sources folder but the version.
