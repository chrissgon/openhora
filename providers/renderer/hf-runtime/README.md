# hf-runtime: the HyperFrames runtime and GSAP of the common image

What is here (and in the image's manifest): `npm-pins.json` (two npm tarballs, pinned by url, sha512 integrity and a sha256 of each member we
extract), `registry.sha256` (the HyperFrames registry commit and the sha256 of each raw file the image carries: only `LICENSE` for now),
`fetch_hf.py` (the build-time fetch), and `shims/` (five small scripts the second page contract serves with a page; `SHA256SUMS` pins them).

What is fetched at build and never committed: `gsap.min.js`, `hyperframe.runtime.iife.js` and `hyperframe.manifest.json` go to
`/opt/renderer/vendor`, the registry files to `/opt/renderer/hf-registry`, all read-only. GSAP is under a licence that forbids
redistribution, so it is fetched from the publisher at build and no copy is kept in the repository (decision D19, `docs/decisions/2026-11-24-pf-a1-hf-runtime-image.md`).
`fetch_hf.py` refuses a url outside the npm registry's pattern, a tarball over 64 MiB, an integrity or sha256 that differs, a link, an absolute
path, a `..` or a member over 8 MiB, and leaves no output folder when it refuses. `_inner.py selfcheck` checks every file again.

To raise a version: edit `npm-pins.json` (url, integrity, sha256 of each member) and the lockfile of `hyperframes-image/` together, rebuild the common image
(`ffmpeg.py build --confirmed`). The runtime's hash changes, so every admitted block's determinism record expires and the render refuses it until it is tested again.
