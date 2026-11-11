# Notice: what the HyperFrames engine's image installs

This folder holds the definition of a container image, not the software the image installs. `hf_image.py build --confirmed` builds the
image on the person's own machine and fetches each piece below from its publisher at the pinned version; the workbench distributes none of
them, and none of their files is in this repository. The one exception is the three fonts, which are committed in `fonts/` with their
licence texts. This notice says what the built image holds and under which terms.

| What | Version | Where the build gets it | Licence |
|------|---------|-------------------------|---------|
| HyperFrames (npm package `hyperframes`) | 0.9.19 | registry.npmjs.org, from `package-lock.json` | Apache License 2.0, "Copyright 2026 HeyGen, Inc." |
| GSAP (npm package `gsap`) | 3.14.2 | registry.npmjs.org, from `package-lock.json` | GSAP's "Standard 'no charge' license" (https://gsap.com/standard-license), not an open-source licence; accepted by the maintainer on 2026-11-07 (plan v3, decision 7) |
| The other npm packages of `package-lock.json` | as locked | registry.npmjs.org | 127 packages in all; besides GSAP (the row above): MIT 82, Apache-2.0 20, LGPL-3.0-or-later 10, ISC 6, Apache-2.0 AND LGPL-3.0-or-later 3, BSD-3-Clause 2, Apache-2.0 AND LGPL-3.0-or-later AND MIT 1, CC0-1.0 1, 0BSD 1 (the `license` field of each row) |
| Static ffmpeg and ffprobe | n8.0.1-66-g27b8d1a017 (autobuild-2026-02-28-12-59) | github.com/BtbN/FFmpeg-Builds, the `gpl` variant | GPL; the build's own licence files were not read |
| Chrome for Testing, headless shell | 155.0.8059.39 | storage.googleapis.com/chrome-for-testing-public | its licence files travel inside the archive, unpacked in `/opt/chrome` |
| Debian packages (the browser's libraries, python3, ca-certificates) | snapshot 20261006T000000Z | snapshot.debian.org | each package's own; `/usr/share/doc/<package>/copyright` in the image |
| Base image, Node.js 22 on Debian bookworm | `node:22.23.4-bookworm-slim` by digest | Docker Hub | Node.js: MIT; the Debian part as above |
| Fonts: Inter (500, 800) and JetBrains Mono (500), Latin subsets | as in `fonts/SHA256SUMS` | committed in `fonts/` | SIL Open Font License 1.1; the texts are `fonts/Inter-OFL.txt` and `fonts/JetBrainsMono-OFL.txt`, copied with the fonts to `/opt/fonts` |

Notes:

- **The LGPL packages.** The 14 rows whose licence includes LGPL-3.0-or-later are `@img/sharp-libvips-*` and the builds of `sharp` that
  bundle it. They are optional: npm installs only those that match the build's platform. A render does not load them (S2, 2026-11-07).
- **GSAP is never committed.** It is installed from the lockfile at build time, and the pages a render writes load it from the image.
- **The fonts' provenance is weaker than the rest**, as the ffmpeg engine's `assets/fonts/allowlist.json` states: they are Fontsource's
  Latin subsets of the upstream fonts, and the exact package version they came from was not recorded. Their sha256 is pinned.
- **The registry blocks of HyperFrames are not in this image.** Package V3b-3 admitted none (the maintainer's choice), so the image holds only the
  registry's `LICENSE` file at the pinned commit, and the allowlist of admitted components (`blocks/hf/allowlist.json`) is empty. The five blocks below
  are our own rewrites, kept in `blocks/hf/` of this repository, not copies of registry files; a component admitted later gets its entry here too.
- What the image installed is listed in `/opt/hf/npm-ls.txt` (every npm package) and in the image's labels (the pins).

## Blocks adapted from the HyperFrames registry

Five blocks under `providers/renderer/blocks/hf/` are derivative works of components of the HyperFrames registry, rewritten as our own
`gsap.html` fragments (the contract of `_gsap_lint.py`). The registry's repository is licensed under the Apache License, Version 2.0. Its
LICENSE file at commit `b4cc674f7f312e77ded32e0b53006cc0bad6723b` (tag v0.9.19), sha256
`4259155fb06f127687ee7b0a8a3682d45132db0f2da26cbc0b7a2d1e796436b8`, is `LICENSE-registry-Apache-2.0.txt` in this folder, byte for byte; it
ends with the line "Copyright 2026 HeyGen, Inc.", the only copyright line the registry's repository carries (spike finding C9). The registry
components have no per-file licence header and that repository has no NOTICE file, so there is no other notice to carry. Each block's own file starts with a
comment that names its source component, file, commit, licence and the changes, and each `block.json` points here in its `notice` field.

| Block | Source component and file at the commit | Source file sha256 | Licence | Copyright line as found | Changes | Our file |
|-------|-----------------------------------------|--------------------|---------|-------------------------|---------|----------|
| `hf:caption-highlight` | `caption-highlight` / `caption-highlight.html` | `769a0c2012088525b75401079bfae45e774fa39decdc37194d7f7e607c5c908e` | Apache-2.0 | Copyright 2026 HeyGen, Inc. | Rewritten as one fragment of our contract; words and times read from the payload; bottom-anchored in the caption band with type sized by arithmetic; theme tokens and the allow-listed fonts; no sample text; monotone word spans with no overlap by openhora, 2026-11-10 | `blocks/hf/caption-highlight/gsap.html` |
| `hf:caption-pill-karaoke` | `caption-pill-karaoke` / `caption-pill-karaoke.html` | `cdbbc72af7fbac440c0bf5750cf9e3d4ded20f26588b00ac79399342ca60b3e3` | Apache-2.0 | Copyright 2026 HeyGen, Inc. | Rewritten as one fragment of our contract; words and times read from the payload; bottom-anchored with the pill sized by arithmetic; colour fade by opacity cross-fade; theme tokens and the allow-listed font; no sample text | `blocks/hf/caption-pill-karaoke/gsap.html` |
| `hf:count-up` | `count-up` / `count-up.html` | `6b34b9873a243fedb060d23f4eb5cef1b61a5b169ec1ae064030b70b48beea66` | Apache-2.0 | Copyright 2026 HeyGen, Inc. | Rewritten as one fragment of our contract; the figure is the written value counted from zero; label and colour parameters; pixel sizes by arithmetic; theme tokens and the allow-listed fonts | `blocks/hf/count-up/gsap.html` |
| `hf:testimonial-card` | `testimonial-card` / `testimonial-card.html` | `7edb7eaa573f8331a3f5c76c689d47989ccccbfb6027b7ac072de22df52f0510` | Apache-2.0 | Copyright 2026 HeyGen, Inc. | Rewritten as one fragment of our contract; sentence, author and colour read from the payload; star rating and handle left out; initials avatar; pixel sizes by arithmetic; theme tokens and the allow-listed fonts | `blocks/hf/testimonial-card/gsap.html` |
| `hf:spring-pop` | `spring-pop` / `spring-pop.html` | `542423b2d98bb48400280b621e7421b16ae026c2abc1ee8f64d5cca18fd8f51d` | Apache-2.0 | Copyright 2026 HeyGen, Inc. | Rewritten as one fragment of our contract; phrase, icon of our closed list and colour read from the payload; pixel sizes by arithmetic; a short fade at the end; theme tokens and the allow-listed font; fit and two-line layout by openhora, 2026-11-10 | `blocks/hf/spring-pop/gsap.html` |

Notes:

- **The source files are not in this repository.** The hashes name the files the ports were written from (read from a survey of the registry at
  the pinned commit, outside any checkout); a port quotes no sample text of its source.
- **The `caption-kinetic-slam` style is not ported** (the spike measured 50 face hits).
- **Our own blocks are not derivative.** `blocks/oh/*` (MIT, the repository's licence) are ours and carry no entry here.
- **Licence review.** The review of these five entries is the maintainer's (decision `docs/decisions/2026-11-08-v3b-4-hf-ports.md`); this
  notice is the text it reviews.
