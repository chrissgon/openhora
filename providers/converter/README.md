# The document converter (`converter:document`)

Turns a file into text for the sources of a project (`runtime/sources.py`, `docs/architecture/platform/sources.md`): PDF, Word (docx), spreadsheet (xlsx), presentation (pptx), CSV, HTML and plain text to Markdown or CSV. A class the runtime uses and no skill may require, like the messenger: on purpose it is not in `contracts/environment.md`, and in `providers/resolve.py` it is a role (`ROLES`) and not a listed class (`LISTED`). One implementation, `container.py`.

## What it adopts (principle 14)

Nothing here converts a document by code written for the purpose. The tools are open and pinned: poppler and pandoc by a dated snapshot of the Debian archive (bookworm), openpyxl and python-pptx by a lock of exact versions and sha256 hashes (see "The tools, chosen by a comparison" below):

| Format | Tool | Notes |
|--------|------|-------|
| PDF | poppler's `pdftotext` (package `poppler-utils`) | a text layer only; a PDF of scanned pages has none and the manifest says so (no OCR). One `[page n]` line before each page |
| Word (docx) | `pandoc` (`--sandbox`: no file but the input is read) to GitHub-flavoured Markdown | pictures are dropped |
| HTML | `pandoc --sandbox` after `<script>`, `<style>`, `<noscript>` and `<template>` blocks are removed | text a person cannot see (CSS, white on white, off the page) is flagged in `info.json` by the standard library's parser (see "Hidden text") |
| Presentation (pptx) | `python-pptx` (1.0.2, from the lock), written as Markdown by `convert_pptx` in `_inner.py` | one section per visible slide: `# <title>` (`# Slide n` when it has none), its text (the body placeholder as list items, indented by level), its tables as Markdown tables, its speaker notes under `### Notes`; a hidden slide (`show` is `0` or `false`) is not read and the manifest says so; pictures and charts are dropped |
| Spreadsheet (xlsx) | `openpyxl` (3.1.5, from the lock), stored values only (`data_only`), visible sheets only | one sheet comes out as `converted.csv`; several as `converted.md` with a `## Sheet: <name>` section and a `csv` fence each; a hidden sheet is not read and the manifest says so |
| CSV | the standard library's `csv` | the delimiter (`,` `;` tab `|`) is detected and the file is written with commas; UTF-8, else Windows-1252 |
| Text | the standard library | UTF-8 (a byte order mark dropped), else Windows-1252; NUL characters out |

`providers/converter/_inner.py` is the small program that drives them inside the container; it adds a guard against an archive that declares too much data or too many entries, and cuts the text one byte over the cap (1 MiB) so that the host sees it and refuses.

## Macro-enabled packages are refused (ATT-5)

A Word document, a spreadsheet or a presentation that carries macros is refused for every source (a file the person adds, a file from a messaging app, a Drive file), before any tool reads it: no tool of the image runs VBA, but a file that holds code is not a source this converter takes, and the original stays only where the person put it. `refuse_macros` in `_inner.py` runs first in `convert` for the types `docx`, `xlsx`, `pptx` and `ooxml`, after the same size guard (`check_package`: entries and declared bytes). It judges by content, never by name (the input is mounted as `/in/input`, and a sender chooses a name): it refuses when the package has

- a part named `vbaProject.bin`, `vbaProjectSignature.bin` or `vbaData.xml`, at any depth;
- a part under `xl/macrosheets/` (Excel 4 macro sheets, which hold macros with no VBA project);
- a content type (a `Default` or an `Override`, any `ContentType` attribute of `[Content_Types].xml`) or a relationship type (the `Type` attribute of every `*.rels` part) that contains `macroEnabled` (the main part of a `.docm`, `.dotm`, `.xlsm`, `.xltm`, `.xlam`, `.pptm`, `.potm`, `.ppsm`, `.ppam` or `.sldm`), `vbaProject` (also the signature), `vbaData` or `macrosheet`.

Part names are compared as a reader would read them: backslashes as slashes, percent escapes decoded, no leading slash, no space at the ends, case folded. A package with two parts whose names are the same after that (an exact name twice, or `[CONTENT_TYPES].XML` beside the real one) is refused, so the part a reader opens is the part this check read; a package with no `[Content_Types].xml` is refused for every declared type. The XML is read with `xml.parsers.expat`, which decodes character references (`m&#97;croEnabled` is read as `macroEnabled`); a part with a document type declaration or an entity is refused before anything is expanded. Each XML part is read up to 2 MiB and all of them up to 32 MiB; a part that is larger, damaged (a corrupt compressed stream) or not well formed is a closed failure with its own sentence (exit 3, no traceback).

A file renamed from `.docm` to `.docx`, or sent with a declared type of `docx`, is refused the same way. The program prints nothing on standard output, writes `error: the package holds macros (VBA code or macro sheets): a macro-enabled Office file is not converted` on standard error and exits 3, which the host reports as a failed conversion (`the conversion failed: ...`) and `runtime/sources.py` records as a refused import (reason `convert`), exactly as it records the converter's other refusals. Not covered, and why: the old binary formats (`.doc`, `.xls`, `.ppt`) are not an Office Open XML package, are not a type the intake takes (`sources.SUBTYPES`) and would fail `check_package` with "not a valid Office package" if named; a macro-enabled file embedded inside an otherwise plain package (an `.xlsm` in `word/embeddings/`) is not opened and not converted, only the outer package's own parts are judged; an OpenDocument file is not accepted at all. Also outside the check, because nothing in the image runs them or follows them (no network, no VBA, no Office): ActiveX controls (`activeX*.bin`), OLE objects (`oleObject*.bin`), `customUI` ribbon callbacks, a remote `attachedTemplate`, and dialog sheets (`xl/dialogsheets/`, which hold no code).

Changing `_inner.py` changes the image's definition hash (`container.py` `DEFINITION_FILES`), so the image of the new definition must be built before the next conversion: `python3 providers/converter/container.py build --confirmed`, then `python3 providers/converter/container.py --check` (prints the new tag and `definition`). It is not a file of the measurement fingerprint (only `evals/container/` is), so no skill, evidence or band is touched.

## Hidden text (package P8, finding S9)

A page or a PDF can hold text a person cannot see and a model reads. For an HTML page and a PDF, `info.json` carries `hidden_text`: `{"examined": true, "count": n, "kinds": {kind: n}, "hints": [...]}` (a hint names a kind and a place, never the text), `{"examined": false, "why": "tool_failed"}` when the check could not be made, and `null` for every other kind (not examined). The kinds are a closed list (`HIDDEN_KINDS` of `_inner.py`, copied in `runtime/sources.py`): `display_none`, `visibility_hidden`, `hidden_attribute`, `zero_size`, `tiny_text`, `off_page`, `transparent`, `white_on_white`, `color_matched`, `invisible_text`. HTML is read with the standard library's parser (the style attribute, the simple rules of `<style>` blocks, the `hidden`, `bgcolor` and font `color` attributes); a PDF with poppler's `pdftohtml -xml`, twice, the second time with `-hidden`: a fill colour that matches the white page, a font of 2pt or less, and the pieces only the second run has (the invisible render mode). The host keeps only the closed words, bounded numbers and plain hints (`sources.hidden_text_record`), writes the record into the version's manifest and row, and adds a count and a warning to the catalog entry. What it does not find is listed in `docs/architecture/platform/outputs.md`; a scanned PDF with a text layer is flagged on purpose.

## The other direction

The converter turns a file into text. Turning a task's text into a file (CSV, workbook, Word document, PDF) is its twin, `providers/exporter/` (class `exporter:document`, `providers/exporter/README.md`).

## The tools, chosen by a comparison

Microsoft's MarkItDown was measured and not adopted. `tests/compare_tools.py` ran it and the tool already there on every fixture, inside an image built for the purpose, and measured by script: words of the document missing from the output, phrases that must come out whole, text that must never come out (a script's body, a hidden sheet or slide), headings, table rows and whether the table keeps its header, list items, `(cid:n)` noise, the PDF page marks, size and time. The table and the reasons are in `docs/decisions.md` (2026-10-15). In short:

- **Word (docx):** pandoc. Equal on words, headings and lists; MarkItDown writes the table's first row as an empty header.
- **HTML:** pandoc. Raw MarkItDown leaves the text of `<noscript>` and `<template>` in the output; with the same pre-filter it would only tie, and it is about ten times slower.
- **Spreadsheet (xlsx):** openpyxl. MarkItDown reads hidden sheets and writes `NaN` for an empty cell and `10.0` for `10`.
- **PDF:** `pdftotext`. Equal on words, columns and reading order; MarkItDown keeps a table as a Markdown table where `pdftotext` writes its cells one per line, but it drops the `[page n]` marks and writes `(cid:127)` for a bullet. A table in a PDF is therefore a known limit of the choice.
- **Presentation (pptx):** python-pptx, directly. MarkItDown uses it underneath, writes no list markers, leaves the text of a hidden slide in, and would have added `magika`, `onnxruntime`, `numpy` and `requests` to the image (653 MB instead of 440 MB). The image is 444 MB.
- **CSV and plain text:** the standard library, unchanged.

### The Python packages

`requirements.in` names `python-pptx==1.0.2` and `openpyxl==3.1.5` (openpyxl moved from the Debian package into the same environment, so that the image has one Python environment and one hash-checked lock, and the version the comparison measured is the version that runs). `requirements.lock` holds the 7 packages they need, each at an exact version with every sha256 of its wheels, for every platform (one lock serves the amd64 and arm64 images). The Dockerfile installs it into `/opt/venv` with `pip install --require-hashes --only-binary=:all: --no-deps`: a file whose hash is not in the lock is refused, nothing is resolved at build time and no compiler is in the image. pip and setuptools are removed afterwards (the environment holds the 7 packages of the lock and nothing else). The build needs the network once (`container.py build --confirmed`); a conversion never does. To remake the lock, run the command in `requirements.in`.

### The presentation function

`convert_pptx` reads the one package with python-pptx, after a check of its size that is stricter than the other Office files' (150 MiB declared in all, and 24 MiB for every part that is not a known kind of media or an embedded package, whatever the part is called: a slide saved as `slide2.bin` and typed XML by an Override counts). python-pptx keeps every part in memory and the XML becomes trees tens of times its size in a container of 1024 MiB; the caps turn most oversized decks into the named error "the package declares too much XML" or "too much data". They are not a guarantee: a deck just under them made of the densest possible markup can still use the memory, and then the container is killed (exit 137), a closed failure the host reports as a failed conversion, with nothing written; it makes no network connection (before the library is imported `socket.connect`, `create_connection` and `getaddrinfo` raise, behind the container's `--network none`) and loads no plugin. Any input of the program that is an address (`http:`, `file:`, `data:`) or not an absolute path is refused before anything is read (exit 3, nothing on standard output). A failure of the library is `error: python-pptx could not convert the pptx file: <ExceptionName>` (no path, no text of the file) and exit 3, which the host reports as a failed conversion and which writes nothing.

## How a conversion runs

The host side (`container.py`) uses the shared container helper (`providers/_container.py`): no network, a read-only root, every capability dropped, no new privileges, 128 processes, 1024 MiB of memory (swap included), 2 CPUs, a memory-backed `/tmp` and `/scratch` (256 MiB) with no exec, an unprivileged user (on Linux the caller's own uid and gid, which `providers/_container.py` passes with `--user`; 65534 in the image, which is what runs elsewhere, for example with Docker Desktop on a Mac), an image run by its id and never pulled, and a label that lets `reap` remove a container a crash left. The input is mounted read-only at `/in/input`; nothing else of the host is visible and no environment variable passes.

The result leaves the container as a stream of frames on its standard output (`OHF1`, then `FILE <name> <size>` and the bytes, then `END`), which the host reads up to a cap and parses with fixed rules (`parse_frames`): the names are `converted.md` or `converted.csv`, and `info.json`; sizes and counts are capped; anything else is refused. The host writes the outputs into the folder it was given (mode 0700, empty) as new regular files, mode 0600, with `O_EXCL` and `O_NOFOLLOW`. Nothing is copied from the container's file system, so nothing it leaves as a folder, a link or a pipe can come back; the caller (`runtime/sources.py`, `collect_outputs`, limit L24) reads the folder back with its own checks, and scans the converted text for credentials.

## The image

`Dockerfile`, `.dockerignore`, `_inner.py` and `requirements.lock` are the definition (`requirements.in` is not: the lock is what is installed); the image is named `openhora-converter:<12 characters of the hash of those four files>`. It is built here, by a step the person starts, and never pulled when a conversion runs:

```sh
python3 providers/converter/container.py build --dry-run       # the command, nothing built
python3 providers/converter/container.py build --confirmed     # builds it (the network: the base image, the Debian snapshot, PyPI for the files of the lock)
python3 providers/converter/container.py --check               # docker is usable, its daemon is local, the image is built
```

The base image is pinned by digest (`debian:bookworm-20261005-slim`, the digest the other container definitions of the project pin), the Debian packages by the snapshot `20261006T000000Z` and the Python packages by `requirements.lock` (remake it with the command in `requirements.in`). Changing the Dockerfile, `.dockerignore`, `_inner.py` or `requirements.lock` changes the tag: the next conversion asks for a build.

Each change of the definition leaves the earlier image on disk. They are never removed by a run or by the upkeep. `python3 scripts/doctor.py --unattended` shows their count and size in its `images` row; `python3 scripts/doctor.py --remove-old-images --dry-run` lists what would go and `--confirmed` removes it, by tag, never with `--force` or `prune` (an image that is in use is kept and reported). An image is selected only when it carries the label `org.openhora.definition`, its repository is `openhora-converter` exactly and its label and tag differ from the current definition's.

## Tests

- `tests/test_converter_host.py` (offline): the frames, the definition and its hash, the exact command with each limit, the checks on the input and on the out folder, the verbs. No container is started.
- `tests/test_converter_inner.py` (offline): the program on this machine with the tools it finds (pandoc, `pdftotext`, openpyxl, python-pptx; a test that needs one that is missing is skipped and says so), including the presentation function (slides, notes, tables, levels, a hidden slide, a broken file), the socket guard, the refusal of an address and the refusal of macro-enabled packages (every macro main content type, a VBA project part under any name, a macro sheet, a relabelled `.docm`, an injected project in a real fixture, the exit code and the fixed sentence).
- `tests/test_converter_hidden.py` (offline): the hidden-text detection for each kind, on HTML fixtures and on the XML of a real `pdftohtml` run.
- `tests/test_converter_docker.py` (opt in, `WB_CONVERTER_DOCKER_TESTS=1`): the image built, each format converted in a real container, the hidden text of a page and of a PDF flagged (a presentation included, and the version of python-pptx the image holds, with no MarkItDown, numpy or onnxruntime in it), a key hidden in a PDF's compressed text and another in a slide found in the converted text and not in the raw bytes, and refused by the credential scan that runs after the conversion, and the limits as the image really holds them (no network, a read-only root, a scratch with no exec, no secret in the environment, an unprivileged user).

Fixtures are fictional (`tests/fixtures/`); `tests/make_fixtures.py` made the `review.*`, `rich.*` and `columns.pdf` ones (`uv run providers/converter/tests/make_fixtures.py`). To repeat the comparison, build an image from a scratch copy of this folder with `markitdown[docx,pdf,xlsx,pptx]==0.1.8` added to `requirements.in` and the lock remade (MarkItDown is in no image of the project), and run `tests/compare_tools.py` in it as its text says.
