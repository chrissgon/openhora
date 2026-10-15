# The document converter (`converter:document`)

Turns a file into text for the sources of a project (`runtime/sources.py`, `docs/architecture/platform/sources.md`): PDF, Word (docx), spreadsheet (xlsx), presentation (pptx), CSV, HTML and plain text to Markdown or CSV. A class the runtime uses and no skill may require, like the messenger: on purpose it is not in `contracts/environment.md`, and in `providers/resolve.py` it is a role (`ROLES`) and not a listed class (`LISTED`). One implementation, `container.py`.

## What it adopts (principle 14)

Nothing here converts a document by code written for the purpose. The tools are open and pinned: poppler and pandoc by a dated snapshot of the Debian archive (bookworm), openpyxl and MarkItDown by a lock of exact versions and sha256 hashes (see "The tools, chosen by a comparison" below):

| Format | Tool | Notes |
|--------|------|-------|
| PDF | poppler's `pdftotext` (package `poppler-utils`) | a text layer only; a PDF of scanned pages has none and the manifest says so (no OCR). One `[page n]` line before each page |
| Word (docx) | `pandoc` (`--sandbox`: no file but the input is read) to GitHub-flavoured Markdown | pictures are dropped |
| HTML | `pandoc --sandbox` after `<script>`, `<style>`, `<noscript>` and `<template>` blocks are removed | text hidden by CSS is not detected yet: the hidden-text flag is P8 |
| Presentation (pptx) | Microsoft's MarkItDown (`markitdown[pptx]`, version 0.1.8) with its local-file API only | slides as sections (`# <title>` after a `<!-- Slide number: n -->` line), tables as Markdown tables, speaker notes under `### Notes:`; pictures are dropped. The only format MarkItDown converts here (below) |
| Spreadsheet (xlsx) | `openpyxl` (3.1.5, from the lock), stored values only (`data_only`), visible sheets only | one sheet comes out as `converted.csv`; several as `converted.md` with a `## Sheet: <name>` section and a `csv` fence each; a hidden sheet is not read and the manifest says so |
| CSV | the standard library's `csv` | the delimiter (`,` `;` tab `|`) is detected and the file is written with commas; UTF-8, else Windows-1252 |
| Text | the standard library | UTF-8 (a byte order mark dropped), else Windows-1252; NUL characters out |

`providers/converter/_inner.py` is the small program that drives them inside the container; it adds a guard against an archive that declares too much data or too many entries, and cuts the text one byte over the cap (1 MiB) so that the host sees it and refuses.

## The tools, chosen by a comparison

MarkItDown (Microsoft, MIT licence) was adopted where a measured comparison on the same fixtures showed it at least as good as the tool already there, and kept out where it was not. `tests/compare_tools.py` runs both tools on every fixture, inside the image, and measures by script: words of the document missing from the output, phrases that must come out whole, text that must never come out (a script's body, a hidden sheet), headings, table rows and whether the table keeps its header, list items, `(cid:n)` noise, the PDF page marks, size and time. Its result is the table in `docs/decisions.md` (2026-10-15, "The converter adopts MarkItDown"). In short:

- **Presentation (pptx):** MarkItDown. No other tool was there; every word, slide title, table and speaker note comes out.
- **Word (docx):** pandoc stays. Equal on words, headings, lists and tables, but MarkItDown's table loses its header row (the first row is written as an empty header).
- **HTML:** pandoc stays. Raw MarkItDown leaves the text of `<noscript>` and `<template>` in the output; with the same pre-filter that removes them for pandoc it would only tie, and it is about ten times slower.
- **Spreadsheet (xlsx):** openpyxl stays. MarkItDown reads hidden sheets (the content of a hidden sheet came out), writes `NaN` for an empty cell and `10.0` for `10`.
- **PDF:** `pdftotext` stays. Equal on words, columns and reading order; MarkItDown keeps a table as a Markdown table where `pdftotext` writes its cells one per line, but it drops the `[page n]` marks and writes `(cid:127)` for a bullet. A table in a PDF is therefore a known limit of the choice.
- **CSV and plain text:** the standard library, unchanged.

### What of MarkItDown is on, and what is not

- **The pin.** `requirements.in` names `markitdown[pptx]==0.1.8` (the newest stable release when this was chosen, 2026-09-21; it needs Python 3.10 or later, and Debian bookworm's is 3.11) and `openpyxl==3.1.5`. `requirements.lock` holds every package they need, 31 of them, each at an exact version and with every sha256 of its wheels (for every platform, so one lock serves the Linux images of both architectures). The Dockerfile installs it into `/opt/venv` with `pip install --require-hashes --only-binary=:all: --no-deps`: a file whose hash is not in the lock is refused, nothing is resolved at build time, and no compiler is in the image. pip is removed afterwards. The build needs the network once (`container.py build --confirmed`); a conversion never does.
- **Only the extra for presentations is installed.** No Azure, YouTube, audio-transcription, Outlook, PDF, Word or Excel extra (their libraries are not in the lock, and a test reads the lock for it).
- **Only local files.** The program calls `convert_stream` on the open file and nothing else: never `convert`, `convert_uri` or `convert_url`. An input that is an address (`http:`, `file:`, `data:`) or not an absolute path is refused before anything is read (exit 3, nothing on standard output).
- **Built-in converters and plugins off.** `MarkItDown(enable_builtins=False, enable_plugins=False)`, and the one converter of the kind is registered by hand: the YouTube, Wikipedia, RSS, audio, image-description, Outlook, EPUB, notebook, ZIP and CSV converters, Document Intelligence and Content Understanding, and any language-model client are never created, so those types are refused as unsupported. No plugin entry point is read.
- **A second wall behind `--network none`.** Before MarkItDown is imported the program makes `socket.connect`, `create_connection` and `getaddrinfo` raise; the container has no network either.
- **A failure is a conversion error.** Any exception of the library becomes `error: MarkItDown could not convert the pptx file: <ExceptionName>` (no path, no text of the file) and exit 3, which the host reports as a failed conversion and which writes nothing.

## How a conversion runs

The host side (`container.py`) uses the shared container helper (`providers/_container.py`): no network, a read-only root, every capability dropped, no new privileges, 128 processes, 1024 MiB of memory (swap included), 2 CPUs, a memory-backed `/tmp` and `/scratch` (256 MiB) with no exec, an unprivileged user (on Linux the caller's own uid and gid, which `providers/_container.py` passes with `--user`; 65534 in the image, which is what runs elsewhere, for example with Docker Desktop on a Mac), an image run by its id and never pulled, and a label that lets `reap` remove a container a crash left. The input is mounted read-only at `/in/input`; nothing else of the host is visible and no environment variable passes.

The result leaves the container as a stream of frames on its standard output (`OHF1`, then `FILE <name> <size>` and the bytes, then `END`), which the host reads up to a cap and parses with fixed rules (`parse_frames`): the names are `converted.md` or `converted.csv`, and `info.json`; sizes and counts are capped; anything else is refused. The host writes the outputs into the folder it was given (mode 0700, empty) as new regular files, mode 0600, with `O_EXCL` and `O_NOFOLLOW`. Nothing is copied from the container's file system, so nothing it leaves as a folder, a link or a pipe can come back; the caller (`runtime/sources.py`, `collect_outputs`, limit L24) reads the folder back with its own checks, and scans the converted text for credentials.

## The image

`Dockerfile`, `.dockerignore`, `_inner.py` and `requirements.lock` are the definition; the image is named `openhora-converter:<12 characters of the hash of those four files>`. It is built here, by a step the person starts, and never pulled when a conversion runs:

```sh
python3 providers/converter/container.py build --dry-run       # the command, nothing built
python3 providers/converter/container.py build --confirmed     # builds it (the network: the base image, the Debian snapshot, PyPI for the files of the lock)
python3 providers/converter/container.py --check               # docker is usable, its daemon is local, the image is built
```

The base image is pinned by digest (`debian:bookworm-20261005-slim`, the digest the other container definitions of the project pin), the Debian packages by the snapshot `20261006T000000Z` and the Python packages by `requirements.lock` (remake it with the command in `requirements.in`). Changing the Dockerfile or `_inner.py` changes the tag: the next conversion asks for a build.

## Tests

- `tests/test_converter_host.py` (offline): the frames, the definition and its hash, the exact command with each limit, the checks on the input and on the out folder, the verbs. No container is started.
- `tests/test_converter_inner.py` (offline): the program on this machine with the tools it finds (pandoc, `pdftotext`, openpyxl, MarkItDown; a test that needs one that is missing is skipped and says so), including the guard that nothing but the presentation converter is registered, that no plugin entry point is read and that an address is refused.
- `tests/test_converter_docker.py` (opt in, `WB_CONVERTER_DOCKER_TESTS=1`): the image built, each format converted in a real container (a presentation included, and the version of MarkItDown the image holds), a key hidden in a PDF's compressed text and another in a slide found in the converted text and not in the raw bytes, and refused by the credential scan that runs after the conversion, and the limits as the image really holds them (no network, a read-only root, a scratch with no exec, no secret in the environment, an unprivileged user).

Fixtures are fictional (`tests/fixtures/`); `tests/make_fixtures.py` made the `review.*`, `rich.*` and `columns.pdf` ones (`uv run providers/converter/tests/make_fixtures.py`). To repeat the comparison, build the image with `markitdown[docx,pdf,xlsx,pptx]==0.1.8` added to a scratch copy of the lock (the extras only the comparison needs), and run `tests/compare_tools.py` in it as its text says.
