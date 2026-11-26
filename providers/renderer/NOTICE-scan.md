# Notice: what the common image installs or fetches for the `scan` verb

The `scan` verb (P9-a) reads the text and the QR codes in a media set's pictures and clips. It uses the programs below, which the image installs or fetches at
build. The workbench distributes none of them: none is in this repository. Never committed: fetched or installed at build. The licences were accepted by the maintainer on
2026-11-26 ("Aceito (Recomendado)", decision `docs/decisions/2026-11-26-p9a-scan-before-approval.md`).

| What | Version | Where the build gets it | Licence |
|------|---------|-------------------------|---------|
| Tesseract OCR (`tesseract-ocr`, with `tesseract-ocr-eng` and `tesseract-ocr-osd` as its dependencies) | 5.3.0-2 (Debian bookworm) | the pinned Debian snapshot (`DEBIAN_SNAPSHOT` of the `Dockerfile`); apt checks the archive's signature | Apache License 2.0 (Debian copyright file of `tesseract`) |
| Tesseract language data: `tesseract-ocr-por` (Portuguese) and `tesseract-ocr-spa` (Spanish), beside English | 1:4.1.0-2 (Debian bookworm) | the same snapshot | Apache License 2.0; upstream `tesseract-ocr/tessdata_fast` (Debian copyright file of `tesseract-lang`) |
| Leptonica (`liblept5`, which Tesseract links) | 1.82.0-3+b3 | the same snapshot | a BSD-style licence ("Copyright (C) 2001 Leptonica") |
| OpenCV, the wheel `opencv-python-headless` (the QR detector) | 4.14.0.94, `cp37-abi3-manylinux2014` | `files.pythonhosted.org`, pinned by size and sha256 in `wheel-pin.json`; unpacked by `_fetch_wheels.py`, never by pip | OpenCV Apache License 2.0; the packaging scripts MIT. "All wheels ship with FFmpeg licensed under the LGPLv2.1"; the other bundled binaries and their licences are listed in the wheel's `LICENSE-3RD-PARTY.txt` |
| numpy (a requirement of the OpenCV wheel) | pinned in `wheel-pin.json` (the newest 2.x release at least 14 days old when the pin was filled), `cp311` manylinux wheel | `files.pythonhosted.org`, pinned the same way | BSD-3-Clause. Its wheel bundles OpenBLAS and the gfortran runtime, whose licences are in the wheel's `LICENSE.txt` (to be read from the wheel when the pin is filled and added here) |

The packages are installed by the `Dockerfile`; the wheels are unpacked into the image's Python site folder. `selfcheck` (`_inner.py`) starts Tesseract, lists its languages (they must
include English, Portuguese and Spanish) and imports OpenCV and numpy, so the build stops when one is missing. The scan never sends anything off the computer: it runs in a
container with no network, on the normalised files only.
