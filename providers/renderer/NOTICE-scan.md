# Notice: what the common image installs or fetches for the `scan` verb

The `scan` verb (P9-a) reads the text and the QR codes in a media set's pictures and clips. It uses the programs below, which the image installs or fetches at
build. The workbench distributes none of them: none is in this repository. Never committed: fetched or installed at build. The licences were accepted by the maintainer on
2026-11-26 ("Aceito (Recomendado)", decision `docs/decisions/2026-11-26-p9a1-scanner-image.md`).

| What | Version | Where the build gets it | Licence |
|------|---------|-------------------------|---------|
| Tesseract OCR (`tesseract-ocr`, with `tesseract-ocr-eng` and `tesseract-ocr-osd` as its dependencies) | 5.3.0-2 (Debian bookworm) | the pinned Debian snapshot (`DEBIAN_SNAPSHOT` of the `Dockerfile`); apt checks the archive's signature | Apache License 2.0 (Debian copyright file of `tesseract`) |
| Tesseract language data: `tesseract-ocr-por` (Portuguese) and `tesseract-ocr-spa` (Spanish), beside English | 1:4.1.0-2 (Debian bookworm) | the same snapshot | Apache License 2.0; upstream `tesseract-ocr/tessdata_fast` (Debian copyright file of `tesseract-lang`) |
| Leptonica (`liblept5`, which Tesseract links) | 1.82.0-3+b3 | the same snapshot | a BSD-style licence ("Copyright (C) 2001 Leptonica") |
| OpenCV, the wheel `opencv-python-headless` (the QR detector) | 4.14.0.94, `cp37-abi3-manylinux2014` | `files.pythonhosted.org`, pinned by size and sha256 in `wheel-pin.json`; unpacked by `_fetch_wheels.py`, never by pip | OpenCV Apache License 2.0; the packaging scripts MIT. "All wheels ship with FFmpeg licensed under the LGPLv2.1"; the other bundled binaries and their licences are listed in the wheel's `LICENSE-3RD-PARTY.txt` |
| numpy (a requirement of the OpenCV wheel, `numpy>=2`) | 2.4.6, `cp311` `manylinux_2_27`/`manylinux_2_28` (uploaded 2026-05-18) | `files.pythonhosted.org`, pinned the same way | BSD-3-Clause ("Copyright (c) 2005-2025, NumPy Developers"). Its wheel bundles the libraries below; the wheel's own `numpy-2.4.6.dist-info/licenses/LICENSE.txt` (sha256 `4860083caa0de2ac3292ca98bd074bd8f45d8b32624e37b1e70a240bff61e488`) carries the full texts |

What the wheels bundle, as the wheels themselves declare it. Following the pointer-plus-hash form, the long texts stay in the wheels (never committed here) and are read there:

- numpy's `LICENSE.txt` lists: OpenBLAS (`numpy.libs/libscipy_openblas*.so`) BSD-3-Clause; LAPACK (same files) BSD-3-Clause-Open-MPI; the GCC runtime library (`libgfortran*.so`) GPL-3.0-or-later WITH GCC-exception-3.1; libquadmath (`libquadmath*.so`, x86_64 wheel only) LGPL-2.1-or-later. The wheel also carries per-component notices (libdivide, highway, pocketfft, the random generators and others) under `licenses/numpy/`.
- OpenCV's `opencv_python_headless-4.14.0.94.dist-info/LICENSE.txt` (Apache-2.0, sha256 `09d719058e782ac7bc71ba21c944e1136cde2bb957c0e888121f0218d6b5f02c`) and `LICENSE-3RD-PARTY.txt` (sha256 `36bae33968d5e67f66906bc595949cb78d65978604e7392f552a79006c93cf2c`, 179,306 bytes: the texts of the bundled libraries) apply to `cv2/` and its `opencv_python_headless.libs/`: FFmpeg's libavcodec, libavformat, libavutil, libswscale and libswresample (LGPL 2.1), libaom, libdav1d, libavif, libvpx, libpng, libdrm, OpenSSL (libssl, libcrypto 1.1), OpenBLAS, libgfortran and libquadmath. The sha256 values are those of the files inside the wheels the pin names (both architectures hold the same two files).

The packages are installed by the `Dockerfile`; the wheels are unpacked into the image's Python site folder. `selfcheck` (`_inner.py`) starts Tesseract, lists its languages (they must
include English, Portuguese and Spanish) and imports OpenCV and numpy, so the build stops when one is missing. The scan never sends anything off the computer: it runs in a
container with no network, on the normalised files only.
