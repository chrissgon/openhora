# The document converter (`converter:document`)

Turns a file into text for the sources of a project (`runtime/sources.py`, `docs/architecture/platform/sources.md`): PDF, Word (docx), spreadsheet (xlsx), CSV, HTML and plain text to Markdown or CSV. A class the runtime uses and no skill may require, like the messenger: on purpose it is not in `contracts/environment.md`, and in `providers/resolve.py` it is a role (`ROLES`) and not a listed class (`LISTED`). One implementation, `container.py`.

## What it adopts (principle 14)

Nothing here converts a document by code written for the purpose. The tools are open, packaged and pinned by a dated snapshot of the Debian archive (bookworm):

| Format | Tool | Notes |
|--------|------|-------|
| PDF | poppler's `pdftotext` (package `poppler-utils`) | a text layer only; a PDF of scanned pages has none and the manifest says so (no OCR). One `[page n]` line before each page |
| Word (docx) | `pandoc` (`--sandbox`: no file but the input is read) to GitHub-flavoured Markdown | pictures are dropped |
| HTML | `pandoc --sandbox` after `<script>`, `<style>`, `<noscript>` and `<template>` blocks are removed | text hidden by CSS is not detected yet: the hidden-text flag is P8 |
| Spreadsheet (xlsx) | `openpyxl` (package `python3-openpyxl`), stored values only (`data_only`), visible sheets only | one sheet comes out as `converted.csv`; several as `converted.md` with a `## Sheet: <name>` section and a `csv` fence each; a hidden sheet is not read and the manifest says so |
| CSV | the standard library's `csv` | the delimiter (`,` `;` tab `|`) is detected and the file is written with commas; UTF-8, else Windows-1252 |
| Text | the standard library | UTF-8 (a byte order mark dropped), else Windows-1252; NUL characters out |

`providers/converter/_inner.py` is the small program that drives them inside the container; it adds a guard against an archive that declares too much data or too many entries, and cuts the text one byte over the cap (1 MiB) so that the host sees it and refuses.

## How a conversion runs

The host side (`container.py`) uses the shared container helper (`providers/_container.py`): no network, a read-only root, every capability dropped, no new privileges, 128 processes, 1024 MiB of memory (swap included), 2 CPUs, a memory-backed `/tmp` and `/scratch` (256 MiB) with no exec, an unprivileged user (on Linux the caller's own uid and gid, which `providers/_container.py` passes with `--user`; 65534 in the image, which is what runs elsewhere, for example with Docker Desktop on a Mac), an image run by its id and never pulled, and a label that lets `reap` remove a container a crash left. The input is mounted read-only at `/in/input`; nothing else of the host is visible and no environment variable passes.

The result leaves the container as a stream of frames on its standard output (`OHF1`, then `FILE <name> <size>` and the bytes, then `END`), which the host reads up to a cap and parses with fixed rules (`parse_frames`): the names are `converted.md` or `converted.csv`, and `info.json`; sizes and counts are capped; anything else is refused. The host writes the outputs into the folder it was given (mode 0700, empty) as new regular files, mode 0600, with `O_EXCL` and `O_NOFOLLOW`. Nothing is copied from the container's file system, so nothing it leaves as a folder, a link or a pipe can come back; the caller (`runtime/sources.py`, `collect_outputs`, limit L24) reads the folder back with its own checks, and scans the converted text for credentials.

## The image

`Dockerfile`, `.dockerignore` and `_inner.py` are the definition; the image is named `openhora-converter:<12 characters of the hash of those three files>`. It is built here, by a step the person starts, and never pulled when a conversion runs:

```sh
python3 providers/converter/container.py build --dry-run       # the command, nothing built
python3 providers/converter/container.py build --confirmed     # builds it (the network: the base image, the Debian snapshot)
python3 providers/converter/container.py --check               # docker is usable, its daemon is local, the image is built
```

The base image is pinned by digest (`debian:bookworm-20261005-slim`, the digest the other container definitions of the project pin) and the packages by the snapshot `20261006T000000Z`. Changing the Dockerfile or `_inner.py` changes the tag: the next conversion asks for a build.

## Tests

- `tests/test_converter_host.py` (offline): the frames, the definition and its hash, the exact command with each limit, the checks on the input and on the out folder, the verbs. No container is started.
- `tests/test_converter_inner.py` (offline): the program on this machine with the tools it finds (pandoc, `pdftotext`, openpyxl; a test that needs one that is missing is skipped and says so).
- `tests/test_converter_docker.py` (opt in, `WB_CONVERTER_DOCKER_TESTS=1`): the image built, each format converted in a real container, a key hidden in a PDF's compressed text found in the converted text and not in the raw bytes, and the limits as the image really holds them (no network, a read-only root, a scratch with no exec, no secret in the environment, an unprivileged user).

Fixtures are fictional (`tests/fixtures/`).
