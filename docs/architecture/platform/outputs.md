# The outputs of a task

How a task's result leaves the project: as a file made by code, or as a write to the platform that holds the project's documents; and how the text a source holds is checked for what a person cannot see before a model reads it. It crosses the layers like the sources do: the step engine (`runtime/steps.py`) runs the kinds that make a file and the kind that prepares a write, an effect kind (`runtime/effect_write.py`) carries the write, the operations layer approves and executes it (`runtime/ops_step_effects.py`), a provider renders (`providers/exporter/container.py`) and another writes (`providers/documents/`). Package P8 of the delegation plan; decision D17 and finding S9 of `docs/architecture/delegation-platform-plan-2026-10-14.md`.

## Purpose

Three things, one idea: **nothing leaves the project, and nothing reaches a model, in a form the person has not been able to see.**

- **A file made by code.** A task's result, a Markdown or a CSV file, becomes a CSV file, a workbook, a Word document or a PDF, by adopted open tools in a container with no network and no model. The file is written into `docs/outputs/` of the project.
- **A write-back.** The text of a project document replaces, whole, a document on the platform (a Notion page today). It is an **external effect**: the person is shown the exact content, approves its hash once, code writes it once, and the approval and the result are recorded. If the document was edited after the task read it, nothing is written and the person is asked again.
- **Hidden text is flagged.** An HTML page or a PDF can hold text a person cannot see (white on white, a one-pixel font, `display: none`, the invisible render mode of a PDF) that a model reads. The converter counts it, names the kinds and gives location hints, never the text, and the version's manifest and the catalog say so.

## Artifacts it owns

| Artifact | Where | Notes |
|---|---|---|
| An output file | `docs/outputs/<name>.<csv\|xlsx\|docx\|pdf>` of the project | written by the engine's `write_file` only; an existing file is replaced only when the task's arguments say `"replace": true`, and then whole; the project's version control keeps the earlier ones |
| The effect document of a write-back | `<data_dir>/step-effects/<task id>/<cycle>/effect.json` (mode 0600, in a 0700 folder) | the document the approved hash is the hash of: effect, task, provider, target `{id, path}`, base `{text_sha256, version}`, content, content sha256, bytes |
| The pending `effect` decision | the store | kind `effect`, `payload_sha256` = the hash of the effect file; its payload names the step, the cycle and the closed facts (target, path, bytes, content hash), never the text |
| The approval | table `approvals` of the store | scope `action`, bound to the decision and the hash; `pending-execution`, then `executed` (or `revoked` when the effect is answered); a generated row in `docs/workbench/state.md` |
| The hidden-text record | `hidden_text` of a version's `manifest.json`, the version's row (1, 0, null) and the catalog entry | a count, a count for each kind of a closed list, up to ten location hints |
| The renderer's image | `openhora-exporter:<12 characters of the hash of its definition>` | built by a step the person starts (`python3 providers/exporter/container.py build --confirmed`); never pulled when a render runs |

## Abstractions

| Name | What it is | Where |
|---|---|---|
| Export kinds | `export-csv`, `export-xlsx`, `export-docx`, `export-pdf`: one step, `render`; a row of `FORMATS` is a format | `runtime/step_export.py` |
| Renderer | the host side of the container that makes the file: the private input, the exact `docker run`, the frames, the caps | `providers/exporter/container.py` |
| Formula guard | a cell that starts with `=`, `+`, `-`, `@`, a tab, a CR or a LF (after any leading spaces and invisible characters), or their fullwidth forms, is text | `providers/exporter/_render.py` `guarded` |
| Gate | the last step of a kind: no executor, it opens an `effect` decision with the hash of the exact content and the task waits for the person | `runtime/steps.py` `Gate`, `_gate_at` |
| Effectful step | a step whose executor would perform an external effect itself; refused for every kind when it is registered | `runtime/steps.py` `Kind.effectful`, `_check_effects` |
| Write-back kind | `write-back`: `prepare` (read the content and the target, write the effect document) and the gate `write` | `runtime/step_write_back.py` |
| Effect kind `write` | the side-effect word and module of the write; the third path of an effect, the **step path** | `runtime/effect_write.py`, `effects.KINDS` |
| Step-effect approval | the approval and the execution of a gate's effect | `runtime/ops_step_effects.py`, called by `ops._approve_effect` |
| Hidden-text record | `{"examined", "count", "kinds", "hints"}`, checked on the host against the closed list `HIDDEN_KINDS` | `providers/converter/_inner.py` (finds), `runtime/sources.py` `hidden_text_record` (keeps) |

## Entry points

| Call | What it does |
|---|---|
| a step task of kind `export-csv`, `export-xlsx`, `export-docx` or `export-pdf` with `{"input": "docs/<file>", "name": "<name>"}` | makes `docs/outputs/<name>.<ext>`; started with `run-step --task <id>` (not `unattended`) |
| a step task of kind `write-back` with `{"target": "<document id>", "content": "docs/<file>.md"[, "source": "<source id>"]}` | reads, prepares, and stops at an `effect` decision |
| `approve --id <pending id> --sha256 <the hash shown>` | the terminal and the page only: executes the write once |
| `reject --id <pending id>` | cancels the task; nothing is written |
| `python3 providers/exporter/container.py --check \| build (--dry-run \| --confirmed) \| render --format <f> --input <file> --out-dir <folder>` | the renderer's image and a render by hand |
| `sources` | the catalog; an entry with hidden text has `hidden_text` and a warning |

Nothing creates these step tasks from a sentence yet: the flow files learn the key `step` with P6.

## Why these tools (principle 14)

| Format | Tool | Why |
|---|---|---|
| CSV | the standard library's `csv` | a table is rows of text; nothing to adopt |
| XLSX | `openpyxl` (Debian package, already in the converter's image) | writes a cell as a typed string and sets the quote-prefix style; no model of a spreadsheet to build |
| DOCX | `pandoc` (Debian package) | reads GitHub-flavoured Markdown and writes Word |
| PDF | `pandoc` to HTML, then `WeasyPrint` (installed from `requirements.lock`, wheels only, by hash) | HTML and CSS printed on pages, with the DejaVu fonts, in Python with no JavaScript engine. The Debian package of the same name depends on `python3-cffi`, which pulls a compiler, the Python headers and a numerical stack and makes the image about three times as large (measured: 1.27 GB against 506 MB). The short-video renderer's headless browser is an image built for video frames and lives on another branch; a document needs no browser |

Why a second image and not the converter's: the converter reads a person's hostile file into text; the renderer writes a file from a task's text. They share no tool but pandoc and openpyxl, the renderer needs WeasyPrint and its fonts, and another package's change to the converter's definition (the PPTX path of P4b) must not rebuild or break the renderer. Both are built from the same Debian snapshot and base image.

## Where an output goes

`docs/outputs/` of the project, through `write_file`, which refuses the sources folder. The sources folder holds what people gave the project as immutable versions made by the import; an output written there would be read by a later task as something a person provided (limits L23 and L26). A person who wants an output as a source imports it. A task never replaces a file that is already there unless its arguments say `"replace": true` (the plan shows its arguments, so a plan that replaces a file says so); the project's version control is the history.

## The formula guard (finding S9)

A spreadsheet runs a cell as a formula when its text starts with `=`, `+`, `-` or `@`; a tab and a carriage return are on the usual lists (OWASP's guidance), and so is a line feed here; the four fullwidth forms of `=`, `+`, `-` and `@` (U+FF1D, U+FF0B, U+FF0D, U+FF20) are guarded because some spreadsheets read them as their ASCII twins. The guard looks past leading spaces, no-break spaces, ideographic spaces (U+3000), zero-width characters and byte order marks. A guarded cell is written:

- in a CSV file: with a single quote in front of it, as the guidance says (the file has no cell types, so the quote is part of the text), and in front of every segment of the cell that follows a `;`, a bar or a tab inside it, because a spreadsheet in a locale that separates cells with `;` (pt-BR, de, fr) splits there: `x;=1+1` is written `x;'=1+1`. Every cell is quoted and a row ends with CR LF, so a lone CR or LF is inside the quotes;
- in a workbook: as a text cell (never a formula) with the quote-prefix style, its text unchanged.

A cell that starts with none of them is written as it is, except that in a workbook a plain unsigned number (digits, one decimal point, no leading zero, at most 15 digits) is stored as a number. **A signed number such as `-5` is text on purpose**: the guard does not tell it from `-5+cmd`, and a table of negative amounts is read as text in the workbook and with a quote in the CSV. The cost is real; the person converts the column. Tests: one for each guarded character, in a CSV file and in a workbook (`providers/exporter/tests/test_exporter_inner.py`), and the real workbook read back in the container (`test_exporter_docker.py`).

A Markdown document is cleaned before a writer reads it: a picture becomes its text, a raw HTML or other raw fragment is dropped, a metadata block is text and sets nothing, and a link keeps its address only when it is `http`, `https`, `mailto` or a fragment (a `file:`, `smb:` or `javascript:` address in a document is how a file or a login leaks).

## The write-back

```
step task "write-back"                 person                           code
  prepare: read docs/<file>.md (no credential, <= 256 KiB)
           read the target (documents provider `read`)
           record sha256 of the text it holds
           write effect.json (target id + path + base + content)
  write  : the gate opens an `effect`   ->  sees the content whole, the hash,
           decision, hash = sha256(effect.json)    the target's id and what it replaces
                                             approve --sha256 <hash>  (terminal or page)
                                                                      read effect.json by that hash
                                                                      record the approval (scope action)
                                                                      read the target again: same text?
                                                                      provider `write --confirmed`, once
                                                                      effect_done: decision approved, task done
```

**The hash.** It is the sha256 of the canonical text of the effect document, which holds the target's identifier, the path, the content whole, the content's hash and the base. The target's id is inside it (finding S9): a document aimed at another target has another hash, and the approval of the first covers nothing of the second (`test_a_different_target_is_a_different_hash_and_the_first_approval_covers_nothing_of_it`). The effect file is read only if its bytes have the approved hash, so an edit after the preview stops at the read.

**Refused by structure.** Nothing in the engine or in the kind writes to the platform: the gate has no executor and `prepare` only reads. The one function that writes is `effect_write.execute`, reached from the operation `approve` and nowhere else, and it refuses unless it is given the approval of this document: scope `action`, status `pending-execution`, and a `payload_sha256` equal to the hash of the document it is about to write. `approve` itself refuses an effect from any channel but the terminal and the page (`EFFECT_CHANNELS`), and a word typed into a conversation is no approval. A messaging channel or the MCP mode cannot approve a write.

**Edited since it was read.** The platform's version is rounded and may not move for a small edit, so the guard is the text: just before the write the target is read again, and its text must have the sha256 the task recorded. A different text is `stale` and nothing is written, with two exceptions that the same read tells apart. If the text is exactly what this write would leave (the provider's dry run prints the sha256 of its own round trip of the content), an earlier attempt of this approval landed and its answer was lost: nothing is written again, and the write is recorded as `replayed`. And if the write call itself fails, nobody knows whether the page was replaced (a lost answer; a replace that appended the new blocks and failed before deleting the old ones): the effect says the outcome is unknown and to read the page, stays open, and approving the same hash again reads the page first. A `stale` effect is answered with the reason ("nothing was written by this attempt; the document is not the one the task read: it was edited, or an earlier attempt did not finish"), the approval of that attempt is revoked, the task is ready again and, started, starts over from `prepare`, which reads the page as it is now and opens a new effect with a new hash. A page left half written by a failed replace matches neither text and comes back this way. The person's edit is never overwritten. A text that was changed and put back is not stale. Between the second read and the write is the platform's own gap, the width of a call; the write replaces the whole document and merges nothing (the documents contract), so this is said, not hidden. With `source` the task also compares the page with the converted text of that source's newest version, the version it read, and stops at `prepare` if they differ.

**Once.** After `effect_done` the decision is resolved `approved`, the approval `executed` and the task `done`; a second approval of the same hash is refused (`not open`). The provider's write passes an idempotency key built from the store and the decision, but a write to an existing document ignores it (the key serves creation), so what makes a retry safe is the page read described above: a page that already holds this content is recorded as `replayed`, not written again.

**Any platform.** The effect names the class `integration:documents`, not an implementation: `read` and `write` are two verbs of its contract. A provider that cannot write answers exit 2 and the effect fails with nothing written; the Google Drive provider is sources-only today, so a Drive write-back is a second target added with its own work and tests, and edits none of the modules above.

**The configuration bounds apply.** The documents object's `expires` (the bounds of writing to a platform) is checked when the task prepares and again at the approval.

## The rule that a review is harmless to pass

A stop of a step task passes on the word `continue` from any channel, including a messaging app. So no step performs an external effect itself, before a stop or after one, and every external effect goes through a gate, whose approval is the hash of the exact content from the terminal or the page. What is **code**, and what is a **test**:

- Code: `steps.register` refuses a kind that declares an `effectful` step, whatever its place and whether or not the kind starts on its own. A step kind is handed its services through `ctx.services` (`runtime/ops_step_seams.py`): `documents` has `read` and `stat` and no way to write (its two verbs are literals), `effect_files` writes and reads the effect document and does not execute it, `render` makes a file from a text. The document of a write-back and its preview are in `runtime/write_document.py`, which holds no function that calls a provider; the one function that writes to a platform is `effect_write.execute`, which only the operation `approve` reaches, and which refuses unless given the approval of exactly the document it writes. So a step kind has no function in reach that could write.
- Test, not code: Python cannot stop a module from importing another. A static test over `runtime/step_*.py` (`runtime/tests/test_steps_gate.py`) holds each step module to a row of the modules it may import (none that calls a provider: not `documents`, `board`, `effects`, the operations layer or `project_config`), and fails on `--confirmed`, `--dry-run`, `.execute`, a network module of the standard library. It is a tripwire; a new kind is reviewed for what it imports, and adding one to the table is a visible change. `step_ingest` is the one kind with a wider row (it imports a source through the operations of the sources).

A standing approval cannot name the word `write` either (`ops._bounds_words`): each write-back is approved by its own hash.

## Hidden text

| Kind | Found in | Meaning |
|---|---|---|
| `display_none`, `visibility_hidden`, `hidden_attribute` | HTML | the element and what is under it are not shown. Text in a `<title>` outside the head, and the rest of a page after a `<title>` that is never closed (a browser reads it all as the title), is `display_none` too: a browser never shows a title, and a converter reads the tags |
| `zero_size`, `tiny_text` | HTML, PDF | a font of 0, or under 2px in HTML and 2pt or less in a PDF; a box of 1px or less with overflow hidden or a clip |
| `off_page` | HTML | a position or a text-indent 500px or more off the page |
| `transparent` | HTML | opacity 0 or a transparent text colour |
| `white_on_white`, `color_matched` | HTML, PDF | a text colour with a contrast ratio under 1.1 against its background (the page's default white when none is set) |
| `invisible_text` | PDF | text in the invisible render mode: it appears only when poppler's `pdftohtml` is told to show hidden text |

The record is `{"examined": true, "count": n, "kinds": {kind: n}, "hints": ["display_none in div element 11", "white_on_white on page 1 count 1"]}`; a hint names a kind and a place (an element's number in the document, a page), never the text. The host keeps only words of the closed list, bounded numbers and hints of lower-case letters, digits and a few signs, so a container cannot use the flag to carry text (`runtime/sources.py` `hidden_text_record`). `null` means not examined (a Word document, a spreadsheet, a CSV, plain text, a Notion page, a Markdown export); `{"examined": false}` means the check could not be made, and the catalog says so; an HTML page or a PDF whose converter gave no record the host can read is `{"examined": false}` too, never "none found". The count stops at 2000 hidden elements and the record then carries `capped: true` (the catalog says "at least"). A hint is at most 80 characters (its tag name is cut at 20 and reduced to letters, digits and hyphens) and the whole `info.json` is kept whole JSON under its cap, dropping the hints first.

**What it does not find**, because the person should not read "none found" as "none there": text under a picture or a drawn shape (a PDF's gray text on a gray rectangle is not seen); a colour match against a background that a style sheet outside the page, a selector with a combinator, a pseudo-class or an attribute, or a rule inside `@media` sets; text drawn as paths or as an image; the alt or title text of a hidden element; text a script moves or writes; hidden text of a Word document (`w:vanish`), a spreadsheet or a presentation; and, in a PDF, off-page text, which `pdftotext` does not extract and so no model reads. **A false positive on purpose:** a scanned PDF with a recognised-text layer is flagged `invisible_text`, because the person sees the picture and the model reads the layer.

## Known limits and improvements

- Drive write-back is not built (P7's provider is sources-only). D17's real cases, one for each direction, are chosen with the maintainer: everything here is tested on fictional fixtures and the Notion provider's stand-in service, and nothing was run against a real workspace.
- Nothing creates a step task from a request yet (P6). The kinds are started with `run-step`.
- A signed number in a table is text (above). A Markdown table cannot be the input of a workbook: the task writes a CSV.
- The renderer's PDF uses fonts of the image (DejaVu); a script they do not cover (for example Chinese) comes out as boxes.
- The renderer's image is about 500 MB and is built once by a step the person starts; the lock of WeasyPrint's wheels is refreshed by hand.
- A write-back replaces the whole document; there is no merge and no diff against the page beyond the hash. A person who wants to see what changes compares the preview with the page.
