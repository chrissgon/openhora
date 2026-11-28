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

## Ports adapted from the registry

Six blocks under `providers/renderer/blocks/hf/` are derivative works of components of the HyperFrames registry, rewritten as our own `gsap.html` fragments (the
contract of `_gsap_lint.py`). The ffmpeg engine draws them under the second page contract (`_hf_port.py`). The
registry's repository is licensed under the Apache License, Version 2.0. Its LICENSE file at commit `b4cc674f7f312e77ded32e0b53006cc0bad6723b` (tag v0.9.19), sha256
`4259155fb06f127687ee7b0a8a3682d45132db0f2da26cbc0b7a2d1e796436b8`, is the one the common image fetches (`registry.sha256`, the row `LICENSE`). A byte-identical copy of it is `LICENSE-registry-Apache-2.0.txt` in this folder. It ends with the line
"Copyright 2026 HeyGen, Inc.", the only copyright line the registry's repository carries (spike finding C9). The registry components have no per-file licence header and
that repository has no NOTICE file, so there is no other notice to carry. Each block's own file starts with a comment that names its source component, file, commit,
licence and the changes, and each `block.json` points here in its `notice` field.

| Block | Source component and file at the commit | Source file sha256 | Licence | Copyright line as found | Changes | Our file |
|-------|-----------------------------------------|--------------------|---------|-------------------------|---------|----------|
| `hf:caption-highlight` | `caption-highlight` / `caption-highlight.html` | `769a0c2012088525b75401079bfae45e774fa39decdc37194d7f7e607c5c908e` | Apache-2.0 | Copyright 2026 HeyGen, Inc. | Rewritten as one fragment of our contract; words and times read from the payload; bottom-anchored in the caption band with type sized by arithmetic; theme tokens and the allow-listed fonts; no sample text; monotone word spans with no overlap by openhora, 2026-11-10 | `blocks/hf/caption-highlight/gsap.html` |
| `hf:caption-pill-karaoke` | `caption-pill-karaoke` / `caption-pill-karaoke.html` | `cdbbc72af7fbac440c0bf5750cf9e3d4ded20f26588b00ac79399342ca60b3e3` | Apache-2.0 | Copyright 2026 HeyGen, Inc. | Rewritten as one fragment of our contract; words and times read from the payload; bottom-anchored with the pill sized by arithmetic; colour fade by opacity cross-fade; theme tokens and the allow-listed font; no sample text | `blocks/hf/caption-pill-karaoke/gsap.html` |
| `hf:count-up` | `count-up` / `count-up.html` | `6b34b9873a243fedb060d23f4eb5cef1b61a5b169ec1ae064030b70b48beea66` | Apache-2.0 | Copyright 2026 HeyGen, Inc. | Rewritten as one fragment of our contract; the figure is the written value counted from zero; label and colour parameters; pixel sizes by arithmetic; theme tokens and the allow-listed fonts | `blocks/hf/count-up/gsap.html` |
| `hf:testimonial-card` | `testimonial-card` / `testimonial-card.html` | `7edb7eaa573f8331a3f5c76c689d47989ccccbfb6027b7ac072de22df52f0510` | Apache-2.0 | Copyright 2026 HeyGen, Inc. | Rewritten as one fragment of our contract; sentence, author and colour read from the payload; star rating and handle left out; initials avatar; pixel sizes by arithmetic; theme tokens and the allow-listed fonts | `blocks/hf/testimonial-card/gsap.html` |
| `hf:spring-pop` | `spring-pop` / `spring-pop.html` | `542423b2d98bb48400280b621e7421b16ae026c2abc1ee8f64d5cca18fd8f51d` | Apache-2.0 | Copyright 2026 HeyGen, Inc. | Rewritten as one fragment of our contract; phrase, icon of our closed list and colour read from the payload; pixel sizes by arithmetic; a short fade at the end; theme tokens and the allow-listed font; fit and two-line layout by openhora, 2026-11-10 | `blocks/hf/spring-pop/gsap.html` |
| `hf:lt-mask-reveal` | `lt-mask-reveal` / `lt-mask-reveal.html` | `7f348ec3124e211f7ec8e7241f21220134504ab713143e3f9dc10e016892e2e3` | Apache-2.0 | Copyright 2026 HeyGen, Inc. | Rewritten as one fragment of our contract; name and role line read from the payload; pixel sizes by arithmetic; the role line at half the name's size and never under 36 px; theme tokens and the allow-listed fonts; openhora, 2026-11-27 | `blocks/hf/lt-mask-reveal/gsap.html` |

The source files are not in this repository: the hashes name the files the ports were written from, and a port quotes no sample text of its source. Our own blocks
(`blocks/oh/*`, MIT, the repository's licence) are not derivative and carry no entry here. The licence review of these six entries is the maintainer's (decision
`docs/decisions/2026-11-08-v3b-4-hf-ports.md`); this notice is the text it reviews.
