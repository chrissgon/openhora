# Notice: what the common image fetches for the second page contract

This folder holds pins and small files, not the software the image installs. `Dockerfile` runs `fetch_hf.py` once at build time; the workbench
distributes none of the fetched files, and none of them is in this repository.

| What | Version | Where the build gets it | Licence |
|------|---------|-------------------------|---------|
| GSAP (npm package `gsap`), `dist/gsap.min.js` | 3.14.2 | registry.npmjs.org, pinned by sha512 and sha256 in `npm-pins.json` | GSAP's "Standard 'no charge' license" (https://gsap.com/standard-license), not an open-source licence; accepted by the maintainer on 2026-11-07 for the HyperFrames image and extended to the common image by decision D19 (2026-11-24). Never redistributed in this repository: fetched at build |
| HyperFrames runtime (npm package `hyperframes`), `dist/hyperframe.runtime.iife.js` and `dist/hyperframe.manifest.json` | 0.9.19 | registry.npmjs.org, pinned the same way | Apache License 2.0, "Copyright 2026 HeyGen, Inc." (the one place the vendor's name stays, as in decision 2026-11-07 section 8) |
| The registry repository's `LICENSE` | commit `b4cc674f7f312e77ded32e0b53006cc0bad6723b` | raw-file URL at that commit, pinned by sha256 in `registry.sha256` | Apache License 2.0 |
| The five shims in `shims/` | derived at `b4cc674f` | committed here | Apache License 2.0; derived from `packages/producer/src/services/fileServer.ts` and `generated/hf-early-stub-inline.ts` of the registry repository at that commit; one change: the fps literal of `render_mode.js` (`var __renderFps = 30;`) is the placeholder `__OH_FPS__` |

The vendor files are written to `/opt/renderer/vendor` and the registry files to `/opt/renderer/hf-registry`, mode 0444, and `selfcheck` reads them again.

<!-- admitted: hf:spring-pop -->
## Admitted component `hf:spring-pop`

`registry/components/spring-pop/spring-pop.html` of the registry repository at commit `b4cc674f7f312e77ded32e0b53006cc0bad6723b` (Apache License 2.0, notices in the repository's own LICENSE, which the image carries). Fetched at image build from the raw-file URL at that commit, pinned by sha256 in `registry.sha256`; not committed here. Served with the edits `E1`, `E2:Inter` (the CDN GSAP line becomes the vendored one; a font family name becomes the host's) and no other. Determinism test recorded 2026-11-24: 3 samples, 162 frames, 4 runs.
