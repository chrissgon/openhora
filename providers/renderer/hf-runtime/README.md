# hf-runtime: the HyperFrames runtime and GSAP of the common image

What is here (and in the image's manifest): `npm-pins.json` (two npm tarballs, pinned by url, sha512 integrity and a sha256 of each member we
extract), `registry.sha256` (the HyperFrames registry commit and the sha256 of each raw file the image carries: `LICENSE` and each file of an admitted component),
`fetch_hf.py` (the build-time fetch), and `shims/` (five small scripts the second page contract serves with a page; `SHA256SUMS` pins them).

What is fetched at build and never committed: `gsap.min.js`, `hyperframe.runtime.iife.js` and `hyperframe.manifest.json` go to
`/opt/renderer/vendor`, the registry files to `/opt/renderer/hf-registry`, all read-only. GSAP is under a licence that forbids
redistribution, so it is fetched from the publisher at build and no copy is kept in the repository (decision D19, `docs/decisions/2026-11-24-pf-a1-hf-runtime-image.md`).
`fetch_hf.py` refuses a url outside the npm registry's pattern, a tarball over 64 MiB, an integrity or sha256 that differs, a link, an absolute
path, a `..` or a member over 8 MiB, and leaves no output folder when it refuses. `_inner.py selfcheck` checks every file again.

To raise a version: edit `npm-pins.json` (url, integrity, sha256 of each member) and the lockfile of `hyperframes-image/` together, rebuild the common image
(`ffmpeg.py build --confirmed`). The runtime's hash changes, so every admitted block's determinism record expires and the render refuses it until it is tested again.

Who reads them: `_hf_host.py` (the second page contract, PF-a2) loads the three vendor files and the five shims at render, each against its pin, serves the runtime, GSAP and the shims inline or from `/h/vendor/`, and takes the runtime's hash from them. `registry.sha256` rows are what an admitted entry's files come from; `ffmpeg.py admit-block` adds them. `entries/` holds our fields of an entry (the input of `admit-block`), `staged/` the admitted entries that are not active (validated, never loaded by the catalogue).

Our own tier-B ports (`blocks/hf/<name>/gsap.html`, PF-a4) are drawn by the ffmpeg engine with this same runtime: `_hf_port.py` builds their page, `ffmpeg.py admit-block --port hf:<name>` records their determinism test in their own `block.json`, and a change of the runtime above expires those records too. The notice of the five ports is in `NOTICE.md` ("Ports adapted from the registry"); the staged `spring-pop` original here is evidence and is never activated.
