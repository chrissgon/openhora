# The document exporter (`exporter:document`)

Turns a task's text into a file for the project: a CSV file, a workbook (XLSX), a Word document (DOCX) or a PDF. The converter's twin for the other direction (`providers/converter/`): the converter reads a person's hostile file into text, the exporter writes a file from a task's text. A class the runtime uses and no skill may require, like the converter and the messenger: on purpose it is not in `contracts/environment.md`, and in `providers/resolve.py` it is a role (`ROLES`) and not a listed class (`LISTED`). One implementation, `container.py`; its one caller is `runtime/step_export.py`, through the resolver. Package P8 of the delegation plan; `docs/architecture/platform/outputs.md` has the whole picture.

## What it adopts (principle 14)

| Format | Tool | Notes |
|--------|------|-------|
| CSV | the standard library's `csv` | UTF-8 with a byte order mark (so that a spreadsheet reads the accents), rows ended by CR LF (RFC 4180: a cell with a lone CR or LF is quoted) |
| XLSX | `openpyxl` (package `python3-openpyxl`) | one sheet `Data`, a bold first row, frozen; a guarded cell is a text cell with the quote-prefix style; a plain unsigned number is a number |
| DOCX | `pandoc` (package `pandoc`) | the Markdown is read, cleaned (below), and written as Word |
| PDF | `pandoc` to HTML, then `WeasyPrint` 63 (from `requirements.lock`) | A4, DejaVu fonts, a style sheet of the program's own; nothing is fetched while it prints |

Why WeasyPrint is installed from a lock and not from the Debian package: the package depends on `python3-cffi`, which pulls a compiler, the Python headers and a numerical stack and makes the image about three times as large (1.27 GB against 506 MB, measured). `requirements.lock` has the exact version and the hash of every file pip may take (made with `uv pip compile --universal --generate-hashes requirements.in`); it is installed with `--require-hashes --only-binary=:all: --no-deps` into `/opt/render/lib`, and pip is removed from the image afterwards. Why not the short-video renderer's headless browser: that image is built for video frames, lives on another branch, and a document needs HTML printed on pages, not a JavaScript engine.

`_render.py` is the small program that drives them inside the container. It holds two pieces of code of its own, both guards: the **formula guard** (finding S9: a cell whose text starts with `=`, `+`, `-`, `@`, a tab, a CR or a LF, after any leading spaces and invisible characters, or the fullwidth forms of the first four, is written as text: a quote in front of it in a CSV file, a text cell with the quote-prefix style in a workbook; its text file explains the signed-number cost) and the **cleaning of a Markdown document** before a writer reads it (a picture becomes its alt text, a raw fragment is dropped, a metadata block is text, a link keeps its address only for `http`, `https`, `mailto` and `#`).

## How a render runs

The host side (`container.py`) uses the shared container helper (`providers/_container.py`): no network, a read-only root, every capability dropped, no new privileges, 128 processes, 1024 MiB of memory (swap included), 2 CPUs, a memory-backed `/tmp` and `/scratch` (256 MiB) with no exec, an unprivileged user, an image run by its id and never pulled, and a label that lets `reap` remove a container a crash left. The input (at most 1 MiB, UTF-8) is written to a private folder (0700, the file created exclusively, 0600) and mounted read-only at `/in/input`; nothing else of the host is visible and no environment variable passes.

The result leaves the container as a stream of frames on its standard output (`OHF1`, then `FILE <name> <size>` and the bytes, then `END`), which the host reads up to a cap (8 MiB of output) and parses with fixed rules (`parse_frames`): the names are `output.<format>` and `info.json`, each once, and anything else is refused. Nothing is copied from the container's file system. The verb `render` writes `output.<format>` into an empty folder of this user (mode 0700) as a new regular file, mode 0600, with `O_EXCL` and `O_NOFOLLOW`; the caller reads it back with its own checks.

## The image

`Dockerfile`, `.dockerignore`, `_render.py` and `requirements.lock` are the definition; the image is named `openhora-render:<12 characters of the hash of those four files>`. It is built here, by a step the person starts, and never pulled when a render runs:

```sh
python3 providers/exporter/container.py build --dry-run       # the command, nothing built
python3 providers/exporter/container.py build --confirmed     # builds it (the network: the base image, the Debian snapshot, the wheels)
python3 providers/exporter/container.py --check               # docker is usable, its daemon is local, the image is built
python3 providers/exporter/container.py render --format pdf --input /abs/path/report.md --out-dir /abs/empty/0700/folder
```

The base image and the Debian snapshot are the converter's (`debian:bookworm-20261005-slim`, snapshot `20261006T000000Z`).

## Tests

- `tests/test_exporter_host.py` (offline): the definition and its hash, the Dockerfile's pins, the exact command with each limit, the frames and the rules that parse them, the private copy of the input and its removal, the verbs. No container is started.
- `tests/test_exporter_inner.py` (offline): the program on this machine with the tools it finds; a test for each guarded character in a CSV file and in a workbook; a test that needs openpyxl, pandoc or WeasyPrint is skipped where it is missing and says so.
- `tests/test_exporter_docker.py` (opt in, `WB_CONVERTER_DOCKER_TESTS=1`, also run by the `converter` job of CI): the image built, each format made in a real container, the guard read back from the real workbook and CSV file, a Word document with no picture or file address, a PDF the converter's container reads back, and the limits as the image really holds them.

Fixtures are fictional.
