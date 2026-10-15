# The sources of a project

What a person gives a project to read, how it becomes clean text a task can use, and the guardrails that keep it from becoming a way in. It crosses three layers of the platform map and belongs to none alone: the runtime owns the registry and the folder (`runtime/sources.py`, `runtime/ops_sources.py`), a provider converts (`providers/converter/`), another reads a Notion page (`providers/documents/notion.py`), and the store keeps the rows. Package P4 of the delegation plan; decisions D9, D10, D11, D13, D16, D29 and D30 of `docs/architecture/delegation-platform-plan-2026-10-14.md`.

## Purpose

A project declares **sources**: an uploaded file (a PDF, a Word document, a spreadsheet, a CSV, an HTML page, a text file) or a Notion page chosen by its address. Each import is an **immutable version** kept in the project's **sources folder** (`sources_dir`), as the original, the converted text and a manifest. A **catalog**, built by code from the converted text alone, tells the planning run what each source holds, so that the **plan** can name, for each task, the sources it needs; the person approves that plan by its hash, and a task **receives copies** of the newest version of each source at the moment it starts. The sources folder itself never enters a run.

The idea behind each piece, in one line each:

- the folder is the person's, it is dedicated and private, and the runtime treats it as hostile ground: it writes only inside it, through an open descriptor, and reads nothing from it that it did not first check against a hash;
- a file is never read on this machine: bytes go through the generic intake (the length bounded first, the type read from the bytes), a container with no network converts them with adopted open tools, and only the converted text is scanned, catalogued and handed to a run;
- the planner is given data, not instructions: the catalog is text other people wrote, and it is named in the external-content line of `core-orchestrator`;
- a task sees only the sources chosen for it, and the plan shows them before anyone approves it.

## Artifacts it owns

| Artifact | Where | Notes |
|---|---|---|
| The sources folder | `sources_dir` of `runtime.json` (mandatory, no default; accepted only in the terminal) | `.openhora-sources` (the marker), `.incoming/` (staging, emptied after each import), `<source id>/<version>/original.<ext>`, `converted.md` or `converted.csv`, `manifest.json`. Files are mode 0400; a version is moved into place with one rename and never written again |
| The registry | table `sources` of the store (migration 11) | id, type (`file` or `notion`), origin (a file's name, or a Notion page's address; never a credential), the person's description. Never deleted; only the description changes |
| The versions | table `source_versions` | one row per version: label (`import`, `refresh`, `changed-by-person`), who made it (`runtime` or `person`), the sniffed kind, the hashes and sizes of the original and the converted text, the converter and its tools, `hidden_text` (null: reserved for P8), warnings, the catalog entry, the origin's own version (a Notion page's `last_edited_time`), the date from the clock. Never changed, never deleted |
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

1. **L21** dedicated, private, marked, mode 0700 (at acceptance and before every use).
2. **L22** disjoint from `data_dir`, `store_db`, the checkout and the local evidence folder, by device and inode.
3. **L23** the runtime writes only inside it and never follows a link out; the home folder, the root and a folder that contains the project are refused.
4. **L24** what a container writes comes back only as regular files, with closed names, under a byte cap.
5. **L25** a file changed outside the runtime is found by its hash, checked again, labelled as the person's, and never used unattended.
6. **L26** the work copy excludes the folder, even inside a tracked tree.
7. **L27** the catalog is built only from converted output.

Beside them:

8. **A converted text is scanned for credentials after the conversion**, because text compressed inside a PDF is invisible to a scan of its bytes; a text that fails is not kept, and nothing is left in the folder or the store.
9. **A source has a size cap, with a warning.** An original is at most 25 MiB (the intake's route limit). The converted text is at most 1 MiB: a task reads all of it, 1 MiB is beyond what a model's context takes, and indexing or retrieval waits for a real case. From 256 KiB (about 65,000 tokens at four bytes a token) the import succeeds and says it is large, and the catalog entry carries the warning.
10. **The planner chooses, code checks.** The router's reply may carry a `Sources:` line (`runtime/router.py`); an id the project does not hold, or a skill that is not in the plan, makes no plan (the person is asked). An `@mention` is added by code to every task of the delivery. The ids are part of each task, so they are in the plan hash; a new version of a source changes none of them.
11. **A task receives the newest version at the moment it starts** (D29): copied from the folder after its files are hashed against the record; recorded as id, version and sha256. A source refreshed after the plan and before the start reaches the task as the newer version; one refreshed after the start does not reach that run. A later run of the same task takes the newest version at its own start.
12. **A Notion page is read with its own read-only secret** (`NOTION_SOURCES_TOKEN`, store username `notion-sources`), by `read --as-source`; `NOTION_TOKEN`, which writes, is never used for sources. The page's id is extracted from the address (every URL shape the provider knows: a bare id, `Title-<id>`, a workspace path, a `p=` query, a `notion.site` host); anything else is refused.
13. **The channels.** The four writes (`source-add`, `source-import`, `source-refresh`, `source-describe`) are for the terminal and the page; the catalog read (`sources`) is also for the MCP mode and the messaging channel, and sits in the group `sources`, which a project's policy turns on (it is not in the default policy of messaging: the catalog shows samples of the person's data).

## Entry points

| Call | What it does |
|---|---|
| `source-add --source <id> --type file\|notion --origin <name or address>` | register a source |
| `source-import --source <id> (--file <path> \| --url <address>)` | import a version; an unregistered id is registered |
| `source-refresh --source <id> [--file <path>]` | a new version: a new file, the page again, or the file the person changed in the folder |
| `source-describe --source <id> --description <text>` | the person's description |
| `sources` | the catalog, with each source's status (`ok`, `changed`, `missing`, `empty`) |
| the page | `GET/POST /projects/{p}/sources`, `/sources/{id}/files` (the upload follows the existing file route), `/import`, `/refresh`, `/refresh/files`, `/description` |

## Known limits and improvements

- There is no screen for the sources yet; the page's routes exist and the plan card shows each task's sources (and highlights a web task that receives them). An ingest is not a task before the step engine (P5).
- Google Drive and write-back are P7 and P8; the hidden-text flag of a converted HTML or PDF is P8 (`hidden_text` is null today).
- A PDF of scanned pages has no text layer; no OCR is made, and the manifest notes it.
- A formula cell with no stored value in a workbook comes out empty (the converter reads stored values, it calculates nothing).
- A source over the converted cap is refused, not indexed: indexing and retrieval wait for a real case.
- A folder synced between machines needs the lease file of P-OPS; until then the sources lock is a file under `data_dir`, never inside the folder.
- The converter image is built from a pinned definition by a step the person starts (`providers/converter/container.py build --confirmed`); the base image is pinned by digest and the packages by a dated snapshot of the Debian archive. The tools it holds are the Debian versions of that snapshot: poppler's `pdftotext`, `pandoc` and `python3-openpyxl`.

## Changes

- 2026-10-15: first version, with package P4 (the sources folder and limits L21 to L27, the registry and versions of migration 11, the catalog, `converter:document`, Notion pages by address, the planner's choice in `core-orchestrator` 3.0.0, the plan card, the copies a task receives).
